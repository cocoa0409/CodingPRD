"""Role-based access control and authentication.

Queue-B: rbac instances (staff-exclusive op, peer ownership, unknown role).
"""
import pytest
from test_helpers import (
    validate_error, ApiErrorId,
    new_member, new_gear_sku, submit_trade_in, create_order,
    make_member_headers, build_user_headers,
)


def test_member_cannot_appraise_trade_in(api):
    """PRD §2.1: "Counter and catalog operations — registering gear, taking units in
    and out, appraising and selling trade-ins, fulfilling orders, running trips,
    checking members in, and creating permit pools — are exclusive to StoreStaff."
    PRD §2.1: "When an authenticated caller's role is not permitted to perform the
    requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/member_cannot_appraise_trade_in
    """
    member = new_member()
    sku = new_gear_sku(name="Rb Bag", category="APPAREL", price_cents=12000)
    ti = submit_trade_in(member, sku["id"], condition="GOOD", method="INSTANT_CREDIT")
    res = api.appraise_trade_in(ti["id"], {"appraised_value_cents": 8000},
                                make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_member_cannot_pay_another_members_order(api):
    """PRD §2.1: "a Member may act only on resources whose member_id equals their own
    X-User-ID, and an attempt to read or mutate another member's resource is rejected
    with ERR_UNAUTHORIZED."

    Design: Corner/rbac/member_cannot_pay_another_members_order
    """
    m1 = new_member()
    m2 = new_member()
    sku = new_gear_sku(name="Rb Stove", category="STOVE", price_cents=3000)
    order = create_order(m1, [(sku["id"], 1)])
    res = api.pay_order(order["id"], make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_protected_read_with_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or unrecognized on a protected
    endpoint, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401). The system
    recognizes exactly three roles, spelled precisely as Member, StoreStaff, and
    Public."

    Design: Corner/rbac/protected_read_with_unknown_role_returns_unauthenticated
    """
    member = new_member()
    bad_headers = build_user_headers(member["id"], "Anonymous")
    res = api.get_member(member["id"], bad_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
