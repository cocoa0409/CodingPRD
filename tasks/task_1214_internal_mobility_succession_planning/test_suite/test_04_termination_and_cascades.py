"""Termination cascade, calibration-finalize cascade, and the role cycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_employee, setup_hrbp, setup_manager, setup_talent_manager,
    setup_active_role, add_active_successor, create_and_activate_plan,
    setup_in_progress_session, propose_entry, ratify_entry,
    terminate_and_get_vacancy,
)

ADMIN = TEST_USERS["admin_headers"]


class TestTerminateTerminalLockdown:
    def test_terminate_twice_returns_already_terminal(self, api):
        """PRD §3.1: "Terminating an employee who is already `TERMINATED` is
        rejected with `ERR_ALREADY_TERMINAL`."
        PRD §3.4: "A **Vacancy** is never created by hand: it is auto-created
        with status `OPEN` — referencing its role through `critical_role_id` —
        the moment an `ACTIVE` role's incumbent is terminated"

        Design: Corner/state_machines/terminate_twice_returns_already_terminal
        """
        employee = setup_employee(employee_code="T100", full_name="Tom Twice",
                                  job_level=4, hire_date="2023-06-01")
        first = validate_success(api.terminate_employee(employee["id"], ADMIN), 200)
        assert first["employment_status"] == "TERMINATED"

        resp = api.terminate_employee(employee["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)

        vacancies, meta = validate_paginated(api.list_vacancies(ADMIN))
        assert vacancies == [] and meta["total_count"] == 0, (
            "a non-incumbent's termination must not create any vacancy, "
            "and the rejected second terminate must not fire the cascade again"
        )


class TestTerminationCascade:
    def _setup_coverage_role_pair(self, api):
        """COVERAGE role with two ACTIVE READY_NOW entries (bench 40,
        ADEQUATE): E_TERM at position 1 and E_KEEP at position 2."""
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB7")
        incumbent = setup_employee(employee_code="INC7", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        e_term = setup_employee(employee_code="ETERM7", job_level=6,
                                performance_rating="STRONG", hire_date="2024-05-01")
        e_keep = setup_employee(employee_code="EKEEP7", job_level=6,
                                performance_rating="STRONG", hire_date="2024-05-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="QA Lead",
                                 criticality_tier="TIER_2", assessment_method="COVERAGE")
        entry_term = add_active_successor(role["id"], e_term["id"], hrbp_headers,
                                          readiness_rating="READY_NOW", slate_position=1)
        entry_keep = add_active_successor(role["id"], e_keep["id"], hrbp_headers,
                                          readiness_rating="READY_NOW", slate_position=2)
        before = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert before["bench_strength"] == pytest.approx(40, abs=0.001)
        assert before["bench_posture"] == "ADEQUATE"
        assert before["posture_alert"] is False
        return hrbp_headers, role, e_term, e_keep, entry_term, entry_keep

    def test_termination_removes_entry_and_thins_bench(self, api):
        """PRD §3.1: "Fourth, every successor entry naming this employee in
        `DRAFT`, `ACTIVE`, or `SUSPENDED` status transitions to `REMOVED`."
        PRD §3.1: "Fifth, each role whose slate lost an entry in the previous
        level recomputes its `bench_strength` and `bench_posture`, and if the
        posture degrades into `THIN` or `EMPTY` from `ADEQUATE` or `STRONG`,
        the role's `posture_alert` is set true."

        Design: Difficulty/transitive_cascade/termination_cascade_removes_entry_thins_bench_spawns_assessment
        """
        hrbp_headers, role, e_term, e_keep, entry_term, _ = self._setup_coverage_role_pair(api)

        validate_success(api.terminate_employee(e_term["id"], ADMIN), 200)

        entry = get_success_data(api.get_successor(entry_term["id"], hrbp_headers))
        assert entry["status"] == "REMOVED", (
            "the terminated employee's ACTIVE entry must be REMOVED"
        )

        role = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert role["bench_strength"] == pytest.approx(20, abs=0.001), (
            "COVERAGE bench must fall from 2/5 = 40 to 1/5 = 20"
        )
        assert role["bench_posture"] == "THIN"
        assert role["posture_alert"] is True, (
            "degradation ADEQUATE -> THIN must set posture_alert"
        )

    def test_termination_spawns_bench_thin_auto_assessment(self, api):
        """PRD §3.1: "Sixth, for each role whose `posture_alert` was just set,
        the automatic risk response of §2.9 fires: one `OPEN`, `POINT_IN_TIME`
        retention assessment with `trigger_source` `BENCH_THIN_AUTO` for every
        remaining `ACTIVE`, `READY_NOW` entry on that role."
        PRD §3.8: "Under the `POINT_IN_TIME` variant, the base is 100 minus the
        employee's current rating points (20 for `LOW`, 50 for `SOLID`, 80 for
        `STRONG`, 100 for `EXCEPTIONAL`)."
        PRD §3.8: "and plus 20 when the employee holds any successor entry in
        `ACTIVE` status rated `READY_NOW` — being ready to leave for a bigger
        role is itself a flight risk."

        Design: Difficulty/transitive_cascade/termination_cascade_removes_entry_thins_bench_spawns_assessment
        """
        hrbp_headers, role, e_term, e_keep, _, _ = self._setup_coverage_role_pair(api)

        validate_success(api.terminate_employee(e_term["id"], ADMIN), 200)

        assessments = get_success_data(api.list_retention_assessments(
            hrbp_headers,
            params={"employee_id": e_keep["id"], "trigger_source": "BENCH_THIN_AUTO"},
        ))
        assert len(assessments) == 1, (
            f"exactly one auto assessment must be created for the remaining "
            f"ACTIVE READY_NOW successor, got {len(assessments)}"
        )
        auto = assessments[0]
        assert auto["trigger_source"] == "BENCH_THIN_AUTO"
        assert auto["status"] == "OPEN"
        assert auto["assessment_method"] == "POINT_IN_TIME"
        assert auto["risk_score"] == pytest.approx(40.0, abs=0.001), (
            "STRONG base 20 + 20 READY_NOW (tenure exactly 24 -> no delta) = 40.0"
        )
        assert auto["risk_level"] == "MEDIUM"


class TestRoleRefillCycle:
    def _setup_role_with_ready_successor(self, api):
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB6")
        incumbent = setup_employee(employee_code="INC6", department="FIN", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        successor = setup_employee(employee_code="S6", department="FIN", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Controller",
                                 department="FIN", criticality_tier="TIER_1")
        entry = add_active_successor(role["id"], successor["id"], hrbp_headers,
                                     readiness_rating="READY_NOW", slate_position=1)
        return hrbp_headers, role, incumbent, successor, entry

    def test_incumbent_termination_vacates_role_and_opens_vacancy(self, api):
        """PRD §3.1: "Second, every critical role whose `incumbent_employee_id`
        is this employee and whose status is `ACTIVE` transitions to `VACANT`,
        its `version` incrementing."
        PRD §3.1: "Third, for each role that just became `VACANT`, a `Vacancy`
        is auto-created with status `OPEN` and a `fill_deadline` 60 days out."

        Design: Difficulty/non_linear_state_machine/critical_role_active_vacant_active_refill_cycle
        """
        hrbp_headers, role, incumbent, _, _ = self._setup_role_with_ready_successor(api)

        validate_success(api.terminate_employee(incumbent["id"], ADMIN), 200)

        mid = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert mid["status"] == "VACANT"

        vacancies = get_success_data(
            api.list_vacancies(hrbp_headers, params={"critical_role_id": role["id"]})
        )
        assert len(vacancies) == 1
        assert vacancies[0]["status"] == "OPEN"

    def test_fill_from_slate_reactivates_role_with_successor(self, api):
        """PRD §3.4: "A successful slate fill does four things at once: the
        selected entry becomes `PROMOTED`; the vacancy becomes `FILLED` with
        `fill_source` `SUCCESSION_SLATE` and `filled_by_employee_id` set to the
        selected employee; the role transitions from `VACANT` back to `ACTIVE`
        with the selected employee as `incumbent_employee_id`, its `version`
        incrementing; and the role's bench recomputes because the promoted
        entry left the `ACTIVE` slate."
        PRD §3.2: "An empty `ACTIVE` slate yields exactly 0.00."

        Design: Difficulty/non_linear_state_machine/critical_role_active_vacant_active_refill_cycle
        """
        hrbp_headers, role, incumbent, successor, entry = (
            self._setup_role_with_ready_successor(api)
        )
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)

        filled = validate_success(
            api.fill_vacancy_from_slate(vacancy["id"], hrbp_headers), 200,
        )
        assert filled["status"] == "FILLED"
        assert filled["fill_source"] == "SUCCESSION_SLATE"
        assert filled["filled_by_employee_id"] == successor["id"]

        role = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert role["status"] == "ACTIVE", "the VACANT -> ACTIVE leg closes the cycle"
        assert role["incumbent_employee_id"] == successor["id"]
        assert role["bench_strength"] == pytest.approx(0.00, abs=0.001), (
            "the promotion emptied the ACTIVE slate"
        )
        assert role["bench_posture"] == "EMPTY"

        entry = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert entry["status"] == "PROMOTED"


class TestCalibrationFinalizeCascade:
    def _setup_ratified_session_for_successor(self, api):
        """WEIGHTED role with an ACTIVE READY_NOW entry for E8 (SOLID, plan at
        80 -> score 65.00, bench 15.87); an IN_PROGRESS session holds a
        RATIFIED entry giving E8 EXCEPTIONAL."""
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB8")
        tm, tm_headers = setup_talent_manager(employee_code="TM8")
        manager, _ = setup_manager(employee_code="MGR8")
        incumbent = setup_employee(employee_code="INC8", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        subject = setup_employee(employee_code="E8", job_level=6, hire_date="2024-05-01",
                                 performance_rating="SOLID",
                                 current_manager_id=manager["id"])
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Dev Lead",
                                 criticality_tier="TIER_1")
        entry = add_active_successor(role["id"], subject["id"], hrbp_headers,
                                     readiness_rating="READY_NOW", slate_position=1)
        create_and_activate_plan(entry["id"], hrbp_headers,
                                 target_readiness="READY_NOW", completion_pct=80)
        entry = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert entry["readiness_score"] == pytest.approx(65.00, abs=0.001)

        session = setup_in_progress_session(
            tm_headers, name="CAL-MAY",
            scheduled_start="2026-04-07T09:00:00Z",
            scheduled_end="2026-04-07T12:00:00Z",
        )
        cal_entry = propose_entry(session["id"], manager["id"], subject["id"],
                                  proposed_rating="EXCEPTIONAL")
        ratify_entry(cal_entry["id"], tm_headers, "EXCEPTIONAL")
        return {
            "hrbp_headers": hrbp_headers, "tm_headers": tm_headers,
            "role": role, "entry": entry, "subject": subject,
            "session": session, "cal_entry": cal_entry,
        }

    def test_finalize_applies_rating_and_history(self, api):
        """PRD §3.6: "A successful finalize fires a four-level cascade: every
        `RATIFIED` entry becomes `APPLIED`; each applied entry writes the
        employee's `performance_rating` to its `calibrated_rating` and appends
        a record of the rating, the application instant, and the session to the
        employee's `rating_history` — the only path by which
        `performance_rating` changes after creation"

        Design: Difficulty/transitive_cascade/calibration_finalize_cascades_rating_to_bench
        """
        ctx = self._setup_ratified_session_for_successor(api)

        validate_success(
            api.finalize_calibration_session(ctx["session"]["id"], ctx["tm_headers"]), 200,
        )

        cal_entry = get_success_data(
            api.get_calibration_entry(ctx["cal_entry"]["id"], ctx["tm_headers"])
        )
        assert cal_entry["status"] == "APPLIED"

        subject = get_success_data(api.get_employee(ctx["subject"]["id"], ADMIN))
        assert subject["performance_rating"] == "EXCEPTIONAL"
        assert len(subject["rating_history"]) == 1
        record = subject["rating_history"][0]
        assert record["rating"] == "EXCEPTIONAL"
        assert record["session_id"] == ctx["session"]["id"]

    def test_finalize_recomputes_readiness_and_bench(self, api):
        """PRD §3.6: "every successor entry in `ACTIVE` or `SUSPENDED` whose
        employee was just updated recomputes its `readiness_score`; and every
        role whose slate contains an updated entry recomputes `bench_strength`
        and `bench_posture`, with `posture_alert` maintained per §2.9."
        PRD §3.3: "it is one half of the employee's current rating points —
        20 for `LOW`, 50 for `SOLID`, 80 for `STRONG`, 100 for `EXCEPTIONAL` —
        plus one half of the plan percentage"

        Design: Difficulty/transitive_cascade/calibration_finalize_cascades_rating_to_bench
        """
        ctx = self._setup_ratified_session_for_successor(api)

        validate_success(
            api.finalize_calibration_session(ctx["session"]["id"], ctx["tm_headers"]), 200,
        )

        entry = get_success_data(
            api.get_successor(ctx["entry"]["id"], ctx["hrbp_headers"])
        )
        assert entry["readiness_score"] == pytest.approx(90.00, abs=0.001), (
            "0.5*100 (EXCEPTIONAL) + 0.5*80 (plan) = 90.00"
        )

        role = get_success_data(
            api.get_critical_role(ctx["role"]["id"], ctx["hrbp_headers"])
        )
        assert role["bench_strength"] == pytest.approx(21.98, abs=0.001), (
            "0.900/4.0951*100 = 21.98"
        )
