"""Fit feedback captured at checkout drives learned sizing (decay-weighted for tops
and bottoms, latest-only for shoes) and fit confidence.
"""
from test_helpers import (
    validate_success,
    TEST_USERS, make_client_headers,
    setup_delivered_fix, setup_learned_sizing_two_tops, get_style_profile,
)

OPS = TEST_USERS["ops_headers"]


def _checkout(api, fix_id, client_id, kept_item_ids, item_feedback=None):
    payload = {"kept_item_ids": kept_item_ids}
    if item_feedback is not None:
        payload["item_feedback"] = item_feedback
    return api.checkout_fix(fix_id, payload, headers=make_client_headers(client_id))


# ------------------- Difficulty: weighted (top) vs latest (shoe) learned sizing
def test_two_top_feedbacks_produce_decay_weighted_size(api):
    """PRD §3.8: "For the top and bottom categories, the learned size uses the
    decay-weighted mean over the full feedback history of that category: multiply each
    row's implied ideal by its rank weight, sum those products, divide by the sum of
    the weights, and round the result half up to an integer, stored as learned_top_size
    and learned_bottom_size respectively."

    Design: Difficulty/dual_variant_calc/learned_sizing_weighted_vs_latest_diverge
    """
    ctx = setup_learned_sizing_two_tops()
    _checkout(api, ctx["fix2_id"], ctx["client_id"], [ctx["fix2_kept_item_id"]],
              item_feedback=[{"fix_item_id": ctx["fix2_kept_item_id"], "rating": "TOO_SMALL"}])
    profile = get_style_profile(ctx["client_id"])
    # rank0 = newer size8 TOO_SMALL (implied 9) weight 1; rank1 = older size12 PERFECT
    # (implied 12) weight 0.5 → (9 + 6)/1.5 = 10
    assert profile["learned_top_size"] == 10


def test_learned_sizing_feedback_count_reflects_history(api):
    """PRD §3.8: "After the feedback rows are created, the owning client's StyleProfile
    is recomputed: its learned_top_size, learned_bottom_size, and learned_shoe_size,
    then its fit_confidence, and its feedback_count (the number of feedback rows for
    that client)."

    Design: Difficulty/dual_variant_calc/learned_sizing_weighted_vs_latest_diverge
    """
    ctx = setup_learned_sizing_two_tops()
    _checkout(api, ctx["fix2_id"], ctx["client_id"], [ctx["fix2_kept_item_id"]],
              item_feedback=[{"fix_item_id": ctx["fix2_kept_item_id"], "rating": "TOO_SMALL"}])
    profile = get_style_profile(ctx["client_id"])
    assert profile["feedback_count"] == 2


# ------------------- Difficulty: checkout feedback cascades into learned sizing
def test_checkout_feedback_creates_feedback_row(api):
    """PRD §3.8: "For each entry in the checkout's item_feedback, the system creates a
    FeedbackEntry for the owning client: it records the client_id, the fix_item_id of
    the rated item, a product_size snapshot of that item's size at feedback time, the
    item's category, and the subscriber's rating"

    Design: Difficulty/transitive_cascade/checkout_feedback_updates_style_profile
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")  # item[0] TOP size 8
    top_item = ctx["item_ids"][0]
    validate_success(
        _checkout(api, ctx["fix_id"], ctx["client_id"], [top_item],
                  item_feedback=[{"fix_item_id": top_item, "rating": "TOO_SMALL"}]),
        200,
    )
    profile = get_style_profile(ctx["client_id"])
    assert profile["feedback_count"] == 1


def test_checkout_feedback_recomputes_learned_top_size(api):
    """PRD §3.8: "For a single feedback row, the implied ideal size is the row's
    product_size adjusted by its rating: add 1 for TOO_SMALL, add one-half for
    SLIGHTLY_SMALL, add nothing for PERFECT, subtract one-half for SLIGHTLY_LARGE, and
    subtract 1 for TOO_LARGE."

    Design: Difficulty/transitive_cascade/checkout_feedback_updates_style_profile
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")  # item[0] TOP size 8
    top_item = ctx["item_ids"][0]
    validate_success(
        _checkout(api, ctx["fix_id"], ctx["client_id"], [top_item],
                  item_feedback=[{"fix_item_id": top_item, "rating": "TOO_SMALL"}]),
        200,
    )
    profile = get_style_profile(ctx["client_id"])
    assert profile["learned_top_size"] == 9  # 8 + 1 (TOO_SMALL), rounded


# ------------------------------------------------- Corner: fit confidence formula
def test_single_perfect_feedback_yields_full_confidence(api):
    """PRD §3.8: "Confidence is computed over all of the client's feedback rows,
    regardless of category. Each rating contributes a match value: 1 for PERFECT,
    six-tenths for either SLIGHTLY_SMALL or SLIGHTLY_LARGE, and 0 for either TOO_SMALL
    or TOO_LARGE. The fit_confidence is 100 times the sum of the match values divided
    by the number of feedback rows, rounded half up to an integer between 0 and 100"

    Design: Corner/calculations/fit_confidence_computed_from_feedback
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")  # item[0] TOP
    top_item = ctx["item_ids"][0]
    validate_success(
        _checkout(api, ctx["fix_id"], ctx["client_id"], [top_item],
                  item_feedback=[{"fix_item_id": top_item, "rating": "PERFECT"}]),
        200,
    )
    profile = get_style_profile(ctx["client_id"])
    assert profile["fit_confidence"] == 100
    assert profile["feedback_count"] == 1
