"""Withdraw lifecycle, release rules, state-vs-temporal validation priority."""
from test_helpers import (
    ApiErrorId,
    activate_assignment,
    get_case,
    add_conducted_interview,
    create_interview_payload,
    propose_assignment_auto,
    propose_assignment_override,
    screen_clear,
    setup_case_triaged,
    setup_case_under_investigation,
    setup_standard_staff,
    create_case,
    create_staff,
    make_intake_headers,
    make_reporter_headers,
    triage_case,
    validate_error,
    validate_success,
    api_client,
)


class TestWithdraw:
    def test_withdraw_from_received_then_lockdown(self, api):
        """PRD §3.2: "While the case is still in `RECEIVED` or `TRIAGED`, the
        reporter may withdraw it, which moves it to `WITHDRAWN` ... withdrawal in
        any later state fails with `ERR_CASE_NOT_WITHDRAWABLE`".

        Design: Corner/state_machines/withdraw_then_terminal_lockdown
        """
        case, key = create_case()
        resp = api.withdraw_case(case["id"], make_reporter_headers(key))
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"
        resp2 = api.withdraw_case(case["id"], make_reporter_headers(key))
        validate_error(resp2, ApiErrorId.ERR_CASE_NOT_WITHDRAWABLE)

    def test_withdraw_forbidden_once_assigned(self, api):
        """PRD §3.2: "While the case is still in `RECEIVED` or `TRIAGED`, the
        reporter may withdraw it ... withdrawal in any later state fails with
        `ERR_CASE_NOT_WITHDRAWABLE`".

        Design: Corner/state_machines/withdraw_forbidden_once_assigned
        """
        s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
        create_staff("Ian Vest", "investigator@corp.example", ["INVESTIGATION"])
        case, key = create_case()
        triaged = triage_case(case["id"], make_intake_headers(s_int["id"]))
        api.create_assignment(case["id"], {"expected_case_version": triaged["version"]},
                              make_intake_headers(s_int["id"]))
        resp = api.withdraw_case(case["id"], make_reporter_headers(key))
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_WITHDRAWABLE)


