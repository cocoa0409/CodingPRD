"""Order carts, lines, submission, and the order-total calculation
(PRD §3.6, §3.7). Covers the tiered-discount + free-shipping formula, its
inclusive boundaries, the PAID-vs-REJECTED branch, and order corner cases.

Queue A: combinatorial_formula, boundary_precision_check, non_linear_state_machine.
Queue B: entities, state_machines, calculations sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_order_line_payload,
    TEST_USERS, make_guardian_headers,
)
from test_helpers.fixtures import (
    create_session_gallery_open_all_absent, create_cart_order, add_line,
    create_submitted_order, create_paid_order, add_package, read_session,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["clerk_headers"]


def _gallery_open_one_student(**session_overrides):
    session, students, _default_pkg = create_session_gallery_open_all_absent(
        num_students=1, **session_overrides)
    return session, students[0]


# --------------------------------------------------------------------------- #
# combinatorial_formula / order_total_tier_and_freeship_branches  (queue A)
# --------------------------------------------------------------------------- #
def test_order_total_tier5pct_and_flat_shipping(api):
    """PRD §3.7: "The discount amount, stored as discount_cents, is the subtotal
    times the discount fraction, rounded half up — and it is the single
    subtotal-level discount that is rounded, never the individual lines."
    PRD §3.7: "Shipping, stored as shipping_cents, is free (zero) when the
    merchandise amount is at least 10000 cents and otherwise a flat 599 cents."

    Design: Difficulty/combinatorial_formula/order_total_tier_and_freeship_branches
    """
    session, student = _gallery_open_one_student()
    pkg_b = add_package(session["id"], sku="B", name="Basic", tier="BASIC", base_price_cents=2499)
    pkg_d = add_package(session["id"], sku="D", name="Deluxe", tier="DELUXE", base_price_cents=3999)
    order = create_cart_order(session["id"], student)
    add_line(order, pkg_b["id"], student, quantity=2)
    add_line(order, pkg_d["id"], student, quantity=1)
    g = make_guardian_headers(student["guardian_user_id"])
    submitted = validate_success(api.submit_order(order["id"], g), 200)
    assert submitted["subtotal_cents"] == 8997
    assert submitted["discount_cents"] == 450
    assert submitted["merchandise_cents"] == 8547
    assert submitted["shipping_cents"] == 599
    assert submitted["total_cents"] == 9146


def test_order_total_free_shipping_when_merch_reaches_threshold(api):
    """PRD §3.7: "Shipping, stored as shipping_cents, is free (zero) when the
    merchandise amount is at least 10000 cents and otherwise a flat 599 cents.
    The amount due, stored as total_cents, is the merchandise amount plus shipping."

    Design: Difficulty/combinatorial_formula/order_total_tier_and_freeship_branches
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="P12", name="P12", tier="PREMIUM", base_price_cents=12000)
    order = create_cart_order(session["id"], student)
    add_line(order, pkg["id"], student, quantity=1)
    g = make_guardian_headers(student["guardian_user_id"])
    submitted = validate_success(api.submit_order(order["id"], g), 200)
    # subtotal 12000 -> 5% disc 600 -> merch 11400 (>=10000) -> shipping 0
    assert submitted["merchandise_cents"] == 11400
    assert submitted["shipping_cents"] == 0
    assert submitted["total_cents"] == 11400


