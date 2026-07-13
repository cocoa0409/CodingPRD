"""Readiness score (weighted, tier-conditional) and subscription refund variants."""
from test_helpers import (
    validate_success,
    make_owner_headers, ADMIN_HEADERS,
    setup_plus_plan_completeness_66, set_clock, create_plan,
    create_subscription,
)


# --------------------------------------------------------------------------- #
# plan_completeness_weighted_tiered_score  (Difficulty/combinatorial_formula)
# --------------------------------------------------------------------------- #
def test_completeness_pct_plus_tier_weighted_score_is_66(api):
    """PRD 3.1: "The raw score is the sum of each weight multiplied by its normalized
    signal, and `completeness_pct` is that raw score rounded half up to the nearest
    integer."
    PRD 3.1: "for every other tier (and when there is no subscription) they are 40, 20,
    20, and 20."

    Design: Difficulty/combinatorial_formula/plan_completeness_weighted_tiered_score
    """
    ctx = setup_plus_plan_completeness_66(api)
    resp = api.get_plan_completeness(ctx["plan_id"], make_owner_headers(ctx["plan_id"]))
    data = validate_success(resp, 200)
    assert data["completeness_pct"] == 66, f"expected 66, got {data['completeness_pct']}"


def test_completeness_pct_recomputed_on_plan_read(api):
    """PRD 3.1: "A plan continuously exposes a readiness score, `completeness_pct`, an
    integer from 0 to 100 recomputed each time the plan (or its dedicated completeness
    read) is fetched, alongside the recomputed `seats_used` and `seats_available`."

    Design: Difficulty/combinatorial_formula/plan_completeness_weighted_tiered_score
    """
    ctx = setup_plus_plan_completeness_66(api)
    resp = api.get_plan(ctx["plan_id"], make_owner_headers(ctx["plan_id"]))
    data = validate_success(resp, 200)
    assert data["completeness_pct"] == 66, f"expected 66 on plan read, got {data['completeness_pct']}"


# --------------------------------------------------------------------------- #
# subscription_refund_prorata_variant_on_subscription  (Difficulty/dual_variant_calc)
# --------------------------------------------------------------------------- #
def _plus_prorata_sub_20_days_remaining(api):
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    sub = create_subscription(api, plan_id, tier="PLUS", refund_policy="IMMEDIATE_PRORATA")
    set_clock(api, "2026-06-11T00:00:00Z")
    return plan_id, sub["id"]


def test_prorata_refund_returns_unused_period_cents(api):
    """PRD 3.7: "Under `IMMEDIATE_PRORATA`, the refund returns the unused portion of the
    current 30-day period by whole remaining days: the remaining days are the floor of the
    number of whole days between the current clock and `period_end`, never below zero, and
    the refund is the `monthly_fee_cents` multiplied by those remaining days divided by 30,
    rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/subscription_refund_prorata_variant_on_subscription
    """
    plan_id, sub_id = _plus_prorata_sub_20_days_remaining(api)
    resp = api.cancel_subscription(sub_id, make_owner_headers(plan_id))
    data = validate_success(resp, 200)
    # PLUS monthly_fee_cents 1200, 20 whole days remaining: round_half_up(1200*20/30) = 800.
    assert data["last_refund_cents"] == 800, f"expected 800, got {data['last_refund_cents']}"


def test_prorata_cancel_moves_subscription_to_canceled(api):
    """PRD 3.7: "The lifecycle is `TRIALING | PAST_DUE → ACTIVE`, `ACTIVE → PAST_DUE`, and
    any of `TRIALING`, `ACTIVE`, or `PAST_DUE` to the terminal `CANCELED`."

    Design: Difficulty/dual_variant_calc/subscription_refund_prorata_variant_on_subscription
    """
    plan_id, sub_id = _plus_prorata_sub_20_days_remaining(api)
    resp = api.cancel_subscription(sub_id, make_owner_headers(plan_id))
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELED", f"expected CANCELED, got {data['status']}"


# --------------------------------------------------------------------------- #
# subscription_refund_forfeit_variant_zero  (Corner/calculations)
# --------------------------------------------------------------------------- #
def test_forfeit_refund_is_zero(api):
    """PRD 3.7: "Under `FORFEIT`, the refund is zero and access simply continues until
    `period_end`."

    Design: Corner/calculations/subscription_refund_forfeit_variant_zero
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    sub = create_subscription(api, plan_id, tier="PLUS", refund_policy="FORFEIT")
    set_clock(api, "2026-06-11T00:00:00Z")
    resp = api.cancel_subscription(sub["id"], make_owner_headers(plan_id))
    data = validate_success(resp, 200)
    assert data["last_refund_cents"] == 0, f"expected 0, got {data['last_refund_cents']}"
