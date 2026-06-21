"""State-machine workflow tests: home-study revision loop, ICPC branch-with-revert,
home-study revision parity, and corner-queue state-machine claims.

Difficulty queue (A): non_linear_state_machine, compensating_invariant (home study).
Corner queue (B): state_machines + endpoints + validations instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_agency, create_case, create_family, create_birth_parent,
    create_under_review_home_study, create_deficient_home_study,
    create_approved_home_study, current_case_version,
    setup_case_with_accepted_match, create_irrevocable_consent,
    create_home_study_payload, create_icpc_payload, create_match_payload,
    create_invoice_payload,
    TEST_USERS, make_caseworker_headers, make_supervisor_headers,
)

CW = TEST_USERS["caseworker_headers"]
SUP = TEST_USERS["supervisor_headers"]
CA = TEST_USERS["compact_admin_headers"]
FO = TEST_USERS["finance_officer_headers"]


# ─── non_linear_state_machine / home_study_revision_cycle ─────────────────
class TestHomeStudyRevisionCycle:
    def _deficient_then_resubmit(self):
        agency = create_agency()
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        family = create_family(case["id"], annual_income_cents=8_000_000)
        hs = create_deficient_home_study(case["id"], family["id"])  # DEFICIENT, revision_count=1
        cw = make_caseworker_headers("cw-1")
        api_client.resubmit_home_study(hs["id"], cw)  # RESUBMITTED
        return hs["id"], cw

    def test_resubmitted_submit_returns_to_under_review(self):
        """PRD §3.2: "From RESUBMITTED, the author submits again, advancing RESUBMITTED
        back to UNDER_REVIEW, where it once more faces approval or return."

        Design: Difficulty/non_linear_state_machine/home_study_revision_cycle
        """
        hs_id, cw = self._deficient_then_resubmit()
        res = api_client.submit_home_study(hs_id, cw)
        updated = validate_success(res, 200)
        assert updated["status"] == "UNDER_REVIEW"

    def test_revision_count_preserved_through_loop(self):
        """PRD §3.2: "Returning a study instead advances it from UNDER_REVIEW to
        DEFICIENT ... and increments the study's revision_count by one."

        Design: Difficulty/non_linear_state_machine/home_study_revision_cycle
        """
        hs_id, cw = self._deficient_then_resubmit()
        updated = validate_success(api_client.submit_home_study(hs_id, cw), 200)
        assert updated["revision_count"] == 1


# ─── non_linear_state_machine / icpc_branch_with_revert ───────────────────
class TestIcpcBranchWithRevert:
    def _rejected_clearance(self):
        base = setup_case_with_accepted_match(child_state="NV", family_state="CA",
                                              to_iso8601="2026-06-04T08:00:00.000Z",
                                              birth_state="NV")
        icpc = validate_success(
            api_client.create_icpc_clearance(create_icpc_payload(base["case_id"]), CW), 201)
        api_client.submit_icpc(icpc["id"], CW)
        api_client.reject_icpc(icpc["id"], CA)
        return icpc["id"]

    def test_rework_returns_rejected_to_draft(self):
        """PRD §3.5: "A Caseworker reworks a rejected clearance, moving it from REJECTED
        back to DRAFT and clearing its submitted_at back to null so the packet may be
        re-submitted."

        Design: Difficulty/non_linear_state_machine/icpc_branch_with_revert
        """
        icpc_id = self._rejected_clearance()
        res = api_client.rework_icpc(icpc_id, CW)
        updated = validate_success(res, 200)
        assert updated["status"] == "DRAFT"

    def test_rework_clears_submitted_at(self):
        """PRD §3.5: "A Caseworker reworks a rejected clearance, moving it from REJECTED
        back to DRAFT and clearing its submitted_at back to null so the packet may be
        re-submitted."

        Design: Difficulty/non_linear_state_machine/icpc_branch_with_revert
        """
        icpc_id = self._rejected_clearance()
        updated = validate_success(api_client.rework_icpc(icpc_id, CW), 200)
        assert updated["submitted_at"] is None


# ─── compensating_invariant / home_study_return_then_resubmit_conserves_revision_parity ──
class TestHomeStudyRevisionParity:
    def _returned_study(self):
        agency = create_agency()
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        family = create_family(case["id"], annual_income_cents=8_000_000)
        return create_deficient_home_study(case["id"], family["id"])  # returned -> DEFICIENT

    def test_resubmit_moves_to_resubmitted(self):
        """PRD §3.2: "The author resubmits it, advancing DEFICIENT to RESUBMITTED
        (permitted only while DEFICIENT, and only for the author)."

        Design: Difficulty/compensating_invariant/home_study_return_then_resubmit_conserves_revision_parity
        """
        hs = self._returned_study()
        cw = make_caseworker_headers("cw-1")
        res = api_client.resubmit_home_study(hs["id"], cw)
        updated = validate_success(res, 200)
        assert updated["status"] == "RESUBMITTED"

    def test_revision_count_unchanged_by_resubmit(self):
        """PRD §3.2: "Returning a study instead advances it from UNDER_REVIEW to
        DEFICIENT, requires the same segregation-of-duties separation between the
        returning Supervisor and the author, and increments the study's revision_count
        by one."

        Design: Difficulty/compensating_invariant/home_study_return_then_resubmit_conserves_revision_parity
        """
        hs = self._returned_study()
        assert hs["revision_count"] == 1
        cw = make_caseworker_headers("cw-1")
        updated = validate_success(api_client.resubmit_home_study(hs["id"], cw), 200)
        # The compensating resubmit closes the open deficiency cycle; revision_count stays 1.
        assert updated["revision_count"] == 1


# ─── Corner (B): state_machines / home_study_initial_state_draft ──────────
def test_home_study_initial_state_draft():
    """PRD §3.2: "the study opens in DRAFT status, and the creating operator's
    X-User-ID is recorded as its authoring_caseworker_id."

    Design: Corner/state_machines/home_study_initial_state_draft
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    cw = make_caseworker_headers("cw-1")
    hs = validate_success(api_client.create_home_study(
        create_home_study_payload(case["id"], family["id"]), cw), 201)
    assert hs["status"] == "DRAFT"
    assert hs["revision_count"] == 0
    assert hs["expires_at"] is None


