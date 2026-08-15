"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch through PRD-declared endpoints
and uses the lenient get_success_data() validator so setup failures surface as
clear "Setup step failed" errors. Default operator ids are chosen so that the
complaint owner, the case handler, the QA reviewer, and the remediation
approver are always distinct users unless a test overrides them.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_complaint_payload, create_rca_payload,
    create_remediation_decision_payload, create_quality_review_payload,
    create_escalation_payload, create_trend_snapshot_payload,
    create_response_template_payload,
)
from .test_users import TEST_USERS, headers_for

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
QA = TEST_USERS["qa_reviewer_headers"]
APPROVER = TEST_USERS["remediation_approver_headers"]
EXECUTIVE = TEST_USERS["executive_reviewer_headers"]

DEFAULT_OWNER_ID = "user_intake_owner"
DEFAULT_HANDLER_ID = "user_handler_1"
DEFAULT_REVIEWER_ID = "user_qa_1"
DEFAULT_APPROVER_ID = "user_approver_1"


# ---------------------------------------------------------------------------
# Reference data and clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def create_product(product_code, display_name=None):
    return get_success_data(api_client.create_product(
        {"product_code": product_code,
         "display_name": display_name or f"Product {product_code}"},
        MANAGER,
    ))


def create_channel(channel_code, display_name=None, is_regulator_portal=None):
    payload = {"channel_code": channel_code,
               "display_name": display_name or f"Channel {channel_code}"}
    if is_regulator_portal is not None:
        payload["is_regulator_portal"] = is_regulator_portal
    return get_success_data(api_client.create_channel(payload, MANAGER))


def create_category(category_code, parent_category_code=None):
    payload = {"category_code": category_code}
    if parent_category_code is not None:
        payload["parent_category_code"] = parent_category_code
    return get_success_data(api_client.create_taxonomy_category(payload, MANAGER))


def retire_category(category_id):
    return get_success_data(api_client.retire_taxonomy_category(category_id, MANAGER))


def setup_reference_data(product_code="P-1", channel_code="WEB", category_code="C.1",
                         portal=False):
    """Create a product + channel + category trio. Returns them as a dict."""
    product = create_product(product_code)
    channel = create_channel(
        channel_code, is_regulator_portal=True if portal else None,
    )
    category = create_category(category_code)
    return {"product": product, "channel": channel, "category": category}


def create_template(template_key, channel_code, category_code, body="Template body"):
    return get_success_data(api_client.create_response_template(
        create_response_template_payload(
            template_key=template_key, channel_code=channel_code,
            category_code=category_code, body=body,
        ),
        MANAGER,
    ))


def publish_template(template_id):
    return get_success_data(api_client.publish_response_template(template_id, MANAGER))


def create_active_template(template_key, channel_code, category_code, body="Template body"):
    """Create a template and publish it (DRAFT -> ACTIVE)."""
    template = create_template(template_key, channel_code, category_code, body)
    return publish_template(template["id"])


# ---------------------------------------------------------------------------
# Complaint intake
# ---------------------------------------------------------------------------

def intake_complaint(product_code, channel_code, category_code, *,
                     complainant_ref="CUST-1000", narrative="Consumer narrative",
                     claimed_loss_cents=None, portal_ref=None,
                     role="IntakeSpecialist", user_id=DEFAULT_OWNER_ID):
    payload = create_complaint_payload(
        complainant_ref=complainant_ref, channel_code=channel_code,
        product_code=product_code, category_code=category_code, narrative=narrative,
    )
    if claimed_loss_cents is not None:
        payload["claimed_loss_cents"] = claimed_loss_cents
    if portal_ref is not None:
        payload["portal_ref"] = portal_ref
    return get_success_data(api_client.create_complaint(
        payload, headers_for(role, user_id),
    ))


def setup_complaint(product_code="P-1", channel_code="WEB", category_code="C.1",
                    *, portal=False, owner_id=DEFAULT_OWNER_ID, **intake_overrides):
    """Reference data + one complaint in INTAKE. Returns dict of entities."""
    refs = setup_reference_data(product_code, channel_code, category_code, portal=portal)
    complaint = intake_complaint(
        product_code, channel_code, category_code, user_id=owner_id, **intake_overrides,
    )
    return {**refs, "complaint": complaint}


def list_complaint_referrals(complaint_id):
    data, _meta = validate_paginated(api_client.list_complaint_referrals(complaint_id, AUDITOR))
    return data


def intake_portal_complaint(product_code="P-1", channel_code="CFPB_PORTAL",
                            category_code="C.1", *, owner_id=DEFAULT_OWNER_ID,
                            **intake_overrides):
    """Portal-channel intake: returns (complaint, auto-created referral)."""
    ctx = setup_complaint(
        product_code, channel_code, category_code,
        portal=True, owner_id=owner_id, **intake_overrides,
    )
    referrals = list_complaint_referrals(ctx["complaint"]["id"])
    assert len(referrals) == 1, (
        f"Portal intake must auto-create exactly one referral, got {len(referrals)}"
    )
    return ctx["complaint"], referrals[0]


