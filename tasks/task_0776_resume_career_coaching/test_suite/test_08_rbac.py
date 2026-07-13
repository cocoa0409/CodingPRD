"""Role-based access control: role-denial (ERR_UNAUTHORIZED) and ownership
(ERR_NOT_RESOURCE_OWNER)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_plan,
    create_client_entity,
    create_coach_entity,
    create_order_entity,
    create_order_payload,
    make_client_headers,
    make_coach_headers,
    setup_confirmed_order,
    setup_delivered_order,
    first_deliverable_id,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

BASIC_PLAN = {"tier": "BASIC", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
              "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"}
SATISFACTION_PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
                     "included_revision_rounds": 1, "included_coaching_sessions": 0,
                     "guarantee_type": "SATISFACTION"}


def test_coach_cannot_create_order_returns_unauthorized(api):
    """PRD §2.1: "If the headers are valid but the acting role is not permitted to call the
    requested endpoint, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)." POST
    /orders is a Client-only operation.

    Design: Corner/rbac/coach_cannot_create_order_returns_unauthorized
    """
    plan = create_plan(**BASIC_PLAN)
    coach = create_coach_entity(name="So Coach", email="so@x.com", specialty="GENERAL")
    resp = api.create_order(create_order_payload(plan["id"]), make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_cannot_upload_draft_returns_unauthorized(api):
    """PRD §2.1: "If the headers are valid but the acting role is not permitted to call the
    requested endpoint, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)." Uploading
    a draft is a Coach-only operation.

    Design: Corner/rbac/client_cannot_upload_draft_returns_unauthorized
    """
    ctx = setup_confirmed_order(plan_overrides=BASIC_PLAN, with_coach=False)
    deliv_id = first_deliverable_id(ctx["order_id"])
    resp = api.create_draft(deliv_id, {"notes": "client trying"}, ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_cannot_approve_claim_returns_unauthorized(api):
    """PRD §2.1: "If the headers are valid but the acting role is not permitted to call the
    requested endpoint, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)." Approving
    a guarantee claim is a CareerAdmin-only operation.

    Design: Corner/rbac/client_cannot_approve_claim_returns_unauthorized
    """
    ctx = setup_delivered_order(plan_overrides=SATISFACTION_PLAN)
    claim = validate_success(api.create_guarantee_claim(
        ctx["order_id"], {"claim_type": "SATISFACTION", "evidence": "unhappy"}, ctx["client_headers"]), 201)
    resp = api.approve_guarantee_claim(claim["id"], ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_non_owner_client_confirm_returns_not_owner(api):
    """PRD §2.1: "A Client or Coach acting on a resource they do not own is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)." A second client cannot confirm another client's order.

    Design: Corner/errors/non_owner_client_confirm_returns_not_owner
    """
    plan = create_plan(**BASIC_PLAN)
    client_a = create_client_entity(name="Client A", email="a@x.com")
    client_b = create_client_entity(name="Client B", email="b@x.com")
    order = create_order_entity(plan["id"], client_a["id"])
    resp = api.confirm_order(order["id"], make_client_headers(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
