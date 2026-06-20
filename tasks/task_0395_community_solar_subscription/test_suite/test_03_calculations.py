"""Calculations: bill-credit dual variant, churn-risk snapshot, tiered fee,
true-up overproduction, REC minting floor, and the allocation waterfall.

Translates queue A (Difficulty) rules `dual_variant_calc`, `combinatorial_formula`,
`boundary_precision_check`, and queue B (Corner) `calculations` section instances.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_subscriber_headers,
    factories as f,
    fixtures as fx,
)

GO = TEST_USERS["grid_operator_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── Queue A: dual_variant_calc ───────────────────────────────────────

def test_bill_credit_provisional_vs_final_diverge_on_same_allocation(api):
    """PRD §3.8: "At period `OPEN`, on the forecast basis, the allocation's
    `provisional_credit_cents` is its forecast-basis `allocated_kwh` multiplied by the
    project's `credit_rate_cents_per_kwh`."
    PRD §3.8: "The `final_credit_cents` is populated only later, at reconciliation, as
    the metered-basis `allocated_kwh` multiplied by the same `credit_rate_cents_per_kwh`;
    until then it is empty."

    Design: Difficulty/dual_variant_calc/bill_credit_provisional_vs_final_allocation_domain
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription(
        project_overrides={"name": "Garden A", "program_fee_rate": 0.10},
        requested_share_kw=5.0,
    )
    period = fx.create_open_period(project["id"], "2026-01", 1200)
    alloc_before = fx.first_allocation(period["id"])
    assert alloc_before["provisional_credit_cents"] == 12000  # forecast 1200 * 10
    metered = fx.meter_period(period["id"], 1000, period["version"])
    fx.reconcile_period(period["id"], metered["version"])
    alloc_after = fx.first_allocation(period["id"])
    assert alloc_after["final_credit_cents"] == 10000  # metered 1000 * 10


def test_bill_credit_final_minus_provisional_delta(api):
    """PRD §3.8: "At period `OPEN`, on the forecast basis, the allocation's
    `provisional_credit_cents` is its forecast-basis `allocated_kwh` multiplied by the
    project's `credit_rate_cents_per_kwh`."
    PRD §3.8: "The `final_credit_cents` is populated only later, at reconciliation, as
    the metered-basis `allocated_kwh` multiplied by the same `credit_rate_cents_per_kwh`;
    until then it is empty."

    Design: Difficulty/dual_variant_calc/bill_credit_provisional_vs_final_allocation_domain
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription(
        project_overrides={"name": "Garden A2", "program_fee_rate": 0.10},
        requested_share_kw=5.0,
    )
    period = fx.create_open_period(project["id"], "2026-01", 1200)
    alloc_before = fx.first_allocation(period["id"])
    metered = fx.meter_period(period["id"], 1000, period["version"])
    fx.reconcile_period(period["id"], metered["version"])
    alloc_after = fx.first_allocation(period["id"])
    delta = alloc_after["final_credit_cents"] - alloc_before["provisional_credit_cents"]
    assert delta == -2000


def test_churn_risk_snapshot_suspended_plus_low_income(api):
    """PRD §3.2: "it starts at zero, adds 40 if the subscriber has any subscription
    currently in `SUSPENDED`, adds 35 if the subscriber has any reconciliation whose
    dispute dimension is currently `DISPUTED`, and adds 10 if the subscriber's
    `is_low_income` is true; the running total is then capped so it never exceeds 100."

    Design: Difficulty/dual_variant_calc/churn_risk_snapshot_vs_trailing_subscriber_domain
    """
    project = fx.create_project(name="Garden B")
    subscriber = fx.create_subscriber(full_name="Low Inc", utility_account_no="ACC-2",
                                      is_low_income=True)
    subscription = fx.create_active_subscription(project["id"], subscriber["id"], 5.0)
    get_success_data(api.suspend_subscription(subscription["id"], PA))
    sub = fx.get_subscriber(subscriber["id"])
    assert sub["churn_risk_score"] == 50  # W_SUSPENDED 40 + W_LOW_INCOME 10


def test_churn_risk_snapshot_score_on_subscriber_entity(api):
    """PRD §3.2: "The `churn_risk_score` is a weighted integer from 0 to 100 capturing
    how likely a subscriber is to leave the program."
    PRD §3.2: "it starts at zero, adds 40 if the subscriber has any subscription
    currently in `SUSPENDED`, adds 35 if the subscriber has any reconciliation whose
    dispute dimension is currently `DISPUTED`, and adds 10 if the subscriber's
    `is_low_income` is true; the running total is then capped so it never exceeds 100."

    Design: Difficulty/dual_variant_calc/churn_risk_snapshot_vs_trailing_subscriber_domain
    """
    project = fx.create_project(name="Garden B2")
    subscriber = fx.create_subscriber(full_name="Low Inc 2", utility_account_no="ACC-2b",
                                      is_low_income=True)
    subscription = fx.create_active_subscription(project["id"], subscriber["id"], 5.0)
    get_success_data(api.suspend_subscription(subscription["id"], PA))
    # The score is a field on the Subscriber resource (distinct from any Allocation).
    sub = validate_success(api.get_subscriber(subscriber["id"], PA), 200)
    assert "churn_risk_score" in sub
    assert sub["churn_risk_score"] == 50


# ─── Queue A: combinatorial_formula ───────────────────────────────────

def test_tiered_program_fee_tier2_non_carve_out(api):
    """PRD §3.10: "A tier multiplier is then selected from the gross: when the gross is
    at most 5000 cents the multiplier is 1.00; when the gross is above 5000 cents and at
    most 20000 cents the multiplier is 0.90 (a volume discount); and when the gross is
    above 20000 cents the multiplier is 0.80."
    PRD §3.10: "The `program_fee_cents` is the gross multiplied by the base rate
    multiplied by the tier multiplier, with a single round-half-up applied at the end to
    whole cents. The `net_savings_cents` is the `gross_credit_cents` minus the
    `program_fee_cents` — the on-bill savings."

    Design: Difficulty/combinatorial_formula/tiered_program_fee_mode_a_multi_input_nonlinear
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-02", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden C", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    assert recon["gross_credit_cents"] == 10000
    assert recon["program_fee_cents"] == 900  # round(10000 * 0.10 * 0.90)
    assert recon["net_savings_cents"] == 9100


