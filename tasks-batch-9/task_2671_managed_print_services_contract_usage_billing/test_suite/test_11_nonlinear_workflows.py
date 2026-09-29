"""Workflows that do not run in a straight line.

A meter reading can re-enter `PENDING_VALIDATION` again and again until its
corrected counters validate; a device carries two state dimensions that advance
without ever constraining each other; and two sibling tickets leave `DISPATCHED`
down different branches and rejoin at the same `ONSITE` transition.
"""

import datetime

from test_helpers import (
    FLEET_OPS_2_USER_ID,
    TEST_USERS,
    adjust_part_stock,
    api_client,
    assert_device_dimensions,
    assert_fields,
    create_ticket,
    dispatch_ticket,
    fetch_billing_period,
    fetch_consumable_order,
    fetch_contract,
    fetch_device,
    fetch_meter_read,
    fetch_part_stock,
    fetch_service_ticket,
    fetch_site,
    fetch_technician,
    get_success_data,
    make_field_technician_headers,
    open_order_for_device,
    set_clock,
    setup_print_environment,
    submit_automated_read,
    validate_success,
)

OPS = TEST_USERS["fleet_ops_headers"]
OPS_2 = TEST_USERS["fleet_ops_2_headers"]

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
MONO_RATE = 9_375
DUTY_CYCLE = 20_000


def _instant(value: str) -> datetime.datetime:
    """Parse an ISO 8601 UTC instant regardless of fractional-second formatting."""
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# The meter reading that revisits PENDING_VALIDATION twice
# ---------------------------------------------------------------------------
CYCLE_CONTRACT = {
    "customer_name": "Larkin Mfg",
    "term_months": 36,
    "included_service_scope": "FULL",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 70_000,
    "response_sla_hours_critical": 4,
    "response_sla_hours_standard": 24,
    "labor_rate_cents_per_hour": 9_500,
    "early_termination_fee_cents": 0,
}
FIRST_WINDOW = (PERIOD_START, "2026-08-08T00:00:00Z")
SECOND_WINDOW = ("2026-08-08T00:00:00Z", "2026-08-15T00:00:00Z")


def _resolution_payload(corrected_mono_meter, note):
    """The four inputs an exception resolution takes."""
    return {
        "corrected_mono_meter": corrected_mono_meter,
        "corrected_color_meter": 0,
        "corrected_toner_level_pct": 80,
        "resolution_note": note,
    }


def _device_with_watermark_at_five_thousand():
    """One ACTIVE device whose accepted reading has moved its watermark to 5,000.

    The device's `rated_monthly_duty_cycle` is 20,000, so the plausibility
    ceiling on a combined delta is 60,000 pages.
    """
    env = setup_print_environment(
        contract=CYCLE_CONTRACT,
        mono_tiers=((1, 1, None, MONO_RATE),),
        site={"name": "Plant 1", "address_region": "NE-01", "toner_unit_cap": 4},
        devices=[{"rated_monthly_duty_cycle": DUTY_CYCLE}],
        period=(PERIOD_START, PERIOD_END),
        clock="2026-08-16T00:00:00Z",
    )
    env["first_read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=5_000,
        toner_level_pct=80,
        coverage_start=FIRST_WINDOW[0],
        coverage_end=FIRST_WINDOW[1],
    )
    return env


def _second_read_backwards_in_exception():
    """The same device plus a second reading sitting in EXCEPTION for ROLLBACK."""
    env = _device_with_watermark_at_five_thousand()
    env["second_read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=4_000,
        toner_level_pct=80,
        coverage_start=SECOND_WINDOW[0],
        coverage_end=SECOND_WINDOW[1],
    )
    return env


