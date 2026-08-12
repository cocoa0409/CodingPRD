"""Composite setup helpers (multi-step preconditions shared across tests).

All helpers hit the real API via the shared api_client and use get_success_data
(lenient 2xx validator) so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_asset_payload,
    create_measure_payload,
    create_counterparty_payload,
    create_nda_payload,
    create_obligation_payload,
    create_employee_payload,
    create_exit_interview_payload,
    create_grant_payload,
    create_disclosure_payload,
    create_forensic_review_payload,
    create_demand_letter_payload,
    create_preservation_notice_payload,
    create_evidence_item_payload,
    create_training_assignment_payload,
    create_clean_desk_audit_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_ip_counsel_headers,
    make_security_officer_headers,
    make_senior_counsel_headers,
)

HR = TEST_USERS["hr_partner_headers"]
IP = TEST_USERS["ip_counsel_headers"]
IP2 = TEST_USERS["ip_counsel_2_headers"]
SEC = TEST_USERS["security_officer_headers"]
SEC2 = TEST_USERS["security_officer_2_headers"]
SENIOR = TEST_USERS["senior_counsel_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_registered_asset(**overrides):
    """Create an asset and move it DRAFT -> REGISTERED. Returns the asset dict."""
    resp = api_client.create_asset(create_asset_payload(**overrides), IP)
    asset = get_success_data(resp)
    resp = api_client.transition_asset(asset["id"], {"to_status": "REGISTERED"}, IP)
    return get_success_data(resp)


def create_counterparty(**overrides):
    """Create a counterparty (starts ACTIVE). Returns the counterparty dict."""
    resp = api_client.create_counterparty(create_counterparty_payload(**overrides), IP)
    return get_success_data(resp)


def create_active_nda(counterparty_id, **overrides):
    """Create an NDA and walk DRAFT -> SENT -> EXECUTED -> ACTIVE.

    The EXECUTED step is ownership-gated: the CounterpartyRep identity is the
    counterparty's id (PRD §2.1). Returns the NDA dict.
    """
    resp = api_client.create_nda(create_nda_payload(counterparty_id, **overrides), IP)
    nda = get_success_data(resp)
    api_client.transition_nda(nda["id"], {"to_status": "SENT"}, IP)
    api_client.transition_nda(
        nda["id"], {"to_status": "EXECUTED"}, make_counterparty_rep_headers(counterparty_id)
    )
    resp = api_client.transition_nda(nda["id"], {"to_status": "ACTIVE"}, IP)
    return get_success_data(resp)


def add_verified_measure(asset_id, measure_type, title=None, evidence_uri=None,
                         implementer_headers=None):
    """Create a measure and walk it PLANNED -> IMPLEMENTED -> VERIFIED.

    Verification enforces implementer != verifier (PRD §2.9), so the implementer
    is a security officer and the verifier is counsel. Returns the measure dict.
    """
    payload_kwargs = {"measure_type": measure_type}
    if title is not None:
        payload_kwargs["title"] = title
    if evidence_uri is not None:
        payload_kwargs["evidence_uri"] = evidence_uri
    resp = api_client.create_measure(create_measure_payload(asset_id, **payload_kwargs), SEC)
    measure = get_success_data(resp)
    impl = implementer_headers or SEC
    api_client.transition_measure(measure["id"], {"to_status": "IMPLEMENTED"}, impl)
    resp = api_client.transition_measure(measure["id"], {"to_status": "VERIFIED"}, IP)
    return get_success_data(resp)


def add_implemented_measure(asset_id, measure_type, title=None, evidence_uri=None):
    """Create a measure and walk PLANNED -> IMPLEMENTED (not verified)."""
    payload_kwargs = {"measure_type": measure_type}
    if title is not None:
        payload_kwargs["title"] = title
    if evidence_uri is not None:
        payload_kwargs["evidence_uri"] = evidence_uri
    resp = api_client.create_measure(create_measure_payload(asset_id, **payload_kwargs), SEC)
    measure = get_success_data(resp)
    resp = api_client.transition_measure(measure["id"], {"to_status": "IMPLEMENTED"}, SEC)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: employee hierarchy (ack + training + activation)
# ---------------------------------------------------------------------------

def get_pending_ack_id(employee_id, policy_version=None):
    """Find the PENDING acknowledgment for an employee (auto-created at onboarding)."""
    params = {"employee_id": employee_id, "status": "PENDING"}
    if policy_version is not None:
        params["policy_version"] = policy_version
    resp = api_client.list_acknowledgments(HR, params=params)
    rows = get_success_data(resp)
    assert isinstance(rows, list) and len(rows) >= 1, \
        f"Setup failed: no PENDING acknowledgment for employee {employee_id}"
    return rows[0]["id"]


def sign_employee_ack(employee_id, ack_id=None):
    """Sign the employee's pending acknowledgment as the employee themself."""
    if ack_id is None:
        ack_id = get_pending_ack_id(employee_id)
    resp = api_client.sign_acknowledgment(ack_id, make_employee_headers(employee_id))
    return get_success_data(resp)


