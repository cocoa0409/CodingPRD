"""Operations checkpoints: sweeps, aggregates, SLA verdict, comms lifecycle.

Covers PRD section 3.9 (four-step sweep, aging buckets, SLA finalization)
and the AMI comms dimension of sections 3.1/3.4.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_iso_instant_equal,
    capture_read_payload,
    create_billing_period,
    create_meter,
    create_ops_snapshot_payload,
    create_route,
    generate_estimate_for_stop,
    get_account,
    get_hazard_flag,
    get_meter,
    get_route_stops,
    get_stop,
    ingest_ami_read,
    make_field_technician_headers,
    make_investigator_headers,
    mark_stop_no_read_as,
    open_investigation,
    open_period_window,
    report_hazard,
    run_ops_snapshot,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_ami_account_with_history,
    setup_in_progress_route,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]


class TestSnapshotAggregates:
    def test_ops_snapshot_aggregate_counts(self, api):
        """PRD section 3.9: "Step four counts the world as of the snapshot.
        `eligible_stop_count` counts stops on non-`CANCELLED` routes whose
        `scheduled_date` is on or before the snapshot date, excluding
        `CANCELLED` stops; `covered_stop_count` counts the eligible stops in
        `VALIDATED`, `ESTIMATED`, or `SUPERSEDED`; `backlog_count` counts
        stops in `PENDING` or `NO_READ_PENDING` on non-`CANCELLED` routes"
        PRD section 3.9: "From these, `read_rate_percent` is the gross rate —
        covered over eligible, times one hundred, rounded half-up to two
        decimal places, null when no stops are eligible — and
        `net_read_rate_percent` is the net rate, covered over the eligible
        count less the `SKIPPED_HAZARD` stops, null when that denominator is
        zero."
        PRD section 3.9: "The breach test — a field that is null while the
        snapshot remains `DRAFT` — uses exact integer arithmetic on the raw
        counts, never the rounded display rate"

        Design: Corner/entities/entity_computed_ops_snapshot_aggregate_counts
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account_1, meter_1 = setup_account_with_installed_meter(
            "C-0005", "C23", service_address="5 Agg Ave"
        )
        account_2, meter_2 = setup_account_with_installed_meter(
            "C-0006", "C23", service_address="6 Agg Ave"
        )
        period, route, stops, tech = setup_in_progress_route(
            "C23",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            route_shift="FULL",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Agg Tech",
        )
        assert len(stops) == 2
        read = validate_success(
            api.capture_read(
                stops[0]["id"],
                capture_read_payload(
                    meter_1["id"], 100, "2026-08-03T09:00:00Z", stops[0]["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        validate_success(api.validate_read(read["id"], BILLING), 200)
        mark_stop_no_read_as(stops[1]["id"], tech["id"])

        snapshot = run_ops_snapshot("2026-08-04T00:00:00Z")
        assert snapshot["snapshot_status"] == "DRAFT"
        assert snapshot["eligible_stop_count"] == 2
        assert snapshot["covered_stop_count"] == 1
        assert snapshot["backlog_count"] == 1
        assert snapshot["read_rate_percent"] == pytest.approx(50.00, abs=0.001)
        assert snapshot["net_read_rate_percent"] == pytest.approx(50.00, abs=0.001)
        assert snapshot["validated_read_count"] == 1
        assert snapshot["estimated_read_count"] == 0
        assert snapshot["sla_breach"] is None

    def test_ops_snapshot_finalize_is_terminal(self, api):
        """PRD section 3.9: "A `MeterOpsAdmin` finalizes a `DRAFT` snapshot,
        moving `snapshot_status` to the terminal `FINALIZED` state and locking
        in `sla_breach`."
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/state_machines/ops_snapshot_finalize_is_terminal
        """
        snapshot = run_ops_snapshot("2026-08-02T00:00:00Z")
        finalized = validate_success(api.finalize_ops_snapshot(snapshot["id"], ADMIN), 200)
        assert finalized["snapshot_status"] == "FINALIZED"

        res = api.finalize_ops_snapshot(snapshot["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)


class TestEndpointCommsDegradation:
    def test_ami_miss_threshold_two_degraded_three_non_communicating(self, api):
        """PRD section 3.9: "Otherwise the meter's `consecutive_missed_days`
        is incremented by one: a first miss moves a `COMMUNICATING` meter to
        `DEGRADED`, a second consecutive miss leaves it `DEGRADED`, and on the
        third consecutive miss a meter in `COMMUNICATING` or `DEGRADED`
        becomes `NON_COMMUNICATING` with `non_communicating_since` set to
        `snapshot_at` — three consecutive misses always pass through
        `DEGRADED`; no direct jump exists."

        Design: Corner/calculations/ami_miss_threshold_two_degraded_three_non_communicating
        """
        account, meter = setup_account_with_installed_meter(
            "C-0055", "C55", meter_type="AMI", service_address="55 Miss Ave"
        )
        run_ops_snapshot("2026-08-02T00:00:00Z")
        run_ops_snapshot("2026-08-03T00:00:00Z")
        after_two = get_meter(meter["id"])
        assert after_two["endpoint_comms_status"] == "DEGRADED"
        assert after_two["consecutive_missed_days"] == 2

        run_ops_snapshot("2026-08-04T00:00:00Z")
        after_three = get_meter(meter["id"])
        assert after_three["endpoint_comms_status"] == "NON_COMMUNICATING"
        assert after_three["consecutive_missed_days"] == 3
        assert_iso_instant_equal(
            after_three["non_communicating_since"], "2026-08-04T00:00:00Z"
        )

    def test_endpoint_failed_at_exactly_fourteen_days(self, api):
        """PRD section 3.9: "A meter already `NON_COMMUNICATING` whose
        `non_communicating_since` is at least fourteen days before
        `snapshot_at` — exactly fourteen days qualifies; the boundary is
        inclusive — becomes `FAILED` and is from that moment eligible for
        replacement-campaign enrollment."

        Design: Corner/calculations/endpoint_failed_at_exactly_fourteen_days
        """
        account, meter = setup_account_with_installed_meter(
            "C-0056", "C56", meter_type="AMI", service_address="56 Fail Ave"
        )
        run_ops_snapshot("2026-08-02T00:00:00Z")
        run_ops_snapshot("2026-08-03T00:00:00Z")
        run_ops_snapshot("2026-08-04T00:00:00Z")  # NON_COMMUNICATING since 08-04
        run_ops_snapshot("2026-08-17T00:00:00Z")  # 13 days: still not FAILED
        assert get_meter(meter["id"])["endpoint_comms_status"] == "NON_COMMUNICATING"

        run_ops_snapshot("2026-08-18T00:00:00Z")  # exactly 14 days: FAILED
        assert get_meter(meter["id"])["endpoint_comms_status"] == "FAILED"


class TestMeterParallelDimensions:
    def _parallel_dimension_scenario(self, api):
        """AMI meter driven COMMUNICATING -> DEGRADED -> NON_COMMUNICATING via
        three missed snapshots, then tamper SUSPECTED via an investigation,
        then an AMI read arrives. Returns (account, meter, comms_mid, read)."""
        account, meter = setup_account_with_installed_meter(
            "A-5001", "C11P", meter_type="AMI", service_address="5 Cedar Ave"
        )
        run_ops_snapshot("2026-08-02T00:00:00Z")
        run_ops_snapshot("2026-08-03T00:00:00Z")
        run_ops_snapshot("2026-08-04T00:00:00Z")
        comms_mid = get_meter(meter["id"])["endpoint_comms_status"]
        open_investigation(
            account["id"], meter["id"], indication_type="TAMPER_FLAG", opened_by="inv-002"
        )
        read = ingest_ami_read(meter["id"], 5000, "2026-08-05T10:00:00Z")
        return account, meter, comms_mid, read

    def test_meter_comms_recovers_independent_of_tamper(self, api):
        """PRD section 3.4: "Two further effects follow: when the ingested
        read's `read_at` is the latest among the account's validated reads,
        the account's `last_validated_read_value` and
        `last_validated_read_at` advance; and the meter's comms dimension
        recovers — a meter in `DEGRADED`, `NON_COMMUNICATING`, or `FAILED`
        returns to `COMMUNICATING` with `consecutive_missed_days` reset to
        zero and `non_communicating_since` cleared to null."
        PRD section 3.4: "the created `AMI_REMOTE` read is auto-validated."

        Design: Difficulty/non_linear_state_machine/meter_three_parallel_dimensions_evolve_independently
        """
        _account, meter, comms_mid, read = self._parallel_dimension_scenario(api)
        assert comms_mid == "NON_COMMUNICATING"

        meter_after = get_meter(meter["id"])
        assert meter_after["endpoint_comms_status"] == "COMMUNICATING"
        assert meter_after["consecutive_missed_days"] == 0
        assert meter_after["non_communicating_since"] is None

        assert read["read_status"] == "VALIDATED"
        assert read["read_source"] == "AMI_REMOTE"

    def test_meter_tamper_dimension_unaffected_by_comms_recovery(self, api):
        """PRD section 3.1: "Meters are physical assets tracked on three
        independent state dimensions that evolve in parallel on one record."
        PRD section 3.1: "The comms dimension walks `COMMUNICATING`,
        `DEGRADED`, `NON_COMMUNICATING`, and `FAILED` under the checkpoint
        sweep (§3.9), while the tamper dimension walks `NONE`, `SUSPECTED`,
        and `CONFIRMED` under investigations (§3.6); the lifecycle dimension
        moves only through installs, exchanges, and retirement."

        Design: Difficulty/non_linear_state_machine/meter_three_parallel_dimensions_evolve_independently
        """
        _account, meter, comms_mid, _read = self._parallel_dimension_scenario(api)
        assert comms_mid == "NON_COMMUNICATING"

        meter_after = get_meter(meter["id"])
        # comms recovered, but the tamper and lifecycle dimensions are untouched
        assert meter_after["endpoint_comms_status"] == "COMMUNICATING"
        assert meter_after["tamper_status"] == "SUSPECTED"
        assert meter_after["meter_status"] == "IN_SERVICE"


class TestNoReadEscalation:
    def _escalation_contrast_scenario(self, api):
        """Account A1 (one prior estimate -> streak 1) and A2 (streak 0), both
        NO_READ_PENDING on an August route; snapshot at 2026-08-05.
        Returns (acct_1, acct_2, stop_a1, stop_a2)."""
        set_logical_clock("2026-06-01T00:00:00Z")
        acct_1, meter_1 = setup_ami_account_with_history(
            "A-3001", "C09",
            [(9700, "2026-06-01T10:00:00Z"), (10000, "2026-07-01T10:00:00Z")],
            service_address="1 Pine St",
        )
        acct_2, meter_2 = setup_ami_account_with_history(
            "A-3002", "C09",
            [(5000, "2026-06-01T10:00:00Z"), (5400, "2026-07-01T10:00:00Z")],
            service_address="2 Pine St",
        )
        run_ops_snapshot("2026-07-20T00:00:00Z")
        run_ops_snapshot("2026-07-21T00:00:00Z")

        # July period: A1's stop is estimated (streak -> 1)
        period_1, route_1, stops_1, tech = setup_in_progress_route(
            "C09",
            "2026-07-01", "2026-07-31", "2026-07-22", "2026-07-28", "2026-07-31",
            "2026-07-22",
            route_shift="FULL",
            open_clock="2026-07-22T08:00:00Z",
            tech_name="Tech Three",
        )
        stop_1_a1 = next(s for s in stops_1 if s["service_account_id"] == acct_1["id"])
        mark_stop_no_read_as(stop_1_a1["id"], tech["id"])
        generate_estimate_for_stop(stop_1_a1["id"])

        # August period: both stops marked NO_READ_PENDING
        period_2, route_2, stops_2, _tech = setup_in_progress_route(
            "C09",
            "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31",
            "2026-08-03",
            route_shift="FULL",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Tech Three",
        )
        stop_a1 = next(s for s in stops_2 if s["service_account_id"] == acct_1["id"])
        stop_a2 = next(s for s in stops_2 if s["service_account_id"] == acct_2["id"])
        mark_stop_no_read_as(stop_a1["id"], _tech["id"])
        mark_stop_no_read_as(stop_a2["id"], _tech["id"])

        run_ops_snapshot("2026-08-05T00:00:00Z")
        return acct_1, acct_2, stop_a1, stop_a2

    def test_escalation_creates_reread_for_streaked_account(self, api):
        """PRD section 3.9: "The score starts from a base of 10, adds 25 for
        each unit of the account's `estimated_read_streak`, adds 5 for each
        day by which seven days exceeds the number of days from the snapshot
        date to the `read_window_close_date` — that day count is measured as
        close date minus snapshot date and turns negative once the close has
        passed, so this term is zero while seven or more days remain and keeps
        growing past the close — and adds 15 when the account carries an
        `ACTIVE` hazard flag; the total is capped at 100. When the score
        reaches at least 40 — the threshold boundary is inclusive — and no
        `RE_READ` work order in `OPEN`, `DISPATCHED`, `IN_PROGRESS`, or
        `REWORK` already exists for the stop, the sweep auto-creates a
        `RE_READ` work order in `OPEN` linked to the stop, scheduled on the
        snapshot date with a `FULL` shift."

        Design: Difficulty/combinatorial_formula/escalation_score_multi_input_threshold_contrast
        """
        acct_1, _acct_2, stop_a1, _stop_a2 = self._escalation_contrast_scenario(api)
        assert get_account(acct_1["id"])["estimated_read_streak"] == 1

        # score = 10 + 25*1 + 5*(7-2) = 60 >= 40 -> order auto-created
        orders, meta = validate_paginated(
            api.list_work_orders(DISPATCHER, params={"route_stop_id": stop_a1["id"]})
        )
        assert meta["total_count"] == 1
        assert orders[0]["work_order_type"] == "RE_READ"
        assert orders[0]["work_order_status"] == "OPEN"
        assert orders[0]["scheduled_date"] == "2026-08-05"
        assert orders[0]["work_shift"] == "FULL"

    def test_escalation_skips_zero_streak_account(self, api):
        """PRD section 3.9: "When the score reaches at least 40 — the
        threshold boundary is inclusive — and no `RE_READ` work order in
        `OPEN`, `DISPATCHED`, `IN_PROGRESS`, or `REWORK` already exists for
        the stop, the sweep auto-creates a `RE_READ` work order in `OPEN`
        linked to the stop, scheduled on the snapshot date with a `FULL`
        shift."

        Design: Difficulty/combinatorial_formula/escalation_score_multi_input_threshold_contrast
        """
        _acct_1, acct_2, _stop_a1, stop_a2 = self._escalation_contrast_scenario(api)
        assert get_account(acct_2["id"])["estimated_read_streak"] == 0

        # score = 10 + 0 + 5*(7-2) = 35 < 40 -> no order
        orders, meta = validate_paginated(
            api.list_work_orders(DISPATCHER, params={"route_stop_id": stop_a2["id"]})
        )
        assert meta["total_count"] == 0
        assert orders == []

    def test_escalation_threshold_exactly_40_creates_reread_order(self, api):
        """PRD section 3.9: "When the score reaches at least 40 — the
        threshold boundary is inclusive — and no `RE_READ` work order in
        `OPEN`, `DISPATCHED`, `IN_PROGRESS`, or `REWORK` already exists for
        the stop, the sweep auto-creates a `RE_READ` work order in `OPEN`
        linked to the stop, scheduled on the snapshot date with a `FULL`
        shift."

        Design: Corner/calculations/escalation_threshold_exactly_40_creates_reread_order
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0054", "C54", service_address="54 Esc Ave"
        )
        period, route, stops, tech = setup_in_progress_route(
            "C54",
            "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Esc Tech",
        )
        mark_stop_no_read_as(stops[0]["id"], tech["id"])

        # snapshot one day before the 08-07 close: 10 + 5*(7-1) = 40 >= 40
        run_ops_snapshot("2026-08-06T00:00:00Z")
        orders, meta = validate_paginated(
            api.list_work_orders(DISPATCHER, params={"route_stop_id": stops[0]["id"]})
        )
        assert meta["total_count"] == 1
        assert orders[0]["work_order_type"] == "RE_READ"
        assert orders[0]["work_order_status"] == "OPEN"
        assert orders[0]["scheduled_date"] == "2026-08-06"
        assert orders[0]["work_shift"] == "FULL"


class TestSlaEvaluation:
    def test_sla_breach_uses_integer_cross_multiplication_both_legs(self, api):
        """PRD section 3.9: "The breach test — a field that is null while the
        snapshot remains `DRAFT` — uses exact integer arithmetic on the raw
        counts, never the rounded display rate: the snapshot is in breach only
        when two hundred times the covered count is strictly less than one
        hundred ninety-seven times the eligible count, that is, when the true
        covered ratio falls strictly below 98.50 percent. Exact equality —
        two hundred times covered equal to one hundred ninety-seven times
        eligible, precisely 98.50 percent — is not a breach, and the verdict,
        once written at finalization, is locked thereafter."

        Design: Corner/calculations/sla_breach_uses_integer_cross_multiplication_both_legs
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        accounts, meters = [], []
        for i in range(1, 5):
            account, meter = setup_account_with_installed_meter(
                f"C-006{i}", "C58", service_address=f"6{i} Sla Ave"
            )
            accounts.append(account)
            meters.append(meter)
        period, route, stops, tech = setup_in_progress_route(
            "C58",
            "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31",
            "2026-08-03",
            route_shift="FULL",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="SLA Tech",
        )
        assert len(stops) == 4
        for stop, meter, value, at in [
            (stops[0], meters[0], 100, "2026-08-03T09:00:00Z"),
            (stops[1], meters[1], 200, "2026-08-03T09:10:00Z"),
            (stops[2], meters[2], 300, "2026-08-03T09:20:00Z"),
        ]:
            read = validate_success(
                api.capture_read(
                    stop["id"],
                    capture_read_payload(meter["id"], value, at, stop["version"]),
                    make_field_technician_headers(tech["id"]),
                ),
                201,
            )
            validate_success(api.validate_read(read["id"], BILLING), 200)
        mark_stop_no_read_as(stops[3]["id"], tech["id"])

        # S1: covered 3 of eligible 4 -> 3*200=600 < 4*197=788 -> breach
        snap_1 = run_ops_snapshot("2026-08-04T00:00:00Z")
        finalized_1 = validate_success(api.finalize_ops_snapshot(snap_1["id"], ADMIN), 200)
        assert finalized_1["sla_breach"] is True
        assert finalized_1["read_rate_percent"] == pytest.approx(75.00, abs=0.001)
        assert finalized_1["backlog_count"] == 1

        # Resolve the fourth stop, then S2: 4*200=800 >= 4*197 -> no breach
        stop_4 = get_stop(stops[3]["id"])
        read_4 = validate_success(
            api.capture_read(
                stop_4["id"],
                capture_read_payload(
                    meters[3]["id"], 400, "2026-08-04T09:00:00Z", stop_4["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        validate_success(api.validate_read(read_4["id"], BILLING), 200)

        snap_2 = run_ops_snapshot("2026-08-05T00:00:00Z")
        finalized_2 = validate_success(api.finalize_ops_snapshot(snap_2["id"], ADMIN), 200)
        assert finalized_2["sla_breach"] is False
        assert finalized_2["read_rate_percent"] == pytest.approx(100.00, abs=0.001)
        assert finalized_2["backlog_count"] == 0


class TestBacklogAging:
    def test_backlog_aging_inclusive_seven_day_boundary(self, api):
        """PRD section 3.9: "`backlog_aged_7plus_count` counts backlog stops
        whose `created_at` is at least seven days before `snapshot_at` — a
        stop created exactly seven days earlier counts as aged, the boundary
        inclusive."

        Design: Corner/calculations/backlog_aging_inclusive_seven_day_boundary
        """
        # Route (and its stops) created while the clock reads 2026-08-01T08:00.
        set_logical_clock("2026-08-01T08:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0065", "C59", service_address="65 Age Ave"
        )
        period = create_billing_period(
            "C59", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        stops = get_route_stops(route["id"])
        assert len(stops) == 1

        set_logical_clock("2026-08-03T08:00:00Z")
        open_period_window(period["id"])
        tech = validate_success(
            api.create_field_technician({"display_name": "Age Tech"}, ADMIN), 201
        )
        validate_success(
            api.assign_route(route["id"], {"technician_id": tech["id"]}, DISPATCHER), 200
        )
        validate_success(
            api.start_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        mark_stop_no_read_as(stops[0]["id"], tech["id"])

        # One second before the stop's created_at + 7 days: not yet aged.
        snap_early = run_ops_snapshot("2026-08-08T07:59:59Z")
        assert snap_early["backlog_count"] == 1
        assert snap_early["backlog_aged_7plus_count"] == 0

        # Exactly seven days after creation: aged (inclusive boundary).
        snap_exact = run_ops_snapshot("2026-08-08T08:00:00Z")
        assert snap_exact["backlog_aged_7plus_count"] == 1


class TestSweepOrder:
    def test_ops_sweep_order_hazard_expiry_before_escalation(self, api):
        """PRD section 3.9: "the system creates an OpsSnapshot in `DRAFT` and
        immediately executes its pinned four-step sweep in order: hazard
        expiry first, AMI comms evaluation second, no-read escalation scoring
        third, and aggregate counting with aging buckets fourth."
        PRD section 3.9: "adds 15 when the account carries an `ACTIVE` hazard
        flag; the total is capped at 100. When the score reaches at least 40 —
        the threshold boundary is inclusive — and no `RE_READ` work order in
        `OPEN`, `DISPATCHED`, `IN_PROGRESS`, or `REWORK` already exists for
        the stop, the sweep auto-creates a `RE_READ` work order in `OPEN`
        linked to the stop, scheduled on the snapshot date with a `FULL`
        shift."

        Design: Corner/complexity_layers/ops_sweep_order_hazard_expiry_before_escalation
        """
        # Hazard reported 2026-07-01T09:00 -> expires 2026-07-31T09:00.
        set_logical_clock("2026-07-01T09:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0133", "CE5", service_address="133 Sweep Rd"
        )
        tech = validate_success(
            api.create_field_technician({"display_name": "Sweep Tech"}, ADMIN), 201
        )
        flag = report_hazard(account["id"], tech["id"], hazard_type="DOG", severity="HIGH")

        period = create_billing_period(
            "CE5", "2026-08-01", "2026-08-31", "2026-08-01", "2026-08-04", "2026-08-31"
        )
        set_logical_clock("2026-08-01T08:00:00Z")
        open_period_window(period["id"])
        route = create_route(
            period["id"], "2026-08-01", route_shift="AM", two_person_crew=True
        )
        stops = get_route_stops(route["id"])
        assert len(stops) == 1
        validate_success(
            api.assign_route(route["id"], {"technician_id": tech["id"]}, DISPATCHER), 200
        )
        validate_success(
            api.start_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        mark_stop_no_read_as(stops[0]["id"], tech["id"])

        # Step 1 expires the flag (2026-07-31T09:00 < 2026-08-02T00:00), so the
        # step-3 score is 10 + 0 + 5*(7-2) = 35 < 40 and no order is created.
        snapshot = run_ops_snapshot("2026-08-02T00:00:00Z")
        assert get_hazard_flag(flag["id"])["flag_status"] == "EXPIRED"
        orders, meta = validate_paginated(
            api.list_work_orders(DISPATCHER, params={"route_stop_id": stops[0]["id"]})
        )
        assert meta["total_count"] == 0
        assert snapshot["backlog_count"] == 1