def test_tiered_program_fee_net_savings_subtraction(api):
    """PRD §3.10: "Each reconciliation's `gross_credit_cents` is the
    `final_credit_cents` of its linked allocation at reconciliation time."
    PRD §3.10: "The `net_savings_cents` is the `gross_credit_cents` minus the
    `program_fee_cents` — the on-bill savings."

    Design: Difficulty/combinatorial_formula/tiered_program_fee_mode_a_multi_input_nonlinear
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-02", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden C2", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    # gross 10000, fee 900 (TIER2 m=0.90, base 0.10) → net = gross - fee.
    assert recon["net_savings_cents"] == recon["gross_credit_cents"] - recon["program_fee_cents"]
    assert recon["net_savings_cents"] == 9100


def test_trueup_overproduction_pinned_eval_order(api):
    """PRD §3.12: "First the cap is computed as the smaller of a fixed ceiling of 2000
    kWh and the ceiling of the project's `committed_kw` multiplied by 50 kWh per kW.
    Second, the `rollover_kwh` is the smaller of the period's `overproduction_kwh` and
    that cap. Third, the `forfeited_kwh` is the `overproduction_kwh` minus the
    `rollover_kwh`. Fourth, the `rollover_credit_cents` is the `rollover_kwh` multiplied
    by the project's `credit_rate_cents_per_kwh`."

    Design: Difficulty/combinatorial_formula/trueup_overproduction_mode_c_pinned_eval_order
    """
    project, subscriber, subscription, reconciled = fx.setup_overproduction_period(
        project_overrides={"name": "Garden D"},
        requested_share_kw=10.0, period_month="2026-03", metered_production_kwh=10000,
    )
    trued = get_success_data(api.true_up_period(reconciled["id"], GO))
    assert trued["overproduction_kwh"] == 10000
    assert trued["rollover_kwh"] == 500   # cap = min(2000, ceil(10*50)) = 500
    assert trued["forfeited_kwh"] == 9500
    assert trued["rollover_credit_cents"] == 5000  # 500 * 10


def test_trueup_overproduction_full_pool_unallocated(api):
    """PRD §3.7: "If the sum of `share_kw` across eligible subscriptions is zero, every
    allocation's `allocated_kwh` is zero and the entire pool becomes the period's
    overproduction."
    PRD §3.12: "Second, the `rollover_kwh` is the smaller of the period's
    `overproduction_kwh` and that cap. Third, the `forfeited_kwh` is the
    `overproduction_kwh` minus the `rollover_kwh`. Fourth, the `rollover_credit_cents`
    is the `rollover_kwh` multiplied by the project's `credit_rate_cents_per_kwh`."

    Design: Difficulty/combinatorial_formula/trueup_overproduction_mode_c_pinned_eval_order
    """
    project, subscriber, subscription, reconciled = fx.setup_overproduction_period(
        project_overrides={"name": "Garden D2"},
        requested_share_kw=10.0, period_month="2026-03", metered_production_kwh=10000,
    )
    trued = get_success_data(api.true_up_period(reconciled["id"], GO))
    # forfeited = overproduction - rollover = 10000 - 500.
    assert trued["forfeited_kwh"] == trued["overproduction_kwh"] - trued["rollover_kwh"]
    assert trued["rollover_credit_cents"] == trued["rollover_kwh"] * 10


# ─── Queue A: boundary_precision_check ────────────────────────────────

def test_tier_boundary_gross_exactly_5000_uses_tier1(api):
    """PRD §3.10: "A tier multiplier is then selected from the gross: when the gross is
    at most 5000 cents the multiplier is 1.00; when the gross is above 5000 cents and at
    most 20000 cents the multiplier is 0.90 (a volume discount); and when the gross is
    above 20000 cents the multiplier is 0.80."

    Design: Difficulty/boundary_precision_check/tier_boundary_gross_5000_vs_5001_on_reconcile
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-06", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden K", "credit_rate_cents_per_kwh": 5,
                           "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    assert recon["gross_credit_cents"] == 5000  # exactly TIER1 boundary
    assert recon["program_fee_cents"] == 500    # TIER1 m=1.00: round(5000*0.10*1.00)


