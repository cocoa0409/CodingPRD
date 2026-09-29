"""Numeric boundaries where one page decides the outcome.

Three different thresholds are probed through three different endpoints: the
combined implausible-spike ceiling on automated meter intake, the waste-control
page floor on auto-replenishment, and the empty-input-set edge of the pricing
pipeline on provisional statement generation.  Each threshold is exercised at
its exact boundary value and at the first value past it.
"""

from test_helpers import (
    api_client,
    assert_fields,
    fetch_billing_period,
    fetch_contract,
    fetch_device,
    fetch_site,
    fetch_statement_lines,
    generate_provisional_statement,
    get_success_data,
    make_fleet_ops_headers,
    make_field_technician_headers,
    meter_read_payload,
    open_order_for_device,
    set_clock,
    setup_print_environment,
    submit_automated_read,
    validate_success,
)

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"

FLAT_MONO_TIERS = ((1, 1, None, 9_375),)
FLAT_COLOR_TIERS = ((1, 1, None, 61_875),)

# Duty cycle 20,000 puts the combined spike ceiling at exactly 60,000 pages.
COLOUR_DEVICE = {
    "model_code": "XR-C7100",
    "color_capable": True,
    "rated_monthly_duty_cycle": 20_000,
    "assessed_monthly_mono_pages": 9_000,
    "assessed_monthly_color_pages": 1_200,
    "baseline_cost_micro_dollars_per_page": 21_000,
    "baseline_overhead_cents_per_month": 4_500,
}

OPS_HEADERS = make_fleet_ops_headers("ops-1")


def _spike_boundary_environment():
    """One ACTIVE colour-capable device, both meters at zero, inside an OPEN period."""
    return setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        color_tiers=FLAT_COLOR_TIERS,
        devices=[dict(COLOUR_DEVICE)],
        period=(PERIOD_START, PERIOD_END),
        clock="2026-08-20T00:00:00Z",
    )


def _capture_read(api, device_id, period_id, **overrides):
    """Push one automated reading and return the created reading row."""
    payload = meter_read_payload(device_id, period_id, **overrides)
    return validate_success(api.submit_automated_meter_read(payload, OPS_HEADERS), 201)


