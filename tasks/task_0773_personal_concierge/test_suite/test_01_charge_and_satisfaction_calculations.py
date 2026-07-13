"""Charge, overage, priority, and satisfaction calculations.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: calculations, plus the plan-default and priority computed-field entities.
"""
from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    setup_membership,
    setup_confirmed_engagement,
    setup_time_logged,
    intake_request,
    fulfill_and_rate,
    create_vendor,
    propose_engagement,
    confirm_engagement,
    reconcile_engagement,
)

AM = TEST_USERS["account_manager_headers"]
AGENT = TEST_USERS["concierge_agent_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


# ─── Difficulty/dual_variant_calc/engagement_provisional_vs_final_charge ────
def test_engagement_final_charge_and_expense_variance(api):
    """PRD §3.6: "At confirm the lines used are the `estimated_cost_lines`, producing
    the provisional charge; at reconcile the lines used are the `actual_cost_lines`,
    producing the final charge."
    PRD §3.6: "Reconciliation sets `charge_basis` to `FINAL`, recomputes
    `client_charge_cents` from the actual lines, and creates an `Expense` (see Section 3.7)."
    PRD §3.7: "The expense snapshots the prior provisional charge as `estimated_cents`
    and the final charge as `actual_cents`, and records their difference as
    `variance_cents`, defined as the actual amount minus the estimated amount."

    Design: Difficulty/dual_variant_calc/engagement_provisional_vs_final_charge
    """
    s = setup_confirmed_engagement(vip_tier="GOLD", plan_kind="GOLD",
                                   markup_pct=0.10, estimated_cost_lines=[333, 333, 333])
    eng = reconcile_engagement(s["engagement"]["id"], [500, 500, 500])
    assert eng["charge_basis"] == "FINAL", f"expected FINAL, got {eng['charge_basis']}"
    assert eng["client_charge_cents"] == 1650, f"expected 1650, got {eng['client_charge_cents']}"

    expenses, _ = _list_expenses_for(api, eng["id"])
    assert len(expenses) == 1, f"expected one Expense, got {len(expenses)}"
    exp = expenses[0]
    assert exp["estimated_cents"] == 1098, f"expected estimated 1098, got {exp['estimated_cents']}"
    assert exp["actual_cents"] == 1650, f"expected actual 1650, got {exp['actual_cents']}"
    assert exp["variance_cents"] == 552, f"expected variance 552, got {exp['variance_cents']}"


def test_engagement_provisional_charge_differs_from_final(api):
    """PRD §3.6: "On confirmation the engagement's `charge_basis` is set to `PROVISIONAL`
    and its `client_charge_cents` is computed from the `estimated_cost_lines`; the
    membership's `outstanding_balance_cents` is recomputed to add this charge, and the
    member's `lifetime_billed_cents` follows."

    Design: Difficulty/dual_variant_calc/engagement_provisional_vs_final_charge
    """
    s = setup_confirmed_engagement(vip_tier="GOLD", plan_kind="GOLD",
                                   markup_pct=0.10, estimated_cost_lines=[333, 333, 333])
    eng = s["engagement"]
    assert eng["charge_basis"] == "PROVISIONAL", f"expected PROVISIONAL, got {eng['charge_basis']}"
    assert eng["client_charge_cents"] == 1098, f"expected provisional 1098, got {eng['client_charge_cents']}"
    # Provisional (1098) is distinct from the eventual final (1650).
    assert eng["client_charge_cents"] != 1650


# ─── Difficulty/dual_variant_calc/satisfaction_lifetime_vs_current_standing ─
def _make_membership_with_four_ratings():
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    for score in (5, 3, 2, 4):
        fulfill_and_rate(ctx, score)
    return ctx


def test_satisfaction_lifetime_average_over_all_ratings(api):
    """PRD §3.8: "The `lifetime_average` is the mean of the `score` values across all
    of the membership's ratings, rounded half up to two decimal places."
    PRD §3.8: "The `current_standing` is the mean of the scores of only the three most
    recent ratings, selected by `sequence_no` in descending order, likewise rounded half
    up to two decimal places; when a membership has three or fewer ratings, all of them
    are included."
    PRD §3.8: "The computed satisfaction summary for a membership reports
    `lifetime_average`, `current_standing`, and `rating_count` together."

    Design: Difficulty/dual_variant_calc/satisfaction_lifetime_vs_current_standing
    """
    ctx = _make_membership_with_four_ratings()
    data = validate_success(api.get_membership_satisfaction(ctx["ms_id"], AM))
    assert data["rating_count"] == 4, f"expected rating_count 4, got {data['rating_count']}"
    assert data["lifetime_average"] == 3.50, f"expected lifetime 3.50, got {data['lifetime_average']}"
    assert data["current_standing"] == 3.00, f"expected current 3.00, got {data['current_standing']}"


def test_membership_satisfaction_score_holds_current_standing(api):
    """PRD §3.8: "The membership's stored `satisfaction_score` holds the `current_standing`
    value."

    Design: Difficulty/dual_variant_calc/satisfaction_lifetime_vs_current_standing
    """
    ctx = _make_membership_with_four_ratings()
    ms = validate_success(api.get_membership(ctx["ms_id"], AM))
    assert ms["satisfaction_score"] == 3.00, f"expected satisfaction_score 3.00, got {ms['satisfaction_score']}"


# ─── Difficulty/combinatorial_formula/overage_tiered_nonlinear_charge ───────
def test_overage_charge_gold_tier_nonlinear(api):
    """PRD §3.5: "The overage minutes are the consumed minutes minus the cycle's
    `included_minutes`, floored at zero, so that consuming exactly the included allotment
    yields zero overage while consuming one minute beyond it yields the first overage minute."
    PRD §3.5: "The base `overage_rate_cents_per_hour` is adjusted for the membership tier
    by a multiplier — 1.00 for `STANDARD`, 0.95 for `SILVER`, 0.90 for `GOLD`, and 0.85 for
    `PLATINUM` — and the product is rounded half up to a whole-cent effective rate per hour."
    PRD §3.5: "The `overage_charge_cents` is then the overage minutes multiplied by that
    effective per-hour rate, divided by 60, with the result taken as the ceiling to a whole cent."

    Design: Difficulty/combinatorial_formula/overage_tiered_nonlinear_charge
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=700)
    cycle = validate_success(api.get_billing_cycle(s["cycle_id"], AM))
    assert cycle["consumed_minutes"] == 700, f"expected 700, got {cycle['consumed_minutes']}"
    assert cycle["overage_minutes"] == 100, f"expected 100, got {cycle['overage_minutes']}"
    # effective rate = round_half_up(8000 * 0.90) = 7200; ceil(100*7200/60) = 12000
    assert cycle["overage_charge_cents"] == 12000, f"expected 12000, got {cycle['overage_charge_cents']}"


def test_overage_exhausts_hour_bank(api):
    """PRD §3.2: "The membership's `hour_bank_remaining_minutes` reflects the current
    `OPEN` cycle: it is the cycle's `included_minutes` minus its `consumed_minutes`, never
    below zero."

    Design: Difficulty/combinatorial_formula/overage_tiered_nonlinear_charge
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=700)
    ms = validate_success(api.get_membership(s["ctx"]["ms_id"], AM))
    assert ms["hour_bank_remaining_minutes"] == 0, f"expected 0, got {ms['hour_bank_remaining_minutes']}"