class TestMeterReadExceptionCycle:
    """One reading row travels PENDING_VALIDATION, EXCEPTION, PENDING_VALIDATION, EXCEPTION, ACCEPTED."""

    def test_a_backwards_counter_lands_the_new_reading_in_exception_at_201(self, api):
        """A submitted meter of 4,000 against a watermark of 5,000 is ROLLBACK, still created with 201.

        PRD: "Both stamp `submitted_by_user_id` with the caller's `X-User-ID` and
        `read_at` with the logical clock, and both create the reading with `status`
        `PENDING_VALIDATION` and `exception_reason` `NONE`."
        PRD: "Both return 201 — and this is important — **whether or not the reading
        validates**."
        PRD: "The candidate monochrome delta is the submitted `mono_meter` less the
        device's `last_accepted_mono_meter`, and the candidate colour delta is the
        submitted `color_meter` less the device's `last_accepted_color_meter`."
        PRD: "If **either** candidate delta is negative, the reading lands in
        `EXCEPTION` with `exception_reason` `ROLLBACK` — a counter that went
        backwards means the panel was replaced, the wrong asset was read, or the
        agent is confused."
        PRD: "A reading that is not `ACCEPTED` carries a `mono_delta` and a
        `color_delta` of exactly 0 and moves no device counter whatsoever."

        Design: Difficulty/non_linear_state_machine/meter_read_exception_resolution_cycle_revisits_pending_validation_twice
        """
        env = _device_with_watermark_at_five_thousand()

        read = validate_success(
            api.submit_automated_meter_read(
                {
                    "device_id": env["device_id"],
                    "billing_period_id": env["period_id"],
                    "mono_meter": 4_000,
                    "color_meter": 0,
                    "toner_level_pct": 80,
                    "coverage_start": SECOND_WINDOW[0],
                    "coverage_end": SECOND_WINDOW[1],
                },
                OPS,
            ),
            201,
        )

        assert_fields(
            read,
            status="EXCEPTION",
            exception_reason="ROLLBACK",
            source="AUTOMATED",
            mono_meter=4_000,
            mono_delta=0,
            color_delta=0,
        )
        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=5_000,
            lifetime_mono_pages=5_000,
            pages_since_last_cartridge=5_000,
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=1)

    def test_the_first_resolution_revalidates_and_lands_back_in_exception_on_a_new_reason(self, api):
        """A corrected meter of 200,000 is a 195,000-page delta, over the 60,000 ceiling.

        PRD: "Resolution overwrites the reading's `mono_meter`, `color_meter` and
        `toner_level_pct` with the three corrected values, records the
        `resolution_note`, stamps `resolved_by_user_id` with the acting `X-User-ID`,
        increments the reading's `version`, and moves it `EXCEPTION →
        PENDING_VALIDATION` — after which **exactly the same validation runs again**
        and lands the reading either in `ACCEPTED`, with the full four-hop cascade
        above, or right back in `EXCEPTION`."
        PRD: "Otherwise, if the **sum** of the two candidate deltas is strictly
        greater than three times the device's `rated_monthly_duty_cycle`, the reading
        lands in `EXCEPTION` with `exception_reason` `IMPLAUSIBLE_SPIKE`; a combined
        delta exactly equal to three times the rated duty cycle is plausible and is
        accepted."
        PRD: "The reading must currently be in `EXCEPTION` (otherwise
        `ERR_READ_INVALID_STATE`), its period must not be `CLOSED` (otherwise
        `ERR_PERIOD_ALREADY_CLOSED`), and the resolving `X-User-ID` must differ from
        the reading's `submitted_by_user_id` (otherwise
        `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/non_linear_state_machine/meter_read_exception_resolution_cycle_revisits_pending_validation_twice
        """
        env = _second_read_backwards_in_exception()

        read = validate_success(
            api.resolve_meter_read_exception(
                env["second_read"]["id"],
                _resolution_payload(200_000, "re-keyed from panel photo, digit slipped"),
                OPS_2,
            ),
            200,
        )

        assert_fields(
            read,
            status="EXCEPTION",
            exception_reason="IMPLAUSIBLE_SPIKE",
            mono_meter=200_000,
            mono_delta=0,
            resolved_by_user_id=FLEET_OPS_2_USER_ID,
            resolution_note="re-keyed from panel photo, digit slipped",
        )
        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=5_000,
            lifetime_mono_pages=5_000,
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=1)

    def test_the_second_resolution_finally_accepts_and_runs_the_full_cascade(self, api):
        """After two failed loops a corrected meter of 8,000 accepts a 3,000-page delta.

        PRD: "The cycle `EXCEPTION → PENDING_VALIDATION → EXCEPTION` may repeat as
        many times as it takes for the corrected counters to validate."
        PRD: "Otherwise the reading is `ACCEPTED`, and `mono_delta` and `color_delta`
        are written with the two candidate values."
        PRD: "The second hop writes the device: `last_accepted_mono_meter` and
        `last_accepted_color_meter` take the submitted absolute values, `last_read_at`
        takes the reading's `coverage_end`, `toner_level_pct` takes the reading's
        reported level, `lifetime_mono_pages` grows by `mono_delta`,
        `lifetime_color_pages` grows by `color_delta`, `pages_since_last_cartridge`
        grows by the sum of the two deltas, and the device's `version` increments."
        PRD: "Independently of all of this, the target period's
        `exception_open_count` is recomputed — upward when the reading lands in
        `EXCEPTION`, and back down when a previously open reading becomes
        `ACCEPTED`."

        Design: Difficulty/non_linear_state_machine/meter_read_exception_resolution_cycle_revisits_pending_validation_twice
        """
        env = _second_read_backwards_in_exception()
        get_success_data(
            api_client.resolve_meter_read_exception(
                env["second_read"]["id"],
                _resolution_payload(200_000, "re-keyed from panel photo, digit slipped"),
                OPS_2,
            )
        )

        read = validate_success(
            api.resolve_meter_read_exception(
                env["second_read"]["id"],
                _resolution_payload(8_000, "second correction from the device web page"),
                OPS_2,
            ),
            200,
        )

        assert_fields(
            read,
            status="ACCEPTED",
            exception_reason="NONE",
            mono_meter=8_000,
            mono_delta=3_000,
            color_delta=0,
        )
        assert_fields(fetch_meter_read(env["first_read"]["id"]), status="ACCEPTED")
        device = fetch_device(env["device_id"])
        assert_fields(
            device,
            last_accepted_mono_meter=8_000,
            last_accepted_color_meter=0,
            lifetime_mono_pages=8_000,
            pages_since_last_cartridge=8_000,
            toner_level_pct=80,
        )
        assert_device_dimensions(device, lifecycle_state="ACTIVE", supply_state="SUPPLY_OK")
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)


