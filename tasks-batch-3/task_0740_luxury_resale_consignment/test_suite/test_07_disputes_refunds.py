"""Disputes, returns, and refund variants, plus the file-dispute validation guards
(state-beats-temporal precedence, the inclusive window boundary, terminal lockdown,
one-open-dispute rule, and the one-second-past rejection).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_dispute_payload,
    make_buyer_headers, TEST_USERS,
    # fixtures
    setup_delivered_sale, get_sale, get_seller, get_sale_payout,
    file_dispute, resolve_dispute, set_clock,
)

_ADMIN = TEST_USERS["ops_admin_headers"]


# --- dual_variant_calc: authenticity full refund vs change-of-mind restocking -
def test_authenticity_dispute_refunds_full_order_total(api):
    """PRD §3.8: "For an `AUTHENTICITY` or `CONDITION` dispute, the `restocking_fee_cents`
    is zero and the `refund_amount_cents` is the full `order_total_cents` — the buyer gets
    back the sale price, the buyer fee, and the tax in their entirety."

    Design: Difficulty/dual_variant_calc/refund_authenticity_full_vs_change_of_mind_restocking
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "AUTHENTICITY", "fake stitching")
    resolved = resolve_dispute(dispute["id"], "BUYER")
    # order_total for 180000 = 180000 + 18500 + 15880 = 214380.
    assert resolved["refund_amount_cents"] == 214380, resolved["refund_amount_cents"]
    assert resolved["restocking_fee_cents"] == 0, resolved["restocking_fee_cents"]


def test_change_of_mind_dispute_refund_retains_buyer_fee_and_charges_restocking(api):
    """PRD §3.8: "For a `CHANGE_OF_MIND` dispute, the `restocking_fee_cents` is the
    `sale_price_cents` multiplied by the ten-percent restocking fraction (`0.10`), rounded
    half up to whole cents, and the `refund_amount_cents` is the `sale_price_cents` plus
    the `tax_cents` minus that `restocking_fee_cents` — note the `buyer_fee_cents` is
    non-refundable on a change-of-mind return."

    Design: Difficulty/dual_variant_calc/refund_authenticity_full_vs_change_of_mind_restocking
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "CHANGE_OF_MIND", "did not fit")
    resolved = resolve_dispute(dispute["id"], "BUYER")
    # restocking = round(180000*0.10)=18000; refund = 180000 + 15880 - 18000 = 177880.
    assert resolved["refund_amount_cents"] == 177880, resolved["refund_amount_cents"]
    assert resolved["restocking_fee_cents"] == 18000, resolved["restocking_fee_cents"]
    # Diverges from the authenticity full refund (the sale's order_total_cents = 214380).
    assert resolved["refund_amount_cents"] != ctx["sale"]["order_total_cents"]


# --- transitive_cascade: resolve BUYER unwinds sale -> payout -> seller -------
def test_resolve_buyer_refunds_and_returns_sale(api):
    """PRD §3.8: "In both buyer-favour cases the sale's `payment_status` moves from
    `CAPTURED` to `REFUNDED`, crediting the computed `refund_amount_cents` to the buyer,
    and the sale's `fulfillment_status` moves from `DELIVERED` to `RETURNED`."

    Design: Difficulty/transitive_cascade/buyer_dispute_cascade_sale_payout_seller
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "AUTHENTICITY", "counterfeit")
    resolve_dispute(dispute["id"], "BUYER")
    sale = get_sale(ctx["sale_id"])
    assert sale["payment_status"] == "REFUNDED", sale["payment_status"]
    assert sale["fulfillment_status"] == "RETURNED", sale["fulfillment_status"]