# ─── Difficulty/combinatorial_formula/engagement_markup_rounding_order ──────
def test_markup_charge_rounds_per_line(api):
    """PRD §3.6: "Under `MARKUP`, each individual line is multiplied by one plus the
    `markup_pct`, that per-line product is rounded half up to whole cents, and only then
    are the rounded lines summed to the total — the rounding is applied per line before
    summing, never to a single combined total."

    Design: Difficulty/combinatorial_formula/engagement_markup_rounding_order
    """
    s = setup_confirmed_engagement(vip_tier="STANDARD", plan_kind="STD",
                                   markup_pct=0.10, estimated_cost_lines=[333, 333, 333])
    eng = s["engagement"]
    # 333*1.10 = 366.3 -> 366 per line; 366*3 = 1098
    assert eng["client_charge_cents"] == 1098, f"expected 1098, got {eng['client_charge_cents']}"
    assert eng["charge_basis"] == "PROVISIONAL", f"expected PROVISIONAL, got {eng['charge_basis']}"


def test_markup_charge_is_not_sum_then_round(api):
    """PRD §3.6: "Under `MARKUP`, each individual line is multiplied by one plus the
    `markup_pct`, that per-line product is rounded half up to whole cents, and only then
    are the rounded lines summed to the total — the rounding is applied per line before
    summing, never to a single combined total."

    Design: Difficulty/combinatorial_formula/engagement_markup_rounding_order
    """
    s = setup_confirmed_engagement(vip_tier="STANDARD", plan_kind="STD",
                                   markup_pct=0.10, estimated_cost_lines=[333, 333, 333])
    # sum-then-round would give round(999*1.10) = round(1098.9) = 1099; per-line gives 1098.
    assert s["engagement"]["client_charge_cents"] != 1099, "must round per line, not sum-then-round"