# ---------------------------------------------------------------------------
# The two device dimensions that never constrain each other
# ---------------------------------------------------------------------------
SUPPLY_CONTRACT = {
    "customer_name": "Larkin Mfg",
    "term_months": 36,
    "included_service_scope": "BASIC",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 70_000,
    "response_sla_hours_critical": 4,
    "response_sla_hours_standard": 24,
    "labor_rate_cents_per_hour": 9_500,
    "early_termination_fee_cents": 0,
}
SUPPLY_CLOCK = "2026-08-10T00:00:00Z"
TONER_UNIT_PRICE_CENTS = 8_900


def _toner_ordered_device_with_an_open_ticket():
    """An ACTIVE device sitting in SUPPLY_ORDERED with one OPEN ticket waiting.

    The accepted reading reports a toner level of 12 percent, which is at or
    below the 15 percent trigger, so the automatic order was raised inside that
    acceptance.
    """
    env = setup_print_environment(
        contract=SUPPLY_CONTRACT,
        mono_tiers=((1, 1, None, MONO_RATE),),
        site={"name": "Plant 1", "address_region": "NE-01", "toner_unit_cap": 4},
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        clock=SUPPLY_CLOCK,
    )
    env["first_read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=4_000,
        toner_level_pct=12,
        coverage_start=PERIOD_START,
        coverage_end="2026-08-09T00:00:00Z",
    )
    env["order"] = open_order_for_device(env["device_id"])
    env["ticket"] = create_ticket(
        env["device_id"], env["site_id"], severity="STANDARD", symptom_code="STREAKING"
    )
    return env


