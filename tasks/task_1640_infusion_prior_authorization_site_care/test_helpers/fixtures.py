"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data
validator so a broken precondition surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    appeal_decision_payload,
    complete_p2p_payload,
    create_appeal_payload,
    create_appointment_payload,
    create_auth_request_payload,
    create_chair_payload,
    create_criteria_payload,
    create_dose_change_payload,
    create_line_item_payload,
    create_p2p_payload,
    create_patient_payload,
    create_policy_payload,
    create_site_determination_payload,
    determination_payload,
    dose_change_decision_payload,
    reschedule_p2p_payload,
    review_criteria_payload,
    verify_benefit_payload,
)
from .test_users import (
    AUTH_COORDINATOR_HEADERS,
    FINANCE_SPECIALIST_2_HEADERS,
    FINANCE_SPECIALIST_HEADERS,
    MEDICAL_DIRECTOR_2_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    POLICY_ADMIN_HEADERS,
    SCHEDULER_HEADERS,
)

ADMIN = POLICY_ADMIN_HEADERS
COORD = AUTH_COORDINATOR_HEADERS
MD_1 = MEDICAL_DIRECTOR_HEADERS
MD_2 = MEDICAL_DIRECTOR_2_HEADERS
FIN_1 = FINANCE_SPECIALIST_HEADERS
FIN_2 = FINANCE_SPECIALIST_2_HEADERS
SCHED = SCHEDULER_HEADERS


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and single-step actions
# ---------------------------------------------------------------------------

def create_policy(drug_code="J9001", **overrides) -> dict:
    """Create a payer policy. Returns the policy."""
    payload = create_policy_payload(drug_code=drug_code, **overrides)
    return get_success_data(api_client.create_payer_policy(payload, ADMIN))


def create_patient(member_id="M1001", **overrides) -> dict:
    """Register a patient with plan accumulators. Returns the patient."""
    payload = create_patient_payload(member_id=member_id, **overrides)
    return get_success_data(api_client.create_patient(payload, COORD))


def create_chair(site_type="OFFICE", label="CH-1", **overrides) -> dict:
    """Create an infusion chair. Returns the chair."""
    payload = create_chair_payload(site_type=site_type, label=label, **overrides)
    return get_success_data(api_client.create_infusion_chair(payload, ADMIN))


def create_draft_request(patient_id, policy_id, **overrides) -> dict:
    """Create an authorization request (born DRAFT). Returns the request."""
    payload = create_auth_request_payload(patient_id, policy_id, **overrides)
    return get_success_data(api_client.create_authorization_request(payload, COORD))


def add_benefit_investigation(auth_id) -> dict:
    """Open a benefit investigation (born INITIATED). Returns it."""
    return get_success_data(api_client.create_benefit_investigation(auth_id, COORD))


def verify_benefit_investigation(bi_id, determined_channel="MEDICAL") -> dict:
    """Verify a benefit investigation (VERIFIED, routing derived)."""
    return get_success_data(api_client.verify_benefit_investigation(
        bi_id, verify_benefit_payload(determined_channel), FIN_1))


def add_criteria_submission(auth_id, criterion_code="DIAG_CONFIRM",
                            response_value="biopsy-on-file") -> dict:
    """File a criteria submission (born SUBMITTED). Returns it."""
    return get_success_data(api_client.create_criteria_submission(
        auth_id, create_criteria_payload(criterion_code, response_value), COORD))


def review_criteria_submission(cs_id, outcome="ACCEPTED") -> dict:
    """MedicalDirector reviews a criterion (ACCEPTED/REJECTED, terminal)."""
    return get_success_data(api_client.review_criteria_submission(
        cs_id, review_criteria_payload(outcome), MD_1))


def run_site_determination(auth_id, **amounts) -> dict:
    """Run the site-of-care steering determination. Returns it."""
    return get_success_data(api_client.create_site_of_care_determination(
        auth_id, create_site_determination_payload(**amounts), MD_1))


def submit_request(auth_id) -> dict:
    """Submit (or resubmit) a request. Returns the SUBMITTED request."""
    return get_success_data(api_client.submit_authorization_request(auth_id, COORD))


def record_determination(auth_id, outcome, expected_version,
                         denial_reason=None) -> dict:
    """MedicalDirector records a determination with OCC. Returns the request."""
    return get_success_data(api_client.record_determination(
        auth_id,
        determination_payload(outcome, expected_version, denial_reason),
        MD_2,
    ))


def open_appeal(auth_id, reason="new-evidence") -> dict:
    """Open an appeal on a DENIED request (born LEVEL_1). Returns it."""
    return get_success_data(api_client.create_appeal(
        auth_id, create_appeal_payload(reason), COORD))


def decide_appeal(appeal_id, outcome="UPHELD") -> dict:
    return get_success_data(api_client.decide_appeal(
        appeal_id, appeal_decision_payload(outcome), MD_1))