# --------------------------------------------------------------------------- #
# boundary_precision_check / order_discount_tier_at_5000_inclusive  (queue A)
# --------------------------------------------------------------------------- #
def test_discount_tier_inclusive_at_exactly_5000(api):
    """PRD §3.7: "A volume discount is then selected by the subtotal, with
    inclusive boundaries: when the subtotal is at least 15000 cents the discount
    fraction, stored as discount_pct, is ten percent; otherwise when the subtotal
    is at least 5000 cents it is five percent; otherwise it is zero. The boundary
    is inclusive, so a subtotal of exactly 5000 cents earns the five-percent tier
    while 4999 earns nothing."

    Design: Difficulty/boundary_precision_check/order_discount_tier_at_5000_inclusive
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="F5", name="Five", tier="BASIC", base_price_cents=5000)
    order = create_cart_order(session["id"], student)
    add_line(order, pkg["id"], student, quantity=1)
    g = make_guardian_headers(student["guardian_user_id"])
    submitted = validate_success(api.submit_order(order["id"], g), 200)
    assert submitted["subtotal_cents"] == 5000
    assert submitted["discount_cents"] == 250
    assert submitted["merchandise_cents"] == 4750
    assert submitted["total_cents"] == 5349  # 4750 + 599 shipping


def test_discount_tier_no_discount_below_5000(api):
    """PRD §3.7: "The boundary is inclusive, so a subtotal of exactly 5000 cents
    earns the five-percent tier while 4999 earns nothing."

    Design: Difficulty/boundary_precision_check/order_discount_tier_at_5000_inclusive
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="N", name="Near", tier="BASIC", base_price_cents=4999)
    order = create_cart_order(session["id"], student)
    add_line(order, pkg["id"], student, quantity=1)
    g = make_guardian_headers(student["guardian_user_id"])
    submitted = validate_success(api.submit_order(order["id"], g), 200)
    assert submitted["discount_cents"] == 0
    assert submitted["merchandise_cents"] == 4999
    assert submitted["total_cents"] == 5598  # 4999 + 599 shipping


# --------------------------------------------------------------------------- #
# Queue B / calculations  (order_total corner instances)
# --------------------------------------------------------------------------- #
def test_order_discount_tier_below_5000_no_discount_corner(api):
    """PRD §3.7: "The boundary is inclusive, so a subtotal of exactly 5000 cents
    earns the five-percent tier while 4999 earns nothing."

    Design: Corner/calculations/order_discount_tier_below_5000_no_discount
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="N", name="Near", tier="BASIC", base_price_cents=4999)
    order = create_cart_order(session["id"], student)
    add_line(order, pkg["id"], student, quantity=1)
    g = make_guardian_headers(student["guardian_user_id"])
    submitted = validate_success(api.submit_order(order["id"], g), 200)
    assert submitted["discount_cents"] == 0
    assert submitted["merchandise_cents"] == 4999
    assert submitted["total_cents"] == 5598


def test_order_free_shipping_corner(api):
    """PRD §3.7: "Shipping, stored as shipping_cents, is free (zero) when the
    merchandise amount is at least 10000 cents and otherwise a flat 599 cents."

    Design: Corner/calculations/order_free_shipping_when_merch_reaches_threshold
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="P12", name="P12", tier="PREMIUM", base_price_cents=12000)
    order = create_cart_order(session["id"], student)
    add_line(order, pkg["id"], student, quantity=1)
    g = make_guardian_headers(student["guardian_user_id"])
    submitted = validate_success(api.submit_order(order["id"], g), 200)
    assert submitted["merchandise_cents"] == 11400
    assert submitted["shipping_cents"] == 0
    assert submitted["total_cents"] == 11400


# --------------------------------------------------------------------------- #
# non_linear_state_machine / order_branch_paid_vs_rejected  (queue A)
# --------------------------------------------------------------------------- #
def test_order_branch_paid_accrues_commission(api):
    """PRD §3.7: "This order's commission line is its own merchandise_cents times
    that rate, rounded half up, and that rounded line is added to the session's
    school_commission_balance_cents."
    PRD §3.7: "Recording the payment also adds the order's merchandise_cents to the
    session's total_merchandise_cents."

    Design: Difficulty/non_linear_state_machine/order_branch_paid_vs_rejected
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=2)
    pkg = add_package(session["id"], sku="K5", name="K5", tier="BASIC", base_price_cents=5000)
    order_a = create_submitted_order(session["id"], students[0], pkg["id"], quantity=1)
    order_b = create_submitted_order(session["id"], students[1], pkg["id"], quantity=1)
    paid = validate_success(api.pay_order(order_a["id"], CLERK), 200)
    rejected = validate_success(api.reject_order(order_b["id"], CLERK), 200)
    assert paid["status"] == "PAID"
    assert rejected["status"] == "REJECTED"
    sess = read_session(session["id"])
    # Only the PAID order's merch (4750) counts; commission round(4750*0.15)=713
    assert sess["total_merchandise_cents"] == 4750
    assert sess["school_commission_balance_cents"] == 713


def test_order_branch_rejected_accrues_nothing(api):
    """PRD §3.7: "A clerk may instead reject a submitted order, advancing it
    SUBMITTED → REJECTED and freezing it with no commission accrued"

    Design: Difficulty/non_linear_state_machine/order_branch_paid_vs_rejected
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K5", name="K5", tier="BASIC", base_price_cents=5000)
    order = create_submitted_order(session["id"], students[0], pkg["id"], quantity=1)
    rejected = validate_success(api.reject_order(order["id"], CLERK), 200)
    assert rejected["status"] == "REJECTED"
    sess = read_session(session["id"])
    assert sess["total_merchandise_cents"] == 0
    assert sess["school_commission_balance_cents"] == 0