def _service_hold_device_still_awaiting_its_cartridge():
    """The same device after the dispatch has driven lifecycle_state to SERVICE_HOLD."""
    env = _toner_ordered_device_with_an_open_ticket()
    dispatch_ticket(
        env["ticket"]["id"],
        env["technician_id"],
        "2026-08-11T09:00:00Z",
        "2026-08-11T11:00:00Z",
    )
    return env


class TestDeviceDimensionsAdvanceIndependently:
    """`lifecycle_state` and `supply_state` share one row and move on their own."""

    def test_a_dispatch_moves_lifecycle_only_and_leaves_the_supply_dimension_ordered(self, api):
        """Dispatch drives ACTIVE to SERVICE_HOLD while supply_state stays SUPPLY_ORDERED.

        PRD: "Successful dispatch performs `OPEN → DISPATCHED`, writes
        `assigned_technician_id` from the supplied `technician_id`, recomputes the
        technician's `open_dispatch_count` upward, increments the ticket's `version`,
        and cascades onto the hardware: when the ticket's device has a
        `lifecycle_state` of `ACTIVE`, that device moves `ACTIVE → SERVICE_HOLD` and
        its own `version` increments."
        PRD: "Note that the supply dimension evolves entirely independently of
        `lifecycle_state`: a device on `SERVICE_HOLD` still reorders toner, and a
        device in `SUPPLY_BLOCKED` still meters pages."
        PRD: "When both hold, the supply dimension moves `SUPPLY_LOW →
        SUPPLY_ORDERED` and a cartridge order is created with `trigger_source`
        `AUTO_THRESHOLD`, a `quantity` of exactly 1, a `unit_price_cents` of 8,900 —
        the provider's standard automatic-replenishment unit price of $89 per
        cartridge — and a `part_type` chosen from the device and the reading:
        `TONER_COLOR` when the device is `color_capable` **and** the accepted
        reading's `color_delta` is greater than zero, and `TONER_BLACK` in every
        other case."

        Design: Difficulty/non_linear_state_machine/device_lifecycle_and_supply_dimensions_advance_independently
        """
        env = _toner_ordered_device_with_an_open_ticket()

        ticket = validate_success(
            api.dispatch_service_ticket(
                env["ticket"]["id"],
                {
                    "technician_id": env["technician_id"],
                    "window_start": "2026-08-11T09:00:00Z",
                    "window_end": "2026-08-11T11:00:00Z",
                },
                OPS,
            ),
            200,
        )

        assert_fields(ticket, status="DISPATCHED", assigned_technician_id=env["technician_id"])
        assert_device_dimensions(
            fetch_device(env["device_id"]),
            lifecycle_state="SERVICE_HOLD",
            supply_state="SUPPLY_ORDERED",
        )
        assert_fields(
            fetch_consumable_order(env["order"]["id"]),
            status="ORDERED",
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            unit_price_cents=TONER_UNIT_PRICE_CENTS,
            part_type="TONER_BLACK",
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=TONER_UNIT_PRICE_CENTS,
        )
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=1)

    def test_a_delivery_moves_supply_only_and_leaves_the_lifecycle_on_service_hold(self, api):
        """Delivery returns SUPPLY_ORDERED to SUPPLY_OK while the device stays on SERVICE_HOLD.

        PRD: "Delivery performs `ORDERED → DELIVERED`, stamps `delivered_at` with the
        logical clock, returns the device's supply dimension `SUPPLY_ORDERED →
        SUPPLY_OK`, resets the device's `pages_since_last_cartridge` to 0 against the
        new delivery watermark, releases the commitment by reducing the site's
        `open_toner_units` by the order's `quantity` and the contract's
        `consumables_committed_cents` by the order's `committed_cents`, and increments
        both the order's `version` and the device's `version`."
        PRD: "The full supply cycle is therefore `SUPPLY_OK → SUPPLY_LOW →
        SUPPLY_ORDERED → SUPPLY_OK`."
        PRD: "Note that the supply dimension evolves entirely independently of
        `lifecycle_state`: a device on `SERVICE_HOLD` still reorders toner, and a
        device in `SUPPLY_BLOCKED` still meters pages."

        Design: Difficulty/non_linear_state_machine/device_lifecycle_and_supply_dimensions_advance_independently
        """
        env = _service_hold_device_still_awaiting_its_cartridge()

        order = validate_success(
            api.deliver_consumable_order(
                env["order"]["id"], make_field_technician_headers(env["technician_id"])
            ),
            200,
        )

        assert_fields(order, status="DELIVERED")
        assert _instant(order["delivered_at"]) == _instant(SUPPLY_CLOCK), (
            f"delivered_at must be stamped from the logical clock, got {order['delivered_at']}"
        )
        device = fetch_device(env["device_id"])
        assert_device_dimensions(
            device, lifecycle_state="SERVICE_HOLD", supply_state="SUPPLY_OK"
        )
        assert_fields(device, pages_since_last_cartridge=0, lifetime_mono_pages=4_000)
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)
        assert_fields(fetch_service_ticket(env["ticket"]["id"]), status="DISPATCHED")

    def test_meter_intake_still_works_while_the_device_sits_on_service_hold(self, api):
        """A SERVICE_HOLD device is meterable, and the new pages count from the delivery watermark.

        PRD: "Four gates precede validation: the governing contract must be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`); the target period must not be `CLOSED`
        (`ERR_PERIOD_ALREADY_CLOSED`); the device must belong to the same contract as
        the period and `coverage_end` must fall inside the period's half-open window
        (`ERR_READ_OUTSIDE_PERIOD`); the device must be meterable, meaning its
        `lifecycle_state` is `ACTIVE` or `SERVICE_HOLD` (`ERR_DEVICE_NOT_METERABLE`);
        and `coverage_start` must be strictly earlier than `coverage_end` with the
        resulting interval not intersecting the interval of any other reading of the
        same device that is `PENDING_VALIDATION` or `ACCEPTED`
        (`ERR_READ_INTERVAL_OVERLAP`, with touching endpoints explicitly allowed)."
        PRD: "It is the total of monochrome plus colour pages across the device's
        accepted readings whose `coverage_end` falls after the `delivered_at` of the
        device's most recent delivered cartridge order; when no order has ever been
        delivered for that device, it is simply the device's `lifetime_mono_pages`
        plus its `lifetime_color_pages`."
        PRD: "Note that the supply dimension evolves entirely independently of
        `lifecycle_state`: a device on `SERVICE_HOLD` still reorders toner, and a
        device in `SUPPLY_BLOCKED` still meters pages."

        Design: Difficulty/non_linear_state_machine/device_lifecycle_and_supply_dimensions_advance_independently
        """
        env = _service_hold_device_still_awaiting_its_cartridge()
        get_success_data(
            api_client.deliver_consumable_order(
                env["order"]["id"], make_field_technician_headers(env["technician_id"])
            )
        )

        read = validate_success(
            api.submit_automated_meter_read(
                {
                    "device_id": env["device_id"],
                    "billing_period_id": env["period_id"],
                    "mono_meter": 9_000,
                    "color_meter": 0,
                    "toner_level_pct": 50,
                    "coverage_start": "2026-08-09T00:00:00Z",
                    "coverage_end": "2026-08-15T00:00:00Z",
                },
                OPS,
            ),
            201,
        )

        assert_fields(read, status="ACCEPTED", exception_reason="NONE", mono_delta=5_000)
        device = fetch_device(env["device_id"])
        assert_device_dimensions(
            device, lifecycle_state="SERVICE_HOLD", supply_state="SUPPLY_OK"
        )
        assert_fields(
            device,
            lifetime_mono_pages=9_000,
            pages_since_last_cartridge=5_000,
            last_accepted_mono_meter=9_000,
            toner_level_pct=50,
        )