def test_resolve_buyer_reverses_payout_and_seller_ledger(api):
    """PRD §3.8: "the sale's payout, whether it was `SCHEDULED` or `HELD`, moves to
    `REVERSED`, subtracting its `amount_cents` from the seller's `pending_payout_cents` and
    adding it to the seller's `reversed_payout_cents`."

    Design: Difficulty/transitive_cascade/buyer_dispute_cascade_sale_payout_seller
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "AUTHENTICITY", "counterfeit")
    resolve_dispute(dispute["id"], "BUYER")
    payout = get_sale_payout(ctx["sale_id"])
    seller = get_seller(ctx["seller_id"])
    assert payout["status"] == "REVERSED", payout["status"]
    assert seller["pending_payout_cents"] == 0, seller["pending_payout_cents"]
    assert seller["reversed_payout_cents"] == 144000, seller["reversed_payout_cents"]


# --- priority_pair_validation_conflict: state (disputable) beats temporal -----
def _setup_returned_past_window(api):
    """Sale returned via a CHANGE_OF_MIND buyer-favour resolution, then the clock advanced
    past the return window — so a further dispute violates BOTH the state precondition
    (RETURNED) and the temporal precondition (past window)."""
    set_clock("2026-03-01T00:00:00Z")
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")  # delivered 2026-03-01
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "CHANGE_OF_MIND", "changed mind")
    resolve_dispute(dispute["id"], "BUYER")  # sale -> RETURNED
    set_clock("2026-04-01T00:00:00Z")  # past window end (2026-03-15)
    return ctx


def test_dispute_on_returned_past_window_reports_state_error(api):
    """PRD §3.8: "Filing runs several checks in order after existence and ownership: the
    sale must be disputable — its `fulfillment_status` must be `DELIVERED` and not yet
    `RETURNED`, or the request is rejected with `ERR_SALE_NOT_DISPUTABLE` (HTTP 409); there
    must be no other dispute already in `FILED` status for the sale, or it is rejected with
    `ERR_DISPUTE_ALREADY_EXISTS` (HTTP 409); and the current logical clock must be at or
    before the sale's `return_window_ends_at`, or it is rejected with
    `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/dispute_state_beats_temporal
    """
    ctx = _setup_returned_past_window(api)
    res = api.create_dispute(create_dispute_payload(ctx["sale_id"], "AUTHENTICITY", "second attempt"),
                             make_buyer_headers(ctx["buyer_id"]))
    validate_error(res, "ERR_SALE_NOT_DISPUTABLE", expected_status=409)


def test_dispute_on_returned_past_window_persists_no_filed_dispute(api):
    """PRD §3.8: "the sale must be disputable — its `fulfillment_status` must be `DELIVERED`
    and not yet `RETURNED`, or the request is rejected with `ERR_SALE_NOT_DISPUTABLE`
    (HTTP 409);"

    Design: Difficulty/priority_pair_validation_conflict/dispute_state_beats_temporal
    """
    ctx = _setup_returned_past_window(api)
    api.create_dispute(create_dispute_payload(ctx["sale_id"], "AUTHENTICITY", "second attempt"),
                       make_buyer_headers(ctx["buyer_id"]))
    # The rejected filing created nothing; the sale stays RETURNED with no FILED dispute.
    assert get_sale(ctx["sale_id"])["fulfillment_status"] == "RETURNED"
    disputes, _meta = validate_paginated(api.list_sale_disputes(ctx["sale_id"], _ADMIN))
    assert all(d["status"] != "FILED" for d in disputes), [d["status"] for d in disputes]


# --- boundary_precision_check: filing at exactly return_window_ends_at --------
def test_dispute_at_exact_window_boundary_is_filed(api):
    """PRD §3.6: "sets `return_window_ends_at` to `delivered_at` plus the category's
    `return_window_days` (the inclusive last instant a dispute may be filed)."
    PRD §3.8: "and the current logical clock must be at or before the sale's
    `return_window_ends_at`, or it is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/dispute_window_inclusive_boundary
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS",
                               delivered_clock="2026-03-10T00:00:00Z")
    set_clock("2026-03-24T00:00:00Z")  # exactly delivered_at + 14 days
    res = api.create_dispute(create_dispute_payload(ctx["sale_id"], "CONDITION", "scuff not disclosed"),
                             make_buyer_headers(ctx["buyer_id"]))
    dispute = validate_success(res, 201)
    assert dispute["status"] == "FILED", dispute["status"]


def test_dispute_at_exact_window_boundary_reachable_via_subresource(api):
    """PRD §2.9: "The payouts and disputes belonging to a sale are retrieved as
    sub-resource lists under that sale, giving reverse reachability from a `Sale` to its
    `Payout` records (by `sale_id`) and its `Dispute` records (by `sale_id`)."
    PRD §3.8: "A successful filing creates the dispute in `FILED` status and cascades the
    sale's `SCHEDULED` payout to `HELD`, freezing the seller's money while the case is
    open."

    Design: Difficulty/boundary_precision_check/dispute_window_inclusive_boundary
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS",
                               delivered_clock="2026-03-10T00:00:00Z")
    set_clock("2026-03-24T00:00:00Z")
    file_dispute(ctx["sale_id"], ctx["buyer_id"], "CONDITION", "scuff")
    disputes, _meta = validate_paginated(api.list_sale_disputes(ctx["sale_id"], _ADMIN))
    assert len(disputes) == 1, len(disputes)
    assert disputes[0]["status"] == "FILED", disputes[0]["status"]
    assert disputes[0]["sale_id"] == ctx["sale_id"], disputes[0]["sale_id"]


# --- Corner: resolve a terminal (already-resolved) dispute -------------------
def test_resolve_already_resolved_dispute_rejected(api):
    """PRD §3.8: "An `OpsAdmin` resolves a filed dispute by supplying an `outcome`, and the
    resolution must act on a dispute in `FILED` status or it is rejected with
    `ERR_DISPUTE_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/resolve_terminal_dispute_returns_invalid_state
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "CONDITION", "minor")
    resolve_dispute(dispute["id"], "SELLER")  # -> RESOLVED_SELLER (terminal)
    from test_helpers import create_resolve_payload
    res = api.resolve_dispute(dispute["id"], create_resolve_payload("BUYER"), _ADMIN)
    validate_error(res, "ERR_DISPUTE_INVALID_STATE", expected_status=409)


# --- Corner: at most one open dispute per sale -------------------------------
def test_second_open_dispute_rejected(api):
    """PRD §3.8: "there must be no other dispute already in `FILED` status for the sale, or
    it is rejected with `ERR_DISPUTE_ALREADY_EXISTS` (HTTP 409);"

    Design: Corner/validations/second_open_dispute_returns_already_exists
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    file_dispute(ctx["sale_id"], ctx["buyer_id"], "CONDITION", "first")
    res = api.create_dispute(create_dispute_payload(ctx["sale_id"], "AUTHENTICITY", "second"),
                             make_buyer_headers(ctx["buyer_id"]))
    validate_error(res, "ERR_DISPUTE_ALREADY_EXISTS", expected_status=409)


# --- Corner: one second past the window --------------------------------------
def test_dispute_one_second_past_window_rejected(api):
    """PRD §3.8: "and the current logical clock must be at or before the sale's
    `return_window_ends_at`, or it is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`
    (HTTP 409)."

    Design: Corner/validations/dispute_one_second_past_window_returns_expired
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS",
                               delivered_clock="2026-03-10T00:00:00Z")
    set_clock("2026-03-24T00:00:01Z")  # one second past delivered_at + 14 days
    res = api.create_dispute(create_dispute_payload(ctx["sale_id"], "CONDITION", "too late"),
                             make_buyer_headers(ctx["buyer_id"]))
    validate_error(res, "ERR_DISPUTE_WINDOW_EXPIRED", expected_status=409)
