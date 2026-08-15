"""Service-day epoch: dispatch, OCC lock, reconcile checkpoint, doubling
decisions, day cancellation, and contract termination cascade."""
from test_helpers import (
    ApiErrorId,
    assert_coverage_invariant,
    build_service_day,
    confirm_assignment,
    create_active_contract,
    create_approved_charter,
    create_contract,
    create_district,
    create_route,
    create_service_day,
    get_day_assignments,
    get_success_data,
    lock_service_day,
    make_district_admin_headers,
    make_driver_headers,
    run_assignment,
    setup_ops_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import HR, OPS


class TestLockStateRules:
    def test_invalid_transition_lock_from_scheduled_returns_409(self, api):
        """PRD section 3.2: "Locking moves `DISPATCH_OPEN` to `LOCKED` and is
        OCC-guarded per §2.7: the request carries `expected_service_day_version`,
        a mismatch is rejected with `ERR_STALE_VERSION`, and a successful lock
        increments the version."
        PRD section 2.8: "7. **From-state validity.** The entity must be in a
        state from which the requested transition exists, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/invalid_transition_lock_from_scheduled_returns_409
        """
        ctx = setup_ops_scenario(district_name="D-SM4", with_driver=False,
                                 with_bus=False)
        day = create_service_day(ctx["contract"]["id"], "2026-06-01")

        resp = api.lock_service_day(
            day["id"], {"expected_service_day_version": day["version"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        fetched = validate_success(api.get_service_day(day["id"], OPS))
        assert fetched["status"] == "SCHEDULED"

    def test_occ_service_day_lock_stale_version_returns_412(self, api):
        """PRD section 2.7: "Locking a ServiceDay requires
        `expected_service_day_version`. A lock issued against a stale view of
        the day — one that does not reflect confirms or cancellations that have
        since landed — is rejected with `ERR_STALE_VERSION` (HTTP 412), so a lock
        never freezes a state the caller never observed."
        PRD section 2.4: "`version`, an integer that starts at its initial value
        and increments by one on every mutation, including system-driven
        mutations caused by cascades and clock advancement."

        Design: Corner/cross_cutting_layers/occ_service_day_lock_stale_version_returns_412
        """
        ctx = setup_ops_scenario(district_name="D-CC1")
        day = create_service_day(ctx["contract"]["id"], "2026-06-01")
        stale_version = day["version"]
        get_success_data(api.open_dispatch(day["id"], OPS))
        assignments = get_day_assignments(day["id"])
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"],
                           ctx["bus"]["id"])
        current = get_success_data(api.get_service_day(day["id"], OPS))
        assert current["version"] > stale_version, (
            "open-dispatch and the confirm recompute each bumped the version")

        resp = api.lock_service_day(
            day["id"], {"expected_service_day_version": stale_version}, OPS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        locked = validate_success(api.lock_service_day(
            day["id"], {"expected_service_day_version": current["version"]}, OPS))
        assert locked["status"] == "LOCKED", "rebased on the observed version"


class TestReconcileCheckpoint:
    def test_error_assignments_in_flight_on_reconcile_returns_422(self, api):
        """PRD section 3.5: "`ContractorOps` reconciles a `LOCKED` day to
        `RECONCILED`, but only once no assignment on the day remains `EN_ROUTE`
        — an in-flight run blocks the reconcile with `ERR_ASSIGNMENTS_IN_FLIGHT`
        (HTTP 422)."

        Design: Corner/errors/error_assignments_in_flight_on_reconcile_returns_422
        """
        ctx = setup_ops_scenario(district_name="D-ERR6")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        get_success_data(api.start_assignment(
            assignments[0]["id"], make_driver_headers(ctx["driver"]["id"])))
        lock_service_day(day["id"])

        resp = api.reconcile_service_day(day["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENTS_IN_FLIGHT, 422)
        fetched = validate_success(api.get_service_day(day["id"], OPS))
        assert fetched["status"] == "LOCKED"

    def test_reconcile_checkpoint_finalizes_billable(self, api):
        """PRD section 3.5: "Reconcile performs final accounting: each
        assignment's `billable` flag is set true exactly when its status is
        `COMPLETED`; assignments still `PLANNED` or `CONFIRMED` at this point are
        treated as uncovered and bill nothing."
        PRD section 3.5: "The day's `shortage_credit_cents` is computed per the
        contract's `penalty_mode`: under `FLAT_PER_ROUTE`, the uncovered count
        multiplied by `shortage_penalty_flat_cents`; under `PER_STUDENT_MINUTE`,
        the sum over each uncovered assignment of its route's `student_count`
        multiplied by `assumed_minutes_per_missed_route` multiplied by
        `shortage_penalty_per_student_minute_cents`."

        Design: Corner/cross_cutting_layers/reconcile_checkpoint_finalizes_billable
        """
        ctx = setup_ops_scenario(district_name="D-CC2",
                                 routes=[(420, 480, 40), (480, 540, 30)])
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        confirm_assignment(assignments[1]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        run_assignment(assignments[0]["id"], ctx["driver"]["id"], 420, 480, 60)
        # assignments[1] stays CONFIRMED — never run.
        lock_service_day(day["id"])

        reconciled = validate_success(api.reconcile_service_day(day["id"], OPS))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["covered_routes"] == 1
        assert reconciled["uncovered_routes"] == 1
        assert reconciled["shortage_credit_cents"] == 15000, (
            "FLAT_PER_ROUTE x 1 uncovered route")

        a1 = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        a2 = validate_success(api.get_assignment(assignments[1]["id"], OPS))
        assert a1["billable"] is True, "COMPLETED bills"
        assert a2["billable"] is False, "CONFIRMED but never run does not bill"


class TestDoublingDecision:
    def _setup_lockable_shortage_day(self, api):
        ctx = setup_ops_scenario(district_name="D-INV1",
                                 routes=[(420, 480, 40), (480, 540, 30)])
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-03")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        pre = get_success_data(api.get_service_day(day["id"], OPS))
        lock_service_day(day["id"])
        return ctx, day, assignments, pre

    def test_doubling_decision_confirms_uncovered_with_shifted_window(self, api):
        """PRD section 3.5: "An accepted decision confirms the uncovered
        assignment with the absorbing driver and bus copied over, sets
        `is_doubled` true, points `doubled_after_assignment_id` at the absorbing
        assignment, and shifts the planned window: `planned_start_minute` becomes
        the absorbing assignment's planned end, and `planned_end_minute` becomes
        that start plus the uncovered route's own duration."

        Design: Difficulty/compensating_invariant/doubling_conserves_route_coverage
        """
        ctx, day, assignments, _pre = self._setup_lockable_shortage_day(api)
        doubled = validate_success(api.post_doubling_decision(
            day["id"], {"uncovered_assignment_id": assignments[1]["id"],
                        "absorbing_assignment_id": assignments[0]["id"]}, OPS))
        assert doubled["status"] == "CONFIRMED"
        assert doubled["is_doubled"] is True
        assert doubled["doubled_after_assignment_id"] == assignments[0]["id"]
        assert doubled["driver_id"] == ctx["driver"]["id"]
        assert doubled["bus_id"] == ctx["bus"]["id"]
        assert doubled["planned_start_minute"] == 480, (
            "shifted to the absorbing assignment's planned end")
        assert doubled["planned_end_minute"] == 540, "plus the 60-minute route"

    def test_doubling_conserves_route_coverage_invariant(self, api):
        """PRD section 3.2: "From then on the system maintains `covered_routes`
        — assignments of the day with a `driver_id` set and status `CONFIRMED`,
        `EN_ROUTE`, or `COMPLETED` — and `uncovered_routes` as the required count
        minus the covered count, with `shortage_flag` true exactly when anything
        is uncovered."
        PRD section 3.5: "The driver's weekly projection and the day's coverage
        counts recompute accordingly."

        Design: Difficulty/compensating_invariant/doubling_conserves_route_coverage
        """
        ctx, day, assignments, pre = self._setup_lockable_shortage_day(api)
        assert pre["required_routes"] == 2
        assert pre["covered_routes"] == 1
        assert pre["uncovered_routes"] == 1
        assert_coverage_invariant(pre)

        validate_success(api.post_doubling_decision(
            day["id"], {"uncovered_assignment_id": assignments[1]["id"],
                        "absorbing_assignment_id": assignments[0]["id"]}, OPS))

        post = get_success_data(api.get_service_day(day["id"], OPS))
        assert post["required_routes"] == 2
        assert post["covered_routes"] == 2
        assert post["uncovered_routes"] == 0
        assert_coverage_invariant(post)


class TestDoublingInfeasible:
    def test_error_doubling_infeasible_delay_returns_422(self, api):
        """PRD section 3.5: "The decision is feasible only when the absorbing
        assignment is `CONFIRMED` on the same service day; when the absorbing bus
        seats at least the uncovered route's `student_count`; when the absorbing
        assignment's `planned_end_minute` is no later than the uncovered route's
        `am_start_minute` plus 45 minutes, the maximum doubling delay; and when
        the absorbing driver's projected weekly minutes plus the uncovered run's
        planned minutes stay within the 2700-minute hard cap."
        PRD section 3.5: "Feasibility failures are rejected with
        `ERR_DOUBLING_INFEASIBLE` (HTTP 422), and a hard-cap breach with
        `ERR_DRIVER_HOURS_CAP_EXCEEDED`."

        Design: Corner/errors/error_doubling_infeasible_delay_returns_422
        """
        ctx = setup_ops_scenario(district_name="D-ERR21",
                                 routes=[(420, 1000, 40), (900, 960, 30)])
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        lock_service_day(day["id"])

        resp = api.post_doubling_decision(
            day["id"], {"uncovered_assignment_id": assignments[1]["id"],
                        "absorbing_assignment_id": assignments[0]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_DOUBLING_INFEASIBLE, 422)

        fetched = validate_success(api.get_assignment(assignments[1]["id"], OPS))
        assert fetched["status"] == "PLANNED"
        assert fetched["is_doubled"] is False


class TestDoublingOvertimeWindow:
    def test_doubling_overtime_threshold_window(self, api):
        """PRD section 3.5: "A plain confirmation requires the projection to be
        at most 2400 minutes — forty hours — with exactly 2400 passing. Route
        doubling, described below, is the only sanctioned way past the soft cap:
        a doubling decision may push the projection beyond 2400 but never beyond
        the hard cap of 2700 minutes — forty-five hours — with exactly 2700
        passing and anything higher rejected with `ERR_DRIVER_HOURS_CAP_EXCEEDED`
        (HTTP 422)."

        Design: Corner/cross_cutting_layers/doubling_overtime_threshold_window
        """
        # Route creation order fixes the assignment listing order on every day:
        # data[0] is the 600-minute run, data[1] the 60-minute run.
        ctx = setup_ops_scenario(district_name="D-CC3",
                                 routes=[(420, 1020, 40), (1020, 1080, 30)])
        driver_id = ctx["driver"]["id"]
        bus_id = ctx["bus"]["id"]

        # 2026-06-01..04 are Monday..Thursday of one ISO week; each day's
        # 600-minute run is confirmed for the same driver.
        day4 = None
        b4 = None
        for date in ("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"):
            day, assignments = build_service_day(ctx["contract"]["id"], date)
            confirmed = confirm_assignment(assignments[0]["id"], driver_id, bus_id)
            if date == "2026-06-04":
                day4, b4 = day, assignments[1]
        # The Thursday confirm is the fourth 600-minute run in the same ISO
        # week: it projects exactly 2400 and must pass the inclusive soft cap.
        assert confirmed["status"] == "CONFIRMED", (
            "exactly 2400 projected minutes passes the soft cap")

        lock_service_day(day4["id"])
        doubled = validate_success(api.post_doubling_decision(
            day4["id"], {"uncovered_assignment_id": b4["id"],
                         "absorbing_assignment_id": confirmed["id"]}, OPS))
        assert doubled["status"] == "CONFIRMED", (
            "doubling may exceed the soft cap up to the 2700 hard cap; "
            "2400 + 60 = 2460 stays under it")

        # A plain confirmation on Friday projects 2460 + 600 = 3060 > 2400.
        _day5, day5_assignments = build_service_day(ctx["contract"]["id"], "2026-06-05")
        resp = api.confirm_assignment(
            day5_assignments[0]["id"], {"driver_id": driver_id, "bus_id": bus_id}, OPS)
        validate_error(resp, ApiErrorId.ERR_DRIVER_HOURS_CAP_EXCEEDED, 422)


class TestServiceDayCancel:
    def test_service_day_cancel_cascades_to_assignments(self, api):
        """PRD section 3.2: "Weather and district closures cancel a day outright:
        from `SCHEDULED`, `DISPATCH_OPEN`, or `LOCKED`, `ContractorOps` cancels
        with a `cancellation_reason` of `WEATHER` or `DISTRICT_CLOSURE`. Every
        assignment of the day in `PLANNED` or `CONFIRMED` is cancelled with
        reason `WEATHER`, and a cancelled day is excluded from invoice billing
        under both variants and from shortage credit entirely."

        Design: Corner/state_machines/service_day_cancel_cascades_to_assignments
        """
        ctx = setup_ops_scenario(district_name="D-SM8")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])

        cancelled = validate_success(api.cancel_service_day(
            day["id"], {"cancellation_reason": "WEATHER"}, OPS))
        assert cancelled["status"] == "CANCELLED"

        asg = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        assert asg["status"] == "CANCELLED", "cascade down"
        assert asg["cancellation_reason"] == "WEATHER"


class TestContractTerminateCascade:
    def test_contract_terminate_full_cascade(self, api):
        """PRD section 3.1: "The owning `DistrictAdmin` may terminate an `ACTIVE`
        contract, optionally supplying a `reason`, and the cascade is total:
        every route of the contract in `ACTIVE` or `SUSPENDED` status becomes
        `ARCHIVED`; every service day in `SCHEDULED`, `DISPATCH_OPEN`, or
        `LOCKED` becomes `CANCELLED` under the contract-termination cause; every
        assignment on those days in `PLANNED` or `CONFIRMED` becomes `CANCELLED`
        with `cancellation_reason` `CONTRACT_TERMINATED`; and every charter trip
        of the contract in `REQUESTED`, `QUOTED`, `APPROVED`, or `SCHEDULED`
        becomes `CANCELLED` with `cancel_fee_cents` zero and `refund_cents` equal
        to the full `deposit_cents` — termination is fee-free to the district."

        Design: Corner/state_machines/contract_terminate_full_cascade
        """
        ctx = setup_ops_scenario(district_name="D-SM9")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        charter = create_approved_charter(ctx["contract"]["id"], ctx["district"]["id"],
                                          deposit_cents=5000)

        district_headers = make_district_admin_headers(ctx["district"]["id"])
        terminated = validate_success(api.terminate_contract(
            ctx["contract"]["id"], {"reason": "District consolidated"},
            district_headers))
        assert terminated["status"] == "TERMINATED"

        route = validate_success(api.get_route(ctx["routes"][0]["id"], OPS))
        assert route["status"] == "ARCHIVED"

        day_after = validate_success(api.get_service_day(day["id"], OPS))
        assert day_after["status"] == "CANCELLED"

        asg = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        assert asg["status"] == "CANCELLED"
        assert asg["cancellation_reason"] == "CONTRACT_TERMINATED"

        ch = validate_success(api.get_charter_trip(charter["id"], OPS))
        assert ch["status"] == "CANCELLED"
        assert ch["cancel_fee_cents"] == 0
        assert ch["refund_cents"] == 5000, "full deposit refund on termination"


class TestContractGates:
    def test_error_contract_not_active_on_service_day_returns_409(self, api):
        """PRD section 3.2: "`ContractorOps` creates one with a `contract_id`
        and a `service_date`; the contract must be `ACTIVE` (else
        `ERR_CONTRACT_NOT_ACTIVE`), the date must fall within the contract's
        `start_date`-to-`end_date` term inclusive (else
        `ERR_OUTSIDE_CONTRACT_TERM`, HTTP 422), and one contract may not have two
        days on the same date (else `ERR_SERVICE_DAY_DATE_CONFLICT`)."

        Design: Corner/errors/error_contract_not_active_on_service_day_returns_409
        """
        district = create_district(name="D-ERR8")
        contract = create_contract(district["id"], bid_reference="BID-E8")
        get_success_data(api.submit_contract(contract["id"], OPS))
        awarded = get_success_data(api.award_contract(
            contract["id"], make_district_admin_headers(district["id"])))
        assert awarded["status"] == "AWARDED"

        resp = api.create_service_day(
            {"contract_id": contract["id"], "service_date": "2026-06-01"}, OPS)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)

    def test_error_contract_not_yet_started_on_activate_returns_409(self, api):
        """PRD section 3.1: "An awarded contract goes live when the contractor
        activates it, but only once the logical clock date has reached the
        contract's `start_date`; activating earlier is rejected with
        `ERR_CONTRACT_NOT_YET_STARTED`."
        PRD section 2.5: "At server startup the clock is exactly
        `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Corner/errors/error_contract_not_yet_started_on_activate_returns_409
        """
        district = create_district(name="D-ERR9")
        contract = create_contract(district["id"], bid_reference="BID-E9",
                                   start_date="2026-06-01", end_date="2026-12-31")
        get_success_data(api.submit_contract(contract["id"], OPS))
        get_success_data(api.award_contract(
            contract["id"], make_district_admin_headers(district["id"])))

        resp = api.activate_contract(contract["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_YET_STARTED, 409)
        fetched = validate_success(api.get_contract(contract["id"], OPS))
        assert fetched["status"] == "AWARDED"

    def test_error_outside_contract_term_returns_422(self, api):
        """PRD section 3.2: "the date must fall within the contract's
        `start_date`-to-`end_date` term inclusive (else `ERR_OUTSIDE_CONTRACT_TERM`, HTTP 422)"

        Design: Corner/errors/error_outside_contract_term_returns_422
        """
        district = create_district(name="D-ERR23")
        contract = create_active_contract(district["id"], bid_reference="BID-E23")

        resp = api.create_service_day(
            {"contract_id": contract["id"], "service_date": "2027-01-15"}, OPS)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_CONTRACT_TERM, 422)

    def test_error_service_day_date_conflict_triggerable(self, api):
        """PRD section 3.2: "and one contract may not have two days on the same
        date (else `ERR_SERVICE_DAY_DATE_CONFLICT`)."

        Design: Corner/errors/error_service_day_date_conflict_triggerable
        """
        district = create_district(name="D-ERR4")
        contract = create_active_contract(district["id"], bid_reference="BID-E4")
        create_service_day(contract["id"], "2026-06-01")

        resp = api.create_service_day(
            {"contract_id": contract["id"], "service_date": "2026-06-01"}, OPS)
        validate_error(resp, ApiErrorId.ERR_SERVICE_DAY_DATE_CONFLICT, 409)

    def test_error_duplicate_route_code_triggerable(self, api):
        """PRD section 3.2: "Under an `ACTIVE` contract, `ContractorOps` defines
        Routes, each created `ACTIVE` with a `route_code` unique within the
        contract among non-archived routes — a duplicate is rejected with `ERR_DUPLICATE_ROUTE_CODE`"

        Design: Corner/errors/error_duplicate_route_code_triggerable
        """
        district = create_district(name="D-ERR1")
        contract = create_active_contract(district["id"], bid_reference="BID-E1")
        create_route(contract["id"], route_code="R1")

        resp = api.create_route(
            {"contract_id": contract["id"], "route_code": "R1",
             "school_site": "Other", "am_start_minute": 500, "am_end_minute": 560,
             "student_count": 10},
            OPS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROUTE_CODE, 409)


class TestServiceDayRoleDenial:
    def test_rbac_hr_recruiter_cannot_lock_service_day_returns_403(self, api):
        """PRD section 2.1: "A request whose role is not in the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /busops/service-days/{id}/lock is authorized for
        ContractorOps only.

        Design: Corner/rbac/rbac_hr_recruiter_cannot_lock_service_day_returns_403
        """
        ctx = setup_ops_scenario(district_name="D-RB1", with_driver=False,
                                 with_bus=False)
        day = create_service_day(ctx["contract"]["id"], "2026-06-01")
        opened = get_success_data(api.open_dispatch(day["id"], OPS))

        resp = api.lock_service_day(
            day["id"], {"expected_service_day_version": opened["version"]}, HR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        fetched = validate_success(api.get_service_day(day["id"], OPS))
        assert fetched["status"] == "DISPATCH_OPEN", "unchanged"