def escalate_appeal(appeal_id) -> dict:
    return get_success_data(api_client.escalate_appeal(appeal_id, COORD))


def schedule_p2p(appeal_id, reviewer_user_id="md-9",
                 scheduled_start="2026-08-05T10:00:00Z",
                 scheduled_end="2026-08-05T10:30:00Z") -> dict:
    """Schedule a peer-to-peer call (born SCHEDULED, reschedule_count 0)."""
    return get_success_data(api_client.create_peer_to_peer_review(
        appeal_id,
        create_p2p_payload(reviewer_user_id, scheduled_start, scheduled_end),
        MD_1,
    ))


def reschedule_p2p(p2p_id, scheduled_start, scheduled_end) -> dict:
    return get_success_data(api_client.reschedule_peer_to_peer_review(
        p2p_id, reschedule_p2p_payload(scheduled_start, scheduled_end), MD_1))


def complete_p2p(p2p_id, outcome="UPHOLD") -> dict:
    return get_success_data(api_client.complete_peer_to_peer_review(
        p2p_id, complete_p2p_payload(outcome), MD_1))


def create_clearance(auth_id) -> dict:
    """Open a financial clearance on an APPROVED request (born ESTIMATED)."""
    return get_success_data(api_client.create_financial_clearance(auth_id, FIN_1))


def add_line_item(fc_id, description="drug", allowed_amount_cents=100000,
                  billed_charges_cents=100000) -> dict:
    """Add a responsibility line item; recomputes the estimate. Returns it."""
    return get_success_data(api_client.create_line_item(
        fc_id,
        create_line_item_payload(description, allowed_amount_cents,
                                 billed_charges_cents),
        FIN_1,
    ))


def void_line_item(li_id) -> dict:
    return get_success_data(api_client.void_line_item(li_id, FIN_1))


def clear_clearance(fc_id) -> dict:
    """Clear an ESTIMATED clearance via a second specialist (SoD-clean)."""
    return get_success_data(api_client.clear_financial_clearance(fc_id, FIN_2))


def get_clearance(fc_id) -> dict:
    return get_success_data(api_client.get_financial_clearance(fc_id, FIN_1))


def get_request(auth_id) -> dict:
    return get_success_data(api_client.get_authorization_request(auth_id, COORD))


def book_appointment(auth_id, chair_id, scheduled_start, scheduled_end) -> dict:
    """Book an infusion appointment (born SCHEDULED). Returns it."""
    return get_success_data(api_client.create_appointment(
        auth_id,
        create_appointment_payload(chair_id, scheduled_start, scheduled_end),
        SCHED,
    ))


def create_dose_change(auth_id, new_dose_mg) -> dict:
    """Request a dose change (born PENDING, delta/reauth computed)."""
    return get_success_data(api_client.create_dose_change_request(
        auth_id, create_dose_change_payload(new_dose_mg), COORD))


def decide_dose_change(dcr_id, outcome) -> dict:
    return get_success_data(api_client.decide_dose_change_request(
        dcr_id, dose_change_decision_payload(outcome), MD_1))


