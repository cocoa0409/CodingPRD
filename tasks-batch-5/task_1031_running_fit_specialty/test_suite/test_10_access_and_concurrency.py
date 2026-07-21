"""Role-based access, resource ownership, and optimistic concurrency on price
overrides.

Queue B (Corner): rbac (authorization + ownership), cross_cutting (OCC).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_member_headers,
    fixtures as fx,
)


# ---------------------------------------------------------------------------
# Corner: rbac
# ---------------------------------------------------------------------------
def test_member_cannot_create_product(api, sm):
    """PRD 2.1: "When the headers are present and valid but the named role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/c_rbac_member_cannot_create_product
    """
    member = fx.create_member()
    headers = make_member_headers(member["id"])
    resp = api.create_product(
        {"sku": "C-NO", "name": "No", "category": "GEAR", "unit_price_cents": 3000},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_member_cannot_checkin_fitment(api, sm):
    """PRD 2.1: "When the headers are present and valid but the named role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/c_rbac_member_cannot_checkin_fitment
    """
    member = fx.create_member()
    fitter = fx.create_fitter("Coach Ada")
    session = fx.create_fitment(
        member["id"], fitter["id"], "2026-08-22T10:00:00Z", "2026-08-22T11:00:00Z"
    )
    headers = make_member_headers(member["id"])
    resp = api.checkin_fitment(session["id"], headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_member_cannot_log_other_members_shoe(api, sm):
    """PRD 2.1: "Ownership checks on any resource that references a member — an
    order, a return, a subscription, a running shoe, a fitment session, or a
    training booking — compare that resource's member foreign key to `X-User-ID`.
    A member acting on a resource they do not own is rejected with
    `ERR_OWNERSHIP_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/c_ownership_member_cannot_log_other_members_shoe
    """
    member_a = fx.create_member()
    member_b = fx.create_member()
    _m, _p, _o, shoe = fx.setup_fulfilled_shoe(member=member_b)  # owned by member_b
    headers_a = make_member_headers(member_a["id"])
    resp = api.log_mileage(shoe["id"], {"miles": 20}, headers_a)
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_FORBIDDEN.value, 403)


# ---------------------------------------------------------------------------
# Corner: cross_cutting — optimistic concurrency on price overrides
# ---------------------------------------------------------------------------
def test_price_override_success_increments_version(api, sm):
    """PRD 3.4: "which is stored as the order's `price_override_discount_cents`
    and, while set, takes the place of the normally computed `discount_cents` in
    every subsequent repricing."
    PRD 3.4: "Each override supersedes any prior one, and the operation
    increments the order's `version` by one."

    Design: Corner/cross_cutting/c_occ_price_override_success_increments_version
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=10000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    v0 = order["version"]
    resp = api.price_override(
        order["id"], {"expected_order_version": v0, "override_discount_cents": 1500}, sm
    )
    data = validate_success(resp, 200)
    assert data["discount_cents"] == 1500
    assert data["version"] == v0 + 1


def test_price_override_stale_version_rejected(api, sm):
    """PRD 2.8: "If `expected_order_version` does not equal the order's current
    `version` — because some other writer has advanced the order since the client
    read it — the override is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/c_occ_stale_version_rejected
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=10000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    v0 = order["version"]
    # First override advances version to v0 + 1.
    fx.get_success_data(
        api.price_override(
            order["id"], {"expected_order_version": v0, "override_discount_cents": 1000}, sm
        )
    )
    # Second override still carries the now-stale v0.
    resp = api.price_override(
        order["id"], {"expected_order_version": v0, "override_discount_cents": 2000}, sm
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
