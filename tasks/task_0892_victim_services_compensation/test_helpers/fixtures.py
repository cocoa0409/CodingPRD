"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch via PRD-declared endpoints, because
the harness restarts the server (empty DB) before every test. Helpers use the
lenient get_success_data() validator so setup failures surface as clear errors.

All roles are opaque (§2.1); helpers accept explicit user ids where a workflow
records the acting X-User-ID (denials, appeal decisions) so segregation-of-duties
scenarios (§2.10) can be built precisely.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_headers
from . import factories as f


# --------------------------------------------------------------------------
# Header shortcuts
# --------------------------------------------------------------------------
def _admin():
    return TEST_USERS["program_admin_headers"]


def _intake():
    return TEST_USERS["intake_counselor_headers"]


def _adj(user_id=None):
    return make_headers("Adjudicator", user_id)


def _finance():
    return TEST_USERS["finance_officer_headers"]


def _recovery():
    return TEST_USERS["recovery_officer_headers"]


def _appeals(user_id=None):
    return make_headers("AppealsOfficer", user_id)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def set_clock(api, iso):
    """Set the server logical clock (§2.6)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, _admin()))


def make_program(api, **overrides):
    """Create an OPEN program (§3.1). Returns the program dict."""
    return get_success_data(api.create_program(f.create_program_payload(**overrides), _admin()))


def program_version(api, program_id):
    """Read the program's current version (OCC token source, §2.8)."""
    return get_success_data(api.get_program(program_id, _admin()))["version"]


def make_case(api, program_id, **overrides):
    """Create a DRAFT case (§3.2)."""
    return get_success_data(api.create_case(f.create_case_payload(program_id, **overrides), _intake()))


def case_transition(api, case_id, to_status, role="Adjudicator", user_id=None, **extra):
    """Transition a case. IntakeCounselor drives SUBMITTED; Adjudicator the rest."""
    headers = _intake() if role == "IntakeCounselor" else _adj(user_id)
    payload = {"to_status": to_status, **extra}
    return get_success_data(api.transition_case(case_id, payload, headers))


def make_eligible_case(api, program=None, program_id=None, **case_overrides):
    """Create (or reuse) a program and drive a case to ELIGIBLE (§3.2).

    Returns (program, case). Defaults satisfy eligibility: reported_to_le=True,
    COOPERATIVE, filing within FILING_DEADLINE_DAYS.
    """
    if program_id is None:
        if program is None:
            program = make_program(api)
        program_id = program["id"]
    case = make_case(api, program_id, **case_overrides)
    case_transition(api, case["id"], "SUBMITTED", role="IntakeCounselor")
    case_transition(api, case["id"], "UNDER_REVIEW")
    case = case_transition(api, case["id"], "ELIGIBLE")
    return program, case


def make_under_review_case(api, program=None, program_id=None, **case_overrides):
    """Create a case and drive it to UNDER_REVIEW (no determination). Returns (program, case)."""
    if program_id is None:
        if program is None:
            program = make_program(api)
        program_id = program["id"]
    case = make_case(api, program_id, **case_overrides)
    case_transition(api, case["id"], "SUBMITTED", role="IntakeCounselor")
    case = case_transition(api, case["id"], "UNDER_REVIEW")
    return program, case


def make_claim(api, case_id, category="MEDICAL", **overrides):
    """Create a DRAFT claim (§3.3)."""
    return get_success_data(api.create_claim(f.create_claim_payload(case_id, category, **overrides), _intake()))


def claim_transition(api, claim_id, to_status, role="Adjudicator", user_id=None, **extra):
    headers = _intake() if role == "IntakeCounselor" else _adj(user_id)
    payload = {"to_status": to_status, **extra}
    return get_success_data(api.transition_claim(claim_id, payload, headers))


def make_approved_claim(api, case_id, category="MEDICAL", verified_amount_cents=None, **overrides):
    """Create a claim and drive it to APPROVED under an ELIGIBLE case (§3.5).

    verified_amount_cents required for non-LOST_WAGE at APPROVED; defaults to the
    claimed amount when omitted.
    """
    claim = make_claim(api, case_id, category, **overrides)
    claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
    claim_transition(api, claim["id"], "UNDER_REVIEW")
    extra = {}
    if category != "LOST_WAGE":
        if verified_amount_cents is None:
            verified_amount_cents = claim.get("claimed_amount_cents", overrides.get("claimed_amount_cents", 500000))
        extra["verified_amount_cents"] = verified_amount_cents
    claim = claim_transition(api, claim["id"], "APPROVED", **extra)
    return claim


def make_collateral_source(api, claim_id, **overrides):
    """Declare a collateral source (§3.4)."""
    return get_success_data(
        api.create_collateral_source(f.create_collateral_source_payload(claim_id, **overrides), _intake())
    )