# ---------------------------------------------------------------------------
# The dispatch fork that rejoins at ONSITE
# ---------------------------------------------------------------------------
FORK_CONTRACT = {
    "customer_name": "Baird Logistics",
    "term_months": 36,
    "included_service_scope": "BASIC",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 70_000,
    "response_sla_hours_critical": 4,
    "response_sla_hours_standard": 24,
    "labor_rate_cents_per_hour": 9_500,
    "early_termination_fee_cents": 0,
}
IN_STOCK_SKU = "DRUM-4"
MISSING_SKU = "FUSER-9"
TICKETS_OPENED_AT = "2026-08-05T00:00:00Z"
WINDOW = ("2026-08-05T01:00:00Z", "2026-08-05T03:00:00Z")
HOLD_STARTED_AT = "2026-08-05T01:00:00Z"
HOLD_ENDED_AT = "2026-08-05T07:00:00Z"
RESOLVED_AT = "2026-08-05T08:00:00Z"


def _two_dispatched_tickets_one_part_short():
    """Sibling STANDARD tickets on two devices: DRUM-4 is on the shelf, FUSER-9 is not.

    Both tickets open at 2026-08-05T00:00:00Z, so their 24-hour standard deadline
    falls at 2026-08-06T00:00:00Z, and each goes to its own technician so the
    travel-buffer rule never bites. The clock is left at the window start.
    """
    env = setup_print_environment(
        contract=FORK_CONTRACT,
        mono_tiers=((1, 1, None, MONO_RATE),),
        site={"name": "Depot 7", "address_region": "NE-01", "toner_unit_cap": 4},
        devices=2,
        technician={"full_name": "Tess Rowan", "home_region": "NE-01", "skill_level": "L3"},
        extra_technicians=(
            {"full_name": "Ivo Sand", "home_region": "NE-01", "skill_level": "L3"},
        ),
        clock=TICKETS_OPENED_AT,
    )
    adjust_part_stock(env["site_id"], IN_STOCK_SKU, 1)

    technician_a, technician_b = env["technicians"][0]["id"], env["technicians"][1]["id"]
    ticket_a = create_ticket(
        env["device_ids"][0],
        env["site_id"],
        severity="STANDARD",
        symptom_code="DRUM-WEAR",
        part_sku=IN_STOCK_SKU,
    )
    ticket_b = create_ticket(
        env["device_ids"][1],
        env["site_id"],
        severity="STANDARD",
        symptom_code="FUSER-JAM",
        part_sku=MISSING_SKU,
    )
    dispatch_ticket(ticket_a["id"], technician_a, WINDOW[0], WINDOW[1])
    dispatch_ticket(ticket_b["id"], technician_b, WINDOW[0], WINDOW[1])
    set_clock(HOLD_STARTED_AT)

    env.update(
        {
            "technician_a": technician_a,
            "technician_b": technician_b,
            "headers_a": make_field_technician_headers(technician_a),
            "headers_b": make_field_technician_headers(technician_b),
            "ticket_a": ticket_a["id"],
            "ticket_b": ticket_b["id"],
        }
    )
    return env


