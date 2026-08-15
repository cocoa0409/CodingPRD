"""Inspection scoring boundaries, submit cascades, corrective-action due dates
and lifecycle, overdue sweep, and the CRITICAL-reopen re-suspension cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_inspection,
    create_hall,
    create_scheduled_period,
    drive_period_to_in_service,
    file_inspection,
    get_hall,
    get_period,
    list_report_corrective_actions,
    reactivate_hall,
    set_clock,
    setup_hall_cycle_recipe,
    submit_inspection,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["dining_admin_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]
INSPECTOR = TEST_USERS["health_inspector_headers"]


def _violations(*specs):
    return [{"code": code, "severity": sev} for code, sev in specs]


class TestInspectionScoreBoundary:
    def test_score_exactly_70_passes(self, api):
        """PRD §3.7: "The `outcome` follows: any report containing at least one
        `CRITICAL` violation is a `FAIL` regardless of score; otherwise a
        `score` of 70 or better is a `PASS` (exactly 70 passes); otherwise a
        `score` of 40 through 69 is `CONDITIONAL`; anything below 40 is a
        `FAIL`."

        Design: Difficulty/boundary_precision_check/inspection_score_exactly_70_passes
        """
        hall = create_hall(name="Hall IN")
        report = file_inspection(hall["id"], "2026-08-05",
                                 _violations(("M1", "MAJOR"), ("M2", "MAJOR"),
                                             ("M3", "MAJOR")))
        submitted = submit_inspection(report["id"])
        assert submitted["score"] == 70, "100 - 3 * 10"
        assert submitted["outcome"] == "PASS"
        assert get_hall(hall["id"])["status"] == "ACTIVE"

    def test_one_extra_minor_drops_to_conditional(self, api):
        """PRD §3.7: "The `outcome` follows: any report containing at least one
        `CRITICAL` violation is a `FAIL` regardless of score; otherwise a
        `score` of 70 or better is a `PASS` (exactly 70 passes); otherwise a
        `score` of 40 through 69 is `CONDITIONAL`; anything below 40 is a
        `FAIL`."
        PRD §3.7: "Submission also cascade-creates one **corrective action** per
        violation, each bound to the report through its `inspection_report_id`,
        copying the violation's severity and code, setting each action's
        `due_date` relative to the inspection date — 7 days out for `CRITICAL`,
        14 days for `MAJOR`, 30 days for `MINOR` — and starting each action
        `OPEN` with `resolved_by_user_id` and `verified_by_user_id` null."

        Design: Difficulty/boundary_precision_check/inspection_score_exactly_70_passes
        """
        hall = create_hall(name="Hall IN")
        report = file_inspection(hall["id"], "2026-08-06",
                                 _violations(("M1", "MAJOR"), ("M2", "MAJOR"),
                                             ("M3", "MAJOR"), ("m1", "MINOR")))
        submitted = submit_inspection(report["id"])
        assert submitted["score"] == 67, "100 - 33"
        assert submitted["outcome"] == "CONDITIONAL"

        actions = list_report_corrective_actions(report["id"])
        assert len(actions) == 4
        majors = [a for a in actions if a["severity"] == "MAJOR"]
        minors = [a for a in actions if a["severity"] == "MINOR"]
        assert len(majors) == 3 and len(minors) == 1
        for action in majors:
            assert str(action["due_date"])[:10] == "2026-08-20", "insp +14d"
            assert action["status"] == "OPEN"
        assert str(minors[0]["due_date"])[:10] == "2026-09-05", "insp +30d"
        assert get_hall(hall["id"])["status"] == "ACTIVE"


class TestInspectionFailCascade:
    def _setup(self, api):
        """Hall with a SCHEDULED period P1 and an IN_SERVICE period P2, plus a
        DRAFT report carrying one CRITICAL violation."""
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall IC")
        p1 = create_scheduled_period(hall["id"], cycle["id"], "2026-08-10")
        p2 = drive_period_to_in_service(hall["id"], cycle["id"], recipe["id"],
                                        "2026-08-11")
        report = file_inspection(hall["id"], "2026-08-12",
                                 _violations(("TEMP-01", "CRITICAL")))
        return hall, p1, p2, report

    def test_fail_outcome_suspends_hall(self, api):
        """PRD §3.7: "And submission carries the system's sharpest cascade: when
        the computed `outcome` is `FAIL`, the parent hall transitions from
        `ACTIVE` to `SUSPENDED`, whose own side effect (§2.10) cancels every
        `SCHEDULED` meal period at the hall — a transitive cascade three levels
        deep, from report to hall to periods."
        PRD §3.7: "The `outcome` follows: any report containing at least one
        `CRITICAL` violation is a `FAIL` regardless of score; otherwise a
        `score` of 70 or better is a `PASS` (exactly 70 passes); otherwise a
        `score` of 40 through 69 is `CONDITIONAL`; anything below 40 is a
        `FAIL`."

        Design: Difficulty/transitive_cascade/inspection_fail_suspends_hall_cancels_periods
        """
        hall, _p1, _p2, report = self._setup(api)
        submitted = submit_inspection(report["id"])
        assert submitted["outcome"] == "FAIL", (
            "any CRITICAL forces FAIL despite score 75 (100 - 25)")
        assert submitted["score"] == 75
        assert get_hall(hall["id"])["status"] == "SUSPENDED"

    def test_cascade_cancels_only_scheduled_periods_and_creates_actions(self, api):
        """PRD §2.10: "When a hall leaves `ACTIVE` — whether suspended directly
        by a `DiningAdmin` or cascaded out of a failed inspection or a reopened
        critical corrective action — the system immediately resolves its
        dependent work: every `MealPeriodService` at the hall still in
        `SCHEDULED` status transitions to `CANCELLED`, with each cancelled
        period's `version` incremented by 1. Meal periods that have already
        advanced to `FORECAST_LOCKED` or beyond are deliberately *not*
        auto-cancelled, because they carry locked forecasts or live service data
        that must settle through their own lifecycle."
        PRD §3.7: "Submission also cascade-creates one **corrective action** per
        violation, each bound to the report through its `inspection_report_id`,
        copying the violation's severity and code, setting each action's
        `due_date` relative to the inspection date — 7 days out for `CRITICAL`,
        14 days for `MAJOR`, 30 days for `MINOR` — and starting each action
        `OPEN` with `resolved_by_user_id` and `verified_by_user_id` null."

        Design: Difficulty/transitive_cascade/inspection_fail_suspends_hall_cancels_periods
        """
        _hall, p1, p2, report = self._setup(api)
        submit_inspection(report["id"])
        assert get_period(p1["id"])["status"] == "CANCELLED"
        assert get_period(p2["id"])["status"] == "IN_SERVICE", (
            "the cascade touches only SCHEDULED periods")

        actions = list_report_corrective_actions(report["id"])
        assert len(actions) == 1
        action = actions[0]
        assert action["severity"] == "CRITICAL"
        assert action["status"] == "OPEN"
        assert str(action["due_date"])[:10] == "2026-08-19", (
            "inspection_date 2026-08-12 + 7d")


class TestCorrectiveDueDates:
    def test_due_dates_derived_from_severity(self, api):
        """PRD §3.7: "Submission also cascade-creates one **corrective action**
        per violation, each bound to the report through its
        `inspection_report_id`, copying the violation's severity and code,
        setting each action's `due_date` relative to the inspection date — 7
        days out for `CRITICAL`, 14 days for `MAJOR`, 30 days for `MINOR` — and
        starting each action `OPEN` with `resolved_by_user_id` and
        `verified_by_user_id` null."
        PRD §3.7: "The `outcome` follows: any report containing at least one
        `CRITICAL` violation is a `FAIL` regardless of score; otherwise a
        `score` of 70 or better is a `PASS` (exactly 70 passes); otherwise a
        `score` of 40 through 69 is `CONDITIONAL`; anything below 40 is a
        `FAIL`."

        Design: Corner/calculations/corrective_due_dates_from_severity
        """
        hall = create_hall(name="Hall C5")
        report = file_inspection(hall["id"], "2026-08-01",
                                 _violations(("C1", "CRITICAL"), ("M1", "MAJOR"),
                                             ("m1", "MINOR")),
                                 inspector_id="insp-2")
        submitted = submit_inspection(report["id"], inspector_id="insp-2")
        assert submitted["score"] == 62, "100 - 25 - 10 - 3"
        assert submitted["outcome"] == "FAIL", "CRITICAL present forces FAIL"

        actions = list_report_corrective_actions(report["id"])
        assert len(actions) == 3
        by_severity = {a["severity"]: a for a in actions}
        assert str(by_severity["CRITICAL"]["due_date"])[:10] == "2026-08-08"
        assert str(by_severity["MAJOR"]["due_date"])[:10] == "2026-08-15"
        assert str(by_severity["MINOR"]["due_date"])[:10] == "2026-08-31"
        for action in actions:
            assert action["status"] == "OPEN"
            assert action["resolved_by_user_id"] is None
            assert action["verified_by_user_id"] is None


class TestInspectionCloseGate:
    def test_close_blocked_until_all_actions_verified(self, api):
        """PRD §3.7: "From `SUBMITTED`, a `HallManager` acknowledges the report
        (`SUBMITTED` → `ACKNOWLEDGED`), and a `HealthInspector` eventually
        closes it (`ACKNOWLEDGED` → `CLOSED`), but only when every corrective
        action belonging to the report has reached `VERIFIED` — otherwise
        `ERR_INSPECTION_INCOMPLETE`."

        Design: Corner/errors/inspection_close_incomplete_blocked_then_succeeds
        """
        hall = create_hall(name="Hall E4")
        report = file_inspection(hall["id"], "2026-08-03",
                                 _violations(("M1", "MAJOR")),
                                 inspector_id="insp-3")
        submitted = submit_inspection(report["id"], inspector_id="insp-3")
        assert submitted["score"] == 90
        assert submitted["outcome"] == "PASS"
        acknowledge_inspection(report["id"])
        action = list_report_corrective_actions(report["id"])[0]

        validate_success(api.resolve_corrective_action(action["id"],
                                                       HALL_MANAGER))
        resp = api.close_inspection_report(report["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_INCOMPLETE)

        validate_success(api.verify_corrective_action(action["id"], INSPECTOR))
        closed = validate_success(api.close_inspection_report(report["id"],
                                                              INSPECTOR))
        assert closed["status"] == "CLOSED"


class TestOverdueSweep:
    def test_overdue_only_when_due_date_strictly_before_clock_date(self, api):
        """PRD §2.4: "Second, every corrective action in `OPEN` status whose
        `due_date` falls strictly before the new clock's date transitions to
        `OVERDUE` — an action whose due date equals the new clock date is *not*
        overdue."

        Design: Corner/cross_cutting_layers/clock_sweep_marks_corrective_overdue
        """
        hall = create_hall(name="Hall L4")
        report = file_inspection(hall["id"], "2026-08-01",
                                 _violations(("M1", "MAJOR")),
                                 inspector_id="insp-6")
        submit_inspection(report["id"], inspector_id="insp-6")
        action = list_report_corrective_actions(report["id"])[0]
        assert str(action["due_date"])[:10] == "2026-08-15"

        sweep1 = set_clock("2026-08-15T00:00:00Z")
        assert action["id"] not in sweep1["overdue_corrective_action_ids"]
        assert validate_success(api.get_corrective_action(
            action["id"], INSPECTOR))["status"] == "OPEN", (
            "due_date == clock date is not overdue")

        sweep2 = set_clock("2026-08-16T00:00:00Z")
        assert action["id"] in sweep2["overdue_corrective_action_ids"]
        assert validate_success(api.get_corrective_action(
            action["id"], INSPECTOR))["status"] == "OVERDUE"
        assert get_hall(hall["id"])["status"] == "ACTIVE", (
            "a single MAJOR scores 90 -> PASS, no suspension")


class TestCorrectiveReopenResuspendsHall:
    def _setup_reactivated_hall(self, api):
        """FAIL inspection -> hall SUSPENDED; CA RESOLVED (not VERIFIED); hall
        reactivated; fresh SCHEDULED period P2."""
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall CR",
                                                      unit_cost_cents=300,
                                                      station="DELI")
        report = file_inspection(hall["id"], "2026-08-05",
                                 _violations(("SAN-07", "CRITICAL")))
        submit_inspection(report["id"])
        action = list_report_corrective_actions(report["id"])[0]
        acknowledge_inspection(report["id"])
        validate_success(api.resolve_corrective_action(action["id"],
                                                       HALL_MANAGER))
        reactivate_hall(hall["id"])
        p2 = create_scheduled_period(hall["id"], cycle["id"], "2026-08-20")
        return hall, report, action, p2

    def test_critical_reopen_clears_resolver_and_suspends_hall(self, api):
        """PRD §3.7: "When verification fails, the inspector reopens the action
        (`RESOLVED` → `OPEN`), clearing `resolved_by_user_id` to null; and if
        the reopened action's severity is `CRITICAL` while the report's hall is
        currently `ACTIVE`, the hall is suspended on the spot — again cascading
        to cancel the hall's `SCHEDULED` meal periods."

        Design: Difficulty/transitive_cascade/corrective_reopen_resuspends_hall
        """
        hall, _report, action, _p2 = self._setup_reactivated_hall(api)
        reopened = validate_success(api.reopen_corrective_action(action["id"],
                                                                 INSPECTOR))
        assert reopened["status"] == "OPEN"
        assert reopened["resolved_by_user_id"] is None
        assert get_hall(hall["id"])["status"] == "SUSPENDED"

    def test_critical_reopen_cancels_scheduled_periods(self, api):
        """PRD §3.7: "When verification fails, the inspector reopens the action
        (`RESOLVED` → `OPEN`), clearing `resolved_by_user_id` to null; and if
        the reopened action's severity is `CRITICAL` while the report's hall is
        currently `ACTIVE`, the hall is suspended on the spot — again cascading
        to cancel the hall's `SCHEDULED` meal periods."

        Design: Difficulty/transitive_cascade/corrective_reopen_resuspends_hall
        """
        _hall, _report, action, p2 = self._setup_reactivated_hall(api)
        validate_success(api.reopen_corrective_action(action["id"], INSPECTOR))
        assert get_period(p2["id"])["status"] == "CANCELLED", (
            "the same hall cascade fires from the corrective-reopen trigger")


class TestReactivateGate:
    def test_reactivate_blocked_by_open_critical_then_succeeds(self, api):
        """PRD §3.1: "Reactivation moves the hall from `SUSPENDED` back to
        `ACTIVE`, but only when no `CRITICAL` corrective action in `OPEN` or
        `OVERDUE` status exists on any inspection report filed for that hall —
        otherwise the request is refused with `ERR_CRITICAL_VIOLATION_OPEN`."

        Design: Corner/errors/hall_reactivate_blocked_by_open_critical_then_succeeds
        """
        hall = create_hall(name="Hall E7")
        report = file_inspection(hall["id"], "2026-08-04",
                                 _violations(("CR-1", "CRITICAL")),
                                 inspector_id="insp-4")
        submit_inspection(report["id"], inspector_id="insp-4")
        action = list_report_corrective_actions(report["id"])[0]
        acknowledge_inspection(report["id"])

        resp = api.reactivate_dining_hall(hall["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CRITICAL_VIOLATION_OPEN)

        # Verify requires the report ACKNOWLEDGED, so acknowledge precedes
        # resolve/verify in this chain.
        validate_success(api.resolve_corrective_action(action["id"],
                                                       HALL_MANAGER))
        validate_success(api.verify_corrective_action(action["id"], INSPECTOR))
        reactivated = validate_success(api.reactivate_dining_hall(hall["id"],
                                                                  ADMIN))
        assert reactivated["status"] == "ACTIVE"