# ---------------------------------------------------------------------------
# Reads (Auditor is read-only on every resource per PRD §2.1)
# ---------------------------------------------------------------------------

def get_complaint(complaint_id):
    return get_success_data(api_client.get_complaint(complaint_id, AUDITOR))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, AUDITOR))


def get_referral(referral_id):
    return get_success_data(api_client.get_referral(referral_id, AUDITOR))


def get_rca(rca_id):
    return get_success_data(api_client.get_rca(rca_id, AUDITOR))


def get_decision(decision_id):
    return get_success_data(api_client.get_remediation_decision(decision_id, AUDITOR))


def get_review(review_id):
    return get_success_data(api_client.get_quality_review(review_id, AUDITOR))


def get_template(template_id):
    return get_success_data(api_client.get_response_template(template_id, AUDITOR))


def get_escalation(escalation_id):
    return get_success_data(api_client.get_escalation(escalation_id, AUDITOR))


def list_complaint_events(complaint_id):
    data, _meta = validate_paginated(api_client.list_complaint_events(complaint_id, AUDITOR))
    return data


def list_complaint_decisions(complaint_id, params=None):
    data, _meta = validate_paginated(
        api_client.list_complaint_remediation_decisions(complaint_id, AUDITOR, params=params)
    )
    return data


def list_product_snapshots(product_id):
    data, _meta = validate_paginated(
        api_client.list_product_trend_snapshots(product_id, AUDITOR)
    )
    return data


def list_templates(params=None):
    data, _meta = validate_paginated(api_client.list_response_templates(AUDITOR, params=params))
    return data


# ---------------------------------------------------------------------------
# Complaint workflow progression
# ---------------------------------------------------------------------------

def triage(complaint_id, user_id=DEFAULT_HANDLER_ID):
    return get_success_data(api_client.triage_complaint(
        complaint_id, headers_for("CaseHandler", user_id),
    ))


def start_investigation(complaint_id, user_id=DEFAULT_HANDLER_ID):
    return get_success_data(api_client.start_investigation(
        complaint_id, headers_for("CaseHandler", user_id),
    ))


def drive_to_investigating(complaint_id, user_id=DEFAULT_HANDLER_ID):
    """INTAKE -> TRIAGED -> INVESTIGATING. Returns the updated complaint."""
    triage(complaint_id, user_id)
    return start_investigation(complaint_id, user_id)


def create_rca(complaint_id, verdict="SUBSTANTIATED", linked_product_code="P-1",
               process_step="ST", user_id=DEFAULT_HANDLER_ID):
    return get_success_data(api_client.create_rca(
        complaint_id,
        create_rca_payload(verdict=verdict, linked_product_code=linked_product_code,
                           process_step=process_step),
        headers_for("CaseHandler", user_id),
    ))


def complete_rca(rca_id, user_id=DEFAULT_HANDLER_ID):
    return get_success_data(api_client.complete_rca(
        rca_id, headers_for("CaseHandler", user_id),
    ))


def create_and_complete_rca(complaint_id, verdict="SUBSTANTIATED",
                            linked_product_code="P-1", process_step="ST",
                            user_id=DEFAULT_HANDLER_ID):
    """Create a DRAFT RCA and complete it. Returns the COMPLETED RCA."""
    rca = create_rca(complaint_id, verdict, linked_product_code, process_step, user_id)
    return complete_rca(rca["id"], user_id)


def draft_response(complaint_id, response_text="We have addressed the issue.",
                   response_template_key=None, user_id=DEFAULT_HANDLER_ID):
    payload = {"response_text": response_text}
    if response_template_key is not None:
        payload["response_template_key"] = response_template_key
    return get_success_data(api_client.draft_response(
        complaint_id, payload, headers_for("CaseHandler", user_id),
    ))


def submit_for_qa(complaint_id, user_id=DEFAULT_HANDLER_ID):
    return get_success_data(api_client.submit_for_qa(
        complaint_id, headers_for("CaseHandler", user_id),
    ))


def drive_to_response_qa(complaint_id, *, user_id=DEFAULT_HANDLER_ID,
                         response_text="We have addressed the issue.",
                         response_template_key=None):
    """Assumes a COMPLETED RCA exists. INVESTIGATING -> RESPONSE_QA."""
    draft_response(complaint_id, response_text, response_template_key, user_id)
    return submit_for_qa(complaint_id, user_id)


def claim_review(complaint_id, reviewer_id=DEFAULT_REVIEWER_ID,
                 window_start_at="2026-08-01T00:00:00Z",
                 window_end_at="2026-08-15T00:00:00Z"):
    return get_success_data(api_client.claim_quality_review(
        complaint_id,
        create_quality_review_payload(window_start_at=window_start_at,
                                      window_end_at=window_end_at),
        headers_for("QAReviewer", reviewer_id),
    ))


def complete_review(review_id, outcome="PASS", reviewer_id=DEFAULT_REVIEWER_ID):
    return get_success_data(api_client.complete_quality_review(
        review_id, {"outcome": outcome}, headers_for("QAReviewer", reviewer_id),
    ))


