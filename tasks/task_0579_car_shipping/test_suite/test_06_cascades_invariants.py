"""Cancel/revoke cascades, conservation invariants, close precedence, exposure.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 (transitive_cascade,
compensating_invariant, priority_pair_validation_conflict, dual_variant_calc).
"""
from test_helpers import (
    TEST_USERS,
    dispatch_order_for_carrier,
    get_carrier,
    get_listing,
    get_offer,
    list_order_ledger,
    make_shipper_headers,
    read_order,
    register_carrier,
    register_shipper,
    setup_dispatched_order,
    setup_listed_order,
    setup_pending_offer,
    validate_error,
    validate_success,
)


def _posted_ledger_sum(order_id):
    entries = list_order_ledger(order_id)
    return sum(e["amount_cents"] for e in entries if e["status"] == "POSTED")


# ─── transitive_cascade / cancel → listing → offers + refund — 2 tests ──────

def test_cancel_withdraws_listing(api):
    """PRD §3.8: "Any OPEN LoadListing on the order is withdrawn to WITHDRAWN, and
    its offers still in PENDING or COUNTERED flip to DECLINED."
    PRD §3.8: "Cancellation moves the order to the terminal CANCELLED state."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_listing_offer_refund_depth3
    """
    ctx = setup_pending_offer(route_miles=1200)
    order = validate_success(
        api.cancel_order(ctx["order"]["id"], make_shipper_headers(ctx["shipper"]["id"])), 200
    )
    assert order["status"] == "CANCELLED"
    listing = get_listing(ctx["listing"]["id"])
    assert listing["status"] == "WITHDRAWN"


def test_cancel_declines_pending_offer_and_refunds_deposit(api):
    """PRD §3.8: "its offers still in PENDING or COUNTERED flip to DECLINED."
    PRD §3.8: "If a POSTED DEPOSIT exists on the order, the system posts a
    compensating REFUND ledger entry equal to the negative of deposit_cents and
    reconciles amount_paid_cents and outstanding_balance_cents accordingly".

    Design: Difficulty/transitive_cascade/order_cancel_cascade_listing_offer_refund_depth3
    """
    ctx = setup_pending_offer(route_miles=1200)
    validate_success(
        api.cancel_order(ctx["order"]["id"], make_shipper_headers(ctx["shipper"]["id"])), 200
    )
    offer = get_offer(ctx["offer"]["id"])
    assert offer["status"] == "DECLINED"
    assert _posted_ledger_sum(ctx["order"]["id"]) == 0


# ─── compensating_invariant / cancel refund conserves cash — 2 tests ────────

def test_cancel_refund_returns_net_posted_cash_to_zero(api):
    """PRD §3.8: "the system posts a compensating REFUND ledger entry equal to the
    negative of deposit_cents".
    PRD §2.10: "Only entries whose status is POSTED participate in reconciliation".

    A forward DEPOSIT (+20000) and its cancel-triggered REFUND (-20000) net to 0.

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_order_cash_to_zero
    """
    ctx = setup_listed_order(route_miles=1200, deposit_cents=20000)
    validate_success(
        api.cancel_order(ctx["order"]["id"], make_shipper_headers(ctx["shipper"]["id"])), 200
    )
    assert _posted_ledger_sum(ctx["order"]["id"]) == 0


def test_cancel_posts_exactly_one_refund_entry(api):
    """PRD §3.8: "the system posts a compensating REFUND ledger entry equal to the
    negative of deposit_cents".
    PRD §3.8: "Cancellation moves the order to the terminal CANCELLED state."

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_order_cash_to_zero
    """
    ctx = setup_listed_order(route_miles=1200, deposit_cents=20000)
    order = validate_success(
        api.cancel_order(ctx["order"]["id"], make_shipper_headers(ctx["shipper"]["id"])), 200
    )
    assert order["status"] == "CANCELLED"
    refunds = [e for e in list_order_ledger(ctx["order"]["id"])
               if e["kind"] == "REFUND" and e["status"] == "POSTED"]
    assert len(refunds) == 1, f"Expected exactly one POSTED REFUND, got {len(refunds)}"


# ─── compensating_invariant / dispatch ↔ revoke conservation — 2 tests ──────

def test_revoke_returns_order_to_listed_and_clears_carrier(api):
    """PRD §3.6: "On revoke the order moves from DISPATCHED back to LISTED, the
    assignment flips to REVOKED, the order's assigned_carrier_id is cleared to
    null, and the LoadListing reopens from AWARDED to OPEN with its best_offer_id
    recomputed so the board can be reworked."

    Design: Difficulty/compensating_invariant/dispatch_revoke_conserves_active_assignment_count
    """
    ctx = setup_dispatched_order(route_miles=1200)
    assignment = validate_success(
        api.revoke_assignment(ctx["assignment"]["id"], TEST_USERS["broker_headers"]), 200
    )
    assert assignment["status"] == "REVOKED"
    order = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    assert order["status"] == "LISTED"
    assert order["assigned_carrier_id"] is None