def get_basic_training_id(employee_id):
    """Find the auto-created BASIC_TS training assignment for an employee."""
    resp = api_client.list_training_assignments(
        HR, params={"employee_id": employee_id, "module": "BASIC_TS"}
    )
    rows = get_success_data(resp)
    assert isinstance(rows, list) and len(rows) >= 1, \
        f"Setup failed: no BASIC_TS assignment for employee {employee_id}"
    return rows[0]["id"]


def complete_basic_training(employee_id):
    """Complete the auto-created BASIC_TS assignment as the employee themself."""
    tr_id = get_basic_training_id(employee_id)
    resp = api_client.transition_training_assignment(
        tr_id, {"to_status": "COMPLETED"}, make_employee_headers(employee_id)
    )
    return get_success_data(resp)


def create_employee_record(**overrides):
    """Create an employee record (PREBOARDING; ack + BASIC_TS auto-created)."""
    resp = api_client.create_employee(create_employee_payload(**overrides), HR)
    return get_success_data(resp)


def create_active_employee(complete_training=True, **overrides):
    """Onboard an employee, sign their ack, activate them; optionally complete
    the auto-created BASIC_TS assignment so training_current is true.
    Returns the employee dict."""
    emp = create_employee_record(**overrides)
    sign_employee_ack(emp["id"])
    resp = api_client.transition_employee(emp["id"], {"to_status": "ACTIVE"}, HR)
    emp = get_success_data(resp)
    if complete_training:
        complete_basic_training(emp["id"])
        resp = api_client.get_employee(emp["id"], HR)
        emp = get_success_data(resp)
    return emp


# ---------------------------------------------------------------------------
# Tier 3: grant lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_grant_request(employee_id, asset_id, **overrides):
    """Employee requests a grant for themself (ownership: X-User-ID == employee_id)."""
    resp = api_client.create_grant(
        create_grant_payload(employee_id, asset_id, **overrides),
        make_employee_headers(employee_id),
    )
    return get_success_data(resp)


def create_approved_grant(employee_id, asset_id, approver_headers=None, **overrides):
    """Grant REQUESTED -> APPROVED by a non-requester officer. Returns grant dict."""
    grant = create_grant_request(employee_id, asset_id, **overrides)
    approver = approver_headers or make_security_officer_headers("sec_officer_1")
    resp = api_client.transition_grant(grant["id"], {"to_status": "APPROVED"}, approver)
    return get_success_data(resp)


def create_provisioned_grant(employee_id, asset_id, **overrides):
    """Grant walked REQUESTED -> APPROVED -> PROVISIONED. Returns grant dict."""
    grant = create_approved_grant(employee_id, asset_id, **overrides)
    resp = api_client.transition_grant(grant["id"], {"to_status": "PROVISIONED"}, SEC)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: disclosure lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_disclosure(employee_id, asset_id, nda_id, **overrides):
    """Employee drafts a disclosure request (requester_employee_id = X-User-ID)."""
    resp = api_client.create_disclosure(
        create_disclosure_payload(asset_id, nda_id, **overrides),
        make_employee_headers(employee_id),
    )
    return get_success_data(resp)