# ─── Corner (B): state_machines / approve_home_study_from_draft_invalid_state ──
def test_approve_home_study_from_draft_invalid_state():
    """PRD §3.2: "Any attempt to drive a transition from a state in which it is not
    defined is rejected with ERR_INVALID_STATE."
    PRD §3.2: "Approval requires the study to be UNDER_REVIEW".

    Design: Corner/state_machines/approve_home_study_from_draft_invalid_state
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    cw = make_caseworker_headers("cw-1")
    hs = validate_success(api_client.create_home_study(
        create_home_study_payload(case["id"], family["id"]), cw), 201)
    sup = make_supervisor_headers("sup-1")
    res = api_client.approve_home_study(hs["id"], sup)  # still DRAFT
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner (B): state_machines / terminal_match_declined_no_further_transition ──
def test_terminal_match_declined_no_further_transition():
    """PRD §3.3: "Declining requires only that the match be PROPOSED and moves it to
    DECLINED."
    PRD §3.3: "Acceptance requires the match to be PROPOSED".

    Design: Corner/state_machines/terminal_match_declined_no_further_transition
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    bp = create_birth_parent(agency["id"], birth_state="CA")
    match = validate_success(api_client.create_match(
        create_match_payload(case["id"], family["id"], bp["id"]), CW), 201)
    api_client.decline_match(match["id"], SUP)  # DECLINED (terminal)
    res = api_client.accept_match(match["id"], SUP)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner (B): state_machines / idempotency_double_sign_consent ─────────
def test_idempotency_double_sign_consent():
    """PRD §3.4: "Signing requires the consent to be PENDING".
    PRD §3.2: "Any attempt to drive a transition from a state in which it is not
    defined is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/idempotency_double_sign_consent
    """
    base = setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                          to_iso8601="2026-06-04T08:00:00.000Z",
                                          birth_state="CA")
    from test_helpers import create_signed_consent
    cv = current_case_version(base["case_id"])
    consent = create_signed_consent(base["case_id"], base["bp_id"], cv,
                                    revocation_basis="CALENDAR_DAYS",
                                    child_dob="2026-06-01T08:00:00.000Z")
    res = api_client.sign_consent(consent["id"], CW)  # already SIGNED
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner (B): state_machines / bubble_up_phase_to_matched_on_match_accept ──
def test_bubble_up_phase_to_matched_on_match_accept():
    """PRD §3.3: "on success the match moves to ACCEPTED and the case phase is
    recomputed (advancing toward MATCHED)."
    PRD §3.1: "if any match for the case is ACCEPTED, the phase is MATCHED."

    Design: Corner/state_machines/bubble_up_phase_to_matched_on_match_accept
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    hs = create_approved_home_study(case["id"], family["id"])
    bp = create_birth_parent(agency["id"], birth_state="CA")
    match = validate_success(api_client.create_match(
        create_match_payload(case["id"], family["id"], bp["id"]), CW), 201)
    accepted = validate_success(api_client.accept_match(match["id"], SUP), 200)
    assert accepted["status"] == "ACCEPTED"
    got = validate_success(api_client.get_case(case["id"], SUP), 200)
    assert got["phase"] == "MATCHED"


# ─── Corner (B): endpoints / pay_invoice_action_endpoint ──────────────────
def test_pay_invoice_action_endpoint():
    """PRD §3.8: "An issued invoice may be paid by a FinanceOfficer, moving it from
    ISSUED to PAID".

    Design: Corner/endpoints/pay_invoice_action_endpoint
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    create_family(case["id"], annual_income_cents=8_000_000)
    inv = validate_success(api_client.create_invoice(create_invoice_payload(case["id"]), FO), 201)
    paid = validate_success(api_client.pay_invoice(inv["id"], FO), 200)
    assert paid["status"] == "PAID"
