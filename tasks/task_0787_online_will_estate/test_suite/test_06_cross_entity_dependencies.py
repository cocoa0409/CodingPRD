"""Cross-entity state dependencies: a transition on one entity gated by the state
of a related entity (document ← subscription, share grant ← document).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_plan, set_clock, register_member, create_pending_subscription,
    make_completed_questionnaire, make_member_headers,
    make_active_subscription, generate_document,
)


def _pending_sub_with_completed_will():
    """Subscription still PENDING_PAYMENT (never paid) with a COMPLETED WILL
    questionnaire ready. Returns (sub_id, hdr, q_id)."""
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(email="pending@example.com")
    hdr = make_member_headers(member["id"])
    sub = create_pending_subscription(member["id"], plan_tier="PLUS")
    q = make_completed_questionnaire(sub["id"], hdr, "WILL", "CA")
    return sub["id"], hdr, q["id"]


# ─── Difficulty: cross_entity_state_dependency / document_generate_requires_subscription_active ─
def test_generate_document_requires_active_subscription(api):
    """PRD §3.6: "Generation is subject to several checks. The owning subscription must
    be `ACTIVE`, or the request is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/document_generate_requires_subscription_active
    """
    sub_id, hdr, q_id = _pending_sub_with_completed_will()
    res = api.create_document({"questionnaire_id": q_id}, hdr)
    validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")


def test_generate_on_pending_subscription_creates_no_document(api):
    """PRD §3.6: "The owning subscription must be `ACTIVE`, or the request is rejected
    with `ERR_SUBSCRIPTION_NOT_ACTIVE`." (Rejected generation produces no document.)

    Design: Difficulty/cross_entity_state_dependency/document_generate_requires_subscription_active
    """
    sub_id, hdr, q_id = _pending_sub_with_completed_will()
    api.create_document({"questionnaire_id": q_id}, hdr)
    docs, _meta = validate_paginated(api.list_questionnaire_documents(q_id, hdr))
    assert len(docs) == 0


# ─── Difficulty: cross_entity_state_dependency / share_grant_requires_document_executed ─
def test_share_grant_requires_executed_document(api):
    """PRD §3.11: "The target document must exist (otherwise `ERR_DOCUMENT_NOT_FOUND`)
    and must be in `EXECUTED` status; sharing a document that has not been executed is
    rejected with `ERR_DOCUMENT_NOT_EXECUTED`."

    Design: Difficulty/cross_entity_state_dependency/share_grant_requires_document_executed
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")  # GENERATED, not EXECUTED
    res = api.create_share_grant(
        {"document_id": doc["id"], "grantee_email": "g@example.com",
         "scope": "VIEW", "expires_at": "2027-01-01T00:00:00Z"}, hdr)
    validate_error(res, "ERR_DOCUMENT_NOT_EXECUTED")


def test_share_grant_on_generated_document_creates_no_grant(api):
    """PRD §3.11: "sharing a document that has not been executed is rejected with
    `ERR_DOCUMENT_NOT_EXECUTED`." (No grant is created.)

    Design: Difficulty/cross_entity_state_dependency/share_grant_requires_document_executed
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")
    api.create_share_grant(
        {"document_id": doc["id"], "grantee_email": "g@example.com",
         "scope": "VIEW", "expires_at": "2027-01-01T00:00:00Z"}, hdr)
    grants, _meta = validate_paginated(api.list_document_share_grants(doc["id"], hdr))
    assert len(grants) == 0