def advance_clock(to_iso8601) -> dict:
    """Advance the logical clock, applying all time-based transitions."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2/3: lifecycle chains over the authorization request
# ---------------------------------------------------------------------------

def setup_submittable_request(drug_code="J9001", member_id="M1001",
                              policy_overrides=None, patient_overrides=None,
                              request_overrides=None,
                              verify_channel="MEDICAL") -> dict:
    """Policy + patient + DRAFT request carrying all three evidentiary
    workstreams: a VERIFIED benefit investigation, an ACCEPTED criteria
    submission, and a site-of-care determination. Ready for submission.

    Returns a workspace dict: policy, patient, auth, benefit, criterion,
    site_determination.
    """
    policy_kwargs = {"drug_code": drug_code}
    policy_kwargs.update(policy_overrides or {})
    patient_kwargs = {"member_id": member_id}
    patient_kwargs.update(patient_overrides or {})
    policy = create_policy(**policy_kwargs)
    patient = create_patient(**patient_kwargs)
    auth = create_draft_request(patient["id"], policy["id"],
                                **(request_overrides or {}))
    benefit = add_benefit_investigation(auth["id"])
    benefit = verify_benefit_investigation(benefit["id"], verify_channel)
    criterion = add_criteria_submission(auth["id"])
    criterion = review_criteria_submission(criterion["id"], "ACCEPTED")
    site_determination = run_site_determination(auth["id"])
    return {
        "policy": policy,
        "patient": patient,
        "auth": auth,
        "benefit": benefit,
        "criterion": criterion,
        "site_determination": site_determination,
    }


def setup_submitted_request(**kwargs) -> dict:
    """A submittable request driven to SUBMITTED. auth carries the post-submit
    version (the OCC token for the first determination)."""
    ws = setup_submittable_request(**kwargs)
    ws["auth"] = submit_request(ws["auth"]["id"])
    return ws


def setup_approved_request(**kwargs) -> dict:
    """A submitted request driven to APPROVED. auth carries the post-approval
    state, including the computed validity window and approved_dose_mg."""
    ws = setup_submitted_request(**kwargs)
    ws["auth"] = record_determination(
        ws["auth"]["id"], "APPROVED", ws["auth"]["version"])
    return ws


def setup_denied_request(denial_reason="criteria-not-met", **kwargs) -> dict:
    """A submitted request driven to DENIED (appeal window open)."""
    ws = setup_submitted_request(**kwargs)
    ws["auth"] = record_determination(
        ws["auth"]["id"], "DENIED", ws["auth"]["version"], denial_reason)
    return ws


def setup_appeal_at_level1(reason="contest", **kwargs) -> dict:
    """A denied request with a fresh LEVEL_1 appeal. Adds key 'appeal'."""
    ws = setup_denied_request(**kwargs)
    ws["appeal"] = open_appeal(ws["auth"]["id"], reason)
    return ws


def setup_appeal_decided_upheld(**kwargs) -> dict:
    """A denied request with its appeal UPHELD at LEVEL_1 (LEVEL_1_DECIDED),
    the resting state from which peer-to-peer calls may be scheduled."""
    ws = setup_appeal_at_level1(**kwargs)
    ws["appeal"] = decide_appeal(ws["appeal"]["id"], "UPHELD")
    return ws


def setup_p2p_on_decided_appeal(reviewer_user_id="md-9",
                                scheduled_start="2026-08-05T10:00:00Z",
                                scheduled_end="2026-08-05T10:30:00Z",
                                **kwargs) -> dict:
    """A LEVEL_1_DECIDED appeal carrying one SCHEDULED peer-to-peer review.
    Adds key 'p2p'."""
    ws = setup_appeal_decided_upheld(**kwargs)
    ws["p2p"] = schedule_p2p(ws["appeal"]["id"], reviewer_user_id,
                             scheduled_start, scheduled_end)
    return ws


# ---------------------------------------------------------------------------
# Tier 4: financial-clearance states
# ---------------------------------------------------------------------------

def setup_approved_with_clearance(line_items=(), **kwargs) -> dict:
    """An APPROVED request with an ESTIMATED clearance, optionally pre-loaded
    with line items. Each entry is (description, allowed_cents, billed_cents).
    Adds keys 'clearance' and 'line_items'."""
    ws = setup_approved_request(**kwargs)
    ws["clearance"] = create_clearance(ws["auth"]["id"])
    ws["line_items"] = [
        add_line_item(ws["clearance"]["id"], description=d,
                      allowed_amount_cents=a, billed_charges_cents=b)
        for (d, a, b) in line_items
    ]
    ws["clearance"] = get_clearance(ws["clearance"]["id"])
    return ws


def setup_approved_with_cleared_clearance(line_items=(("drug", 10000, 10000),),
                                          **kwargs) -> dict:
    """An APPROVED request whose clearance is CLEARED (estimate comfortably
    below the prepay limit, cleared by a second specialist)."""
    ws = setup_approved_with_clearance(line_items=line_items, **kwargs)
    ws["clearance"] = clear_clearance(ws["clearance"]["id"])
    return ws


def setup_approved_with_chair(site_type="OFFICE", label="CH-1",
                              chair_overrides=None, **kwargs) -> dict:
    """An APPROVED request plus an infusion chair matching the recommended
    site. Adds key 'chair'."""
    ws = setup_approved_request(**kwargs)
    ws["chair"] = create_chair(site_type=site_type, label=label,
                               **(chair_overrides or {}))
    return ws


def setup_approved_with_cleared_clearance_and_chair(
        line_items=(("drug", 10000, 10000),), site_type="OFFICE", label="CH-1",
        chair_overrides=None, **kwargs) -> dict:
    """Full scheduling-ready scenario: APPROVED request, CLEARED clearance,
    matching-site chair."""
    ws = setup_approved_with_cleared_clearance(line_items=line_items, **kwargs)
    ws["chair"] = create_chair(site_type=site_type, label=label,
                               **(chair_overrides or {}))
    return ws


def setup_superseded_request(new_dose_mg=600, **kwargs) -> dict:
    """An APPROVED request driven to SUPERSEDED by an approved dose change
    whose delta reaches the re-authorization threshold. Adds key
    'dose_change'."""
    ws = setup_approved_request(**kwargs)
    ws["dose_change"] = create_dose_change(ws["auth"]["id"], new_dose_mg)
    ws["dose_change"] = decide_dose_change(ws["dose_change"]["id"], "APPROVED")
    ws["auth"] = get_request(ws["auth"]["id"])
    return ws
