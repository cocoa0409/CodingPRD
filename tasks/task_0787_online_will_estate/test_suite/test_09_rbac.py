"""Role-based access control: an endpoint's exclusive role rejects other roles."""
from test_helpers import (
    validate_success, validate_error,
    setup_plan, register_member, make_member_headers,
    make_active_subscription, add_beneficiary, generate_document, NOTARY,
)


# ─── Corner: rbac / notary_cannot_create_subscription_returns_unauthorized ─
def test_notary_cannot_create_subscription(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." (Per §4, `POST /v1/subscriptions` is authorized for `Member`.)

    Design: Corner/rbac/notary_cannot_create_subscription_returns_unauthorized
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    member = register_member(email="rbac1@example.com")
    res = api.create_subscription(
        {"member_id": member["id"], "plan_tier": "PLUS", "bundle_type": "INDIVIDUAL"}, NOTARY)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: rbac / member_cannot_execute_document_returns_unauthorized ──
def test_member_cannot_execute_document(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." (Per §4, `POST /v1/documents/{id}/execute` is authorized for `Notary`.)

    Design: Corner/rbac/member_cannot_execute_document_returns_unauthorized
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_beneficiary(sub["id"], hdr, allocation_pct=100)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")
    res = api.execute_document(doc["id"], {"witnesses_count": 2}, hdr)
    validate_error(res, "ERR_UNAUTHORIZED")
    after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert after["status"] == "GENERATED"
