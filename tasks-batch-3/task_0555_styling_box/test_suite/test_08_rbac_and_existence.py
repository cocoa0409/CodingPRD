"""Role-based access control (authorization, peer ownership isolation), authentication,
and left-to-right existence checks.
"""
from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS, make_client_headers, make_stylist_headers,
    create_active_client, create_stylist, register_client,
    setup_delivered_fix, setup_styling_fix,
    BOGUS_UUID,
)

OPS = TEST_USERS["ops_headers"]


def test_stylist_cannot_ship_fix(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/rbac/stylist_cannot_ship_returns_unauthorized
    """
    from test_helpers import setup_preview_fix
    ctx = setup_preview_fix(prices=[3000, 3000, 3000])
    resp = api.ship_fix(ctx["fix_id"], headers=make_stylist_headers(ctx["stylist_id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_cannot_checkout_another_clients_fix(api):
    """PRD §2.1: "When an entity-backed actor (a Client or Stylist) targets a resource
    they do not own, the request is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/client_cannot_checkout_other_clients_fix
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    other = create_active_client(region_code="CA")
    resp = api.checkout_fix(
        ctx["fix_id"], {"kept_item_ids": [ctx["item_ids"][0]]},
        headers=make_client_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unassigned_stylist_cannot_add_item(api):
    """PRD §2.1: "When X-User-Role is Stylist, X-User-ID is the id of the acting
    Stylist. Ownership checks on a fix compare the fix's stylist_id to X-User-ID; a
    stylist may only curate fixes assigned to them."

    Design: Corner/rbac/stylist_cannot_add_item_to_unassigned_fix
    """
    ctx = setup_styling_fix(prices=[3000])  # assigned to ctx['stylist_id']
    other_stylist = create_stylist()
    resp = api.add_fix_item(
        ctx["fix_id"], {"product_id": ctx["product_ids"][0]},
        headers=make_stylist_headers(other_stylist["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_protected_endpoint_without_headers_unauthenticated(api):
    """PRD §2.1: "When either header is missing or unrecognizable on a protected
    endpoint, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    client = register_client(region_code="CA")
    resp = api.get_client(client["id"], headers={})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_get_missing_fix_returns_not_found(api):
    """PRD §2.5: "The existence family is: ERR_CLIENT_NOT_FOUND, ERR_FIX_NOT_FOUND,
    ERR_FIXITEM_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_STYLIST_NOT_FOUND,
    ERR_RETURN_NOT_FOUND, and ERR_PURCHASE_NOT_FOUND, each returned with HTTP 404."

    Design: Corner/errors/fix_not_found_under_wrong_path
    """
    resp = api.get_fix(BOGUS_UUID, headers=OPS)
    validate_error(resp, ApiErrorId.ERR_FIX_NOT_FOUND.value)
