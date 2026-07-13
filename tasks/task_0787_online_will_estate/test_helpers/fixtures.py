"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch — the test harness restarts the
server (empty database) before every test.

Identity threading: the Member role is entity-backed, so every ownership-gated
call uses make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_catalog_payload, create_member_payload, create_subscription_payload,
    create_questionnaire_payload, create_beneficiary_payload, create_asset_payload,
    create_executor_payload, create_share_grant_payload, full_answers, partial_answers,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["platform_admin_headers"]
NOTARY = TEST_USERS["notary_headers"]
ATTORNEY = TEST_USERS["attorney_headers"]


# ─── Primitive building blocks ───────────────────────────────────────────
def setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=None,
               max_documents=10, allows_trust=False):
    """Create one PlanCatalog row. Returns the catalog entity."""
    if included_document_types is None:
        included_document_types = ["WILL"]
    return get_success_data(api_client.create_plan_catalog(
        create_plan_catalog_payload(
            plan_tier=plan_tier, base_price_cents=base_price_cents,
            included_document_types=included_document_types,
            max_documents=max_documents, allows_trust=allows_trust,
        ), ADMIN))


def set_clock(iso: str):
    """Advance the logical clock to the given instant."""
    return api_client.set_clock({"to_iso8601": iso}, ADMIN)


def register_member(email="member@example.com", full_name="Test Member", state_code="CA"):
    """Public member registration (no auth headers). Returns the member entity."""
    return get_success_data(api_client.create_member(
        create_member_payload(email=email, full_name=full_name, state_code=state_code)))


def create_pending_subscription(member_id, plan_tier="PLUS", **overrides):
    """Create a subscription in PENDING_PAYMENT. Returns the subscription."""
    hdr = make_member_headers(member_id)
    return get_success_data(api_client.create_subscription(
        create_subscription_payload(member_id, plan_tier=plan_tier, **overrides), hdr))


def activate(sub_id):
    """Settle a PENDING_PAYMENT subscription's charge → ACTIVE. Returns the sub."""
    return get_success_data(api_client.simulate_payment(
        {"subscription_id": sub_id, "outcome": "SUCCEEDED"}, ADMIN))


# ─── Tier 1/2: Active subscription foundation ────────────────────────────
def make_active_subscription(
    plan_tier="PLUS", base_price_cents=20000, included_document_types=None,
    max_documents=10, allows_trust=False,
    bundle_type="INDIVIDUAL", attorney_support=False, spouse_name=None, spouse_email=None,
    state_code="CA", email="member@example.com", clock="2026-06-01T00:00:00Z",
):
    """Plan catalog + clock + member + subscription + activation.

    Returns (member, subscription, member_headers) with the subscription ACTIVE
    for the coverage window [clock, clock + 365 days).
    """
    setup_plan(plan_tier, base_price_cents, included_document_types, max_documents, allows_trust)
    set_clock(clock)
    member = register_member(email=email, state_code=state_code)
    hdr = make_member_headers(member["id"])
    sub_overrides = {"bundle_type": bundle_type}
    if attorney_support:
        sub_overrides["attorney_support"] = True
    if spouse_name is not None:
        sub_overrides["spouse_name"] = spouse_name
    if spouse_email is not None:
        sub_overrides["spouse_email"] = spouse_email
    sub = create_pending_subscription(member["id"], plan_tier=plan_tier, **sub_overrides)
    sub = activate(sub["id"])
    return member, sub, hdr


# ─── Estate building blocks ──────────────────────────────────────────────
def add_beneficiary(sub_id, hdr, full_name="Test Heir", relationship="CHILD",
                    allocation_pct=100, is_contingent=None):
    payload = create_beneficiary_payload(
        sub_id, full_name=full_name, relationship=relationship, allocation_pct=allocation_pct)
    if is_contingent is not None:
        payload["is_contingent"] = is_contingent
    return get_success_data(api_client.create_beneficiary(payload, hdr))


def add_asset(sub_id, hdr, estimated_value_cents=50000, asset_type="BANK",
              description="Test Asset", funding_status="UNFUNDED", assigned_beneficiary_id=None):
    payload = create_asset_payload(
        sub_id, asset_type=asset_type, description=description,
        estimated_value_cents=estimated_value_cents, funding_status=funding_status)
    if assigned_beneficiary_id is not None:
        payload["assigned_beneficiary_id"] = assigned_beneficiary_id
    return get_success_data(api_client.create_asset(payload, hdr))


