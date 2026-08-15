"""Case closure blockers, the closure cascade, and reopening."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_case,
    complete_checkin,
    get_case,
    list_case_checkins,
    list_case_plans,
    list_cases,
    make_threat_assessor_headers,
    reopen_case,
    reschedule_checkin,
    send_referral,
    set_clock,
    setup_case_plan_active,
    validate_error,
    validate_paginated,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")
TL1 = TEST_USERS["team_lead_headers"]

OPEN_STATUSES = ("INTAKE", "TRIAGED", "UNDER_ASSESSMENT", "PLAN_ACTIVE", "REMOVED")


def _open_case_count(api):
    """District count of cases not in a closed or purged status."""
    total = 0
    for status in OPEN_STATUSES:
        _data, meta = validate_paginated(
            api.list_cases(TL1, params={"status": status, "limit": 1}))
        total += meta["total_count"]
    return total


class TestClosureCascadeAndReopenCycle:
    def test_close_cascades_to_plans_and_checkins(self, api):
        """PRD: "A clean close moves the case to `CLOSED_MANAGED`, stamps
        `closed_at` from the logical clock, computes `retention_purge_after`
        as the closure calendar date plus the school's `retention_days`,
        cascades every `ACTIVE` and every `DRAFT` management plan for the
        case to `CLOSED`, cancels every `SCHEDULED` check-in for the case (the
        only producer of `CANCELLED` check-ins), and writes `CASE_CLOSED`."

        Design: Difficulty/non_linear_state_machine/threat_case_close_reopen_cycle
        """
        case, _ra, plan, chk = setup_case_plan_active()

        closed = close_case(case["id"])
        assert closed["status"] == "CLOSED_MANAGED"
        assert closed["closed_at"] is not None
        assert closed["retention_purge_after"] == "2027-08-01", (
            "closure on 2026-08-01 plus the school's 365-day default window"
        )

        cancelled, cancelled_meta = list_case_checkins(case["id"],
                                                       status="CANCELLED")
        assert cancelled_meta["total_count"] == 1
        assert cancelled[0]["id"] == chk["id"], (
            "the case-closure cascade is the only producer of CANCELLED "
            "check-ins"
        )

        closed_plans, closed_meta = list_case_plans(case["id"], status="CLOSED")
        assert closed_meta["total_count"] == 1
        assert closed_plans[0]["id"] == plan["id"]

    def test_reopen_clears_closure_fields_and_counters(self, api):
        """PRD: "When a new report arrives concerning a previously closed
        subject, an `IntakeCoordinator` reopens the case: from either
        `CLOSED_NO_THREAT` or `CLOSED_MANAGED` (`ERR_CASE_NOT_REOPENABLE`
        otherwise) the case returns to `TRIAGED`, `closed_at` and
        `retention_purge_after` are cleared to null,
        `consecutive_missed_count` resets to zero, `escalation_flag` resets to
        false, the prior `triage_priority` is preserved, and `CASE_REOPENED`
        is written."

        Design: Difficulty/non_linear_state_machine/threat_case_close_reopen_cycle
        """
        case, _ra, _plan, _chk = setup_case_plan_active()
        close_case(case["id"])

        reopened = reopen_case(case["id"])
        assert reopened["status"] == "TRIAGED"
        assert reopened["closed_at"] is None
        assert reopened["retention_purge_after"] is None
        assert reopened["consecutive_missed_count"] == 0
        assert reopened["escalation_flag"] is False
        assert reopened["triage_priority"] == "ROUTINE", (
            "the prior triage_priority is preserved across reopen"
        )


class TestCloseBlockers:
    def test_close_blocked_by_missed_checkin(self, api):
        """PRD: "Three blockers guard it, evaluated in this order: a check-in
        in `MISSED` status rejects the close with `ERR_OPEN_CHECKINS_EXIST`; a
        referral still in `SENT` status rejects it with
        `ERR_OPEN_REFERRALS_EXIST`; and a case whose `escalation_flag` is set
        rejects it with `ERR_ESCALATION_UNRESOLVED`."

        Design: Corner/state_machines/close_blocked_by_missed_checkin
        """
        case, _ra, _plan, chk = setup_case_plan_active(cadence_days=7)
        set_clock("2026-08-09T00:00:00Z")

        blocked = api.close_case(case["id"], TL1)
        validate_error(blocked, ApiErrorId.ERR_OPEN_CHECKINS_EXIST)

        reschedule_checkin(chk["id"], "2026-08-10")
        closed = validate_success(api.close_case(case["id"], TL1), 200)
        assert closed["status"] == "CLOSED_MANAGED", (
            "rescheduling the MISSED check-in clears the blocker"
        )

    def test_close_blocked_by_sent_referral(self, api):
        """PRD: "Three blockers guard it, evaluated in this order: a check-in
        in `MISSED` status rejects the close with `ERR_OPEN_CHECKINS_EXIST`; a
        referral still in `SENT` status rejects it with
        `ERR_OPEN_REFERRALS_EXIST`; and a case whose `escalation_flag` is set
        rejects it with `ERR_ESCALATION_UNRESOLVED`."

        Design: Corner/state_machines/close_blocked_by_sent_referral
        """
        case, _ra, _plan, _chk = setup_case_plan_active(cadence_days=7)
        send_referral(case["id"], referral_type="MENTAL_HEALTH",
                      agency_name="County MH", urgency="ROUTINE")

        resp = api.close_case(case["id"], TL1)
        validate_error(resp, ApiErrorId.ERR_OPEN_REFERRALS_EXIST)

        after = get_case(case["id"])
        assert after["status"] == "PLAN_ACTIVE", "a rejected close changes nothing"

    def test_close_blocked_by_unresolved_escalation(self, api):
        """PRD: "An outcome of `CONCERNS_ESCALATED` additionally sets the
        case's `escalation_flag` to true and writes `ESCALATION_RAISED`."
        PRD: "Three blockers guard it, evaluated in this order: a check-in in
        `MISSED` status rejects the close with `ERR_OPEN_CHECKINS_EXIST`; a
        referral still in `SENT` status rejects it with
        `ERR_OPEN_REFERRALS_EXIST`; and a case whose `escalation_flag` is set
        rejects it with `ERR_ESCALATION_UNRESOLVED`."
        PRD: "Under `FROM_COMPLETION`, the next `due_date` is the completion
        calendar date plus the cadence in days, so a late completion pushes
        the schedule out by the full cadence from the actual completion date."

        Design: Corner/state_machines/close_blocked_by_unresolved_escalation
        """
        case, _ra, _plan, chk = setup_case_plan_active(cadence_days=7)

        completed = complete_checkin(chk["id"], outcome="CONCERNS_ESCALATED",
                                     notes="new concerning statements")
        assert completed["status"] == "COMPLETED"

        case_after = get_case(case["id"])
        assert case_after["escalation_flag"] is True
        assert case_after["consecutive_missed_count"] == 0

        scheduled, meta = list_case_checkins(case["id"], status="SCHEDULED")
        assert meta["total_count"] == 1
        assert scheduled[0]["due_date"] == "2026-08-08", (
            "completion on 2026-08-01 chains the successor seven days out"
        )

        resp = api.close_case(case["id"], TL1)
        validate_error(resp, ApiErrorId.ERR_ESCALATION_UNRESOLVED)


class TestCloseReopenConservesOpenCount:
    def test_close_drops_open_case_count(self, api):
        """PRD: "Closure is the managed end-state for a case that is
        `PLAN_ACTIVE` (`ERR_CASE_NOT_CLOSABLE` from anywhere else)."
        PRD: "A clean close moves the case to `CLOSED_MANAGED`, stamps
        `closed_at` from the logical clock, computes `retention_purge_after`
        as the closure calendar date plus the school's `retention_days`,
        cascades every `ACTIVE` and every `DRAFT` management plan for the
        case to `CLOSED`, cancels every `SCHEDULED` check-in for the case (the
        only producer of `CANCELLED` check-ins), and writes `CASE_CLOSED`."

        Design: Difficulty/compensating_invariant/case_close_reopen_conserves_open_count
        """
        case, _ra, _plan, _chk = setup_case_plan_active()
        assert _open_case_count(api) == 1

        closed = close_case(case["id"])
        assert closed["status"] == "CLOSED_MANAGED"
        assert _open_case_count(api) == 0, (
            "closing moves the case out of the open-status set"
        )
        _all, meta = list_cases()
        assert meta["total_count"] == 1, "closure creates no new case rows"

    def test_reopen_restores_open_case_count(self, api):
        """PRD: "When a new report arrives concerning a previously closed
        subject, an `IntakeCoordinator` reopens the case: from either
        `CLOSED_NO_THREAT` or `CLOSED_MANAGED` (`ERR_CASE_NOT_REOPENABLE`
        otherwise) the case returns to `TRIAGED`, `closed_at` and
        `retention_purge_after` are cleared to null,
        `consecutive_missed_count` resets to zero, `escalation_flag` resets to
        false, the prior `triage_priority` is preserved, and `CASE_REOPENED`
        is written."

        Design: Difficulty/compensating_invariant/case_close_reopen_conserves_open_count
        """
        case, _ra, _plan, _chk = setup_case_plan_active()
        close_case(case["id"])
        assert _open_case_count(api) == 0

        reopened = reopen_case(case["id"])
        assert reopened["status"] == "TRIAGED"
        assert _open_case_count(api) == 1, (
            "close then reopen leaves the open-case count unchanged"
        )
        _all, meta = list_cases()
        assert meta["total_count"] == 1, (
            "the close+reopen pair neither creates nor destroys case rows"
        )
