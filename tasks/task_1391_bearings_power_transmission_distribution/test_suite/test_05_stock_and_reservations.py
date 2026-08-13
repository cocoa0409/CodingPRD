"""Branch stock mechanics and the reservation lifecycle (72h TTL, release,
expiry cascade, availability boundary)."""
import pytest
from datetime import timedelta
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_product, create_branch, create_customer, create_branch_stock,
    create_confirmed_order_with_line, reserve_line, set_clock,
    get_order, get_order_line, get_branch_stock, get_reservation,
    parse_iso, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_reserved_order(on_hand=8, qty=3, reserve_at="2026-08-01T10:00:00Z"):
    """Confirmed order with one line reserved; order reaches FULLY_SOURCED."""
    set_clock(reserve_at)
    product = create_product(sku="CHN-40", list_price_cents=5000, family="CHAIN")
    branch = create_branch(code="HOU-07")
    customer = create_customer(name="Gulf Coast Plant")
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=on_hand)
    order, line = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=qty)
    reservation = reserve_line(line["id"], stock["id"], qty)
    assert get_order(order["id"])["fulfillment_status"] == "FULLY_SOURCED"
    return {"product": product, "branch": branch, "customer": customer,
            "stock": stock, "order": order, "line": line,
            "reservation": reservation}


def test_reservation_expiry_moves_reservation_to_expired(api):
    """PRD §3.3: "When a line is reserved (see §3.4), the server creates a
    reservation in `ACTIVE` status whose `expires_at` is exactly 72 hours after
    creation" and "When the logical clock passes `expires_at`, the reservation
    goes `EXPIRED` with the same three-hop cascade".

    Design: Difficulty/transitive_cascade/reservation_expiry_cascades_line_and_order_revert
    """
    ctx = _setup_reserved_order()
    reservation = ctx["reservation"]
    expected_expiry = parse_iso("2026-08-01T10:00:00Z") + timedelta(hours=72)
    assert parse_iso(reservation["expires_at"]) == expected_expiry, (
        f"expires_at must be created_at + 72h; got {reservation['expires_at']}")

    set_clock("2026-08-05T10:00:00Z")  # past expiry 2026-08-04T10:00
    expired = get_reservation(reservation["id"])
    assert expired["status"] == "EXPIRED"


def test_reservation_expiry_cascades_line_and_order_revert(api):
    """PRD §3.3: "When the logical clock passes `expires_at`, the reservation
    goes `EXPIRED` with the same three-hop cascade — line back to
    `PENDING_SOURCING`, reserved quantity recomputed, order re-evaluated."

    Design: Difficulty/transitive_cascade/reservation_expiry_cascades_line_and_order_revert
    """
    ctx = _setup_reserved_order()
    set_clock("2026-08-05T10:00:00Z")
    line = get_order_line(ctx["line"]["id"])
    assert line["sourcing_status"] == "PENDING_SOURCING", (
        f"hop 2 reversion; got {line['sourcing_status']}")
    order = get_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "CONFIRMED", (
        f"hop 3: FULLY_SOURCED bubble collapses to CONFIRMED; got {order['fulfillment_status']}")
    stock = get_branch_stock(ctx["stock"]["id"])
    assert stock["reserved_qty"] == 0
    assert stock["available_qty"] == 8


def _setup_two_confirmed_orders():
    """Stock on_hand 5; order A line qty 5 confirmed; order B line qty 1."""
    product = create_product(sku="BRG-51205", list_price_cents=6000)
    branch = create_branch(code="STL-12")
    customer = create_customer(name="Gateway Plant")
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=5)
    order_a, line_a = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=5)
    order_b, line_b = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    return {"product": product, "branch": branch, "customer": customer,
            "stock": stock, "line_a": line_a, "line_b": line_b}


def test_reserve_exactly_available_quantity_succeeds(api):
    """PRD §3.4: "provided the line is `PENDING_SOURCING`
    (`ERR_LINE_NOT_SOURCABLE`, 409), the order is `CONFIRMED` or
    `FULLY_SOURCED` (`ERR_ORDER_NOT_CONFIRMABLE`), the stock record matches,
    the quantity matches the line exactly, and `available_qty` covers the full
    `qty` (`ERR_INSUFFICIENT_AVAILABLE_STOCK`, 409)". Covers means >=, so
    reserving exactly the available quantity is legal.

    Design: Difficulty/boundary_precision_check/reserve_exactly_available_succeeds_plus_one_fails
    """
    ctx = _setup_two_confirmed_orders()
    reservation = reserve_line(ctx["line_a"]["id"], ctx["stock"]["id"], 5)
    assert reservation["status"] == "ACTIVE"
    stock = get_branch_stock(ctx["stock"]["id"])
    assert stock["reserved_qty"] == 5
    assert stock["available_qty"] == 0


def test_reserve_one_above_available_fails(api):
    """PRD §3.4: "provided the line is `PENDING_SOURCING`
    (`ERR_LINE_NOT_SOURCABLE`, 409), the order is `CONFIRMED` or
    `FULLY_SOURCED` (`ERR_ORDER_NOT_CONFIRMABLE`), the stock record matches,
    the quantity matches the line exactly, and `available_qty` covers the full
    `qty` (`ERR_INSUFFICIENT_AVAILABLE_STOCK`, 409)".

    Design: Difficulty/boundary_precision_check/reserve_exactly_available_succeeds_plus_one_fails
    """
    ctx = _setup_two_confirmed_orders()
    reserve_line(ctx["line_a"]["id"], ctx["stock"]["id"], 5)  # available now 0
    res = api.reserve_line(ctx["line_b"]["id"],
                           {"branch_stock_id": ctx["stock"]["id"], "qty": 1}, REP)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_STOCK,
                   expected_status=409)
    line_b = get_order_line(ctx["line_b"]["id"])
    assert line_b["sourcing_status"] == "PENDING_SOURCING"