# ─── Corner/calculations/passthrough_charge_has_no_markup ───────────────────
def test_passthrough_charge_is_plain_sum(api):
    """PRD §3.6: "Under `PASS_THROUGH`, the charge is simply the sum of the relevant cost
    lines, since those lines were already capped at creation."

    Design: Corner/calculations/passthrough_charge_has_no_markup
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = intake_request(ctx, category="BOOKING", title="r")
    eng = propose_engagement(sr["id"], vendor["id"], "PASS_THROUGH", [1000, 2000],
                             "2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z")
    eng = confirm_engagement(eng["id"])
    assert eng["client_charge_cents"] == 3000, f"expected 3000, got {eng['client_charge_cents']}"
    assert eng["charge_basis"] == "PROVISIONAL", f"expected PROVISIONAL, got {eng['charge_basis']}"


# ─── Corner/calculations/outstanding_excludes_proposed_engagement ───────────
def test_proposed_engagement_excluded_from_outstanding(api):
    """PRD §3.6: "The membership's `outstanding_balance_cents` is the sum of two
    components: the total of `overage_charge_cents` across all of the membership's billing
    cycles, both `OPEN` and `CLOSED`, plus the total of `client_charge_cents` across the
    membership's engagements that are in `CONFIRMED` or `RECONCILED` status. Engagements in
    `PROPOSED` or `VOID` status contribute nothing to this balance."

    Design: Corner/calculations/outstanding_excludes_proposed_engagement
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = intake_request(ctx, category="BOOKING", title="r")
    propose_engagement(sr["id"], vendor["id"], "MARKUP", [1000],
                       "2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z", markup_pct=0.10)
    ms = validate_success(api.get_membership(ctx["ms_id"], AM))
    assert ms["outstanding_balance_cents"] == 0, f"expected 0, got {ms['outstanding_balance_cents']}"


# ─── Corner/entities/request_priority_score_computed ────────────────────────
def test_priority_score_gold_rush_travel(api):
    """PRD §3.3: "The tier weight is 1 for `STANDARD`, 2 for `SILVER`, 3 for `GOLD`, and 5
    for `PLATINUM`."
    PRD §3.3: "The category weight is 0 for `ERRAND`, 1 for `BOOKING`, 2 for `GIFT`, and 3
    for `TRAVEL`."
    PRD §3.3: "The rush bonus adds 2 when `rush` is true and 0 otherwise."

    Design: Corner/entities/request_priority_score_computed
    """
    ctx = setup_membership(vip_tier="GOLD", plan_kind="GOLD")
    sr = intake_request(ctx, category="TRAVEL", title="flight", rush=True)
    # GOLD(3) + TRAVEL(3) + rush(2) = 8
    assert sr["priority_score"] == 8, f"expected 8, got {sr['priority_score']}"


# ─── Corner/entities/retainer_plan_default_markup_applied ───────────────────
def test_plan_default_markup_pct_defaults_to_015(api):
    """PRD §3.1: "a `default_markup_pct` default vendor markup fraction (for example, 0.15
    denotes fifteen percent) that must be at least zero and defaults to 0.15 when omitted."

    Design: Corner/entities/retainer_plan_default_markup_applied
    """
    resp = api.create_retainer_plan({
        "name": "Base", "monthly_retainer_cents": 100000, "included_hours": 5,
        "overage_rate_cents_per_hour": 6000, "max_pass_through_cents": 40000,
    }, AM)
    plan = validate_success(resp, expected_status=201)
    assert plan["default_markup_pct"] == 0.15, f"expected 0.15, got {plan['default_markup_pct']}"


# ---- local helper ----
def _list_expenses_for(api, engagement_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_expenses(FINANCE, params={"vendor_engagement_id": engagement_id}))