def test_tier_boundary_gross_5001_crosses_into_tier2(api):
    """PRD §3.10: "A tier multiplier is then selected from the gross: when the gross is
    at most 5000 cents the multiplier is 1.00; when the gross is above 5000 cents and at
    most 20000 cents the multiplier is 0.90 (a volume discount); and when the gross is
    above 20000 cents the multiplier is 0.80."

    Design: Difficulty/boundary_precision_check/tier_boundary_gross_5000_vs_5001_on_reconcile
    """
    # gross 5001 = metered 5001 kWh * credit_rate 1; share 50, annual usage high.
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-06", forecast_production_kwh=5001, metered_production_kwh=5001,
        requested_share_kw=50.0,
        project_overrides={"name": "Garden K2", "credit_rate_cents_per_kwh": 1,
                           "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    assert recon["gross_credit_cents"] == 5001  # just above TIER1 boundary
    assert recon["program_fee_cents"] == 450    # TIER2 m=0.90: round(5001*0.10*0.90)=round(450.09)


def test_rec_mint_zero_floor_under_1000_kwh(api):
    """PRD §3.10: "in status `MINTED`, whose `rec_count` is the floor of the period's
    `metered_production_kwh` divided by 1000 (one REC per 1000 metered kWh)."

    Design: Difficulty/boundary_precision_check/rec_mint_zero_floor_under_1000_kwh_metered
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-07", forecast_production_kwh=999, metered_production_kwh=999,
        project_overrides={"name": "Garden L"},
    )
    batch = fx.first_rec_batch(reconciled["id"])
    assert batch["rec_count"] == 0  # floor(999/1000)
    proj = fx.get_project(project["id"])
    assert proj["rec_minted_total"] == 0


def test_rec_mint_one_at_exactly_1000_kwh(api):
    """PRD §3.10: "in status `MINTED`, whose `rec_count` is the floor of the period's
    `metered_production_kwh` divided by 1000 (one REC per 1000 metered kWh)."
    PRD §3.10: "The period's own `rec_minted_count` records the same floor."

    Design: Difficulty/boundary_precision_check/rec_mint_zero_floor_under_1000_kwh_metered
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-07", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden L2"},
    )
    batch = fx.first_rec_batch(reconciled["id"])
    assert batch["rec_count"] == 1  # floor(1000/1000)
    proj = fx.get_project(project["id"])
    assert proj["rec_minted_total"] == 1


# ─── Queue B: calculations section ────────────────────────────────────

def test_waterfall_remainder_distribution_fractional_then_created_at(api):
    """PRD §3.7: "fourth, hand out the leftover one kWh at a time to eligible
    subscriptions ordered by descending fractional part of their raw amount, breaking
    ties by ascending subscription `created_at`. Each subscription's `allocated_kwh` is
    its floor plus one if it received a remainder kWh."

    Design: Corner/calculations/waterfall_remainder_distribution_fractional_then_created_at
    """
    project = fx.create_project(name="P15")
    sub_a = fx.create_subscriber(full_name="Wf A", utility_account_no="ACC-C12")
    sub_b = fx.create_subscriber(full_name="Wf B", utility_account_no="ACC-C13")
    subscription_a = fx.create_active_subscription(project["id"], sub_a["id"], 5.0)
    subscription_b = fx.create_active_subscription(project["id"], sub_b["id"], 5.0)
    period = fx.create_open_period(project["id"], "2026-05", 10001)
    a_allocs = get_success_data(
        api.list_allocations(GO, params={"subscription_id": subscription_a["id"]})
    )
    b_allocs = get_success_data(
        api.list_allocations(GO, params={"subscription_id": subscription_b["id"]})
    )
    assert a_allocs[0]["allocated_kwh"] == 5001, "earlier-created A wins the .5 tie"
    assert b_allocs[0]["allocated_kwh"] == 5000