def make_completed_questionnaire(sub_id, hdr, document_type="WILL", state_code="CA"):
    """Create an intake and drive it to COMPLETED with a full answer set."""
    q = get_success_data(api_client.create_questionnaire(
        create_questionnaire_payload(sub_id, document_type=document_type, state_code=state_code), hdr))
    q = get_success_data(api_client.submit_answers(
        q["id"], {"answers": full_answers(document_type)}, hdr))
    return q


def generate_document(sub_id, hdr, document_type="WILL", state_code="CA"):
    """Completed questionnaire → generated document. Returns (questionnaire, document)."""
    q = make_completed_questionnaire(sub_id, hdr, document_type, state_code)
    doc = get_success_data(api_client.create_document({"questionnaire_id": q["id"]}, hdr))
    return q, doc


def execute_document(doc_id, witnesses_count=2):
    """Notary executes a GENERATED / PENDING_EXECUTION document. Returns the doc."""
    return get_success_data(api_client.execute_document(
        doc_id, {"witnesses_count": witnesses_count}, NOTARY))


# ─── Tier 3: Document + review composites ────────────────────────────────
def setup_executed_will_with_share_grant(state_code="CA", clock="2026-06-01T00:00:00Z",
                                         grantee_email="grantee@example.com",
                                         expires_at="2027-01-01T00:00:00Z"):
    """Active subscription → beneficiary → executed WILL → one ACTIVE share grant.

    Returns dict with member, subscription, headers, document, grant, beneficiary.
    """
    member, sub, hdr = make_active_subscription(state_code=state_code, clock=clock)
    ben = add_beneficiary(sub["id"], hdr, allocation_pct=100)
    _q, doc = generate_document(sub["id"], hdr, "WILL", state_code)
    doc = execute_document(doc["id"], witnesses_count=2)
    grant = get_success_data(api_client.create_share_grant(
        create_share_grant_payload(doc["id"], grantee_email=grantee_email, expires_at=expires_at), hdr))
    return {"member": member, "subscription": sub, "headers": hdr,
            "document": doc, "grant": grant, "beneficiary": ben}


def setup_document_in_attorney_review(state_code="CA", clock="2026-06-01T00:00:00Z"):
    """Active attorney_support subscription → WILL submitted for review → attorney
    STARTED the review (document IN_REVIEW, review IN_REVIEW).

    Returns dict with member, subscription, headers, document, review.
    """
    member, sub, hdr = make_active_subscription(
        included_document_types=["WILL", "TRUST", "POA", "HEALTHCARE_DIRECTIVE"],
        allows_trust=True, attorney_support=True, state_code=state_code, clock=clock)
    _q, doc = generate_document(sub["id"], hdr, "WILL", state_code)
    get_success_data(api_client.submit_review(doc["id"], hdr))
    reviews, _meta = _list(api_client.list_document_attorney_reviews(doc["id"], hdr))
    review = reviews[0]
    review = get_success_data(api_client.review_decision(
        review["id"], {"action": "START_REVIEW"}, ATTORNEY))
    return {"member": member, "subscription": sub, "headers": hdr,
            "document": doc, "review": review}


def setup_review_changes_requested_resubmitted(state_code="CA", clock="2026-06-01T00:00:00Z"):
    """As setup_document_in_attorney_review, then attorney REQUEST_CHANGES (doc→GENERATED,
    review→CHANGES_REQUESTED), then member re-submits (doc→IN_REVIEW, review still
    CHANGES_REQUESTED).

    Returns dict with member, subscription, headers, document, review.
    """
    ctx = setup_document_in_attorney_review(state_code, clock)
    doc, review, hdr = ctx["document"], ctx["review"], ctx["headers"]
    get_success_data(api_client.review_decision(
        review["id"], {"action": "REQUEST_CHANGES", "notes": "Revise"}, ATTORNEY))
    get_success_data(api_client.submit_review(doc["id"], hdr))
    return ctx


def _list(response):
    """Unpack a paginated list response into (data_list, meta)."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)