def _ticket_b_held_for_six_hours(env):
    """Put ticket B on a parts hold, restock the SKU, and move the clock six hours on."""
    held = get_success_data(api_client.put_service_ticket_on_parts_hold(env["ticket_b"], env["headers_b"]))
    adjust_part_stock(env["site_id"], MISSING_SKU, 1)
    set_clock(HOLD_ENDED_AT)
    return held


class TestDispatchForkRejoinsAtOnsite:
    """The in-stock ticket goes straight to ONSITE; the out-of-stock one detours."""

    def test_branch_a_arrives_directly_and_accrues_no_hold_time(self, api):
        """DRUM-4 is on the shelf, so the ticket goes DISPATCHED to ONSITE and consumes one unit.

        PRD: "**Branch A**: the part is on the shelf, and the technician records
        arrival directly, performing `DISPATCHED → ONSITE`."
        PRD: "Arrival requires either a null `part_sku` or a locker row for the
        device's `site_id` and that SKU with `on_hand_qty` of at least 1; a missing
        row or a row at zero reports `ERR_PART_NOT_AVAILABLE`."
        PRD: "When a part is required, arrival consumes exactly one unit — the locker
        row's `on_hand_qty` falls by 1 and its `version` increments — and the ticket's
        `version` increments."
        PRD: "On this branch no hold time accrues and `parts_hold_hours` remains 0."

        Design: Difficulty/non_linear_state_machine/ticket_parts_hold_fork_and_direct_fork_rejoin_at_onsite
        """
        env = _two_dispatched_tickets_one_part_short()

        ticket = validate_success(api.arrive_onsite(env["ticket_a"], env["headers_a"]), 200)

        assert_fields(
            ticket,
            status="ONSITE",
            parts_hold_hours=0,
            hold_started_at=None,
            part_sku=IN_STOCK_SKU,
        )
        assert_fields(fetch_part_stock(env["site_id"], IN_STOCK_SKU), on_hand_qty=0)
        assert fetch_part_stock(env["site_id"], MISSING_SKU) is None, (
            "arriving on branch A must not manufacture a locker row for the other SKU"
        )
        assert_fields(fetch_device(env["device_ids"][0]), lifecycle_state="SERVICE_HOLD")
        assert_fields(fetch_service_ticket(env["ticket_b"]), status="DISPATCHED")

    def test_branch_b_detours_through_parts_hold_and_accrues_six_hours(self, api):
        """FUSER-9 is missing, so the hold runs from 01:00 to 07:00 and lands 6 whole hours.

        PRD: "**Branch B**: the part is not there, and the technician declares a parts
        hold, performing `DISPATCHED → PARTS_HOLD`."
        PRD: "The hold stamps `hold_started_at` with the logical clock and increments
        the ticket's `version`."
        PRD: "Once the part arrives the technician records arrival from the hold,
        performing `PARTS_HOLD → ONSITE`: this requires the locker row for that site
        and SKU to now exist with `on_hand_qty` of at least 1 (otherwise
        `ERR_PART_NOT_AVAILABLE`), accumulates the elapsed hold time into
        `parts_hold_hours` by adding the number of hours between `hold_started_at` and
        the current logical clock **rounded up to a whole hour**, clears
        `hold_started_at` back to null, consumes one locker unit and increments the
        locker row's `version`, and increments the ticket's `version`."

        Design: Difficulty/non_linear_state_machine/ticket_parts_hold_fork_and_direct_fork_rejoin_at_onsite
        """
        env = _two_dispatched_tickets_one_part_short()
        held = _ticket_b_held_for_six_hours(env)
        assert_fields(held, status="PARTS_HOLD", parts_hold_hours=0)
        assert _instant(held["hold_started_at"]) == _instant(HOLD_STARTED_AT), (
            f"hold_started_at must be stamped from the logical clock, got {held['hold_started_at']}"
        )

        ticket = validate_success(api.arrive_onsite(env["ticket_b"], env["headers_b"]), 200)

        assert_fields(
            ticket,
            status="ONSITE",
            parts_hold_hours=6,
            hold_started_at=None,
            part_sku=MISSING_SKU,
        )
        assert_fields(fetch_part_stock(env["site_id"], MISSING_SKU), on_hand_qty=0)
        assert_fields(fetch_part_stock(env["site_id"], IN_STOCK_SKU), on_hand_qty=1)
        assert_fields(fetch_device(env["device_ids"][1]), lifecycle_state="SERVICE_HOLD")

    def test_both_branches_rejoin_at_the_same_resolution_and_each_consumed_one_unit(self, api):
        """Resolved at 08:00, well inside the 24-hour deadline: 1 hour bills 9,500 and 2 bill 19,000.

        PRD: "Both branches converge at `ONSITE`, and stock is consumed on exactly one
        of them — the arrival — never twice."
        PRD: "Resolution performs `ONSITE → RESOLVED`, stamps `responded_at` from the
        logical clock, recomputes the technician's `open_dispatch_count` downward,
        increments the ticket's `version`, and cascades onto the hardware: when the
        device's `lifecycle_state` is `SERVICE_HOLD` it returns `SERVICE_HOLD →
        ACTIVE` with its own `version` increment, making `ACTIVE → SERVICE_HOLD →
        ACTIVE` a cycle that repeats once per dispatched ticket."
        PRD: "First, `hours_late`: the number of hours between `respond_by` and
        `responded_at`, rounded up to a whole hour, floored at zero so that a ticket
        resolved on or before its deadline records exactly 0."
        PRD: "Second, `labor_cents`: exactly 0 whenever the contract's
        `included_service_scope` is `FULL`, and otherwise the reported `labor_hours`
        **rounded up to a whole number of hours first** and then multiplied by the
        contract's `labor_rate_cents_per_hour` — the rounding happens before the
        multiplication, never after."
        PRD: "Step two: the billable late hours are `hours_late` less that excused
        portion; if the result is zero, `sla_credit_cents` is 0 and the calculation
        stops."

        Design: Difficulty/non_linear_state_machine/ticket_parts_hold_fork_and_direct_fork_rejoin_at_onsite
        """
        env = _two_dispatched_tickets_one_part_short()
        _ticket_b_held_for_six_hours(env)
        get_success_data(api_client.arrive_onsite(env["ticket_a"], env["headers_a"]))
        get_success_data(api_client.arrive_onsite(env["ticket_b"], env["headers_b"]))
        set_clock(RESOLVED_AT)

        resolved_a = validate_success(
            api.resolve_service_ticket(env["ticket_a"], {"labor_hours": 1.0}, env["headers_a"]),
            200,
        )
        resolved_b = validate_success(
            api.resolve_service_ticket(env["ticket_b"], {"labor_hours": 2.0}, env["headers_b"]),
            200,
        )

        assert_fields(
            resolved_a,
            status="RESOLVED",
            parts_hold_hours=0,
            hours_late=0,
            sla_credit_cents=0,
            labor_cents=9_500,
        )
        assert_fields(
            resolved_b,
            status="RESOLVED",
            parts_hold_hours=6,
            hold_started_at=None,
            hours_late=0,
            sla_credit_cents=0,
            labor_cents=19_000,
        )
        for resolved in (resolved_a, resolved_b):
            assert _instant(resolved["responded_at"]) == _instant(RESOLVED_AT), (
                f"responded_at must come from the logical clock, got {resolved['responded_at']}"
            )
        for device_id in env["device_ids"]:
            assert_fields(fetch_device(device_id), lifecycle_state="ACTIVE")
        for technician_id in (env["technician_a"], env["technician_b"]):
            assert_fields(fetch_technician(technician_id), open_dispatch_count=0)
        assert_fields(fetch_part_stock(env["site_id"], IN_STOCK_SKU), on_hand_qty=0)
        assert_fields(fetch_part_stock(env["site_id"], MISSING_SKU), on_hand_qty=0)