def test_waterfall_input_set_excludes_suspended_subscriptions(api):
    """PRD §3.7: "Subscriptions in `SUSPENDED` are excluded and earn nothing while
    suspended."
    PRD §3.7: "A subscription is **eligible** for a period if its status is `ACTIVE` and
    either it has no `cancellation_effective_period_id` or the period named by its
    `cancellation_effective_period_id` has a `sequence_index` strictly greater than this
    period's `sequence_index`."

    Design: Corner/calculations/waterfall_input_set_excludes_suspended_subscriptions
    """
    project = fx.create_project(name="P16")
    sub_s = fx.create_subscriber(full_name="Sus", utility_account_no="ACC-C14")
    sub_a = fx.create_subscriber(full_name="Act", utility_account_no="ACC-C15")
    subscription_s = fx.create_active_subscription(project["id"], sub_s["id"], 5.0)
    get_success_data(api.suspend_subscription(subscription_s["id"], PA))
    subscription_a = fx.create_active_subscription(project["id"], sub_a["id"], 5.0)
    period = fx.create_open_period(project["id"], "2026-06", 1000)
    a_allocs = get_success_data(
        api.list_allocations(GO, params={"subscription_id": subscription_a["id"]})
    )
    s_allocs = get_success_data(
        api.list_allocations(GO, params={"subscription_id": subscription_s["id"]})
    )
    assert a_allocs[0]["allocated_kwh"] == 1000, "ACTIVE sub gets the entire pool"
    assert len(s_allocs) == 0, "no allocation created for SUSPENDED subscription"


def test_trueup_cap_binds_at_rollover_cap_kwh_constant(api):
    """PRD §3.12: "First the cap is computed as the smaller of a fixed ceiling of 2000
    kWh and the ceiling of the project's `committed_kw` multiplied by 50 kWh per kW.
    Second, the `rollover_kwh` is the smaller of the period's `overproduction_kwh` and
    that cap. Third, the `forfeited_kwh` is the `overproduction_kwh` minus the
    `rollover_kwh`."

    Design: Corner/calculations/trueup_cap_binds_at_rollover_cap_kwh_constant
    """
    project, subscriber, subscription, reconciled = fx.setup_overproduction_period(
        project_overrides={"name": "P17"},
        requested_share_kw=50.0, period_month="2026-07", metered_production_kwh=10000,
    )
    trued = get_success_data(api.true_up_period(reconciled["id"], GO))
    # committed_kw 50 → ceil(50*50)=2500; cap = min(2000, 2500) = 2000.
    assert trued["rollover_kwh"] == 2000
    assert trued["forfeited_kwh"] == 8000


def test_carve_out_fee_variant_selected_for_carve_out_subscription(api):
    """PRD §3.10: "The base rate is the carve-out fee rate of 0.05 when the
    subscription's `is_carve_out` is true, and otherwise the project's
    `program_fee_rate`."
    PRD §3.10: "The `program_fee_cents` is the gross multiplied by the base rate
    multiplied by the tier multiplier, with a single round-half-up applied at the end to
    whole cents. The `net_savings_cents` is the `gross_credit_cents` minus the
    `program_fee_cents` — the on-bill savings."

    Design: Corner/calculations/carve_out_fee_variant_selected_for_carve_out_subscription
    """
    project = fx.create_project(name="P18", carve_out_pct=0.40, program_fee_rate=0.10)
    subscriber = fx.create_subscriber(full_name="CO Sub", utility_account_no="ACC-C17",
                                      is_low_income=True)
    subscription = fx.create_active_subscription(project["id"], subscriber["id"], 5.0)
    period = fx.create_open_period(project["id"], "2026-08", 1000)
    metered = fx.meter_period(period["id"], 1000, period["version"])
    fx.reconcile_period(period["id"], metered["version"])
    recon = fx.first_reconciliation(period["id"])
    assert recon["program_fee_cents"] == 450  # round(10000 * 0.05 * 0.90)
    assert recon["net_savings_cents"] == 9550
