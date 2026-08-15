"""The denial-to-appeal pipeline: filing gates, the decision outcomes, and
the depth-3 overturn cascade back onto the authorization and the case
(PRD §3.5, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appeal_decision_payload,
    assert_appeal_case,
    assert_denial_case,
    decide_appeal,
    file_appeal_payload,
    get_appeal,
    get_auth,
    get_case,
    get_denial,
    list_appeals,
    make_advisor_headers,
    complete_p2p_payload,
    set_clock,
    setup_appeal_filed,
    setup_denied_auth,
    setup_p2p_scheduled,
    validate_error,
    validate_success,
)

NURSE = TEST_USERS["ur_nurse_headers"]
PAYER_REVIEWER = TEST_USERS["payer_reviewer_headers"]
APPEALS = TEST_USERS["appeals_coordinator_headers"]


class TestOverturnCascade:
    def test_appeal_overturn_resolves_appeal_and_denial(self, api):
        """PRD §3.8: "**OVERTURNED**: the appeal moves to `DECIDED_OVERTURNED`; `overturned_day_count` is set equal to the denial's `denied_day_count`; the denial resolves to `RESOLVED_OVERTURNED`; the linked authorization request moves `DENIED` → `APPROVED` with a certified interval appended at the case frontier covering the overturned days"

        Design: Difficulty/transitive_cascade/appeal_overturn_depth3_cascade
        """
        ctx = setup_appeal_filed(patient_mrn="MRN-C3",
                                 denial_reason_code="CRITERIA_NOT_MET")
        decided = validate_success(api.appeal_decision(
            ctx["appeal"]["id"], appeal_decision_payload("OVERTURNED"),
            PAYER_REVIEWER))
        assert_appeal_case(decided)
        assert decided["status"] == "DECIDED_OVERTURNED"
        assert decided["overturned_day_count"] == 3, (
            "the overturn restores the denial's full denied_day_count")
        assert decided.get("decided_at"), "decided_at must be stamped"

        denial = get_denial(ctx["denial"]["id"])
        assert_denial_case(denial)
        assert denial["status"] == "RESOLVED_OVERTURNED"

    def test_appeal_overturn_restores_auth_and_case(self, api):
        """PRD §3.8: "the linked authorization request moves `DENIED` → `APPROVED` with a certified interval appended at the case frontier covering the overturned days; every `OPEN` avoidable-day record of the case whose `day_date` falls on or after the denied window's start transitions to `OVERTURNED`, processed in order by `day_date` ascending and then `created_at` ascending (each appending `AVOIDABLE_DAY_OVERTURNED`); the case's `auth_status` returns to `AUTHORIZED`; certified counters are recomputed; the case `version` increments; and `APPEAL_DECIDED` is appended."

        Design: Difficulty/transitive_cascade/appeal_overturn_depth3_cascade
        """
        ctx = setup_appeal_filed(patient_mrn="MRN-C3B",
                                 denial_reason_code="CRITERIA_NOT_MET")
        decide_appeal(ctx["appeal"]["id"], "OVERTURNED")

        auth = get_auth(ctx["auth"]["id"])
        assert auth["status"] == "APPROVED"
        assert auth["certified_day_start"] == 1
        assert auth["certified_day_end"] == 4, (
            "the restored interval appends at the case frontier as [1, 4)")

        case = get_case(ctx["case"]["id"])
        assert case["auth_status"] == "AUTHORIZED"
        assert case["certified_day_count"] == 3


class TestFilingGates:
    def test_appeal_blocked_while_p2p_scheduled(self, api):
        """PRD §3.8: "Filing enforces four preconditions: the denial must be `OPEN`; no linked conference may be `SCHEDULED` (filing while a peer-to-peer is still on the calendar is rejected with `ERR_DENIAL_NOT_FINAL`); logical now must be at or before `appeal_deadline_at` (`ERR_APPEAL_DEADLINE_PASSED`, equality allowed); and no prior appeal may exist for the denial — a second filing attempt, whether the denial sits in `APPEAL_FILED` or any resolved state, is rejected with `ERR_APPEAL_ALREADY_FILED`."

        Design: Difficulty/cross_entity_state_dependency/appeal_blocked_while_p2p_scheduled
        """
        ctx = setup_p2p_scheduled(denial_reason_code="LEVEL_OF_CARE",
                                  patient_mrn="MRN-CE3")
        assert get_denial(ctx["denial"]["id"])["status"] == "P2P_SCHEDULED"
        resp = api.file_appeal(
            ctx["denial"]["id"],
            file_appeal_payload(
                1, argument_summary="Filed while conference still scheduled."),
            APPEALS)
        validate_error(resp, ApiErrorId.ERR_DENIAL_NOT_FINAL,
                       expected_status=409)
        assert list_appeals(ctx["denial"]["id"]) == []

    def test_appeal_allowed_after_p2p_upheld(self, api):
        """PRD §3.5: "An `UPHELD` outcome merely returns the denial from `P2P_SCHEDULED` to `OPEN`, leaving the authorization denied and the appeal path available."
        PRD §3.8: "A successful filing creates the appeal in `FILED` with `filed_at` stamped, moves the denial `OPEN` → `APPEAL_FILED`, and appends `APPEAL_FILED`."

        Design: Difficulty/cross_entity_state_dependency/appeal_blocked_while_p2p_scheduled
        """
        ctx = setup_p2p_scheduled(denial_reason_code="LEVEL_OF_CARE",
                                  patient_mrn="MRN-CE3B")
        set_clock("2026-08-03T10:25:00Z")  # inside the scheduled window
        completed = validate_success(api.complete_p2p(
            ctx["conference"]["id"], complete_p2p_payload("UPHELD"),
            make_advisor_headers(ctx["advisor"]["id"])))
        assert completed["outcome"] == "UPHELD"
        assert get_denial(ctx["denial"]["id"])["status"] == "OPEN"

        appeal = validate_success(api.file_appeal(
            ctx["denial"]["id"],
            file_appeal_payload(
                1, argument_summary="Filed after upheld peer-to-peer."),
            APPEALS), expected_status=201)
        assert appeal["status"] == "FILED"
        assert get_denial(ctx["denial"]["id"])["status"] == "APPEAL_FILED"

    def test_appeal_after_deadline_passed(self, api):
        """PRD §3.8: "logical now must be at or before `appeal_deadline_at` (`ERR_APPEAL_DEADLINE_PASSED`, equality allowed)"

        Design: Corner/validations/appeal_after_deadline_passed
        """
        ctx = setup_denied_auth(patient_mrn="MRN-DL")
        # appeal_deadline_at == 2026-10-01T12:00:00Z; file one second late.
        set_clock("2026-10-01T12:00:01Z")
        resp = api.file_appeal(
            ctx["denial"]["id"],
            file_appeal_payload(1, argument_summary="Filed one second late."),
            APPEALS)
        validate_error(resp, ApiErrorId.ERR_APPEAL_DEADLINE_PASSED,
                       expected_status=422)
        assert list_appeals(ctx["denial"]["id"]) == []

    def test_appeal_second_filing_rejected(self, api):
        """PRD §3.8: "no prior appeal may exist for the denial — a second filing attempt, whether the denial sits in `APPEAL_FILED` or any resolved state, is rejected with `ERR_APPEAL_ALREADY_FILED`."

        Design: Corner/validations/appeal_second_filing_rejected
        """
        ctx = setup_appeal_filed(patient_mrn="MRN-2AP")
        assert get_denial(ctx["denial"]["id"])["status"] == "APPEAL_FILED"
        resp = api.file_appeal(
            ctx["denial"]["id"],
            file_appeal_payload(2, argument_summary="Second appeal attempt."),
            APPEALS)
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_FILED,
                       expected_status=409)

    def test_ur_nurse_cannot_file_appeal_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/ur_nurse_cannot_file_appeal_forbidden
        """
        ctx = setup_denied_auth(patient_mrn="MRN-RBAC2")
        resp = api.file_appeal(
            ctx["denial"]["id"],
            file_appeal_payload(1, argument_summary="Nurse attempting to file."),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestDecisionTerminalLockdown:
    def test_appeal_decision_terminal_lockdown(self, api):
        """PRD §3.8: "**UPHELD**: the appeal moves to `DECIDED_UPHELD` with `decided_at` stamped and `overturned_day_count` set to 0; the denial resolves to `RESOLVED_UPHELD`; `APPEAL_DECIDED` is appended. No authorization restoration occurs."
        PRD §2.5: "State-machine legality — the target resource's current state permits the requested transition (repeated discharge, double decisions, writes against terminal states all fail here) with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/appeal_decision_terminal_lockdown
        """
        ctx = setup_appeal_filed(patient_mrn="MRN-ATL")
        upheld = decide_appeal(ctx["appeal"]["id"], "UPHELD")
        assert upheld["status"] == "DECIDED_UPHELD"
        assert upheld["overturned_day_count"] == 0

        resp = api.appeal_decision(
            ctx["appeal"]["id"], appeal_decision_payload("OVERTURNED"),
            PAYER_REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        appeal = get_appeal(ctx["denial"]["id"], ctx["appeal"]["id"])
        assert appeal["status"] == "DECIDED_UPHELD"
        assert appeal["overturned_day_count"] == 0
