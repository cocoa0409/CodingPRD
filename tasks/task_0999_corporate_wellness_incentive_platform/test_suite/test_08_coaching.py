"""Coaching referrals: lifecycle, discharge guards, re-referral cycle (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    SESSION_DATES,
    create_referral,
    discharge_referral,
    engage_referral,
    log_sessions,
    make_coach_headers,
    setup_active_enrollment,
    setup_discharged_referral,
    validate_error,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


class TestRereferCycle:
    """Difficulty instance: cyclic machine — DISCHARGED -> REFERRED re-enters with
    referral_round incremented and per-round fields reset."""

    def test_rerefer_from_discharged_resets_round_fields(self, api):
        """PRD §3.6: "From either `DISCHARGED` or `DECLINED`, a `BenefitsAdmin` may
        rerefer, returning the referral to `REFERRED` for another round:
        `referral_round` increments by one, `sessions_completed` resets to zero,
        `outcome` is cleared to null, and `assigned_coach_id` is cleared to null —
        while the lifetime `session_dates` history is preserved untouched."

        Design: Difficulty/non_linear_state_machine/coaching_referral_rerefer_cycle
        """
        ctx = setup_discharged_referral(reason="HIGH_RISK", outcome="GOALS_MET")
        referral = ctx["referral"]
        assert referral["status"] == "DISCHARGED"
        assert referral["sessions_completed"] == 4

        rereferred = validate_success(api.rerefer_coaching_referral(referral["id"], BA), 200)
        assert rereferred["status"] == "REFERRED"
        assert rereferred["referral_round"] == 2
        assert rereferred["sessions_completed"] == 0
        assert rereferred["outcome"] is None
        assert rereferred["assigned_coach_id"] is None

    def test_rerefer_preserves_lifetime_session_dates(self, api):
        """PRD §3.6: "From either `DISCHARGED` or `DECLINED`, a `BenefitsAdmin` may
        rerefer, returning the referral to `REFERRED` for another round:
        `referral_round` increments by one, `sessions_completed` resets to zero,
        `outcome` is cleared to null, and `assigned_coach_id` is cleared to null —
        while the lifetime `session_dates` history is preserved untouched."
        PRD §3.6: "The `session_dates` list is never reset, and billing reads it
        verbatim when computing coaching-session invoice lines."

        Design: Difficulty/non_linear_state_machine/coaching_referral_rerefer_cycle
        """
        ctx = setup_discharged_referral(reason="HIGH_RISK", outcome="GOALS_MET")
        referral = ctx["referral"]
        validate_success(api.rerefer_coaching_referral(referral["id"], BA), 200)

        referrals, _meta = validate_paginated(
            api.list_enrollment_coaching_referrals(ctx["enrollment"]["id"], BA)
        )
        by_id = {r["id"]: r for r in referrals}
        kept = by_id[referral["id"]]
        assert kept["session_dates"] == SESSION_DATES, (
            "lifetime session history must survive the re-referral reset"
        )
        assert kept["status"] == "REFERRED"


class TestDischargePreconditions:
    def test_referral_discharge_sessions_insufficient(self, api):
        """PRD §3.6: "Discharge moves `ENGAGED → DISCHARGED` and requires the logged
        `sessions_completed` to be at least the program's
        `coaching_required_sessions` (otherwise
        `ERR_REFERRAL_SESSIONS_INSUFFICIENT`); only the assigned coach may
        discharge."

        Design: Corner/state_machines/referral_discharge_sessions_insufficient
        """
        ctx = setup_active_enrollment()
        referral = create_referral(ctx["enrollment"]["id"], reason="HIGH_RISK")
        engage_referral(referral["id"], "coach-1")
        log_sessions(referral["id"], "coach-1", dates=["2026-04-02"])

        res = api.discharge_coaching_referral(
            referral["id"], {"outcome": "GOALS_MET"}, make_coach_headers("coach-1")
        )
        validate_error(res, ApiErrorId.ERR_REFERRAL_SESSIONS_INSUFFICIENT, expected_status=409)

        referrals, _meta = validate_paginated(
            api.list_enrollment_coaching_referrals(ctx["enrollment"]["id"], BA)
        )
        by_id = {r["id"]: r for r in referrals}
        assert by_id[referral["id"]]["status"] == "ENGAGED", "referral stays ENGAGED"
        assert by_id[referral["id"]]["sessions_completed"] == 1


class TestCoachAssignmentScope:
    def test_coach_cannot_discharge_unassigned_referral(self, api):
        """PRD §3.6: "Discharge moves `ENGAGED → DISCHARGED` and requires the logged
        `sessions_completed` to be at least the program's
        `coaching_required_sessions` (otherwise
        `ERR_REFERRAL_SESSIONS_INSUFFICIENT`); only the assigned coach may
        discharge."
        PRD §2.1: "A `Coach` in particular acts only on referrals to which they are
        currently assigned: the engaging coach's identifier becomes the referral's
        `assigned_coach_id`, and subsequent session logging and discharge compare
        the caller's `X-User-ID` to that recorded value."

        Design: Corner/rbac/coach_cannot_discharge_unassigned_referral
        """
        ctx = setup_active_enrollment()
        referral = create_referral(ctx["enrollment"]["id"], reason="HIGH_RISK")
        engage_referral(referral["id"], "coach-1")
        log_sessions(referral["id"], "coach-1")

        res = api.discharge_coaching_referral(
            referral["id"], {"outcome": "GOALS_MET"}, make_coach_headers("coach-2")
        )
        validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)

        referrals, _meta = validate_paginated(
            api.list_enrollment_coaching_referrals(ctx["enrollment"]["id"], BA)
        )
        by_id = {r["id"]: r for r in referrals}
        assert by_id[referral["id"]]["status"] == "ENGAGED"
        assert by_id[referral["id"]]["assigned_coach_id"] == "coach-1"