def create_submitted_disclosure(employee_id, asset_id, nda_id, **overrides):
    """Disclosure walked DRAFT -> SUBMITTED (pins captured). Returns dict."""
    disc = create_draft_disclosure(employee_id, asset_id, nda_id, **overrides)
    resp = api_client.transition_disclosure(
        disc["id"], {"to_status": "SUBMITTED"}, make_employee_headers(employee_id)
    )
    return get_success_data(resp)


def create_under_review_disclosure(employee_id, asset_id, nda_id, **overrides):
    """Disclosure walked DRAFT -> SUBMITTED -> UNDER_REVIEW. Returns dict."""
    disc = create_submitted_disclosure(employee_id, asset_id, nda_id, **overrides)
    resp = api_client.transition_disclosure(disc["id"], {"to_status": "UNDER_REVIEW"}, IP)
    return get_success_data(resp)


def create_approved_disclosure(employee_id, asset_id, nda_id, **overrides):
    """Disclosure walked through to APPROVED by a non-requester counsel."""
    disc = create_under_review_disclosure(employee_id, asset_id, nda_id, **overrides)
    resp = api_client.transition_disclosure(
        disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: exit-interview hierarchy
# ---------------------------------------------------------------------------

def create_certified_interview(employee_id, **overrides):
    """Schedule an interview, conduct it, set both flags, certify. Returns dict."""
    resp = api_client.create_exit_interview(
        create_exit_interview_payload(employee_id, **overrides), HR
    )
    interview = get_success_data(resp)
    api_client.transition_exit_interview(interview["id"], {"to_status": "CONDUCTED"}, HR)
    api_client.patch_exit_interview(
        interview["id"],
        {"return_certification": True, "obligations_reiterated": True},
        HR,
    )
    resp = api_client.transition_exit_interview(interview["id"], {"to_status": "CERTIFIED"}, HR)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: forensic review + demand-letter terminal states
# ---------------------------------------------------------------------------

def create_escalated_review(employee_id, exfil_indicator_count=1, evidence_overrides=None):
    """Open a POLICY review and walk it OPENED -> IMAGING -> FINDINGS_DRAFTED
    -> COUNSEL_REVIEW -> ESCALATED with one evidence item and indicators recorded.
    Returns the review dict."""
    resp = api_client.create_forensic_review(
        create_forensic_review_payload(employee_id), IP
    )
    review = get_success_data(resp)
    api_client.transition_forensic_review(review["id"], {"to_status": "IMAGING"}, SEC)
    ev_kwargs = evidence_overrides or {}
    api_client.create_evidence_item(create_evidence_item_payload(review["id"], **ev_kwargs), SEC)
    api_client.transition_forensic_review(review["id"], {"to_status": "FINDINGS_DRAFTED"}, SEC)
    api_client.patch_forensic_review(
        review["id"], {"exfil_indicator_count": exfil_indicator_count}, SEC
    )
    api_client.transition_forensic_review(review["id"], {"to_status": "COUNSEL_REVIEW"}, IP)
    resp = api_client.transition_forensic_review(review["id"], {"to_status": "ESCALATED"}, IP)
    return get_success_data(resp)


def create_involuntary_notice_employee(**overrides):
    """Employee walked ACTIVE -> NOTICE with departure_type=INVOLUNTARY, which
    auto-creates an OPENED forensic review. Returns (employee, review)."""
    emp = create_active_employee(complete_training=False, **overrides)
    resp = api_client.transition_employee(
        emp["id"], {"to_status": "NOTICE", "departure_type": "INVOLUNTARY"}, HR
    )
    emp = get_success_data(resp)
    resp = api_client.list_forensic_reviews(IP, params={"employee_id": emp["id"]})
    reviews = get_success_data(resp)
    assert isinstance(reviews, list) and len(reviews) >= 1, \
        "Setup failed: involuntary notice did not auto-create a forensic review"
    return emp, reviews[0]


def escalate_review(review_id, exfil_indicator_count=1, evidence_overrides=None):
    """Walk an OPENED review through to ESCALATED. Returns the review dict."""
    api_client.transition_forensic_review(review_id, {"to_status": "IMAGING"}, SEC)
    ev_kwargs = evidence_overrides or {}
    api_client.create_evidence_item(create_evidence_item_payload(review_id, **ev_kwargs), SEC)
    api_client.transition_forensic_review(review_id, {"to_status": "FINDINGS_DRAFTED"}, SEC)
    api_client.patch_forensic_review(
        review_id, {"exfil_indicator_count": exfil_indicator_count}, SEC
    )
    api_client.transition_forensic_review(review_id, {"to_status": "COUNSEL_REVIEW"}, IP)
    resp = api_client.transition_forensic_review(review_id, {"to_status": "ESCALATED"}, IP)
    return get_success_data(resp)


def create_escalated_review_via_notice(emp_overrides=None, exfil_indicator_count=1):
    """Involuntary-notice employee whose auto-created review is walked to ESCALATED.
    Returns (employee, review)."""
    emp, review = create_involuntary_notice_employee(**(emp_overrides or {}))
    review = escalate_review(review["id"], exfil_indicator_count=exfil_indicator_count)
    return emp, review


# ---------------------------------------------------------------------------
# Tier 4: exposure / tier targeting
# ---------------------------------------------------------------------------

def make_obligations_overdue(nda_id, count, due_at="2026-05-10T00:00:00Z",
                             clock="2026-05-20T00:00:00Z"):
    """Create `count` obligations with due_at in the past, move the clock past
    them, and sweep so they all become OVERDUE. Returns the list of obligation ids."""
    ids = []
    for _ in range(count):
        resp = api_client.create_obligation(
            create_obligation_payload(nda_id, due_at=due_at), IP
        )
        ids.append(get_success_data(resp)["id"])
    api_client.set_clock({"to_iso8601": clock}, IP)
    api_client.run_sweep(IP)
    return ids


def escalate_obligations(obligation_ids):
    """Escalate each (already OVERDUE) obligation."""
    for ob_id in obligation_ids:
        api_client.transition_obligation(ob_id, {"to_status": "ESCALATED"}, IP)


def create_counterparty_at_trailing(target_points, escalate_count=0):
    """Build a counterparty with an ACTIVE NDA whose obligations are driven to
    OVERDUE (10 pts each, counted now) and optionally ESCALATED (25 pts each).

    trailing = 10 * overdue_count + 25 * escalate_count.

    Returns (counterparty, nda, all_obligation_ids).
    """
    overdue_count = (target_points - 25 * escalate_count) // 10
    cp = create_counterparty()
    nda = create_active_nda(cp["id"])
    ids = make_obligations_overdue(nda["id"], overdue_count + escalate_count)
    if escalate_count:
        escalate_obligations(ids[:escalate_count])
    return cp, nda, ids


# ---------------------------------------------------------------------------
# Composite scenario: counterparty + active NDA + posture-ready asset
# ---------------------------------------------------------------------------

def setup_adequate_asset(measure_specs=None, **asset_overrides):
    """REGISTERED asset carrying VERIFIED measures that place posture at ADEQUATE
    by default (TECHNICAL 25 + PHYSICAL 15 = 40). measure_specs is a list of
    (measure_type, target_status) where target_status is VERIFIED or IMPLEMENTED.
    Returns the asset dict."""
    asset = create_registered_asset(**asset_overrides)
    if measure_specs is None:
        measure_specs = [("TECHNICAL", "VERIFIED"), ("PHYSICAL", "VERIFIED")]
    for measure_type, target in measure_specs:
        if target == "VERIFIED":
            add_verified_measure(asset["id"], measure_type)
        elif target == "IMPLEMENTED":
            add_implemented_measure(asset["id"], measure_type)
        else:
            api_client.create_measure(
                create_measure_payload(asset["id"], measure_type=measure_type), SEC
            )
    resp = api_client.get_asset(asset["id"], IP)
    return get_success_data(resp)
