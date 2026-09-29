"""The error catalogue, family by family: every code this system can be made to report.

Each suite drives one entity family through the states from which its guarded
actions must be refused, and pins both the reported code and its HTTP status.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_contract,
    add_cost_tier,
    api_client,
    assert_fields,
    cancel_order_payload,
    close_period,
    create_contract,
    create_quarterly_review,
    fetch_billing_period,
    fetch_consumable_order,
    fetch_contract,
    fetch_device,
    fetch_meter_read,
    fetch_quarterly_review,
    fetch_removal_order,
    fetch_site,
    fetch_statement_lines,
    generate_provisional_statement,
    get_success_data,
    list_reads_for_device,
    make_account_manager_headers,
    make_field_technician_headers,
    make_fleet_ops_headers,
    meter_read_payload,
    provisional_statement_payload,
    resolve_exception_payload,
    run_sweep,
    sanitize_payload,
    schedule_removal_payload,
    set_clock,
    setup_environment_with_auto_toner_order,
    setup_print_environment,
    setup_removal_order,
    submit_automated_read,
    suspend_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_read_payload,
)

# One unbounded monochrome band, so pricing never fails for want of coverage.
FLAT_MONO_TIERS = ((1, 1, None, 9_375),)

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
MID_PERIOD_CLOCK = "2026-08-20T00:00:00Z"


def _active_contract_with_a_projected_period():
    """An active contract, one active device, and a period already carrying a projection."""
    env = setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )
    env["provisional"] = generate_provisional_statement(env["period_id"])
    return env


class TestContractAndPeriodStateFamily:
    """The state guards on contract suspension, resumption and period close."""

    def test_resume_rejects_a_draft_contract_and_then_accepts_a_suspended_one(
        self, api, account_manager_headers
    ):
        """Resumption is only ever legal out of `SUSPENDED`, and it keeps the reason.

        PRD: "Resuming a contract that is not `SUSPENDED` reports
        `ERR_CONTRACT_INVALID_STATE`."
        PRD: "The move `ACTIVE → SUSPENDED` copies that reason into
        `suspension_reason`, adds 1 to `suspension_count` and increments the
        contract's `version`."
        PRD: "Resuming performs `SUSPENDED → ACTIVE`, deliberately **retaining**
        `suspension_reason` for audit rather than resetting it to `NONE`, and
        increments `version`."

        Design: Corner/errors/every_code_triggerable_contract_and_period_state_family
        """
        contract = create_contract()

        refused = api.resume_service_contract(contract["id"], account_manager_headers)

        validate_error(refused, ApiErrorId.ERR_CONTRACT_INVALID_STATE.value, 409)
        assert_fields(fetch_contract(contract["id"]), status="DRAFT", suspension_reason="NONE",
                      suspension_count=0)

        add_cost_tier(contract["id"])
        activate_contract(contract["id"])
        get_success_data(
            api_client.suspend_service_contract(
                contract["id"], suspend_payload("NONPAYMENT"), account_manager_headers
            )
        )

        resumed = validate_success(
            api.resume_service_contract(contract["id"], account_manager_headers), 200
        )

        assert_fields(resumed, status="ACTIVE", suspension_reason="NONPAYMENT", suspension_count=1)

    def test_meter_intake_on_a_suspended_contract_reports_contract_not_active(
        self, api, account_manager_headers, fleet_ops_headers
    ):
        """A frozen contract accepts no page counts, and the device is left where it was.

        PRD: "Operations that consume the contract require its `status` to be
        `ACTIVE` — otherwise `ERR_CONTRACT_NOT_ACTIVE` (409)."
        PRD: "Suspension blocks meter-read intake, consumable orders and billing runs
        but leaves device lifecycle states untouched: a suspended contract's devices
        remain exactly where they were."

        Design: Corner/errors/every_code_triggerable_contract_and_period_state_family
        """
        env = setup_print_environment(
            mono_tiers=FLAT_MONO_TIERS,
            devices=1,
            period=(PERIOD_START, PERIOD_END),
            clock=MID_PERIOD_CLOCK,
        )
        get_success_data(
            api_client.suspend_service_contract(
                env["contract_id"], suspend_payload("DISPUTE"), account_manager_headers
            )
        )

        response = api.submit_automated_meter_read(
            meter_read_payload(env["device_id"], env["period_id"], mono_meter=1_200,
                               coverage_start=PERIOD_START, coverage_end="2026-08-08T00:00:00Z"),
            fleet_ops_headers,
        )

        validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)
        assert list_reads_for_device(env["device_id"]) == [], "a refused intake stores no reading"
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="ACTIVE",
                      last_accepted_mono_meter=0, lifetime_mono_pages=0)

    def test_closing_before_the_clock_reaches_period_end_reports_period_not_ended(
        self, api, billing_analyst_headers
    ):
        """Mid-period close is refused, and the period keeps its projection.

        PRD: "The logical clock must have reached `period_end`, with equality
        sufficient, failing which the request reports `ERR_PERIOD_NOT_ENDED`."
        PRD: "`provisional_total_cents` mirrors the total of the period's provisional
        statement and stays null while none exists; `final_total_cents` mirrors the
        total of the period's final statement and stays null until the period is
        `CLOSED`."
        PRD: "Generation drives `OPEN → PROVISIONAL`, `SWEPT → PROVISIONAL` or
        `PROVISIONAL → PROVISIONAL`, sets `provisional_total_cents` to the new
        statement's `total_cents`, and increments the period's `version` by 1."

        Design: Corner/errors/every_code_triggerable_contract_and_period_state_family
        """
        env = _active_contract_with_a_projected_period()

        response = api.close_billing_period(env["period_id"], billing_analyst_headers)

        validate_error(response, ApiErrorId.ERR_PERIOD_NOT_ENDED.value, 409)
        period = fetch_billing_period(env["period_id"])
        assert_fields(period, status="PROVISIONAL", final_total_cents=None)
        assert period["provisional_total_cents"] == env["provisional"]["total_cents"], (
            "the projection must survive the refused close: "
            f"{period['provisional_total_cents']} vs {env['provisional']['total_cents']}"
        )

    def test_closing_an_already_closed_period_reports_period_invalid_state(
        self, api, billing_analyst_headers
    ):
        """`CLOSED` offers no close transition, so the second attempt is a state failure.

        PRD: "The target resource is in a state from which the requested transition
        exists — otherwise `ERR_CONTRACT_INVALID_STATE`, `ERR_DEVICE_INVALID_STATE`,
        `ERR_READ_INVALID_STATE`, `ERR_PERIOD_INVALID_STATE`,
        `ERR_ORDER_INVALID_STATE`, `ERR_TICKET_INVALID_STATE`,
        `ERR_REVIEW_ALREADY_APPROVED` or `ERR_REMOVAL_INVALID_STATE` (all 409)."
        PRD: "A **final statement** is issued when a `BillingAnalyst` closes the
        period, which drives `SWEPT → CLOSED` or `PROVISIONAL → CLOSED`; a period
        still `OPEN` and never swept cannot be closed and reports
        `ERR_PERIOD_INVALID_STATE`."
        PRD: "Closing creates the final statement, sets `status` to `CLOSED` and
        `final_total_cents` to the statement's `total_cents`, and then cascades onto
        the contract: `lifetime_billed_cents` grows by the statement's `total_cents`,
        and `true_up_balance_cents` grows by the period's `final_total_cents` less its
        `provisional_total_cents` — treating a null `provisional_total_cents` as equal
        to the final total, so that a period which never carried a projection
        contributes exactly zero to the true-up."
        PRD: "Every statement records which one it is in `variant` — `PROVISIONAL` or
        `FINAL` — and records the corresponding evidence basis in `projection_basis`,
        which is `PROJECTED` on a provisional statement and `ACTUAL` on a final one."

        Design: Corner/errors/every_code_triggerable_contract_and_period_state_family
        """
        env = _active_contract_with_a_projected_period()
        set_clock(PERIOD_END)
        final_statement = close_period(env["period_id"])
        assert_fields(final_statement, variant="FINAL", projection_basis="ACTUAL")

        response = api.close_billing_period(env["period_id"], billing_analyst_headers)

        validate_error(response, ApiErrorId.ERR_PERIOD_INVALID_STATE.value, 409)
        assert_fields(fetch_billing_period(env["period_id"]), status="CLOSED",
                      final_total_cents=final_statement["total_cents"])
        finals, meta = validate_paginated(
            api.list_billing_statements(
                billing_analyst_headers,
                params={"billing_period_id": env["period_id"], "variant": "FINAL"},
            )
        )
        assert meta["total_count"] == 1, f"the refused close must issue no statement: {meta}"
        assert_fields(finals[0], id=final_statement["id"])

    def test_meter_intake_against_a_closed_period_reports_period_already_closed(
        self, api, fleet_ops_headers
    ):
        """A billed-out period accepts no further readings.

        PRD: "A meter reading may not be created, resolved or voided against a
        `BillingPeriod` whose `status` is `CLOSED` — otherwise
        `ERR_PERIOD_ALREADY_CLOSED` (409)."
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

        Design: Corner/errors/every_code_triggerable_contract_and_period_state_family
        """
        env = _active_contract_with_a_projected_period()
        set_clock(PERIOD_END)
        close_period(env["period_id"])

        response = api.submit_automated_meter_read(
            meter_read_payload(env["device_id"], env["period_id"], mono_meter=900,
                               coverage_start=PERIOD_START, coverage_end="2026-08-08T00:00:00Z"),
            fleet_ops_headers,
        )

        validate_error(response, ApiErrorId.ERR_PERIOD_ALREADY_CLOSED.value, 409)
        assert list_reads_for_device(env["device_id"]) == [], "a refused intake stores no reading"
        assert_fields(fetch_billing_period(env["period_id"]), status="CLOSED",
                      exception_open_count=0)


READ_CLOCK = "2026-08-16T00:00:00Z"


def _device_with_two_accepted_readings():
    """One active device carrying two consecutive accepted readings for the period."""
    env = setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        clock=READ_CLOCK,
    )
    env["first_read"] = submit_automated_read(
        env["device_id"], env["period_id"], mono_meter=2_000, toner_level_pct=80,
        coverage_start=PERIOD_START, coverage_end="2026-08-08T00:00:00Z",
    )
    env["second_read"] = submit_automated_read(
        env["device_id"], env["period_id"], mono_meter=5_000, toner_level_pct=70,
        coverage_start="2026-08-08T00:00:00Z", coverage_end="2026-08-15T00:00:00Z",
    )
    return env


class TestMeterReadStateFamily:
    """The void and resolve guards on a device with a two-reading history."""

    def test_voiding_a_superseded_reading_reports_read_not_newest(self, api, fleet_ops_headers):
        """The older of two accepted readings cannot be withdrawn while the newer stands.

        PRD: "Only an `ACCEPTED` reading may be voided (otherwise
        `ERR_READ_INVALID_STATE`), only while its period is not `CLOSED` (otherwise
        `ERR_PERIOD_ALREADY_CLOSED`), and only when it is the **newest** accepted
        reading of its device — newest meaning greatest `coverage_end`, with
        `created_at` breaking a tie — failing which the request reports
        `ERR_READ_NOT_NEWEST`."
        PRD: "**Only the newest accepted reading may be voided** — otherwise
        `ERR_READ_NOT_NEWEST` (409)."

        Design: Corner/errors/every_code_triggerable_meter_read_state_family
        """
        env = _device_with_two_accepted_readings()

        response = api.void_meter_read(
            env["first_read"]["id"], void_read_payload("WRONG_DEVICE"), fleet_ops_headers
        )

        validate_error(response, ApiErrorId.ERR_READ_NOT_NEWEST.value, 409)
        assert_fields(fetch_meter_read(env["first_read"]["id"]), status="ACCEPTED",
                      voided_reason="NONE", mono_delta=2_000)
        assert_fields(fetch_device(env["device_id"]), last_accepted_mono_meter=5_000,
                      lifetime_mono_pages=5_000, pages_since_last_cartridge=5_000,
                      toner_level_pct=70)

    def test_resolving_an_accepted_reading_reports_read_invalid_state(self, api):
        """Exception resolution only ever applies to a reading sitting in `EXCEPTION`.

        PRD: "The reading must currently be in `EXCEPTION` (otherwise
        `ERR_READ_INVALID_STATE`), its period must not be `CLOSED` (otherwise
        `ERR_PERIOD_ALREADY_CLOSED`), and the resolving `X-User-ID` must differ from
        the reading's `submitted_by_user_id` (otherwise
        `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/errors/every_code_triggerable_meter_read_state_family
        """
        env = _device_with_two_accepted_readings()

        response = api.resolve_meter_read_exception(
            env["second_read"]["id"],
            resolve_exception_payload(corrected_mono_meter=4_000),
            make_fleet_ops_headers("ops-2"),
        )

        validate_error(response, ApiErrorId.ERR_READ_INVALID_STATE.value, 409)
        assert_fields(fetch_meter_read(env["second_read"]["id"]), status="ACCEPTED",
                      exception_reason="NONE", mono_meter=5_000, toner_level_pct=70)
        assert_fields(fetch_device(env["device_id"]), last_accepted_mono_meter=5_000,
                      toner_level_pct=70)

    def test_voiding_the_newest_reading_reverts_the_device_and_bars_a_second_void(
        self, api, fleet_ops_headers
    ):
        """The void walks the cascade backwards, and `VOID` is terminal.

        PRD: "The device's `last_accepted_mono_meter`, `last_accepted_color_meter`
        and `last_read_at` revert to the values carried by the device's remaining
        accepted reading with the greatest `coverage_end` (tie broken by
        `created_at`), or to 0, 0 and null when no accepted reading remains."
        PRD: "`lifetime_mono_pages` shrinks by the voided reading's `mono_delta`,
        `lifetime_color_pages` shrinks by its `color_delta`, and
        `pages_since_last_cartridge` shrinks by the sum of the two."
        PRD: "The reading's own `mono_delta` and `color_delta` are zeroed, its
        `status` becomes `VOID` and its `voided_reason` is recorded."
        PRD: "The device's `toner_level_pct` reverts to the `toner_level_pct` of that
        same remaining accepted reading, or to 100 when none remains."

        Design: Corner/errors/every_code_triggerable_meter_read_state_family
        """
        env = _device_with_two_accepted_readings()

        voided = validate_success(
            api.void_meter_read(env["second_read"]["id"], void_read_payload("WRONG_DEVICE"),
                                fleet_ops_headers),
            200,
        )

        assert_fields(voided, status="VOID", voided_reason="WRONG_DEVICE", mono_delta=0,
                      color_delta=0)
        assert_fields(fetch_device(env["device_id"]), last_accepted_mono_meter=2_000,
                      lifetime_mono_pages=2_000, pages_since_last_cartridge=2_000,
                      toner_level_pct=80, supply_state="SUPPLY_OK")

        second_attempt = api.void_meter_read(
            env["second_read"]["id"], void_read_payload("DUPLICATE_CAPTURE"), fleet_ops_headers
        )

        validate_error(second_attempt, ApiErrorId.ERR_READ_INVALID_STATE.value, 409)
        assert_fields(fetch_meter_read(env["second_read"]["id"]), status="VOID",
                      voided_reason="WRONG_DEVICE")

    def test_the_older_reading_becomes_voidable_once_the_newest_is_gone(self, api,
                                                                      fleet_ops_headers):
        """With the newer reading void, the older one is now the newest accepted reading.

        PRD: "The device's `last_accepted_mono_meter`, `last_accepted_color_meter`
        and `last_read_at` revert to the values carried by the device's remaining
        accepted reading with the greatest `coverage_end` (tie broken by
        `created_at`), or to 0, 0 and null when no accepted reading remains."
        PRD: "The device's `toner_level_pct` reverts to the `toner_level_pct` of that
        same remaining accepted reading, or to 100 when none remains."
        PRD: "The period's `exception_open_count` is deliberately **unchanged** by a
        void, because a voided reading is neither open nor billable."

        Design: Corner/errors/every_code_triggerable_meter_read_state_family
        """
        env = _device_with_two_accepted_readings()
        get_success_data(
            api_client.void_meter_read(env["second_read"]["id"],
                                       void_read_payload("DUPLICATE_CAPTURE"), fleet_ops_headers)
        )

        voided = validate_success(
            api.void_meter_read(env["first_read"]["id"], void_read_payload("CUSTOMER_DISPUTE"),
                                fleet_ops_headers),
            200,
        )

        assert_fields(voided, status="VOID", voided_reason="CUSTOMER_DISPUTE", mono_delta=0)
        assert_fields(fetch_device(env["device_id"]), last_accepted_mono_meter=0,
                      last_accepted_color_meter=0, last_read_at=None, lifetime_mono_pages=0,
                      pages_since_last_cartridge=0, toner_level_pct=100)
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)


DELIVERY_CLOCK = "2026-08-15T00:00:00Z"


def _assert_instant(actual, expected_prefix, field):
    """Compare a stamped instant to the clock value that produced it.

    The document pins which clock reading a stamp takes, but not whether the
    serialised form carries a fractional-second component, so only the instant
    itself is compared.
    """
    assert actual is not None, f"{field} must be stamped, got null"
    trimmed = str(actual).replace(".000Z", "Z")
    assert trimmed == expected_prefix, f"{field} must record {expected_prefix}, got {actual}"


def _device_with_an_automatic_toner_order():
    """One active device whose low toner reading has already raised a cartridge order."""
    return setup_environment_with_auto_toner_order(
        mono_tiers=FLAT_MONO_TIERS,
        mono_meter=4_000,
        period=(PERIOD_START, PERIOD_END),
    )


class TestConsumableOrderAndReviewStateFamily:
    """The terminal-state and existence guards on cartridge orders and quarterly reviews."""

    def test_delivering_the_order_twice_reports_order_invalid_state(self, api):
        """The first delivery releases the commitment; `DELIVERED` then refuses everything.

        PRD: "Delivery performs `ORDERED → DELIVERED`, stamps `delivered_at` with the
        logical clock, returns the device's supply dimension `SUPPLY_ORDERED →
        SUPPLY_OK`, resets the device's `pages_since_last_cartridge` to 0 against the
        new delivery watermark, releases the commitment by reducing the site's
        `open_toner_units` by the order's `quantity` and the contract's
        `consumables_committed_cents` by the order's `committed_cents`, and increments
        both the order's `version` and the device's `version`."
        PRD: "Cancellation performs `ORDERED → CANCELLED`, and both `DELIVERED` and
        `CANCELLED` are terminal — attempting to deliver or cancel an order that has
        already reached either reports `ERR_ORDER_INVALID_STATE`."

        Design: Corner/errors/every_code_triggerable_consumable_order_and_review_state_family
        """
        env = _device_with_an_automatic_toner_order()
        technician_headers = make_field_technician_headers(env["technician_id"])
        set_clock(DELIVERY_CLOCK)

        delivered = validate_success(
            api.deliver_consumable_order(env["order"]["id"], technician_headers), 200
        )

        assert_fields(delivered, status="DELIVERED", quantity=1, unit_price_cents=8_900)
        _assert_instant(delivered["delivered_at"], DELIVERY_CLOCK, "delivered_at")
        assert_fields(fetch_device(env["device_id"]), supply_state="SUPPLY_OK",
                      pages_since_last_cartridge=0)
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)

        repeat = api.deliver_consumable_order(env["order"]["id"], technician_headers)

        validate_error(repeat, ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)
        order = fetch_consumable_order(env["order"]["id"])
        assert_fields(order, status="DELIVERED")
        _assert_instant(order["delivered_at"], DELIVERY_CLOCK, "delivered_at")
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)

    def test_cancelling_a_delivered_order_reports_order_invalid_state(self, api,
                                                                     fleet_ops_headers):
        """Cancellation is only ever available from `ORDERED`, never after delivery.

        PRD: "Cancellation performs `ORDERED → CANCELLED`, and both `DELIVERED` and
        `CANCELLED` are terminal — attempting to deliver or cancel an order that has
        already reached either reports `ERR_ORDER_INVALID_STATE`."
        PRD: "A `FleetOpsController` cancels an order in `ORDERED` status by supplying
        a `cancel_reason`, which may be `HOARDING_CONTROL`, `WRONG_PART`,
        `DEVICE_REMOVED` or `READ_VOIDED` (the field's default before any cancellation
        is `NONE`)."

        Design: Corner/errors/every_code_triggerable_consumable_order_and_review_state_family
        """
        env = _device_with_an_automatic_toner_order()
        set_clock(DELIVERY_CLOCK)
        get_success_data(
            api_client.deliver_consumable_order(
                env["order"]["id"], make_field_technician_headers(env["technician_id"])
            )
        )

        response = api.cancel_consumable_order(
            env["order"]["id"], cancel_order_payload("WRONG_PART"), fleet_ops_headers
        )

        validate_error(response, ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)
        assert_fields(fetch_consumable_order(env["order"]["id"]), status="DELIVERED",
                      cancel_reason="NONE")
        assert_fields(fetch_device(env["device_id"]), supply_state="SUPPLY_OK",
                      pages_since_last_cartridge=0)

    def test_cancelling_an_unknown_order_reports_order_not_found(self, api, fleet_ops_headers):
        """An unresolvable order identifier is a 404, and the real order is untouched.

        PRD: "Every failure of this kind carries HTTP 404 with the code specific to the
        missing resource type: `ERR_CONTRACT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
        `ERR_DEVICE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_METER_READ_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or
        `ERR_REMOVAL_ORDER_NOT_FOUND`."

        Design: Corner/errors/every_code_triggerable_consumable_order_and_review_state_family
        """
        env = _device_with_an_automatic_toner_order()

        response = api.cancel_consumable_order(
            NON_EXISTENT_UUID, cancel_order_payload("WRONG_PART"), fleet_ops_headers
        )

        validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)
        assert_fields(fetch_consumable_order(env["order"]["id"]), status="ORDERED",
                      cancel_reason="NONE")
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)

    def test_approving_an_already_approved_review_reports_review_already_approved(self, api):
        """`APPROVED` is terminal, so the second approver is refused and the first stands.

        PRD: "A second `AccountManager` — necessarily a different `X-User-ID` from the
        review's `authored_by_user_id`, or the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` — approves the review, driving `DRAFT → APPROVED`,
        stamping `approved_by_user_id` with the acting `X-User-ID`, and incrementing
        the review's `version`."
        PRD: "`APPROVED` is terminal, and approving an already-approved review reports
        `ERR_REVIEW_ALREADY_APPROVED`."

        Design: Corner/errors/every_code_triggerable_consumable_order_and_review_state_family
        """
        env = setup_print_environment(
            mono_tiers=FLAT_MONO_TIERS,
            devices=1,
            period=(PERIOD_START, PERIOD_END),
            clock=MID_PERIOD_CLOCK,
        )
        review = create_quarterly_review(env["contract_id"], user_id="am-1")
        approved = get_success_data(
            api_client.approve_quarterly_review(review["id"], make_account_manager_headers("am-2"))
        )
        assert_fields(approved, status="APPROVED", authored_by_user_id="am-1",
                      approved_by_user_id="am-2")

        response = api.approve_quarterly_review(
            review["id"], make_account_manager_headers("am-3")
        )

        validate_error(response, ApiErrorId.ERR_REVIEW_ALREADY_APPROVED.value, 409)
        assert_fields(fetch_quarterly_review(review["id"]), status="APPROVED",
                      approved_by_user_id="am-2")

    def test_approving_an_unknown_review_reports_review_not_found(self, api):
        """An unresolvable review identifier is a 404 before any state reasoning happens.

        PRD: "Every failure of this kind carries HTTP 404 with the code specific to the
        missing resource type: `ERR_CONTRACT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
        `ERR_DEVICE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_METER_READ_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or
        `ERR_REMOVAL_ORDER_NOT_FOUND`."
        PRD: "When a path names a parent and a child, the parent must resolve before the
        child is looked at, and the first identifier that fails to resolve determines
        the error."

        Design: Corner/errors/every_code_triggerable_consumable_order_and_review_state_family
        """
        env = setup_print_environment(
            mono_tiers=FLAT_MONO_TIERS,
            devices=1,
            period=(PERIOD_START, PERIOD_END),
            clock=MID_PERIOD_CLOCK,
        )
        review = create_quarterly_review(env["contract_id"], user_id="am-1")

        response = api.approve_quarterly_review(
            NON_EXISTENT_UUID, make_account_manager_headers("am-2")
        )

        validate_error(response, ApiErrorId.ERR_REVIEW_NOT_FOUND.value, 404)
        assert_fields(fetch_quarterly_review(review["id"]), status="DRAFT",
                      approved_by_user_id=None)


REMOVAL_CLOCK = "2026-09-02T00:00:00Z"
COLLECTION_INSTANT = "2026-09-20T00:00:00Z"


def _contract_with_a_requested_removal_order():
    """One active device on a contract whose wind-down has just been requested."""
    env = setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        clock=REMOVAL_CLOCK,
    )
    env["removal"] = setup_removal_order(env["contract_id"], COLLECTION_INSTANT)
    return env


class TestRemovalOrderStateAndTemporalFamily:
    """The transition-existence and temporal guards on the removal workflow."""

    @pytest.mark.parametrize("attempted_stage", ["collect", "sanitize", "settle"])
    def test_skipping_ahead_from_requested_reports_removal_invalid_state(
        self, api, billing_analyst_headers, attempted_stage
    ):
        """The wind-down runs strictly in order; nothing downstream of scheduling exists yet.

        PRD: "The target resource is in a state from which the requested transition
        exists — otherwise `ERR_CONTRACT_INVALID_STATE`, `ERR_DEVICE_INVALID_STATE`,
        `ERR_READ_INVALID_STATE`, `ERR_PERIOD_INVALID_STATE`,
        `ERR_ORDER_INVALID_STATE`, `ERR_TICKET_INVALID_STATE`,
        `ERR_REVIEW_ALREADY_APPROVED` or `ERR_REMOVAL_INVALID_STATE` (all 409)."
        PRD: "A `FieldTechnician` then records physical collection, driving `SCHEDULED
        → COLLECTED`."
        PRD: "Sanitization writes both values onto the order and drives `COLLECTED →
        SANITIZED`; attempting it from any other state reports
        `ERR_REMOVAL_INVALID_STATE`."
        PRD: "Settlement is the last act, performed by a `BillingAnalyst` and driving
        `SANITIZED → SETTLED`, which is terminal."
        PRD: "When a single request violates more than one rule, the response must
        report the violation that comes **first** in the ordered list below, not
        whichever check the implementation happens to run first."

        Design: Corner/errors/every_code_triggerable_removal_order_state_and_temporal_family
        """
        env = _contract_with_a_requested_removal_order()
        removal_id = env["removal"]["id"]
        technician_headers = make_field_technician_headers(env["technician_id"])

        if attempted_stage == "collect":
            response = api.collect_removal_order(removal_id, technician_headers)
        elif attempted_stage == "sanitize":
            response = api.sanitize_removal_order(
                removal_id, sanitize_payload("CRYPTO_ERASE", "CERT-2026-09-02-A"),
                technician_headers,
            )
        else:
            response = api.settle_removal_order(removal_id, billing_analyst_headers)

        validate_error(response, ApiErrorId.ERR_REMOVAL_INVALID_STATE.value, 409)
        assert_fields(fetch_removal_order(removal_id), status="REQUESTED",
                      sanitization_method="NONE", sanitization_certificate_ref=None,
                      settled_at=None, device_count=1)
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="ACTIVE",
                      removal_order_id=removal_id)
        assert_fields(fetch_contract(env["contract_id"]), status="TERMINATING")

    def test_scheduling_into_the_past_then_twice_reports_the_two_scheduling_failures(self, api,
                                                                                    account_manager_headers):
        """A backdated collection date is refused, and confirmation happens exactly once.

        PRD: "Confirming the date drives `REQUESTED → SCHEDULED` and writes the supplied
        `scheduled_for` onto the order, again refusing any instant earlier than the
        logical clock with `ERR_SCHEDULE_IN_PAST` and incrementing the order's
        `version`."
        PRD: "The target resource is in a state from which the requested transition
        exists — otherwise `ERR_CONTRACT_INVALID_STATE`, `ERR_DEVICE_INVALID_STATE`,
        `ERR_READ_INVALID_STATE`, `ERR_PERIOD_INVALID_STATE`,
        `ERR_ORDER_INVALID_STATE`, `ERR_TICKET_INVALID_STATE`,
        `ERR_REVIEW_ALREADY_APPROVED` or `ERR_REMOVAL_INVALID_STATE` (all 409)."

        Design: Corner/errors/every_code_triggerable_removal_order_state_and_temporal_family
        """
        env = _contract_with_a_requested_removal_order()
        removal_id = env["removal"]["id"]

        backdated = api.schedule_removal_order(
            removal_id, schedule_removal_payload("2026-09-01T00:00:00Z"), account_manager_headers
        )

        validate_error(backdated, ApiErrorId.ERR_SCHEDULE_IN_PAST.value, 409)
        unchanged = fetch_removal_order(removal_id)
        assert_fields(unchanged, status="REQUESTED")
        _assert_instant(unchanged["scheduled_for"], COLLECTION_INSTANT, "scheduled_for")

        scheduled = validate_success(
            api.schedule_removal_order(
                removal_id, schedule_removal_payload("2026-09-10T00:00:00Z"),
                account_manager_headers,
            ),
            200,
        )

        assert_fields(scheduled, status="SCHEDULED")
        _assert_instant(scheduled["scheduled_for"], "2026-09-10T00:00:00Z", "scheduled_for")

        repeat = api.schedule_removal_order(
            removal_id, schedule_removal_payload("2026-09-11T00:00:00Z"), account_manager_headers
        )

        validate_error(repeat, ApiErrorId.ERR_REMOVAL_INVALID_STATE.value, 409)
        still_scheduled = fetch_removal_order(removal_id)
        assert_fields(still_scheduled, status="SCHEDULED")
        _assert_instant(still_scheduled["scheduled_for"], "2026-09-10T00:00:00Z", "scheduled_for")

    def test_collecting_before_the_scheduled_instant_reports_collection_not_due(self, api):
        """Hardware cannot be carted away before the confirmed collection moment.

        PRD: "Collection requires the logical clock to have reached `scheduled_for`,
        with equality sufficient, failing which it reports `ERR_COLLECTION_NOT_DUE`; and
        it requires that no covered device has a service ticket still in `DISPATCHED`,
        `PARTS_HOLD` or `ONSITE`, because hardware cannot be carted away while an
        engineer is working on it."

        Design: Corner/errors/every_code_triggerable_removal_order_state_and_temporal_family
        """
        env = setup_print_environment(
            mono_tiers=FLAT_MONO_TIERS,
            devices=1,
            period=(PERIOD_START, PERIOD_END),
            clock=REMOVAL_CLOCK,
        )
        removal = setup_removal_order(env["contract_id"], COLLECTION_INSTANT, stage="SCHEDULED")

        response = api.collect_removal_order(
            removal["id"], make_field_technician_headers(env["technician_id"])
        )

        validate_error(response, ApiErrorId.ERR_COLLECTION_NOT_DUE.value, 409)
        untouched = fetch_removal_order(removal["id"])
        assert_fields(untouched, status="SCHEDULED", device_count=1)
        _assert_instant(untouched["scheduled_for"], COLLECTION_INSTANT, "scheduled_for")
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="ACTIVE",
                      removal_order_id=removal["id"])

    def test_collecting_an_unknown_order_reports_removal_order_not_found(self, api):
        """An unresolvable removal identifier is a 404 before any date comparison happens.

        PRD: "Every failure of this kind carries HTTP 404 with the code specific to the
        missing resource type: `ERR_CONTRACT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
        `ERR_DEVICE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_METER_READ_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or
        `ERR_REMOVAL_ORDER_NOT_FOUND`."

        Design: Corner/errors/every_code_triggerable_removal_order_state_and_temporal_family
        """
        env = _contract_with_a_requested_removal_order()

        response = api.collect_removal_order(
            NON_EXISTENT_UUID, make_field_technician_headers(env["technician_id"])
        )

        validate_error(response, ApiErrorId.ERR_REMOVAL_ORDER_NOT_FOUND.value, 404)
        assert_fields(fetch_removal_order(env["removal"]["id"]), status="REQUESTED",
                      device_count=1)


BOUNDED_MONO_TIERS = ((1, 1, 1_000, 9_375),)
TIER_GAP_CLOCK = "2026-08-15T00:00:00Z"


def _period_whose_volume_overflows_the_top_band():
    """A rate card bounded at 1,000 pages against a device that has printed 1,500."""
    env = setup_print_environment(
        mono_tiers=BOUNDED_MONO_TIERS,
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        clock=TIER_GAP_CLOCK,
    )
    env["read"] = submit_automated_read(
        env["device_id"], env["period_id"], mono_meter=1_500, toner_level_pct=60,
        coverage_start=PERIOD_START, coverage_end=TIER_GAP_CLOCK,
    )
    return env


class TestRateCardCoverageGapFamily:
    """A rate card good enough to activate a contract can still fail to price it."""

    def test_a_projected_volume_above_the_top_band_blocks_the_provisional_statement(
        self, api, billing_analyst_headers
    ):
        """Fourteen days of 1,500 pages project to 3,321, which no band covers.

        PRD: "On the **PROVISIONAL** variant they are scaled up to the whole period:
        the period length in days is the number of seconds between `period_start` and
        `period_end` divided by 86,400 and rounded **up** to a whole day; the elapsed
        length in days is the number of seconds between `period_start` and the earlier
        of the current logical clock and `period_end`, divided by 86,400, rounded
        **down** to a whole day, and then floored at a minimum of 1 day so the scaling
        never divides by zero."
        PRD: "Each device's projected pages for a meter are its actual pages for that
        meter multiplied by the period length in days, divided by the elapsed length in
        days, and rounded half up to a whole page."
        PRD: "Each volume then selects **one** rate-card row from the rows of that
        contract and `page_class`: the single row whose band contains the volume, where
        the band runs from `from_page` to `to_page` with **both bounds inclusive** and a
        null `to_page` meaning unbounded above."
        PRD: "When the volume is greater than zero and no band contains it, pricing
        fails with `ERR_TIER_COVERAGE_GAP`."
        PRD: "`provisional_total_cents` mirrors the total of the period's provisional
        statement and stays null while none exists; `final_total_cents` mirrors the
        total of the period's final statement and stays null until the period is
        `CLOSED`."

        Design: Corner/errors/every_code_triggerable_rate_card_coverage_gap_blocks_both_statement_variants
        """
        env = _period_whose_volume_overflows_the_top_band()
        period_version = fetch_billing_period(env["period_id"])["version"]

        response = api.generate_provisional_statement(
            env["period_id"], provisional_statement_payload(period_version),
            billing_analyst_headers,
        )

        validate_error(response, ApiErrorId.ERR_TIER_COVERAGE_GAP.value, 409)
        assert_fields(fetch_billing_period(env["period_id"]), status="OPEN",
                      provisional_total_cents=None, final_total_cents=None,
                      sweep_run_count=0)
        statements, meta = validate_paginated(
            api.list_billing_statements(
                billing_analyst_headers, params={"billing_period_id": env["period_id"]}
            )
        )
        assert meta["total_count"] == 0, f"a refused projection must issue nothing: {statements}"

    def test_the_final_statement_is_blocked_until_a_covering_band_is_appended(
        self, api, billing_analyst_headers
    ):
        """The actual 1,500 pages are uncovered too, and pricing resumes once a band exists.

        PRD: "Two edges matter: when every eligible device already has an accepted
        reading the sweep creates zero placeholders yet **still** advances the period to
        `SWEPT` and **still** increments `sweep_run_count`; and on a re-run, devices that
        already hold a `SWEEP_ESTIMATE` reading in `EXCEPTION` for that period are
        skipped rather than given a duplicate."
        PRD: "When the volume is greater than zero and no band contains it, pricing
        fails with `ERR_TIER_COVERAGE_GAP`."
        PRD: "`provisional_total_cents` mirrors the total of the period's provisional
        statement and stays null while none exists; `final_total_cents` mirrors the
        total of the period's final statement and stays null until the period is
        `CLOSED`."
        PRD: "The ladder is **non-graduated**: the single selected rate applies to
        *every* page of that class for *every* device, and pages are never split across
        bands."
        PRD: "These two figures are recorded on the statement as `mono_pages_billed`
        and `color_pages_billed`."
        PRD: "The statement's `usage_subtotal_cents` is then the sum of the emitted
        lines' `amount_cents`."
        PRD: "`total_cents` is the `usage_subtotal_cents` plus `shortfall_cents` plus
        `service_labor_cents` plus `waste_penalty_cents`, **minus** `sla_credit_cents`."
        PRD: "Closing creates the final statement, sets `status` to `CLOSED` and
        `final_total_cents` to the statement's `total_cents`, and then cascades onto the
        contract: `lifetime_billed_cents` grows by the statement's `total_cents`, and
        `true_up_balance_cents` grows by the period's `final_total_cents` less its
        `provisional_total_cents` — treating a null `provisional_total_cents` as equal
        to the final total, so that a period which never carried a projection
        contributes exactly zero to the true-up."

        Design: Corner/errors/every_code_triggerable_rate_card_coverage_gap_blocks_both_statement_variants
        """
        env = _period_whose_volume_overflows_the_top_band()
        run_sweep(env["period_id"])
        assert_fields(fetch_billing_period(env["period_id"]), status="SWEPT",
                      sweep_run_count=1, exception_open_count=0)
        set_clock(PERIOD_END)

        refused = api.close_billing_period(env["period_id"], billing_analyst_headers)

        validate_error(refused, ApiErrorId.ERR_TIER_COVERAGE_GAP.value, 409)
        assert_fields(fetch_billing_period(env["period_id"]), status="SWEPT",
                      final_total_cents=None, provisional_total_cents=None)

        appended = add_cost_tier(
            env["contract_id"], page_class="MONO", tier_index=2, from_page=1_001,
            to_page=None, rate_micro_dollars_per_page=7_333,
        )
        assert_fields(appended, tier_index=2, from_page=1_001, to_page=None,
                      rate_micro_dollars_per_page=7_333)

        statement = validate_success(
            api.close_billing_period(env["period_id"], billing_analyst_headers), 201
        )

        assert_fields(statement, variant="FINAL", projection_basis="ACTUAL",
                      mono_tier_index=2, mono_rate_micro_dollars_per_page=7_333,
                      mono_pages_billed=1_500, color_pages_billed=0, shortfall_pages=0,
                      shortfall_cents=0, service_labor_cents=0, sla_credit_cents=0,
                      waste_penalty_cents=0, usage_subtotal_cents=1_100, total_cents=1_100)
        lines = fetch_statement_lines(statement["id"])
        assert len(lines) == 1, f"1,500 monochrome pages must emit exactly one line: {lines}"
        assert_fields(lines[0], device_id=env["device_id"], page_class="MONO", pages=1_500,
                      rate_micro_dollars_per_page=7_333, amount_cents=1_100)
        assert_fields(fetch_billing_period(env["period_id"]), status="CLOSED",
                      final_total_cents=1_100)