class TestCombinedSpikeCeilingOnMeterIntake:
    """The implausible-spike ceiling is a strict comparison against the summed deltas."""

    def test_combined_delta_exactly_three_times_the_duty_cycle_is_accepted(self, api):
        """40,000 mono plus 20,000 colour pages land exactly on the 60,000-page ceiling.

        PRD: "Otherwise, if the **sum** of the two candidate deltas is strictly greater than three times the device's `rated_monthly_duty_cycle`, the reading lands in `EXCEPTION` with `exception_reason` `IMPLAUSIBLE_SPIKE`; a combined delta exactly equal to three times the rated duty cycle is plausible and is accepted."
        PRD: "Otherwise the reading is `ACCEPTED`, and `mono_delta` and `color_delta` are written with the two candidate values."

        Design: Difficulty/boundary_precision_check/combined_meter_delta_exactly_at_three_times_duty_cycle_is_accepted
        """
        env = _spike_boundary_environment()

        read = _capture_read(
            api,
            env["device_id"],
            env["period_id"],
            mono_meter=40_000,
            color_meter=20_000,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-08T00:00:00Z",
        )

        assert_fields(
            read,
            status="ACCEPTED",
            exception_reason="NONE",
            source="AUTOMATED",
            mono_delta=40_000,
            color_delta=20_000,
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

    def test_accepted_boundary_reading_moves_every_device_counter(self, api):
        """The accepted boundary reading writes the watermarks and the cartridge page count.

        PRD: "The second hop writes the device: `last_accepted_mono_meter` and `last_accepted_color_meter` take the submitted absolute values, `last_read_at` takes the reading's `coverage_end`, `toner_level_pct` takes the reading's reported level, `lifetime_mono_pages` grows by `mono_delta`, `lifetime_color_pages` grows by `color_delta`, `pages_since_last_cartridge` grows by the sum of the two deltas, and the device's `version` increments."

        Design: Difficulty/boundary_precision_check/combined_meter_delta_exactly_at_three_times_duty_cycle_is_accepted
        """
        env = _spike_boundary_environment()

        _capture_read(
            api,
            env["device_id"],
            env["period_id"],
            mono_meter=40_000,
            color_meter=20_000,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-08T00:00:00Z",
        )

        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=40_000,
            last_accepted_color_meter=20_000,
            lifetime_mono_pages=40_000,
            lifetime_color_pages=20_000,
            pages_since_last_cartridge=60_000,
            toner_level_pct=80,
            supply_state="SUPPLY_OK",
        )

    def test_combined_delta_one_page_past_the_ceiling_lands_in_implausible_spike(self, api):
        """A second reading whose combined delta is 60,001 pages is refused as a spike.

        PRD: "Otherwise, if the **sum** of the two candidate deltas is strictly greater than three times the device's `rated_monthly_duty_cycle`, the reading lands in `EXCEPTION` with `exception_reason` `IMPLAUSIBLE_SPIKE`; a combined delta exactly equal to three times the rated duty cycle is plausible and is accepted."
        PRD: "A reading that is not `ACCEPTED` carries a `mono_delta` and a `color_delta` of exactly 0 and moves no device counter whatsoever."

        Design: Difficulty/boundary_precision_check/combined_meter_delta_exactly_at_three_times_duty_cycle_is_accepted
        """
        env = _spike_boundary_environment()
        submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=40_000,
            color_meter=20_000,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-08T00:00:00Z",
        )

        read = _capture_read(
            api,
            env["device_id"],
            env["period_id"],
            mono_meter=100_001,
            color_meter=20_000,
            toner_level_pct=75,
            coverage_start="2026-08-08T00:00:00Z",
            coverage_end="2026-08-15T00:00:00Z",
        )

        assert_fields(
            read,
            status="EXCEPTION",
            exception_reason="IMPLAUSIBLE_SPIKE",
            mono_delta=0,
            color_delta=0,
        )
        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=40_000,
            last_accepted_color_meter=20_000,
            lifetime_mono_pages=40_000,
            lifetime_color_pages=20_000,
            pages_since_last_cartridge=60_000,
            toner_level_pct=80,
        )

    def test_ceiling_is_breached_by_the_summed_deltas_not_by_either_meter_alone(self, api):
        """30,001 mono plus 30,000 colour pages breach the ceiling only when summed.

        PRD: "Otherwise, if the **sum** of the two candidate deltas is strictly greater than three times the device's `rated_monthly_duty_cycle`, the reading lands in `EXCEPTION` with `exception_reason` `IMPLAUSIBLE_SPIKE`; a combined delta exactly equal to three times the rated duty cycle is plausible and is accepted."
        PRD: "Independently of all of this, the target period's `exception_open_count` is recomputed — upward when the reading lands in `EXCEPTION`, and back down when a previously open reading becomes `ACCEPTED`."

        Design: Difficulty/boundary_precision_check/combined_meter_delta_exactly_at_three_times_duty_cycle_is_accepted
        """
        env = _spike_boundary_environment()

        read = _capture_read(
            api,
            env["device_id"],
            env["period_id"],
            mono_meter=30_001,
            color_meter=30_000,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-08T00:00:00Z",
        )

        assert_fields(read, status="EXCEPTION", exception_reason="IMPLAUSIBLE_SPIKE")
        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=0,
            last_accepted_color_meter=0,
            lifetime_mono_pages=0,
            lifetime_color_pages=0,
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=1)


def _two_devices_each_with_one_delivered_cartridge():
    """Two identical ACTIVE mono devices, each already carrying one DELIVERED cartridge.

    Both devices end the preamble back in SUPPLY_OK with a cartridge page count
    of zero, so the only thing that differs at the trigger is how many pages the
    device printed before the next automatic order fires.
    """
    env = setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        devices=2,
        period=(PERIOD_START, PERIOD_END),
        clock="2026-08-05T00:00:00Z",
    )
    tech_headers = make_field_technician_headers(env["technician_id"])
    first_orders = []
    for device_id in env["device_ids"]:
        submit_automated_read(
            device_id,
            env["period_id"],
            mono_meter=1_000,
            toner_level_pct=10,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-05T00:00:00Z",
        )
        order = open_order_for_device(device_id)
        get_success_data(api_client.deliver_consumable_order(order["id"], tech_headers))
        first_orders.append(order)
    env["first_orders"] = first_orders
    set_clock("2026-08-12T00:00:00Z")
    return env