def resolve_complaint(complaint_id, user_id=DEFAULT_HANDLER_ID):
    return get_success_data(api_client.resolve_complaint(
        complaint_id, headers_for("CaseHandler", user_id),
    ))


def setup_complaint_in_response_qa(product_code="P-1", channel_code="WEB",
                                   category_code="C.1", *, portal=False,
                                   owner_id=DEFAULT_OWNER_ID,
                                   handler_id=DEFAULT_HANDLER_ID,
                                   verdict="SUBSTANTIATED",
                                   **intake_overrides):
    """Complaint driven INTAKE -> RESPONSE_QA with a COMPLETED RCA on file.

    Returns dict with product/channel/category/complaint/rca.
    """
    ctx = setup_complaint(product_code, channel_code, category_code,
                          portal=portal, owner_id=owner_id, **intake_overrides)
    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid, handler_id)
    rca = create_and_complete_rca(cid, verdict, product_code, user_id=handler_id)
    complaint = drive_to_response_qa(cid, user_id=handler_id)
    return {**ctx, "complaint": complaint, "rca": rca}


def setup_resolved_complaint(product_code="P-1", channel_code="WEB",
                             category_code="C.1", *, portal=False,
                             owner_id=DEFAULT_OWNER_ID,
                             handler_id=DEFAULT_HANDLER_ID,
                             reviewer_id=DEFAULT_REVIEWER_ID,
                             verdict="SUBSTANTIATED",
                             window_start_at="2026-08-01T00:00:00Z",
                             window_end_at="2026-08-15T00:00:00Z",
                             resolve_clock=None,
                             **intake_overrides):
    """Complaint fully resolved (COMPLETED PASS review on file).

    Returns dict with product/channel/category/complaint/rca/review.
    """
    ctx = setup_complaint_in_response_qa(
        product_code, channel_code, category_code,
        portal=portal, owner_id=owner_id, handler_id=handler_id, verdict=verdict,
        **intake_overrides,
    )
    cid = ctx["complaint"]["id"]
    review = claim_review(cid, reviewer_id, window_start_at, window_end_at)
    review = complete_review(review["id"], "PASS", reviewer_id)
    if resolve_clock is not None:
        set_clock(resolve_clock)
    complaint = resolve_complaint(cid, handler_id)
    return {**ctx, "complaint": complaint, "review": review}


# ---------------------------------------------------------------------------
# Remediation decisions
# ---------------------------------------------------------------------------

def create_decision(complaint_id, decision_type="RESTITUTION",
                    line_items=None, drafter_id=DEFAULT_HANDLER_ID):
    """Create a DRAFT RemediationDecision with a fresh OCC version read."""
    if line_items is None:
        line_items = [{"label": "fee", "amount_cents": 1000}]
    current = get_complaint(complaint_id)
    payload = create_remediation_decision_payload(
        decision_type=decision_type, line_items=line_items,
        expected_complaint_version=current["version"],
    )
    return get_success_data(api_client.create_remediation_decision(
        complaint_id, payload, headers_for("CaseHandler", drafter_id),
    ))


def submit_decision(decision_id, user_id=DEFAULT_HANDLER_ID):
    return get_success_data(api_client.submit_remediation_decision(
        decision_id, headers_for("CaseHandler", user_id),
    ))


def setup_pending_decision(product_code="P-1", channel_code="WEB", category_code="C.1",
                           *, decision_type="RESTITUTION", line_items=None,
                           owner_id=DEFAULT_OWNER_ID, drafter_id=DEFAULT_HANDLER_ID,
                           **intake_overrides):
    """Complaint in INVESTIGATING + one decision pushed DRAFT -> PENDING_APPROVAL.

    Returns dict with product/channel/category/complaint/decision.
    """
    ctx = setup_complaint(product_code, channel_code, category_code,
                          owner_id=owner_id, **intake_overrides)
    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid, drafter_id)
    decision = create_decision(cid, decision_type, line_items, drafter_id)
    decision = submit_decision(decision["id"], drafter_id)
    return {**ctx, "complaint": get_complaint(cid), "decision": decision}


# ---------------------------------------------------------------------------
# Posture / aggregation helpers
# ---------------------------------------------------------------------------

def setup_product_with_substantiated(product_code, n, channel_code="WEB",
                                     category_code="C.SUB", *,
                                     verdict="SUBSTANTIATED",
                                     owner_id=DEFAULT_OWNER_ID,
                                     handler_id=DEFAULT_HANDLER_ID):
    """Product with n complaints each carrying a COMPLETED RCA of `verdict`.

    Returns dict with product and the list of complaints.
    """
    refs = setup_reference_data(product_code, channel_code, category_code)
    complaints = []
    for i in range(n):
        complaint = intake_complaint(
            product_code, channel_code, category_code,
            complainant_ref=f"CUST-{product_code}-{i + 1}",
            narrative=f"Complaint {i + 1}", user_id=owner_id,
        )
        create_and_complete_rca(complaint["id"], verdict, product_code,
                                user_id=handler_id)
        complaints.append(complaint)
    return {**refs, "complaints": complaints}
