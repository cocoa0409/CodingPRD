"""Member suspension depth-3 cascade, suspend-state guard, suspend authorization,
and immediate read-after-write visibility.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, get_success_data, make_member_headers,
    create_member, create_service_bay, create_build_in_state,
    create_scheduled_service_order,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]


def _suspend_cascade_setup(api):
    """SETUP_COMPLETE build (1 component, stock 2) for a member, plus a SCHEDULED
    WAX service order on that build reserving 1 part (stock 3). Returns
    (member, build, service_order, comp_product, part_product)."""
    member = create_member(api)
    build, member, components = create_build_in_state(
        api, target_state="SETUP_COMPLETE", member=member,
        lines_spec=[{"price": 6000, "qty": 1, "stock": 2, "category": "DECK"}])
    bay = create_service_bay(api)
    order, member, bay, parts = create_scheduled_service_order(
        api, service_type="WAX",
        parts_spec=[{"price": 500, "qty": 1, "stock": 3, "category": "WAX"}],
        slot_start="2026-07-05T10:00:00Z", slot_end="2026-07-05T11:00:00Z",
        member=member, bay=bay, build_id=build["id"])
    return member, build, order, components[0], parts[0]


def test_member_suspend_cancels_build_and_service_order(api):
    """PRD §2.10: "Suspending a member triggers a depth-three cascade: every one of
    that member's board builds in `DRAFT`, `COMPONENTS_RESERVED`, `ASSEMBLED`, or
    `SETUP_COMPLETE` is cancelled; each such build cancellation in turn cancels any
    linked service orders in `SCHEDULED` or `IN_PROGRESS`; and each of those
    service-order cancellations releases its reserved parts by lowering each part
    product's `stock_reserved`."

    Design: Difficulty/transitive_cascade/member_suspend_cascade_member_build_serviceorder_product
    """
    member, build, order, comp, part = _suspend_cascade_setup(api)
    suspended = validate_success(api.suspend_member(member["id"], SM), 200)
    assert suspended["status"] == "SUSPENDED"
    assert get_success_data(api.get_board_build(build["id"], SM))["status"] == "CANCELLED"
    assert get_success_data(api.get_service_order(order["id"], SM))["status"] == "CANCELLED"


def test_member_suspend_releases_reserved_parts_components(api):
    """PRD §2.10: "each of those service-order cancellations releases its reserved
    parts by lowering each part product's `stock_reserved`."
    PRD §3.3: "when cancelled from a state that held reservations (`COMPONENTS_RESERVED`,
    `ASSEMBLED`, or `SETUP_COMPLETE`), each component product's `stock_reserved` is
    released, and any linked service orders in `SCHEDULED` or `IN_PROGRESS` are cancelled."

    Design: Difficulty/transitive_cascade/member_suspend_cascade_member_build_serviceorder_product
    """
    member, build, order, comp, part = _suspend_cascade_setup(api)
    api.suspend_member(member["id"], SM)
    assert get_success_data(api.get_product(part["id"], SM))["stock_reserved"] == 0
    assert get_success_data(api.get_product(comp["id"], SM))["stock_reserved"] == 0


def test_suspend_suspended_member_invalid_state(api):
    """PRD §2.5: "the target resource is in a state from which the transition is
    allowed (`ERR_INVALID_STATE`, 409)".
    PRD §3.2: "Only a `ShopManager` may suspend an `ACTIVE` member or reinstate a
    `SUSPENDED` one."

    Design: Corner/state_machines/suspend_already_suspended_returns_invalid_state
    """
    member = create_member(api)
    api.suspend_member(member["id"], SM)
    resp = api.suspend_member(member["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_member_cannot_suspend(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/member_cannot_suspend_member_returns_unauthorized
    """
    member = create_member(api)
    resp = api.suspend_member(member["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_member_immediately_readable(api):
    """PRD §1: "It is authoritative, immediate-consistency, and single-tenant: every
    mutation takes effect at once, and derived values such as available stock and
    event registration counts are recomputed on the spot rather than deferred."
    PRD §3.2: "A new member starts `ACTIVE` with `points_balance`, `lifetime_points`,
    and `store_credit_cents` all at 0."

    Design: Corner/consistency_model/immediate_visibility_on_create
    """
    member = create_member(api)
    fetched = validate_success(api.get_member(member["id"], ASSOC), 200)
    assert fetched["status"] == "ACTIVE"
