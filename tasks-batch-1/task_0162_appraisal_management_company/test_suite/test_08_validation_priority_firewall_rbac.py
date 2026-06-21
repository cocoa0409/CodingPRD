"""Validation-priority conflicts, the AIR firewall, authentication, OCC on cancel,
the audit-only FirewallEvent, and pagination.

Covers queue A (Difficulty) priority_pair_validation_conflict instances plus
queue B errors/entities/cross_cutting instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, factories, fixtures,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_firewall_beats_eligibility_on_lender_assign(api):
    """PRD §2.4: "When a `LenderUser` attempts any of these, the request is denied with
    `ERR_AIR_FIREWALL_VIOLATION` (HTTP 403) and a `FirewallEvent` is recorded against the
    order."
    PRD §2.10: "In particular, a mid-flight firewall block (priority 2) surfaces before any
    permission, existence, or business check".

    Design: Difficulty/priority_pair_validation_conflict/firewall_safety_beats_referential_eligibility_on_assign
    """
    # Empty panel => eligibility (priority 5) would also fail, but the LenderUser firewall
    # (priority 2) wins.
    lender = fixtures.create_lender(panel_ids=[], name="Lender E")
    prop = fixtures.create_property(state_code="CA", street_address="8 CA St")
    order = fixtures.create_order(lender["id"], prop["id"], as_lender_id=lender["id"])
    resp = api.create_assignment(
        order["id"], factories.assignment_create_payload(order["version"]),
        fixtures.make_lender_user_headers(lender["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AIR_FIREWALL_VIOLATION.value, 403)


def test_firewall_blocks_lender_assign_even_with_eligible_appraiser(api):
    """PRD §2.4: "The firewall is enforced for the `LenderUser` role on three firewalled
    operations: appraiser selection (creating an assignment on an order), finalizing a
    compliance review, and opening a revision request whose `reason_category` is
    `VALUE_DISPUTE`."
    PRD §2.10: "a mid-flight firewall block (priority 2) surfaces before any permission,
    existence, or business check".

    Design: Difficulty/priority_pair_validation_conflict/firewall_safety_beats_referential_eligibility_on_assign
    """
    # An eligible appraiser IS on the panel, so eligibility (priority 5) would succeed;
    # the LenderUser firewall (priority 2) still governs and blocks.
    appraiser = fixtures.create_appraiser(license_state="CA", full_name="FW Elig A")
    lender = fixtures.create_lender(panel_ids=[appraiser["id"]], name="Lender FW Elig")
    prop = fixtures.create_property(state_code="CA")
    order = fixtures.create_order(lender["id"], prop["id"], as_lender_id=lender["id"])
    resp = api.create_assignment(
        order["id"], factories.assignment_create_payload(order["version"]),
        fixtures.make_lender_user_headers(lender["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AIR_FIREWALL_VIOLATION.value, 403)


def test_state_beats_stale_version_on_complete(api):
    """PRD §2.10: "an `ERR_INVALID_STATE` (priority 7) surfaces before a stale-version
    rejection (priority 8) when both would apply."
    PRD §3.8: "Completion is permitted only when the order is in `DELIVERED`, no
    reconsideration on the order sits in `REQUESTED` or `UNDER_REVIEW`, and the supplied
    `expected_order_version` matches the order's `version`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_budget_on_complete
    """
    # Order still PLACED (never assigned); client passes a deliberately stale version.
    lender = fixtures.create_lender(panel_ids=[], name="Lender S")
    prop = fixtures.create_property(state_code="CA", street_address="9 CA St")
    order = fixtures.create_order(lender["id"], prop["id"])
    stale_version = order["version"] - 1
    resp = api.complete_order(order["id"], factories.assignment_create_payload(stale_version), COORD)
    # Both state (PLACED not completable, priority 7) and OCC (stale, priority 8) fail;
    # the lower-numbered state error wins.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_complete_from_placed_with_matching_version_returns_invalid_state(api):
    """PRD §3.8: "Completion is permitted only when the order is in `DELIVERED`, no
    reconsideration on the order sits in `REQUESTED` or `UNDER_REVIEW`, and the supplied
    `expected_order_version` matches the order's `version`."
    PRD §2.10: "**State legality** — the target resource must be in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_budget_on_complete
    """
    # Order still PLACED; the version supplied MATCHES, so OCC passes — only the state
    # precondition fails, isolating the ERR_INVALID_STATE outcome.
    lender = fixtures.create_lender(panel_ids=[], name="Lender SM")
    prop = fixtures.create_property(state_code="CA", street_address="9b CA St")
    order = fixtures.create_order(lender["id"], prop["id"])
    resp = api.complete_order(order["id"], factories.assignment_create_payload(order["version"]), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_firewall_event_recorded_and_immutable(api):
    """PRD §2.4: "It captures the `order_id` whose firewall was touched, the `actor_role`
    of the blocked actor (the value of their `X-User-Role`), a short `blocked_operation`
    label for the attempted operation (for example `SELECT_APPRAISER` or
    `OPEN_VALUE_DISPUTE`), and the `error_id` returned to that actor."
    PRD §2.4: "`FirewallEvent` is an audit-only entity: it carries only `id` and
    `created_at` and is never mutated, so it has neither an `updated_at` field nor a
    `version` field."

    Design: Corner/entities/firewall_event_immutable_no_version_field
    """
    lender = fixtures.create_lender(panel_ids=[], name="L FE")
    prop = fixtures.create_property(state_code="CA", street_address="44 CA St")
    order = fixtures.create_order(lender["id"], prop["id"], as_lender_id=lender["id"])
    # LenderUser attempts firewalled appraiser selection -> blocked + FirewallEvent logged.
    blocked = api.create_assignment(
        order["id"], factories.assignment_create_payload(order["version"]),
        fixtures.make_lender_user_headers(lender["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_AIR_FIREWALL_VIOLATION.value, 403)

    events, meta = validate_paginated(api.list_order_firewall_events(order["id"], COORD))
    assert len(events) >= 1, "a FirewallEvent must be recorded for the blocked selection"
    ev = events[0]
    assert ev["blocked_operation"] == "SELECT_APPRAISER", (
        f"blocked_operation label must be SELECT_APPRAISER, got {ev['blocked_operation']}"
    )
    assert ev["error_id"] == "ERR_AIR_FIREWALL_VIOLATION", f"recorded error_id mismatch: {ev['error_id']}"
    assert "updated_at" not in ev, "FirewallEvent must NOT carry updated_at (audit-only)"
    assert "version" not in ev, "FirewallEvent must NOT carry version (audit-only)"


def test_lender_budget_exceeded_on_second_order(api):
    """PRD §3.1: "the lender's current `committed_fee_cents` plus this order's
    `order_fee_cents` must not exceed the lender's `monthly_fee_budget_cents` for the
    current calendar month; if it would, placement is rejected with
    `ERR_LENDER_BUDGET_EXCEEDED`."

    Design: Corner/validations/lender_budget_exceeded_on_second_order
    """
    lender = fixtures.create_lender(panel_ids=[], budget_cents=90000, name="L Bud")
    p1 = fixtures.create_property(state_code="CA", street_address="70 CA St")
    p2 = fixtures.create_property(state_code="CA", street_address="71 CA St")
    fixtures.create_order(lender["id"], p1["id"], order_fee_cents=50000)  # committed -> 50000
    # Second 50000 would push committed to 100000 > 90000.
    resp = api.create_order(
        factories.create_order_payload(lender["id"], p2["id"], order_fee_cents=50000, product_type="URAR_1004"),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_LENDER_BUDGET_EXCEEDED.value, 422)


def test_lender_budget_exactly_at_limit_passes(api):
    """PRD §3.1: "the lender's current `committed_fee_cents` plus this order's
    `order_fee_cents` must not exceed the lender's `monthly_fee_budget_cents` for the
    current calendar month; if it would, placement is rejected with
    `ERR_LENDER_BUDGET_EXCEEDED`."

    Design: Corner/validations/lender_budget_exactly_at_limit_passes
    """
    lender = fixtures.create_lender(panel_ids=[], budget_cents=100000, name="L BudOk")
    p1 = fixtures.create_property(state_code="CA", street_address="72 CA St")
    p2 = fixtures.create_property(state_code="CA", street_address="73 CA St")
    fixtures.create_order(lender["id"], p1["id"], order_fee_cents=50000)  # committed -> 50000
    # Second 50000 makes committed exactly 100000 (not exceeding) -> succeeds.
    data = validate_success(
        api.create_order(
            factories.create_order_payload(lender["id"], p2["id"], order_fee_cents=50000, product_type="URAR_1004"),
            COORD,
        ),
        201,
    )
    assert data["status"] == "PLACED", f"order at the exact budget limit must place, got {data['status']}"


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    ghost_headers = {"X-User-ID": "ghost-1", "X-User-Role": "Ghost", "Content-Type": "application/json"}
    resp = api.get_order("00000000-0000-0000-0000-000000000000", ghost_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_stale_order_version_on_cancel(api):
    """PRD §2.8: "The server compares it to the order's current `version`; if they do not
    match, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §3.8: "A coordinator may cancel a non-terminal order — one in `PLACED`, `ASSIGNED`,
    `IN_PROGRESS`, or `IN_QC` — provided the supplied `expected_order_version` matches the
    order's `version`."

    Design: Corner/errors/stale_order_version_on_order_cancel_returns_412
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    pre_version = fixtures.current_order_version(order["id"])  # version before assignment
    fixtures.assign_order(order["id"], pre_version)  # advances version; order now ASSIGNED (cancelable)
    # Cancel from ASSIGNED is a valid transition, so only OCC fails -> deterministic 412.
    resp = api.cancel_order(order["id"], factories.assignment_create_payload(pre_version), COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value, 412)


def test_orders_list_pagination_total_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses carry these four pagination fields inside the `meta` object:
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/orders_list_pagination_total_count_has_more
    """
    lender = fixtures.create_lender(panel_ids=[], name="L Page")
    p1 = fixtures.create_property(state_code="CA", street_address="45 CA St")
    p2 = fixtures.create_property(state_code="CA", street_address="46 CA St")
    fixtures.create_order(lender["id"], p1["id"], order_fee_cents=50000)
    fixtures.create_order(lender["id"], p2["id"], order_fee_cents=50000)
    data, meta = validate_paginated(api.list_orders(COORD, params={"lender_id": lender["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1, f"limit=1 must return exactly 1 item, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more must be true with 2 items and limit 1, got {meta['has_more']}"
