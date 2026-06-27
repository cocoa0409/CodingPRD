"""School fundraising commission: the provisional (round-per-order) accrual vs the
final (sum-then-round) reconciliation at settle, and the conserved commission
gross (PRD §3.7, §3.9).

Queue A: dual_variant_calc, combinatorial_formula, compensating_invariant.
Queue B: consistency_model section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_guardian_headers,
)
from test_helpers.fixtures import (
    create_session, add_student, add_package, create_paid_order,
    create_dispatched_shipment_for_order, read_session,
    create_session_gallery_open_all_absent, create_submitted_order,
)
from test_helpers.api_client import api_client

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["clerk_headers"]
PHOTOG = TEST_USERS["photographer_headers"]


def _build_three_paid_ordering_closed(ship=True):
    """Three PAID orders with merchandise 36000 / 45000 / 45000 (gross 126000),
    each shipped & dispatched, session driven to ORDERING_CLOSED.

    A single PREMIUM line priced 40000 -> subtotal 40000 -> 10% disc 4000 ->
    merch 36000; a 50000 line -> 10% disc 5000 -> merch 45000.
    Returns (session_id, [orders]).
    """
    session = create_session(retouch_budget_cents=0)
    students = [add_student(session["id"], full_name=f"S{i}", homeroom=f"H{i}",
                            guardian_user_id=f"g{i + 1}") for i in range(3)]
    # Stock the catalog while the session is still DRAFT (PRD §3.1) so that
    # opening capture finds an active catalog item (PRD §3.3 requires one,
    # else ERR_EMPTY_CATALOG).
    pkg40 = add_package(session["id"], sku="P40", name="P40", tier="PREMIUM", base_price_cents=40000)
    pkg50 = add_package(session["id"], sku="P50", name="P50", tier="PREMIUM", base_price_cents=50000)
    api_client.lock_roster(session["id"], COORD)
    api_client.open_capture(session["id"], PHOTOG)
    for s in students:
        api_client.mark_absent(s["id"], PHOTOG)
    api_client.open_gallery(session["id"], COORD)
    orders = []
    orders.append(create_paid_order(session["id"], students[0], pkg40["id"]))
    orders.append(create_paid_order(session["id"], students[1], pkg50["id"]))
    orders.append(create_paid_order(session["id"], students[2], pkg50["id"]))
    if ship:
        for i, o in enumerate(orders):
            create_dispatched_shipment_for_order(o["id"], tracking_code=f"T{i}")
    api_client.close_ordering(session["id"], COORD)
    return session["id"], orders


# --------------------------------------------------------------------------- #
# dual_variant_calc / commission_provisional_vs_final_on_session  (queue A)
# --------------------------------------------------------------------------- #
def test_commission_provisional_balance_before_settle(api):
    """PRD §3.7: "Each paid order is thus rounded individually and then summed —
    round-per-order-then-sum."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_on_session
    """
    session_id, _orders = _build_three_paid_ordering_closed()
    sess = read_session(session_id)
    # 5400 + 9000 + 9000 = 23400 (rates 0.15, 0.20, 0.20 on cumulative gross)
    assert sess["school_commission_balance_cents"] == 23400


def test_commission_reconciled_to_final_on_settle(api):
    """PRD §3.7: "A single final rate is taken from the tier of that total gross,
    the final commission is the total gross times that single rate rounded half up
    exactly once over the whole total — sum-then-round, not round-per-order — and
    the session's school_commission_balance_cents is set to that final figure."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_on_session
    """
    session_id, _orders = _build_three_paid_ordering_closed()
    pre = read_session(session_id)
    res = api.settle_session(session_id, {"expected_picture_day_session_version": pre["version"]}, COORD)
    settled = validate_success(res, 200)
    assert settled["status"] == "SETTLED"
    # round(126000 * 0.20) = 25200; delta 25200 - 23400 == 1800
    assert settled["school_commission_balance_cents"] == 25200


# --------------------------------------------------------------------------- #
# combinatorial_formula / commission_rounding_order_perorder_vs_total (queue A)
# --------------------------------------------------------------------------- #
def test_commission_rounding_perorder_then_sum(api):
    """PRD §3.7: "This order's commission line is its own merchandise_cents times
    that rate, rounded half up, and that rounded line is added to the session's
    school_commission_balance_cents. Each paid order is thus rounded individually
    and then summed — round-per-order-then-sum."

    Design: Difficulty/combinatorial_formula/commission_rounding_order_perorder_vs_total
    """
    session_id, _orders = _build_three_paid_ordering_closed()
    sess = read_session(session_id)
    assert sess["school_commission_balance_cents"] == 23400  # 5400 + 9000 + 9000


def test_commission_final_sum_then_round_once(api):
    """PRD §3.7: "the final commission is the total gross times that single rate
    rounded half up exactly once over the whole total — sum-then-round, not
    round-per-order"

    Design: Difficulty/combinatorial_formula/commission_rounding_order_perorder_vs_total
    """
    session_id, _orders = _build_three_paid_ordering_closed()
    pre = read_session(session_id)
    settled = validate_success(
        api.settle_session(session_id, {"expected_picture_day_session_version": pre["version"]}, COORD), 200)
    assert settled["school_commission_balance_cents"] == 25200  # round(126000*0.20)


# --------------------------------------------------------------------------- #
# compensating_invariant / merchandise_gross_conserved_on_settle  (queue A)
# --------------------------------------------------------------------------- #
def test_merchandise_gross_before_settle(api):
    """PRD §3.7: "Recording the payment also adds the order's merchandise_cents to
    the session's total_merchandise_cents."

    Design: Difficulty/compensating_invariant/merchandise_gross_conserved_on_settle
    """
    session_id, _orders = _build_three_paid_ordering_closed()
    sess = read_session(session_id)
    assert sess["total_merchandise_cents"] == 126000


def test_merchandise_gross_conserved_across_settle(api):
    """PRD §3.9: "On success, settlement recomputes the final commission over all
    PAID and FULFILLED orders and reconciles school_commission_balance_cents from
    its provisional value to that final value, applying the reconciliation delta as
    described in §3.7."
    PRD §3.7: "The total gross is the sum of merchandise_cents across every order
    in PAID or FULFILLED at settle time."

    Design: Difficulty/compensating_invariant/merchandise_gross_conserved_on_settle
    """
    session_id, _orders = _build_three_paid_ordering_closed()
    pre = read_session(session_id)
    settled = validate_success(
        api.settle_session(session_id, {"expected_picture_day_session_version": pre["version"]}, COORD), 200)
    # commission moves but the gross is untouched by reconciliation
    assert settled["total_merchandise_cents"] == 126000
    assert settled["school_commission_balance_cents"] == 25200


# --------------------------------------------------------------------------- #
# Queue B / consistency_model / pay_immediately_reflected_in_session_ledgers
# --------------------------------------------------------------------------- #
def test_pay_immediately_reflected_in_ledgers(api):
    """PRD §3.7: "This order's commission line is its own merchandise_cents times
    that rate, rounded half up, and that rounded line is added to the session's
    school_commission_balance_cents."
    PRD §3.7: "Recording the payment also adds the order's merchandise_cents to the
    session's total_merchandise_cents."

    Design: Corner/consistency_model/pay_immediately_reflected_in_session_ledgers
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K", name="K", tier="BASIC", base_price_cents=5000)
    order = create_submitted_order(session["id"], students[0], pkg["id"], quantity=1)
    validate_success(api.pay_order(order["id"], CLERK), 200)
    sess = read_session(session["id"])
    assert sess["total_merchandise_cents"] == 4750
    assert sess["school_commission_balance_cents"] == 713  # round(4750*0.15)