class TestReleaseRules:
    def test_release_active_with_conducted_interview_rejected(self, api):
        """PRD §3.4: "Releasing an `ACTIVE` assignment additionally requires that no
        interview of the case has reached `CONDUCTED` — otherwise the release fails
        with `ERR_CASE_HAS_CONDUCTED_INTERVIEWS`".

        Design: Corner/errors/release_active_assignment_with_conducted_interview_rejected
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        add_conducted_interview(ctx)
        resp = api.release_assignment(ctx["assignment"]["id"], staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_CASE_HAS_CONDUCTED_INTERVIEWS)


class TestActivateReleaseConservation:
    """Difficulty: activate_release_conserves_active_count (2 tests)."""

    def _setup_cleared_medium(self, api):
        staff = setup_standard_staff()
        inv = create_staff("Fred Fresh", "fresh@corp.example", ["INVESTIGATION"])
        case, _ = create_case()
        # FRAUD/STAFF/NONE/NONE = 35 -> MEDIUM (weight 2)
        triaged = triage_case(case["id"], staff["h_int"])
        a1 = propose_assignment_override(case["id"], triaged["version"], inv["id"],
                                         staff["h_off"], reason="Fresh investigator")
        screen_clear(a1["id"], staff["h_int"])
        return staff, inv, case, a1

    def test_activate_increments_counters(self, api):
        """PRD §3.4: "On success the assignment becomes `ACTIVE`, the investigator's
        `active_case_count` rises by 1 and their `weighted_caseload` is recomputed"
        with §3.1 "`MEDIUM` weighs 2".

        Design: Difficulty/compensating_invariant/activate_release_conserves_active_count
        """
        staff, inv, case, a1 = self._setup_cleared_medium(api)
        resp = api.activate_assignment(a1["id"], staff["h_off"])
        assert validate_success(resp)["status"] == "ACTIVE"
        rows = api.list_staff_members(staff["h_off"]).json()["data"]
        by_id = {r["id"]: r for r in rows}
        assert by_id[inv["id"]]["active_case_count"] == 1
        assert by_id[inv["id"]]["weighted_caseload"] == 2

    def test_release_restores_counters(self, api):
        """PRD §3.4: "Releasing an `ACTIVE` assignment ... decrements the
        investigator's `active_case_count` by 1 with `weighted_caseload`
        recomputed" and "always returns the case to `TRIAGED`".

        Design: Difficulty/compensating_invariant/activate_release_conserves_active_count
        """
        staff, inv, case, a1 = self._setup_cleared_medium(api)
        api.activate_assignment(a1["id"], staff["h_off"])
        resp = api.release_assignment(a1["id"], staff["h_off"])
        assert validate_success(resp)["status"] == "RELEASED"
        rows = api.list_staff_members(staff["h_off"]).json()["data"]
        by_id = {r["id"]: r for r in rows}
        assert by_id[inv["id"]]["active_case_count"] == 0
        assert by_id[inv["id"]]["weighted_caseload"] == 0
        after = get_case(case["id"], staff["h_off"])
        assert after["status"] == "TRIAGED"
        assert after["assigned_investigator_id"] is None


class TestStateVsTemporalPriority:
    """Difficulty: interview_create_state_vs_temporal_priority (2 tests)."""

    def _setup(self, api):
        """case1 UNDER_INVESTIGATION with interview 10:00-11:00; case2 ASSIGNED to
        same investigator (PROPOSED)."""
        staff = setup_standard_staff()
        c1, _ = create_case()
        c1_t = triage_case(c1["id"], staff["h_int"])
        a1 = propose_assignment_override(c1["id"], c1_t["version"], staff["s_inv"]["id"],
                                         staff["h_off"], reason="Primary investigator")
        screen_clear(a1["id"], staff["h_int"])
        activate_assignment(a1["id"], staff["h_off"])
        api.create_interview(create_interview_payload(
            c1["id"], interviewee_identifier="w-1",
            scheduled_start="2026-08-05T10:00:00Z", scheduled_end="2026-08-05T11:00:00Z",
        ), staff["h_inv"])
        c2, _ = create_case(channel="EMAIL", category="HARASSMENT",
                            description="Allegation of hostile workplace conduct", region="SOUTH")
        c2_t = triage_case(c2["id"], staff["h_int"], confirmed_category="HARASSMENT",
                           subject_seniority="MANAGER")
        propose_assignment_override(c2["id"], c2_t["version"], staff["s_inv"]["id"],
                                    staff["h_off"], reason="Same subject cluster")
        return staff, c2

    def test_state_error_wins_over_overlap(self, api):
        """PRD §2.11: "Eighth, target-entity state preconditions (the family of state
        errors such as `ERR_CASE_NOT_RECEIVED`, `ERR_ASSIGNMENT_NOT_PROPOSED`, and
        their siblings)" comes before "Twelfth, temporal interval rules
        (`ERR_INTERVIEW_OVERLAP`, `ERR_LEGAL_HOLD_OVERLAP`)".

        Design: Difficulty/priority_pair_validation_conflict/interview_create_state_vs_temporal_priority
        """
        staff, c2 = self._setup(api)
        # 10:30 start violates BOTH case-state (ASSIGNED) and 15-minute buffer
        resp = api.create_interview(create_interview_payload(
            c2["id"], interviewee_role="SUBJECT", interviewee_identifier="s-2",
            scheduled_start="2026-08-05T10:30:00Z", scheduled_end="2026-08-05T11:30:00Z",
        ), staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_UNDER_INVESTIGATION)

    def test_failed_dual_violation_creates_no_interview(self, api):
        """PRD §2.4: "every mutation in this system is applied atomically within the
        request that triggered it" — the rejected interview is not persisted.

        Design: Difficulty/priority_pair_validation_conflict/interview_create_state_vs_temporal_priority
        """
        staff, c2 = self._setup(api)
        api.create_interview(create_interview_payload(
            c2["id"], interviewee_role="SUBJECT", interviewee_identifier="s-2",
            scheduled_start="2026-08-05T10:30:00Z", scheduled_end="2026-08-05T11:30:00Z",
        ), staff["h_inv"])
        rows = api.list_interviews(c2["id"], staff["h_off"]).json()["data"]
        assert rows == []