class TestWasteFlagPageFloorOnAutoReplenishment:
    """The waste comparison against 3,000 pages since the last cartridge is strict."""

    def test_auto_order_at_exactly_three_thousand_pages_is_not_waste_flagged(self, api):
        """A snapshot of exactly 3,000 pages sits on the inclusive side of the floor.

        PRD: "The order is then flagged as waste, in the derived `waste_flagged` field, exactly when two things hold together: the device has at least one earlier cartridge order that reached `DELIVERED`, and the snapshotted page count is **strictly less than 3,000 pages**."
        PRD: "A device's very first cartridge is therefore never a waste event however few pages it has printed, and a snapshot of exactly 3,000 pages is not waste either — the comparison is strict."

        Design: Difficulty/boundary_precision_check/auto_order_at_exactly_min_cartridge_pages_is_not_waste
        """
        env = _two_devices_each_with_one_delivered_cartridge()
        device_id = env["device_ids"][0]

        _capture_read(
            api,
            device_id,
            env["period_id"],
            mono_meter=4_000,
            toner_level_pct=9,
            coverage_start="2026-08-05T00:00:00Z",
            coverage_end="2026-08-10T00:00:00Z",
        )

        order = open_order_for_device(device_id)
        assert order is not None, "the accepted reading should have raised a replenishment order"
        assert_fields(
            order,
            pages_since_last_cartridge_at_order=3_000,
            waste_flagged=False,
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            unit_price_cents=8_900,
            committed_cents=8_900,
            part_type="TONER_BLACK",
            status="ORDERED",
        )
        assert_fields(fetch_device(device_id), supply_state="SUPPLY_ORDERED", waste_event_count=0)

    def test_auto_order_one_page_below_the_floor_is_waste_flagged(self, api):
        """A snapshot of 2,999 pages is one page short of the floor and is waste.

        PRD: "The order is then flagged as waste, in the derived `waste_flagged` field, exactly when two things hold together: the device has at least one earlier cartridge order that reached `DELIVERED`, and the snapshotted page count is **strictly less than 3,000 pages**."
        PRD: "Each device exposes a derived `waste_event_count`: the number of its orders that are flagged as waste and have not been cancelled."

        Design: Difficulty/boundary_precision_check/auto_order_at_exactly_min_cartridge_pages_is_not_waste
        """
        env = _two_devices_each_with_one_delivered_cartridge()
        device_id = env["device_ids"][1]

        _capture_read(
            api,
            device_id,
            env["period_id"],
            mono_meter=3_999,
            toner_level_pct=9,
            coverage_start="2026-08-05T00:00:00Z",
            coverage_end="2026-08-10T00:00:00Z",
        )

        order = open_order_for_device(device_id)
        assert order is not None, "the accepted reading should have raised a replenishment order"
        assert_fields(
            order,
            pages_since_last_cartridge_at_order=2_999,
            waste_flagged=True,
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            unit_price_cents=8_900,
            committed_cents=8_900,
            status="ORDERED",
        )
        assert_fields(fetch_device(device_id), supply_state="SUPPLY_ORDERED", waste_event_count=1)

    def test_the_devices_very_first_cartridge_is_never_waste_however_few_pages_it_printed(self):
        """The preamble's own order snapshots 1,000 pages yet cannot be waste.

        PRD: "At the moment any order is created — automatic or manual — the device's current `pages_since_last_cartridge` is snapshotted into the order's `pages_since_last_cartridge_at_order`."
        PRD: "A device's very first cartridge is therefore never a waste event however few pages it has printed, and a snapshot of exactly 3,000 pages is not waste either — the comparison is strict."

        Design: Difficulty/boundary_precision_check/auto_order_at_exactly_min_cartridge_pages_is_not_waste
        """
        env = _two_devices_each_with_one_delivered_cartridge()

        for order in env["first_orders"]:
            assert_fields(
                order,
                pages_since_last_cartridge_at_order=1_000,
                waste_flagged=False,
                trigger_source="AUTO_THRESHOLD",
            )
        for device_id in env["device_ids"]:
            assert_fields(
                fetch_device(device_id),
                supply_state="SUPPLY_OK",
                pages_since_last_cartridge=0,
                waste_event_count=0,
            )

    def test_both_boundary_orders_commit_against_the_site_and_contract_counters(self, api):
        """One order on each side of the floor still commits the same money and units.

        PRD: "The device's `version` increments, and the resulting order pushes the site's `open_toner_units` up by its `quantity` and the contract's `consumables_committed_cents` up by its committed value."

        Design: Difficulty/boundary_precision_check/auto_order_at_exactly_min_cartridge_pages_is_not_waste
        """
        env = _two_devices_each_with_one_delivered_cartridge()
        first_device, second_device = env["device_ids"]

        _capture_read(
            api,
            first_device,
            env["period_id"],
            mono_meter=4_000,
            toner_level_pct=9,
            coverage_start="2026-08-05T00:00:00Z",
            coverage_end="2026-08-10T00:00:00Z",
        )
        _capture_read(
            api,
            second_device,
            env["period_id"],
            mono_meter=3_999,
            toner_level_pct=9,
            coverage_start="2026-08-05T00:00:00Z",
            coverage_end="2026-08-10T00:00:00Z",
        )

        assert_fields(fetch_site(env["site_id"]), open_toner_units=2)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=17_800)


