"""Meter reading rules, cycle completeness, and billing-cycle window shape."""
from test_helpers import (
    CYCLE_1,
    CYCLE_2,
    ApiErrorId,
    api_client,
    assert_meter_reading,
    bill_cycle_with_readings,
    close_cycle,
    create_active_member,
    create_area,
    create_billing_cycle_payload,
    create_meter_reading_payload,
    create_tap_payload,
    get_success_data,
    open_cycle,
    setup_billed_invoice,
    setup_district_with_schedule,
    setup_member_with_installed_tap,
    submit_reading,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, FIELD, TREASURER


class TestMeterReadingShape:
    def test_meter_reading_is_ledger_style_and_usage_derived(self, api):
        """PRD section 2.4: "`MeterReading`, `MasterMeterReading`, `ReserveEntry`,
        and `NotificationReceipt` expose neither `updated_at` nor `version`."
        PRD section 3.2: "if a billing cycle is currently `OPEN`, an initial
        `ACTUAL` meter reading at 0 gallons is auto-created for the tap in that
        cycle." PRD section 3.3: "The system derives `usage_gallons` as the new
        register value minus the tap's prior accepted cumulative reading".

        Design: Corner/entities/meter_reading_immutable_no_update_endpoint
        """
        district, schedule = setup_district_with_schedule()
        area = create_area(district["id"])
        member = create_active_member(district["id"], area["id"])
        tap = get_success_data(
            api.create_tap(district["id"], create_tap_payload(member["id"]), CLERK),
            expected_status=201,
        )
        get_success_data(
            api.pay_tap_fee(district["id"], tap["id"], {"amount_cents": 75_000}, TREASURER)
        )
        cycle1 = open_cycle(district["id"], **CYCLE_1)
        get_success_data(api.install_meter(district["id"], tap["id"], FIELD))

        readings = get_success_data(api.list_meter_readings(district["id"], CLERK))
        auto = [r for r in readings if r["tap_id"] == tap["id"] and r["cycle_id"] == cycle1["id"]]
        assert len(auto) == 1, "Install while a cycle is OPEN must auto-create one 0-gallon reading"
        assert_meter_reading(auto[0])
        assert auto[0]["reading_gallons"] == 0
        assert auto[0]["reading_type"] == "ACTUAL"
        assert auto[0]["usage_gallons"] == 0

        # Close cycle 1, then read 100 in cycle 2: usage = 100 - 0 (prior register).
        get_success_data(api.mark_readings_complete(district["id"], cycle1["id"], CLERK))
        get_success_data(api.bill_cycle(district["id"], cycle1["id"], CLERK))
        close_cycle(district["id"], cycle1["id"], master_gallons=0)
        cycle2 = open_cycle(district["id"], **CYCLE_2)
        reading = submit_reading(district["id"], tap["id"], cycle2["id"], 100)
        assert_meter_reading(reading)
        assert reading["usage_gallons"] == 100


class TestReadingIntegrity:
    def test_regression_below_prior_register_rejected(self, api):
        """PRD section 3.3: "The system derives `usage_gallons` as the new register
        value minus the tap's prior accepted cumulative reading; a reading below
        that prior value is a regression, rejected with `ERR_READING_REGRESSION`
        (HTTP 422)."

        Design: Corner/validations/meter_reading_regression_rejected
        """
        ctx = setup_member_with_installed_tap()
        district = ctx["district"]
        tap = ctx["tap"]
        cycle1 = open_cycle(district["id"], **CYCLE_1)
        submit_reading(district["id"], tap["id"], cycle1["id"], 500)
        bill = get_success_data(api.mark_readings_complete(district["id"], cycle1["id"], CLERK))
        get_success_data(api.bill_cycle(district["id"], cycle1["id"], CLERK))
        close_cycle(district["id"], cycle1["id"], master_gallons=500)

        cycle2 = open_cycle(district["id"], **CYCLE_2)
        resp = api.create_meter_reading(
            district["id"],
            create_meter_reading_payload(tap["id"], cycle2["id"], 499),
            FIELD,
        )
        validate_error(resp, ApiErrorId.ERR_READING_REGRESSION, expected_status=422)
        readings = get_success_data(api.list_meter_readings(district["id"], CLERK))
        cycle2_rows = [r for r in readings if r["cycle_id"] == cycle2["id"]]
        assert cycle2_rows == [], "A regressed reading must not be persisted"

    def test_duplicate_reading_same_cycle_rejected(self, api):
        """PRD section 3.3: "One accepted reading per tap per cycle is the rule — a
        second submission for the same tap and cycle is `ERR_DUPLICATE_READING`
        (HTTP 409)."

        Design: Corner/validations/duplicate_reading_same_cycle_rejected
        """
        ctx = setup_member_with_installed_tap()
        district = ctx["district"]
        tap = ctx["tap"]
        cycle = open_cycle(district["id"], **CYCLE_1)
        submit_reading(district["id"], tap["id"], cycle["id"], 500)

        resp = api.create_meter_reading(
            district["id"],
            create_meter_reading_payload(tap["id"], cycle["id"], 700),
            FIELD,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_READING, expected_status=409)
        readings = get_success_data(api.list_meter_readings(district["id"], CLERK))
        accepted = [r for r in readings if r["tap_id"] == tap["id"] and r["cycle_id"] == cycle["id"]]
        assert len(accepted) == 1
        assert accepted[0]["reading_gallons"] == 500
        assert accepted[0]["usage_gallons"] == 500


class TestCycleCompletenessAndState:
    def test_mark_readings_complete_with_unread_tap_rejected(self, api):
        """PRD section 3.3: "When every tap in `INSTALLED` or `RECONNECTED` status
        has exactly one accepted reading for the cycle, the clerk asserts
        completeness, moving the cycle `OPEN → READINGS_COMPLETE`; if any such tap
        lacks a reading, the assertion fails with `ERR_MISSING_METER_READINGS`
        (HTTP 409)."

        Design: Corner/validations/mark_readings_complete_missing_reading_fails
        """
        district, schedule = setup_district_with_schedule()
        area = create_area(district["id"])
        taps = []
        for name in ("M1", "M2"):
            member = create_active_member(district["id"], area["id"], legal_name=name)
            tap = get_success_data(
                api.create_tap(district["id"], create_tap_payload(member["id"]), CLERK),
                expected_status=201,
            )
            get_success_data(
                api.pay_tap_fee(district["id"], tap["id"], {"amount_cents": 75_000}, TREASURER)
            )
            taps.append(
                get_success_data(api.install_meter(district["id"], tap["id"], FIELD))
            )
        cycle = open_cycle(district["id"], **CYCLE_1)
        submit_reading(district["id"], taps[0]["id"], cycle["id"], 500)

        resp = api.mark_readings_complete(district["id"], cycle["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_MISSING_METER_READINGS, expected_status=409)
        after = get_success_data(api.get_billing_cycle(district["id"], cycle["id"], CLERK))
        assert after["status"] == "OPEN"

    def test_mark_readings_complete_on_billed_cycle_rejected(self, api):
        """PRD section 3.3: "the clerk asserts completeness, moving the cycle `OPEN
        → READINGS_COMPLETE`" — the only legal from-state is OPEN. PRD section 2.7
        names the state-legality family: "State-legality checks come next
        (`ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_NOT_READINGS_COMPLETE`,
        `ERR_CYCLE_NOT_BILLED`, `ERR_MEMBER_NOT_ACTIVE`, `ERR_ORDER_NOT_SAMPLING`,
        `ERR_PETITION_NOT_REVIEWABLE`, `ERR_RESOLUTION_NOT_PROPOSED`, and the
        generic invalid-state family)".

        Design: Corner/state_machines/invalid_from_mark_readings_complete_on_billed_cycle
        """
        ctx = setup_billed_invoice(usage_gallons=100)
        district = ctx["district"]
        cycle = ctx["cycle"]
        assert get_success_data(api.get_billing_cycle(district["id"], cycle["id"], CLERK))[
            "status"
        ] == "BILLED"
        resp = api.mark_readings_complete(district["id"], cycle["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN, expected_status=409)
        after = get_success_data(api.get_billing_cycle(district["id"], cycle["id"], CLERK))
        assert after["status"] == "BILLED"


class TestCycleWindowShape:
    def _setup_closed_first_cycle(self, api):
        ctx = setup_billed_invoice(usage_gallons=500)
        district = ctx["district"]
        close_cycle(district["id"], ctx["cycle"]["id"], master_gallons=500)
        return ctx

    def test_overlapping_successor_cycle_rejected(self, api):
        """PRD section 3.3: "The window must be well-formed: `period_end_utc`
        strictly after `period_start_utc`, `due_date_utc` at or after
        `period_end_utc`, and the new cycle's start at or after the previous
        `CLOSED` cycle's end — no overlap, no back-dating — else
        `ERR_CYCLE_WINDOW_INVALID` (HTTP 422)." A start one second before the prior
        cycle's end overlaps.

        Design: Difficulty/resource_temporal_overlap/billing_cycle_window_half_open_no_overlap
        """
        ctx = self._setup_closed_first_cycle(api)
        district = ctx["district"]
        resp = api.create_billing_cycle(
            district["id"],
            create_billing_cycle_payload(
                period_start_utc="2026-08-31T23:59:59Z",
                period_end_utc="2026-10-01T00:00:00Z",
                due_date_utc="2026-10-10T00:00:00Z",
            ),
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_INVALID, expected_status=422)

    def test_adjacent_successor_cycle_accepted(self, api):
        """PRD section 3.3: "the new cycle's start at or after the previous
        `CLOSED` cycle's end — no overlap, no back-dating" and "The new cycle's
        `cycle_index` is the district's `current_billing_epoch` plus one, strictly
        increasing per district, and its status is `OPEN`." A start exactly equal
        to the prior cycle's end satisfies "at or after" (half-open adjacency).

        Design: Difficulty/resource_temporal_overlap/billing_cycle_window_half_open_no_overlap
        """
        ctx = self._setup_closed_first_cycle(api)
        district = ctx["district"]
        resp = api.create_billing_cycle(
            district["id"],
            create_billing_cycle_payload(
                period_start_utc="2026-09-01T00:00:00Z",
                period_end_utc="2026-10-01T00:00:00Z",
                due_date_utc="2026-10-10T00:00:00Z",
            ),
            CLERK,
        )
        cycle = validate_success(resp, expected_status=201)
        assert cycle["status"] == "OPEN"
        assert cycle["cycle_index"] == 2, (
            f"cycle_index must be current_billing_epoch + 1 after one close, got {cycle['cycle_index']}"
        )