def collateral_transition(api, cs_id, to_status):
    return get_success_data(api.transition_collateral_source(cs_id, {"to_status": to_status}, _adj()))


def make_award(api, case_id, expected_program_version, **overrides):
    """Create (calculate) an award (§3.6)."""
    return get_success_data(
        api.create_award(f.create_award_payload(case_id, expected_program_version, **overrides), _adj())
    )


def award_transition(api, award_id, to_status):
    """Approve (Adjudicator) or finalize (FinanceOfficer) an award (§3.6)."""
    headers = _finance() if to_status == "FINALIZED" else _adj()
    return get_success_data(api.transition_award(award_id, {"to_status": to_status}, headers))


def make_finalized_award(api, case_id, expected_program_version):
    """Create -> APPROVED -> FINALIZED an award. Returns the award dict (§3.6)."""
    award = make_award(api, case_id, expected_program_version)
    award_transition(api, award["id"], "APPROVED")
    award = award_transition(api, award["id"], "FINALIZED")
    return award


def make_disbursement(api, award_id, **overrides):
    """Schedule a disbursement (§3.7)."""
    return get_success_data(api.create_disbursement(f.create_disbursement_payload(award_id, **overrides), _finance()))


def disbursement_transition(api, disbursement_id, to_status):
    return get_success_data(api.transition_disbursement(disbursement_id, {"to_status": to_status}, _finance()))


def make_recovery(api, case_id, **overrides):
    """Open a restitution recovery (§3.8)."""
    return get_success_data(api.create_recovery(f.create_recovery_payload(case_id, **overrides), _recovery()))


def recovery_transition(api, recovery_id, to_status):
    return get_success_data(api.transition_recovery(recovery_id, {"to_status": to_status}, _recovery()))


def make_receipt(api, recovery_id, **overrides):
    """Record a receipt against a recovery (§3.8)."""
    return get_success_data(api.create_receipt(recovery_id, f.create_receipt_payload(**overrides), _recovery()))


def receipt_transition(api, receipt_id, to_status):
    return get_success_data(api.transition_receipt(receipt_id, {"to_status": to_status}, _recovery()))


def make_appeal(api, case_id, **overrides):
    """File an appeal (§3.9)."""
    return get_success_data(api.create_appeal(f.create_appeal_payload(case_id, **overrides), _intake()))


def appeal_transition(api, appeal_id, to_status, user_id=None):
    """Transition an appeal as AppealsOfficer; user_id sets the acting X-User-ID (§2.10)."""
    return get_success_data(api.transition_appeal(appeal_id, {"to_status": to_status}, _appeals(user_id)))


# --------------------------------------------------------------------------
# High-level composites
# --------------------------------------------------------------------------
def setup_ineligible_case_with_appeal_under_review(api, denier_id="adj-1", with_denied_claim=False,
                                                   claimed_amount_cents=500000):
    """Case denied INELIGIBLE by `denier_id`; appeal filed and moved to UNDER_REVIEW (§3.2, §3.9).

    When with_denied_claim=True, a claim is also DENIED by the same denier before the
    case is ruled INELIGIBLE (so the reopen cascade of §3.9 has a claim to carry back).
    Returns (program, case, appeal, claim_or_None).
    """
    program, case = make_under_review_case(api)
    claim = None
    if with_denied_claim:
        claim = make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=claimed_amount_cents)
        claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
        claim_transition(api, claim["id"], "UNDER_REVIEW")
        claim = claim_transition(api, claim["id"], "DENIED", user_id=denier_id)
    case = case_transition(api, case["id"], "INELIGIBLE", user_id=denier_id)
    appeal = make_appeal(api, case["id"])
    appeal = appeal_transition(api, appeal["id"], "UNDER_REVIEW")
    return program, case, appeal, claim


def setup_finalized_award_with_disbursement(api, claimed_amount_cents=1000000,
                                            verified_amount_cents=1000000,
                                            disbursement_amount_cents=1000000,
                                            payee_type="MEDICAL_PROVIDER"):
    """Full chain to a FINALIZED award with one SCHEDULED disbursement (§3.5–§3.7).

    Returns (program, case, claim, award, disbursement).
    """
    program = make_program(api)
    _, case = make_eligible_case(api, program=program)
    claim = make_approved_claim(api, case["id"], "MEDICAL",
                                claimed_amount_cents=claimed_amount_cents,
                                verified_amount_cents=verified_amount_cents)
    version = program_version(api, program["id"])
    award = make_finalized_award(api, case["id"], version)
    disbursement = make_disbursement(api, award["id"],
                                     amount_cents=disbursement_amount_cents,
                                     payee_type=payee_type)
    return program, case, claim, award, disbursement