# --------------------------------------------------------------------------- #
# Queue B / entities + state_machines  (order corner cases)
# --------------------------------------------------------------------------- #
def test_order_line_unit_price_snapshot_and_total(api):
    """PRD §3.6: "At the moment a line is added, the system snapshots the package
    item's base_price_cents into the line's unit_price_cents, computes the line's
    line_total_cents as the snapshot unit price times the quantity"

    Design: Corner/entities/order_line_unit_price_snapshot_system_field
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="B", name="Basic", tier="BASIC", base_price_cents=2499)
    order = create_cart_order(session["id"], student)
    g = make_guardian_headers(student["guardian_user_id"])
    res = api.create_order_line(create_order_line_payload(order["id"], pkg["id"], 3), g)
    line = validate_success(res, 201)
    assert line["unit_price_cents"] == 2499
    assert line["line_total_cents"] == 7497


def test_order_has_premium_line_flag(api):
    """PRD §3.6: "recomputes the order's has_premium_line flag — which becomes true
    if any line on the order references a PREMIUM-tier package item."

    Design: Corner/entities/package_computed_premium_flag_on_order
    """
    session, student = _gallery_open_one_student()
    pkg_p = add_package(session["id"], sku="PR", name="Prem", tier="PREMIUM", base_price_cents=40000)
    order = create_cart_order(session["id"], student)
    g = make_guardian_headers(student["guardian_user_id"])
    api.create_order_line(create_order_line_payload(order["id"], pkg_p["id"], 1), g)
    fetched = validate_success(api.get_order(order["id"], g), 200)
    assert fetched["has_premium_line"] is True


def test_pay_order_not_submitted_rejected(api):
    """PRD §3.7: "Paying an order requires it to be SUBMITTED (otherwise
    ERR_ORDER_NOT_SUBMITTED) and advances it SUBMITTED → PAID."

    Design: Corner/state_machines/pay_order_not_submitted_invalid
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="K", name="K", tier="BASIC", base_price_cents=5000)
    order = create_cart_order(session["id"], student)
    add_line(order, pkg["id"], student, quantity=1)
    # order still in CART (never submitted)
    res = api.pay_order(order["id"], CLERK)
    validate_error(res, "ERR_ORDER_NOT_SUBMITTED", expected_status=409)


def test_submit_empty_order_rejected(api):
    """PRD §3.6: "Submission freezes the order and is only legal while the session
    is in GALLERY_OPEN (otherwise ERR_SESSION_NOT_ORDERING) and the order has at
    least one line (otherwise ERR_EMPTY_ORDER)."

    Design: Corner/state_machines/submit_empty_order_rejected
    """
    session, student = _gallery_open_one_student()
    order = create_cart_order(session["id"], student)
    g = make_guardian_headers(student["guardian_user_id"])
    res = api.submit_order(order["id"], g)
    validate_error(res, "ERR_EMPTY_ORDER", expected_status=409)


def test_add_line_to_submitted_order_not_cart(api):
    """PRD §3.6: "A line may only be added while its order is in CART; adding to an
    order that is not CART is rejected with ERR_ORDER_NOT_CART."

    Design: Corner/state_machines/add_line_to_submitted_order_not_cart
    """
    session, student = _gallery_open_one_student()
    pkg = add_package(session["id"], sku="K", name="K", tier="BASIC", base_price_cents=5000)
    order = create_submitted_order(session["id"], student, pkg["id"], quantity=1)
    g = make_guardian_headers(student["guardian_user_id"])
    res = api.create_order_line(create_order_line_payload(order["id"], pkg["id"], 1), g)
    validate_error(res, "ERR_ORDER_NOT_CART", expected_status=409)