def test_reservation_release_reverts_line_and_frees_stock(api):
    """PRD §3.3: "A `CounterSalesRep` or `BranchManager` may release an active
    reservation, which requires the reservation still be `ACTIVE`
    (`ERR_RESERVATION_NOT_ACTIVE`, 409) and cascades: the order line falls back
    from `STOCK_RESERVED` to `PENDING_SOURCING`, `reserved_qty` recomputes, and
    the order's fulfillment status is re-evaluated (an order that had reached
    `FULLY_SOURCED` reverts to `CONFIRMED`)."

    Design: Corner/state_machines/reservation_release_reverts_line_and_frees_stock
    """
    ctx = _setup_reserved_order(on_hand=4, qty=4)
    released = validate_success(
        api.release_reservation(ctx["reservation"]["id"], MANAGER), 200)
    assert released["status"] == "RELEASED"
    assert get_order_line(ctx["line"]["id"])["sourcing_status"] == "PENDING_SOURCING"
    stock = get_branch_stock(ctx["stock"]["id"])
    assert stock["reserved_qty"] == 0
    assert stock["available_qty"] == 4
    assert get_order(ctx["order"]["id"])["fulfillment_status"] == "CONFIRMED"


def test_scheduled_reservation_expiry_exact_boundary(api):
    """PRD §3.3: "When the logical clock passes `expires_at`, the reservation
    goes `EXPIRED` with the same three-hop cascade — line back to
    `PENDING_SOURCING`, reserved quantity recomputed, order re-evaluated."

    Design: Corner/cross_cutting_complexity_layers/scheduled_reservation_expiry_exact_boundary
    """
    ctx = _setup_reserved_order(on_hand=5, qty=2)
    # At exactly expires_at the clock has not passed it: still ACTIVE.
    set_clock("2026-08-04T10:00:00Z")
    at_boundary = get_reservation(ctx["reservation"]["id"])
    assert at_boundary["status"] == "ACTIVE", (
        f"clock == expires_at must not expire (strict passing); got {at_boundary['status']}")
    # One second later the clock has passed expires_at.
    set_clock("2026-08-04T10:00:01Z")
    past = get_reservation(ctx["reservation"]["id"])
    assert past["status"] == "EXPIRED"
    assert get_order_line(ctx["line"]["id"])["sourcing_status"] == "PENDING_SOURCING"


def test_stock_adjust_cannot_drop_below_reserved(api):
    """PRD §2.8: "A manual adjustment takes `qty_delta` and a free-text
    `reason`, adds the delta to `on_hand_qty`, and is rejected with
    `ERR_STOCK_BELOW_RESERVED` (409) whenever the resulting shelf quantity
    would fall below the currently reserved quantity."

    Design: Corner/endpoints/stock_adjust_cannot_drop_below_reserved
    """
    product = create_product(sku="BRG-6040", list_price_cents=1000)
    branch = create_branch(code="ADJ-27")
    customer = create_customer(name="Adjust Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=5)
    order, line = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=3)
    reserve_line(line["id"], stock["id"], 3)  # reserved 3

    res = api.adjust_branch_stock(
        stock["id"], {"qty_delta": -3, "reason": "cycle count"}, MANAGER)
    validate_error(res, ApiErrorId.ERR_STOCK_BELOW_RESERVED, expected_status=409)

    adjusted = validate_success(api.adjust_branch_stock(
        stock["id"], {"qty_delta": -2, "reason": "cycle count"}, MANAGER), 200)
    assert adjusted["on_hand_qty"] == 3, (
        "landing exactly at reserved is allowed (>= semantics); "
        f"got {adjusted['on_hand_qty']}")
    assert adjusted["available_qty"] == 0


def test_partial_line_reservation_rejected(api):
    """PRD §3.3: "whose `qty` must equal the full order-line quantity — a
    partial reservation is rejected with `ERR_PARTIAL_RESERVATION` (409)."

    Design: Corner/validations/partial_line_reservation_rejected
    """
    product = create_product(sku="BRG-6032", list_price_cents=1000)
    branch = create_branch(code="PRT-20")
    customer = create_customer(name="Partial Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=10)
    order, line = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=3)
    res = api.reserve_line(line["id"],
                           {"branch_stock_id": stock["id"], "qty": 2}, REP)
    validate_error(res, ApiErrorId.ERR_PARTIAL_RESERVATION, expected_status=409)
    assert get_order_line(line["id"])["sourcing_status"] == "PENDING_SOURCING"


def test_reserve_stock_of_wrong_branch_rejected(api):
    """PRD §3.3: "The stock record named by `branch_stock_id` must belong to
    the order's branch and reference the line's product, else
    `ERR_STOCK_LINE_MISMATCH` (409)."

    Design: Corner/validations/reserve_stock_of_wrong_branch_rejected
    """
    product = create_product(sku="BRG-6033", list_price_cents=1000)
    branch_a = create_branch(code="MSA-21")
    branch_b = create_branch(code="MSB-22")
    customer = create_customer(name="Mismatch Plant", credit_limit_cents=1000000)
    stock_b = create_branch_stock(branch_b["id"], product["id"], on_hand_qty=10)
    order, line = create_confirmed_order_with_line(
        customer["id"], branch_a["id"], product["id"], qty=1)
    res = api.reserve_line(line["id"],
                           {"branch_stock_id": stock_b["id"], "qty": 1}, REP)
    validate_error(res, ApiErrorId.ERR_STOCK_LINE_MISMATCH, expected_status=409)
