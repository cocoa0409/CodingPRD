"""Annual requirement cycles, overdue cascade, and compliance holds."""
from test_helpers import (
    ApiErrorId,
    assert_cycle,
    assert_hold,
    assert_instant,
    complete_cycle_requirement,
    create_cycle_payload,
    cycle_completion_payload,
    get_employee,
    get_cycle,
    list_holds,
    make_cleared_employee,
    open_cycle,
    register_employee,
    set_clock,
    setup_overdue_cycle_hold,
    create_restriction,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCycleDueDateVariants:
    def test_calendar_year_due_date_pinned_to_year_end(self, api):
        """PRD §3.3: "Under `CALENDAR_YEAR`, `tb_due_date` is pinned to the end
        of the cycle year — December 31 of `cycle_year` at 23:59:59 UTC —
        regardless of completion history." and "The `fit_test_due_date` mirrors
        `tb_due_date` when the employee requires a respirator and is null
        otherwise."

        Design: Difficulty/dual_variant_calc/cycle_calendar_vs_anniversary_due_date
        """
        emp = make_cleared_employee("E-DV2A", job_category="TECH", department="LAB",
                                    hire_date="2025-03-10T00:00:00Z")
        cycle = open_cycle(emp["id"], cycle_year=2026, cycle_mode="CALENDAR_YEAR")
        assert_cycle(cycle)
        assert_instant(cycle["tb_due_date"], "2026-12-31T23:59:59")
        assert cycle["fit_test_due_date"] is None, (
            "requires_respirator is false: fit_test_due_date must be null"
        )

    def test_rolling_anniversary_anchors_to_hire_date(self, api):
        """PRD §3.3: "Under `ROLLING_ANNIVERSARY`, the system finds an anchor:
        the greatest `tb_completed_at` among the employee's other cycles whose
        `status` is `SATISFIED`, or the employee's `hire_date` when no
        satisfied prior cycle exists; `tb_due_date` is then exactly twelve
        calendar months after that anchor, preserving the day of month." and
        "An employee hired on March 10, 2025 with no satisfied prior cycle
        therefore falls due on March 10, 2026 — not at the end of the calendar
        year."

        Design: Difficulty/dual_variant_calc/cycle_calendar_vs_anniversary_due_date
        """
        emp = make_cleared_employee("E-DV2B", job_category="TECH", department="LAB",
                                    hire_date="2025-03-10T00:00:00Z")
        cycle = open_cycle(emp["id"], cycle_year=2026, cycle_mode="ROLLING_ANNIVERSARY")
        assert_cycle(cycle)
        assert_instant(cycle["tb_due_date"], "2026-03-10T00:00:00")
        assert cycle["fit_test_due_date"] is None


class TestCycleCreationGates:
    def test_cycle_create_requires_active_employee(self, api, compliance_headers):
        """PRD §3.3: "The employee must be `ACTIVE` at cycle creation
        (`ERR_EMPLOYEE_NOT_ACTIVE`)"

        Design: Corner/state_machines/cycle_create_requires_active_employee
        """
        emp = register_employee("E-SM19", full_name="Pre Place")
        assert emp["status"] == "PREPLACEMENT"
        resp = api.create_cycle(
            emp["id"], create_cycle_payload(cycle_year=2026), compliance_headers
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)
        assert get_employee(emp["id"])["status"] == "PREPLACEMENT"

    def test_second_open_cycle_rejected(self, api, compliance_headers):
        """PRD §3.3: "an employee may have at most one cycle in `OPEN` or
        `OVERDUE` at a time (`ERR_CYCLE_ALREADY_OPEN`)."

        Design: Corner/state_machines/cycle_second_open_rejected
        """
        emp = make_cleared_employee("E-SM6", full_name="One Cycle")
        first = open_cycle(emp["id"], cycle_year=2026, cycle_mode="CALENDAR_YEAR")
        assert first["status"] == "OPEN"

        resp = api.create_cycle(
            emp["id"],
            create_cycle_payload(cycle_year=2027, cycle_mode="ROLLING_ANNIVERSARY"),
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_ALREADY_OPEN)

        _data, meta = validate_paginated(
            api.list_cycles(compliance_headers, params={"employee_id": emp["id"]})
        )
        assert meta["total_count"] == 1


class TestCycleCompletions:
    def test_fit_test_completion_rejected_when_not_required(self, api,
                                                            nurse_headers):
        """PRD §3.3: "Recording a `FIT_TEST` completion for an employee whose
        `requires_respirator` is false is rejected with
        `ERR_FIT_TEST_NOT_REQUIRED`."

        Design: Corner/state_machines/fit_test_completion_when_not_required_rejected
        """
        emp = make_cleared_employee("E-SM5", full_name="No Resp",
                                    job_category="OTHER", department="ADM")
        cycle = open_cycle(emp["id"], cycle_year=2026)

        resp = api.record_cycle_completion(
            cycle["id"],
            cycle_completion_payload("FIT_TEST", completed_at="2026-08-01T00:00:00Z"),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FIT_TEST_NOT_REQUIRED)

        after = get_cycle(cycle["id"])
        assert after["status"] == "OPEN"
        assert after["fit_test_completed_at"] is None

    def test_completion_after_satisfied_rejected(self, api, nurse_headers):
        """PRD §3.3: "Each requirement can be completed once per cycle; a
        repeat completion is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cycle_completion_after_satisfied_rejected
        """
        emp = make_cleared_employee("E-SM4", full_name="Term Inal")
        cycle = open_cycle(emp["id"], cycle_year=2026)
        satisfied = complete_cycle_requirement(
            cycle["id"], "TB_SCREENING", "2026-08-01T00:00:00Z"
        )
        assert satisfied["status"] == "SATISFIED", (
            "TB-only employee satisfies the cycle on TB completion alone"
        )

        resp = api.record_cycle_completion(
            cycle["id"],
            cycle_completion_payload("TB_SCREENING", completed_at="2026-08-01T00:00:00Z"),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_cycle(cycle["id"])
        assert after["status"] == "SATISFIED"
        assert_instant(after["tb_completed_at"], "2026-08-01T00:00:00")


class TestOverdueThreshold:
    def test_cycle_overdue_strictly_after_due_date(self, api):
        """PRD §3.3: "a cycle becomes `OVERDUE` only when the current logical
        time is strictly later than `tb_due_date` while `tb_completed_at`
        remains unset, or — for respirator-requiring employees — strictly
        later than `fit_test_due_date` while `fit_test_completed_at` remains
        unset; on the due date itself the cycle stays `OPEN`." and "The
        overdue transition auto-creates a `ComplianceHold` in `ACTIVE` status
        for each missing obligation, with `reason` `TB_OVERDUE` or
        `FIT_TEST_OVERDUE` respectively"

        Design: Corner/complexity_layers/cycle_overdue_threshold_trigger
        """
        emp = make_cleared_employee("E-L4", full_name="Due Date",
                                    hire_date="2024-06-01T00:00:00Z")
        cycle = open_cycle(emp["id"], cycle_year=2026, cycle_mode="CALENDAR_YEAR")
        assert_instant(cycle["tb_due_date"], "2026-12-31T23:59:59")

        # At now == tb_due_date the strict boundary is not met: still OPEN.
        set_clock("2026-12-31T23:59:59Z")
        assert get_cycle(cycle["id"])["status"] == "OPEN"

        # One second later the cycle flips OVERDUE and the hold cascade fires.
        set_clock("2027-01-01T00:00:00Z")
        assert get_cycle(cycle["id"])["status"] == "OVERDUE"
        holds = list_holds(emp["id"], status="ACTIVE")
        assert len(holds) == 1
        assert holds[0]["reason"] == "TB_OVERDUE"
        assert holds[0]["cycle_id"] == cycle["id"]
        assert get_employee(emp["id"])["status"] == "SUSPENDED"


class TestHoldReleaseRequiresCycleSatisfied:
    def test_release_blocked_while_cycle_overdue(self, api, compliance_headers):
        """PRD §3.3: "for holds with `reason` `TB_OVERDUE` or
        `FIT_TEST_OVERDUE` the linked cycle must be `SATISFIED`, and for holds
        with `reason` `CAMPAIGN_DELINQUENT` the linked `participation_id` must
        reference a participation in `ADMINISTERED`, `DECLINED`, or `EXEMPTED`
        — an unmet underlying requirement is rejected with
        `ERR_UNDERLYING_REQUIREMENT_UNMET`."

        Design: Difficulty/cross_entity_state_dependency/hold_release_requires_cycle_satisfied
        """
        emp, cycle, hold = setup_overdue_cycle_hold("E-XD2", cycle_year=2025)
        assert get_cycle(cycle["id"])["status"] == "OVERDUE"

        resp = api.release_hold(hold["id"], {}, compliance_headers)
        validate_error(resp, ApiErrorId.ERR_UNDERLYING_REQUIREMENT_UNMET)

        # Hold and employee state unchanged by the failed release.
        hold_after = validate_success(api.get_hold(hold["id"], compliance_headers))
        assert hold_after["status"] == "ACTIVE"
        assert get_employee(emp["id"])["active_hold_count"] == 1

    def test_release_succeeds_after_late_completion(self, api, compliance_headers):
        """PRD §3.3: "Satisfaction moves the cycle from `OPEN` to `SATISFIED`,
        or from `OVERDUE` to `SATISFIED` — late completion is allowed — and is
        re-evaluated after every completion call and every clock advancement."
        and "A successful release transitions the hold `ACTIVE → RELEASED` (the
        hold's terminal state), stamps `released_at` and `released_by_user_id`,
        decrements the employee's `active_hold_count` by one, and recomputes
        the posture; when the count reaches zero and the employee is
        `SUSPENDED`, the employee automatically returns `SUSPENDED → ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/hold_release_requires_cycle_satisfied
        """
        emp, cycle, hold = setup_overdue_cycle_hold("E-XD2B", cycle_year=2025)

        complete_cycle_requirement(cycle["id"], "TB_SCREENING", "2026-08-01T00:00:01Z")
        assert get_cycle(cycle["id"])["status"] == "SATISFIED"

        released = validate_success(api.release_hold(hold["id"], {}, compliance_headers))
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None
        assert released["released_by_user_id"] is not None

        emp_after = get_employee(emp["id"])
        assert emp_after["status"] == "ACTIVE"
        assert emp_after["active_hold_count"] == 0
        assert emp_after["compliance_posture"] == "CLEAR"


class TestHoldApplyReleaseConservesCount:
    def test_overdue_cascade_applies_hold_and_suspends(self, api):
        """PRD §3.3: "Each new active hold increments the employee's
        `active_hold_count` by one; when the count rises from zero and the
        employee is `ACTIVE`, the employee automatically transitions `ACTIVE →
        SUSPENDED` and the posture recomputes to `ON_HOLD`"

        Design: Difficulty/compensating_invariant/hold_apply_release_conserves_count
        """
        emp = make_cleared_employee("E-CI1", full_name="Con Serve",
                                    hire_date="2024-06-01T00:00:00Z")
        assert emp["active_hold_count"] == 0 and emp["status"] == "ACTIVE"
        cycle = open_cycle(emp["id"], cycle_year=2025, cycle_mode="CALENDAR_YEAR")

        set_clock("2026-08-01T00:00:01Z")

        emp_mid = get_employee(emp["id"])
        assert emp_mid["active_hold_count"] == 1
        assert emp_mid["status"] == "SUSPENDED"
        assert emp_mid["compliance_posture"] == "ON_HOLD"
        holds = list_holds(emp["id"], status="ACTIVE")
        assert len(holds) == 1 and holds[0]["cycle_id"] == cycle["id"]

    def test_release_returns_count_and_status_to_pre_apply(self, api,
                                                           compliance_headers):
        """PRD §3.3: "A successful release transitions the hold `ACTIVE →
        RELEASED` (the hold's terminal state), stamps `released_at` and
        `released_by_user_id`, decrements the employee's `active_hold_count`
        by one, and recomputes the posture; when the count reaches zero and
        the employee is `SUSPENDED`, the employee automatically returns
        `SUSPENDED → ACTIVE`."

        Design: Difficulty/compensating_invariant/hold_apply_release_conserves_count
        """
        emp, cycle, hold = setup_overdue_cycle_hold("E-CI1B", cycle_year=2025)
        assert emp["active_hold_count"] == 1 and emp["status"] == "SUSPENDED"

        complete_cycle_requirement(cycle["id"], "TB_SCREENING", "2026-08-01T00:00:01Z")
        released = validate_success(api.release_hold(hold["id"], {}, compliance_headers))
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None

        emp_end = get_employee(emp["id"])
        # Conserved quantity: the count returns exactly to its pre-apply value.
        assert emp_end["active_hold_count"] == 0
        assert emp_end["status"] == "ACTIVE"
        assert emp_end["compliance_posture"] == "CLEAR"


class TestDoubleRelease:
    def test_release_of_released_hold_rejected(self, api, compliance_headers):
        """PRD §3.3: "Release requires the hold to be `ACTIVE`
        (`ERR_HOLD_NOT_ACTIVE`)"

        Design: Corner/errors/err_hold_not_active_on_double_release
        """
        emp, cycle, hold = setup_overdue_cycle_hold("E-ER2", cycle_year=2025)
        complete_cycle_requirement(cycle["id"], "TB_SCREENING", "2026-08-01T00:00:01Z")
        validate_success(api.release_hold(hold["id"], {}, compliance_headers))

        resp = api.release_hold(hold["id"], {}, compliance_headers)
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_ACTIVE)

        emp_after = get_employee(emp["id"])
        assert emp_after["active_hold_count"] == 0, (
            "a failed release must not decrement the count a second time"
        )
        hold_after = validate_success(api.get_hold(hold["id"], compliance_headers))
        assert hold_after["status"] == "RELEASED"


class TestPostureDerivationOrder:
    def test_holds_dominate_restrictions_in_posture(self, api):
        """PRD §3.1: "the derivation follows a pinned order in which holds
        dominate restrictions. When the employee's `active_hold_count` is above
        zero, the posture is `ON_HOLD`. Otherwise, when any `ACTIVE` work
        restriction of type `FULL_EXCLUSION` exists for the employee, the
        posture is `WORK_EXCLUDED`."

        Design: Corner/calculations/posture_holds_dominate_restrictions
        """
        emp, _cycle, _hold = setup_overdue_cycle_hold("E-CL6", cycle_year=2025)
        assert emp["compliance_posture"] == "ON_HOLD"

        create_restriction(emp["id"], restriction_type="FULL_EXCLUSION",
                           start_date="2026-08-01T00:00:01Z")

        emp_after = get_employee(emp["id"])
        assert emp_after["active_hold_count"] == 1
        assert emp_after["open_restriction_count"] == 1
        assert emp_after["compliance_posture"] == "ON_HOLD", (
            "holds dominate restrictions: ON_HOLD wins over WORK_EXCLUDED"
        )