SHORTFALL_CONTRACT = {
    "minimum_mono_pages_per_period": 20_000,
    "minimum_color_pages_per_period": 2_000,
}
LADDER_MONO_TIERS = ((1, 1, 20_000, 9_375), (2, 20_001, None, 7_333))
LADDER_COLOR_TIERS = ((1, 1, 5_000, 61_875), (2, 5_001, None, 55_000))
MID_PERIOD_CLOCK = "2026-08-16T00:00:00Z"


def _minimum_volume_environment():
    """A two-band ladder on both meters, contracted minimums, and no readings at all."""
    return setup_print_environment(
        contract=dict(SHORTFALL_CONTRACT),
        mono_tiers=LADDER_MONO_TIERS,
        color_tiers=LADDER_COLOR_TIERS,
        devices=[dict(COLOUR_DEVICE)],
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )


class TestProvisionalStatementAtTheEmptyReadingBoundary:
    """Zero accepted readings is the lower edge of the pricing pipeline."""

    def test_zero_accepted_readings_nominate_tier_one_on_both_meters(self):
        """With no readings the volume is zero on both meters, so entry rows are nominated.

        PRD: "Only readings assigned to the period with `status` `ACCEPTED` contribute anything; readings in `PENDING_VALIDATION`, `EXCEPTION` or `VOID` contribute nothing at all."
        PRD: "When the volume for a `page_class` is zero, the row at `tier_index` 1 is nominated (its rate goes unused because no line will be emitted for that class); when there is no rate-card row for that `page_class` at all, the statement records a tier index of 0 and a rate of 0 for that class."

        Design: Difficulty/boundary_precision_check/provisional_statement_with_zero_accepted_reads_charges_pure_shortfall
        """
        env = _minimum_volume_environment()

        statement = generate_provisional_statement(env["period_id"])

        assert_fields(
            statement,
            variant="PROVISIONAL",
            projection_basis="PROJECTED",
            mono_pages_billed=0,
            color_pages_billed=0,
            mono_tier_index=1,
            color_tier_index=1,
            mono_rate_micro_dollars_per_page=9_375,
            color_rate_micro_dollars_per_page=61_875,
            usage_subtotal_cents=0,
        )

    def test_zero_accepted_readings_emit_no_statement_lines(self):
        """A zero-page meter produces no line, so the whole statement carries none.

        PRD: "A line is emitted only when the device's billable pages for that meter are greater than zero; a zero-page meter produces no line at all."
        PRD: "The statement's `usage_subtotal_cents` is then the sum of the emitted lines' `amount_cents`."

        Design: Difficulty/boundary_precision_check/provisional_statement_with_zero_accepted_reads_charges_pure_shortfall
        """
        env = _minimum_volume_environment()

        statement = generate_provisional_statement(env["period_id"])

        lines = fetch_statement_lines(statement["id"])
        assert lines == [], f"a statement with no accepted readings must carry no lines, got {lines}"
        assert_fields(statement, usage_subtotal_cents=0)

    def test_the_whole_charge_is_the_minimum_volume_shortfall_priced_at_the_entry_rates(self):
        """22,000 shortfall pages priced at 9,375 and 61,875 micro-dollars give 31,125 cents.

        PRD: "The monochrome shortfall in pages is the contract's `minimum_mono_pages_per_period` less the contract-level monochrome volume, floored at zero; the colour shortfall is `minimum_color_pages_per_period` less the contract-level colour volume, likewise floored at zero."
        PRD: "Shortfall is always priced at the **entry** rate, never at the volume-selected rate: for each class the shortfall pages are multiplied by the `rate_micro_dollars_per_page` of that class's `tier_index` 1 row (taken as 0 when no such row exists), divided by 10,000 and rounded half up to a whole cent, and the two class results are then added together to give `shortfall_cents`."
        PRD: "`total_cents` is the `usage_subtotal_cents` plus `shortfall_cents` plus `service_labor_cents` plus `waste_penalty_cents`, **minus** `sla_credit_cents`."

        Design: Difficulty/boundary_precision_check/provisional_statement_with_zero_accepted_reads_charges_pure_shortfall
        """
        env = _minimum_volume_environment()

        statement = generate_provisional_statement(env["period_id"])

        assert_fields(
            statement,
            shortfall_pages=22_000,
            shortfall_cents=31_125,
            service_labor_cents=0,
            sla_credit_cents=0,
            waste_penalty_cents=0,
            total_cents=31_125,
        )

    def test_the_zero_reading_projection_is_mirrored_onto_the_period(self):
        """Generation moves the period to PROVISIONAL and copies the projected total onto it.

        PRD: "Generation drives `OPEN → PROVISIONAL`, `SWEPT → PROVISIONAL` or `PROVISIONAL → PROVISIONAL`, sets `provisional_total_cents` to the new statement's `total_cents`, and increments the period's `version` by 1."
        PRD: "`provisional_total_cents` mirrors the total of the period's provisional statement and stays null while none exists; `final_total_cents` mirrors the total of the period's final statement and stays null until the period is `CLOSED`."

        Design: Difficulty/boundary_precision_check/provisional_statement_with_zero_accepted_reads_charges_pure_shortfall
        """
        env = _minimum_volume_environment()

        generate_provisional_statement(env["period_id"])

        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="PROVISIONAL",
            provisional_total_cents=31_125,
            final_total_cents=None,
            exception_open_count=0,
        )

    def test_one_accepted_reading_past_the_empty_boundary_emits_a_single_mono_line(self, api):
        """A single mono reading projects to 2,067 pages and emits exactly one line.

        PRD: "Each device's projected pages for a meter are its actual pages for that meter multiplied by the period length in days, divided by the elapsed length in days, and rounded half up to a whole page."
        PRD: "A line is emitted only when the device's billable pages for that meter are greater than zero; a zero-page meter produces no line at all."
        PRD: "Each `StatementLine` records its parent `statement_id`, the `device_id` it prices, the `page_class`, the `pages` it covers, the `rate_micro_dollars_per_page` copied from the statement's selected rate for that class, and an `amount_cents` computed as the pages multiplied by that rate, divided by 10,000, and rounded half up to a whole cent."

        Design: Difficulty/boundary_precision_check/provisional_statement_with_zero_accepted_reads_charges_pure_shortfall
        """
        env = _minimum_volume_environment()
        _capture_read(
            api,
            env["device_id"],
            env["period_id"],
            mono_meter=1_000,
            color_meter=0,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-15T00:00:00Z",
        )

        statement = generate_provisional_statement(env["period_id"])

        assert_fields(
            statement,
            mono_pages_billed=2_067,
            color_pages_billed=0,
            mono_tier_index=1,
            color_tier_index=1,
            usage_subtotal_cents=1_938,
            shortfall_pages=19_933,
            shortfall_cents=29_187,
            total_cents=31_125,
        )
        lines = fetch_statement_lines(statement["id"])
        assert len(lines) == 1, f"only the monochrome meter carries pages, got {len(lines)} lines"
        assert_fields(
            lines[0],
            statement_id=statement["id"],
            device_id=env["device_id"],
            page_class="MONO",
            pages=2_067,
            rate_micro_dollars_per_page=9_375,
            amount_cents=1_938,
        )
