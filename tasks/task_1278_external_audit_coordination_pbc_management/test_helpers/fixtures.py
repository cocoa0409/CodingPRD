"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Identity threading: ownership-gated calls (evidence
upload, PBC submit, linked-query respond) always pass the PBC request's
owner_user_id as X-User-ID; rep-letter signing always uses a Controller id
distinct from the letter's prepared_by_user_id (PRD §3.8 SoD).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, VALID_SHA256_A
from .factories import (
    create_adjustment_payload,
    create_engagement_payload,
    create_evidence_upload_payload,
    create_fee_change_request_payload,
    create_fieldwork_visit_payload,
    create_location_payload,
    create_pbc_request_payload,
    create_query_payload,
    create_representation_letter_payload,
    create_sampling_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_controller_headers,
    make_preparer_headers,
)

CONTROLLER = TEST_USERS["controller_headers"]
PREPARER = TEST_USERS["preparer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    data = get_success_data(resp)
    if expected_status is not None and isinstance(data, dict):
        status = data.get("status") or data.get("disposition")
        assert status == expected_status, (
            f"Setup failed at {step}: expected {expected_status}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.8)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, CONTROLLER)
    return _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 1 — engagement stand-up and lifecycle walks
# ---------------------------------------------------------------------------

def create_engagement(**overrides):
    resp = api_client.create_engagement(
        create_engagement_payload(**overrides), CONTROLLER)
    return _ok("create_engagement", resp, expected_status="PLANNING")


def get_engagement(engagement_id):
    resp = api_client.get_engagement(engagement_id, CONTROLLER)
    return _ok("get_engagement", resp)


def engagement_version(engagement_id):
    return get_engagement(engagement_id)["version"]


def add_location(engagement_id, **overrides):
    resp = api_client.create_location(
        create_location_payload(engagement_id, **overrides), CONTROLLER)
    return _ok("create_location", resp)


def commence_fieldwork(engagement_id):
    resp = api_client.commence_fieldwork(engagement_id, CONTROLLER)
    return _ok("commence_fieldwork", resp, expected_status="FIELDWORK")


def complete_fieldwork(engagement_id):
    resp = api_client.complete_fieldwork(engagement_id, AUDITOR)
    return _ok("complete_fieldwork", resp,
               expected_status="FIELDWORK_COMPLETE")


def create_fieldwork_engagement(**overrides):
    """Engagement + one location + commence-fieldwork.

    Returns (engagement, location) with engagement in FIELDWORK.
    """
    eng = create_engagement(**overrides)
    loc = add_location(eng["id"])
    eng = commence_fieldwork(eng["id"])
    return eng, loc


def setup_closing_engagement(**overrides):
    """Engagement walked to FIELDWORK_COMPLETE (no PBCs, no queries).

    Returns dict(engagement=..., location=...).
    """
    eng, loc = create_fieldwork_engagement(**overrides)
    eng = complete_fieldwork(eng["id"])
    return {"engagement": eng, "location": loc}


# ---------------------------------------------------------------------------
# Tier 2 — PBC requests and evidence lifecycle
# ---------------------------------------------------------------------------

def create_pbc(engagement_id, owner=None, **overrides):
    """ExternalAuditor adds a PBC request; starts OPEN (PRD §3.2)."""
    resp = api_client.create_pbc_request(
        create_pbc_request_payload(
            engagement_id,
            owner_user_id=owner or TEST_DEFAULTS["PBC_OWNER"],
            **overrides),
        AUDITOR,
    )
    return _ok("create_pbc_request", resp, expected_status="OPEN")


def upload_evidence(pbc_id, engagement_id, owner=None, **overrides):
    """Owner uploads one evidence version (OCC-guarded).

    Reads the engagement's current version for expected_engagement_version.
    Returns the EvidenceUpload in PENDING_REVIEW.
    """
    owner = owner or TEST_DEFAULTS["PBC_OWNER"]
    version = engagement_version(engagement_id)
    resp = api_client.upload_evidence(
        pbc_id,
        create_evidence_upload_payload(version, **overrides),
        make_preparer_headers(owner),
    )
    return _ok("upload_evidence", resp, expected_status="PENDING_REVIEW")


def submit_pbc(pbc_id, owner=None):
    owner = owner or TEST_DEFAULTS["PBC_OWNER"]
    resp = api_client.submit_pbc_request(
        pbc_id, make_preparer_headers(owner))
    return _ok("submit_pbc_request", resp, expected_status="SUBMITTED")


def review_pbc(pbc_id, decision, rationale=None):
    payload = {"decision": decision}
    if rationale is not None:
        payload["rationale"] = rationale
    resp = api_client.review_pbc_request(pbc_id, payload, AUDITOR)
    return _ok("review_pbc_request", resp)


def create_submitted_pbc(engagement_id, owner=None, **upload_overrides):
    """PBC with one PENDING_REVIEW upload, SUBMITTED. Returns (pbc, upload)."""
    owner = owner or TEST_DEFAULTS["PBC_OWNER"]
    pbc = create_pbc(engagement_id, owner=owner)
    upload = upload_evidence(pbc["id"], engagement_id, owner=owner,
                             **upload_overrides)
    pbc = submit_pbc(pbc["id"], owner=owner)
    return pbc, upload


def create_accepted_pbc(engagement_id, owner=None, **upload_overrides):
    """Full upload -> submit -> ACCEPT cycle. Returns (pbc, upload)."""
    pbc, upload = create_submitted_pbc(engagement_id, owner=owner,
                                       **upload_overrides)
    pbc = review_pbc(pbc["id"], "ACCEPT")
    assert pbc["status"] == "ACCEPTED", (
        f"Setup failed at review ACCEPT: got {pbc['status']}"
    )
    return pbc, upload


def create_rejected_pbc(engagement_id, owner=None, **upload_overrides):
    """Full upload -> submit -> REJECT cycle. Returns (pbc, upload)."""
    pbc, upload = create_submitted_pbc(engagement_id, owner=owner,
                                       **upload_overrides)
    pbc = review_pbc(pbc["id"], "REJECT", rationale="Insufficient detail")
    assert pbc["status"] == "REJECTED", (
        f"Setup failed at review REJECT: got {pbc['status']}"
    )
    return pbc, upload


# ---------------------------------------------------------------------------
# Tier 2 — auditor queries
# ---------------------------------------------------------------------------

def create_query(engagement_id, **overrides):
    resp = api_client.create_query(
        create_query_payload(engagement_id, **overrides),
        make_auditor_headers(TEST_DEFAULTS["VISIT_AUDITOR"]),
    )
    return _ok("create_query", resp, expected_status="OPEN")


def get_query(query_id):
    resp = api_client.get_query(query_id, CONTROLLER)
    return _ok("get_query", resp)


def route_query(query_id):
    resp = api_client.route_query_to_client(query_id, AUDITOR)
    return _ok("route_query_to_client", resp, expected_status="AWAITING_CLIENT")


def respond_query(query_id, responder_user=None, response_text="See attached"):
    headers = (make_preparer_headers(responder_user)
               if responder_user is not None else PREPARER)
    resp = api_client.respond_to_query(
        query_id, {"response_text": response_text}, headers)
    return _ok("respond_to_query", resp, expected_status="RESPONDED")


def escalate_query(query_id):
    resp = api_client.escalate_query(query_id, AUDITOR)
    return _ok("escalate_query", resp, expected_status="ESCALATED")


def close_query(query_id):
    resp = api_client.close_query(query_id, AUDITOR)
    return _ok("close_query", resp, expected_status="CLOSED")


# ---------------------------------------------------------------------------
# Tier 2 — sampling requests and fieldwork visits
# ---------------------------------------------------------------------------

def create_sampling(engagement_id, location_ids, **overrides):
    resp = api_client.create_sampling_request(
        create_sampling_request_payload(engagement_id, location_ids,
                                        **overrides),
        AUDITOR,
    )
    return _ok("create_sampling_request", resp, expected_status="DRAFT")


def get_sampling(sampling_id):
    resp = api_client.get_sampling_request(sampling_id, CONTROLLER)
    return _ok("get_sampling_request", resp)


def dispatch_sampling(sampling_id):
    resp = api_client.dispatch_sampling_request(sampling_id, AUDITOR)
    return _ok("dispatch_sampling_request", resp, expected_status="DISPATCHED")


def create_visit(engagement_id, location_id, auditor_user=None, **overrides):
    resp = api_client.create_fieldwork_visit(
        create_fieldwork_visit_payload(
            engagement_id, location_id,
            auditor_user_id=auditor_user or TEST_DEFAULTS["VISIT_AUDITOR"],
            **overrides),
        AUDITOR,
    )
    return _ok("create_fieldwork_visit", resp, expected_status="SCHEDULED")


def get_visit(visit_id):
    resp = api_client.get_fieldwork_visit(visit_id, CONTROLLER)
    return _ok("get_fieldwork_visit", resp)


# ---------------------------------------------------------------------------
# Tier 2 — adjustments and the passed-adjustment schedule
# ---------------------------------------------------------------------------

def create_adjustment(engagement_id, amount_cents=None, **overrides):
    resp = api_client.create_adjustment(
        create_adjustment_payload(
            engagement_id,
            amount_cents=amount_cents
            if amount_cents is not None
            else TEST_DEFAULTS["ADJUSTMENT_AMOUNT_CENTS"],
            **overrides),
        make_auditor_headers(TEST_DEFAULTS["VISIT_AUDITOR"]),
    )
    return _ok("create_adjustment", resp, expected_status="PROPOSED")


def get_adjustment(adjustment_id):
    resp = api_client.get_adjustment(adjustment_id, CONTROLLER)
    return _ok("get_adjustment", resp)


def disposition_adjustment(adjustment_id, disposition, rationale=None,
                           controller_user="ctrl-1"):
    payload = {"disposition": disposition}
    if rationale is not None:
        payload["rationale"] = rationale
    resp = api_client.disposition_adjustment(
        adjustment_id, payload, make_controller_headers(controller_user))
    return _ok("disposition_adjustment", resp, expected_status=None)


def pass_adjustment(adjustment_id, rationale="Client refuses",
                    controller_user="ctrl-1"):
    adj = disposition_adjustment(adjustment_id, "PASS",
                                 rationale=rationale,
                                 controller_user=controller_user)
    assert adj["disposition"] == "PASSED", (
        f"Setup failed at disposition PASS: got {adj['disposition']}"
    )
    return adj


# ---------------------------------------------------------------------------
# Tier 3 — representation letter and closeout chain
# ---------------------------------------------------------------------------

def create_rep_letter(engagement_id, preparer_user=None):
    preparer_user = preparer_user or TEST_DEFAULTS["REP_PREPARER_USER"]
    resp = api_client.create_representation_letter(
        create_representation_letter_payload(engagement_id),
        make_preparer_headers(preparer_user),
    )
    return _ok("create_representation_letter", resp, expected_status="DRAFT")


def submit_rep_letter(letter_id, preparer_user=None):
    preparer_user = preparer_user or TEST_DEFAULTS["REP_PREPARER_USER"]
    resp = api_client.submit_representation_letter(
        letter_id, make_preparer_headers(preparer_user))
    return _ok("submit_representation_letter", resp,
               expected_status="PENDING_SIGNATURE")


def sign_rep_letter(letter_id, engagement_id, signer_user=None):
    """Controller (distinct from the drafter) signs; OCC version re-read."""
    signer_user = signer_user or TEST_DEFAULTS["REP_SIGNER_USER"]
    version = engagement_version(engagement_id)
    resp = api_client.sign_representation_letter(
        letter_id, {"expected_engagement_version": version},
        make_controller_headers(signer_user))
    return _ok("sign_representation_letter", resp, expected_status="SIGNED")


def setup_pending_rep_letter(engagement_id, preparer_user=None):
    """DRAFT letter submitted for signature. Returns the letter."""
    preparer_user = preparer_user or TEST_DEFAULTS["REP_PREPARER_USER"]
    letter = create_rep_letter(engagement_id, preparer_user=preparer_user)
    return submit_rep_letter(letter["id"], preparer_user=preparer_user)


def setup_signed_engagement(**overrides):
    """Engagement with SIGNED rep letter (posture LOCKED, not yet reported).

    Returns dict(engagement, location, letter).
    """
    ctx = setup_closing_engagement(**overrides)
    letter = setup_pending_rep_letter(ctx["engagement"]["id"])
    letter = sign_rep_letter(letter["id"], ctx["engagement"]["id"])
    ctx["letter"] = letter
    ctx["engagement"] = get_engagement(ctx["engagement"]["id"])
    return ctx


def issue_report(engagement_id):
    resp = api_client.issue_report(engagement_id, AUDITOR)
    return _ok("issue_report", resp, expected_status="REPORT_ISSUED")


# ---------------------------------------------------------------------------
# Tier 2 — fee change requests
# ---------------------------------------------------------------------------

def create_fee_change(engagement_id, delta_cents=None, proposer="auditor",
                      **overrides):
    """proposer: "auditor" (ExternalAuditor) or "controller" (Controller)."""
    headers = AUDITOR if proposer == "auditor" else CONTROLLER
    resp = api_client.create_fee_change_request(
        create_fee_change_request_payload(
            engagement_id,
            delta_cents=delta_cents
            if delta_cents is not None
            else TEST_DEFAULTS["FEE_DELTA_CENTS"],
            **overrides),
        headers,
    )
    return _ok("create_fee_change_request", resp, expected_status="PROPOSED")


def get_fee_change(fee_change_id):
    resp = api_client.get_fee_change_request(fee_change_id, CONTROLLER)
    return _ok("get_fee_change_request", resp)


def resolve_fee_change(fee_change_id, decision, resolver="controller"):
    """resolver must be the counter-party of the proposer (PRD §3.7)."""
    headers = CONTROLLER if resolver == "controller" else AUDITOR
    resp = api_client.resolve_fee_change_request(
        fee_change_id, {"decision": decision}, headers)
    return _ok("resolve_fee_change_request", resp)


def approve_fee_change(fee_change_id, resolver="controller"):
    fcr = resolve_fee_change(fee_change_id, "APPROVE", resolver=resolver)
    assert fcr["status"] == "APPROVED", (
        f"Setup failed at fee resolve APPROVE: got {fcr['status']}"
    )
    return fcr


def withdraw_fee_change(fee_change_id, role="auditor"):
    headers = AUDITOR if role == "auditor" else CONTROLLER
    resp = api_client.withdraw_fee_change_request(fee_change_id, headers)
    return _ok("withdraw_fee_change_request", resp, expected_status="WITHDRAWN")