def test_revoke_reopens_listing_and_resets_carrier_exposure(api):
    """PRD §3.6: "the LoadListing reopens from AWARDED to OPEN".
    PRD §3.6: "Because the load leaves the carrier's active set, the carrier's
    aggregate_exposure_cents is recomputed".

    Design: Difficulty/compensating_invariant/dispatch_revoke_conserves_active_assignment_count
    """
    ctx = setup_dispatched_order(route_miles=1200, declared_value_cents=1_000_000)
    validate_success(
        api.revoke_assignment(ctx["assignment"]["id"], TEST_USERS["broker_headers"]), 200
    )
    listing = get_listing(ctx["listing"]["id"])
    assert listing["status"] == "OPEN"
    carrier = get_carrier(ctx["carrier"]["id"])
    assert carrier["aggregate_exposure_cents"] == 0


# ─── priority_pair_validation_conflict / state beats fiscal on close — 2 ─────

def test_close_on_dispatched_order_returns_invalid_state(api):
    """PRD §2.1: "then whether the target resource is in a state that permits the
    transition (ERR_INVALID_STATE, 409, unless a more specific domain state error
    is declared for that transition), then request-body shape (ERR_INVALID_REQUEST,
    422), and finally the domain-specific temporal, fiscal, and safety checks
    described throughout §2 and §3."
    PRD §3.8: "A Broker closes a DELIVERED order, advancing it from DELIVERED to
    the terminal CLOSED state."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_close_returns_invalid_state
    """
    ctx = setup_dispatched_order(route_miles=1200)  # DISPATCHED, COD still outstanding
    resp = api.close_order(ctx["order"]["id"], TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_rejected_close_leaves_order_dispatched(api):
    """PRD §3.8: "A Broker closes a DELIVERED order, advancing it from DELIVERED to
    the terminal CLOSED state."
    PRD §2.8: "there is no eventual reconciliation and no partial application."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_close_returns_invalid_state
    """
    ctx = setup_dispatched_order(route_miles=1200)
    api.close_order(ctx["order"]["id"], TEST_USERS["broker_headers"])
    order = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    assert order["status"] == "DISPATCHED"


# ─── dual_variant_calc / per-load vs aggregate carrier exposure — 2 tests ───

def test_aggregate_exposure_sums_all_active_loads(api):
    """PRD §2.11: "The aggregate reading is the sum of declared_value_cents across
    the vehicles of every order currently assigned to that carrier whose
    Assignment status is DISPATCHED or PICKED_UP, including the order just
    dispatched."
    PRD §2.11: "For a carrier holding two active loads, aggregate_exposure_cents
    counts both while the per-load gate sees only one."

    Two loads (declared 800000 and 1200000) → aggregate 2000000, not 1200000.

    Design: Difficulty/dual_variant_calc/carrier_per_load_vs_aggregate_exposure
    """
    shipper = register_shipper()
    carrier = register_carrier(equipment_type="OPEN", cargo_insurance_limit_cents=1_500_000)
    dispatch_order_for_carrier(
        shipper["id"], carrier["id"], declared_value_cents=800_000,
        pickup_window_start="2026-06-01T08:00:00Z", pickup_window_end="2026-06-05T18:00:00Z",
        pickup_eta="2026-06-02T09:00:00Z",
    )
    dispatch_order_for_carrier(
        shipper["id"], carrier["id"], declared_value_cents=1_200_000,
        pickup_window_start="2026-06-10T08:00:00Z", pickup_window_end="2026-06-14T18:00:00Z",
        pickup_eta="2026-06-11T09:00:00Z",
    )
    result = get_carrier(carrier["id"])
    assert result["aggregate_exposure_cents"] == 2_000_000
    assert result["aggregate_exposure_cents"] != 1_200_000


def test_aggregate_exposure_of_single_dispatched_load(api):
    """PRD §2.11: "The aggregate reading is the sum of declared_value_cents across
    the vehicles of every order currently assigned to that carrier whose
    Assignment status is DISPATCHED or PICKED_UP, including the order just
    dispatched."

    One dispatched load with a single vehicle declared 800000 → aggregate 800000.

    Design: Difficulty/dual_variant_calc/carrier_per_load_vs_aggregate_exposure
    """
    ctx = setup_dispatched_order(route_miles=1200, declared_value_cents=800_000)
    carrier = get_carrier(ctx["carrier"]["id"])
    assert carrier["aggregate_exposure_cents"] == 800_000
