"""Money math: overage tiers, EIP schedule, group-discount table, proration
rounding, and usage aggregation.

Translates difficulty queue (A) combinatorial_formula, dual_variant_calc, and
boundary_precision_check instances, plus corner queue (B) calculations instances.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_installment_plan_payload,
    setup_account_plan, setup_active_line_on_open_cycle, setup_n_active_lines,
    provision_and_activate_line, ingest_data_usage, set_clock,
    create_billing_cycle, create_device, current_account_version,
    create_line_payload,
)
import test_helpers as H

CA = TEST_USERS["carrier_agent_headers"]
BS = TEST_USERS["billing_system_headers"]


# ─── Queue A: combinatorial_formula ───────────────────────────────────────

def test_overage_tier_straddle_28000mb(api):
    """PRD §3.10: "The tier-1 megabytes is the lesser of the total overage and
    the plan's `overage_tier1_cap_mb`; the tier-2 megabytes is the remainder of
    the overage beyond that cap, floored at zero. The raw milli-cent total is the
    tier-1 megabytes multiplied by `overage_tier1_rate_milli_cents` plus the
    tier-2 megabytes multiplied by `overage_tier2_rate_milli_cents`. That
    milli-cent total is divided by one thousand and rounded half-up to whole
    cents to give the overage in cents."

    Design: Difficulty/combinatorial_formula/per_line_bill_nonlinear_overage_tier_and_discount_mode_a
    """
    account, plan, line, cycle = setup_active_line_on_open_cycle(sim_type="ESIM")
    ingest_data_usage(line["id"], 28000, "2026-06-15T01:00:00Z")

    summary = validate_success(api.get_usage_summary(line["id"], CA), 200)
    assert summary["cycle_data_used_mb"] == 28000
    # over=7520; tier1=5120 @1000mc + tier2=2400 @500mc = 6,320,000 mc -> 6320 c
    assert summary["overage_cents"] == 6320


def test_plan_base_subtotal_round_per_line_then_sum(api):
    """PRD §3.10: "with a `monthly_fee_cents` of 6995 across three lines at a
    0.10 discount, each line's discounted base is 6296 (because 6295.5 rounds
    half-up), so the base subtotal across the three lines is 18888 — not the
    18887 that a sum-then-round order would have produced."

    Design: Difficulty/combinatorial_formula/account_base_subtotal_round_per_line_then_sum_mode_b
    """
    account = H.create_account()
    plan = H.create_plan(monthly_fee_cents=6995)
    set_clock("2026-06-01T00:00:00Z")
    cycle = create_billing_cycle(account["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    for _ in range(3):
        provision_and_activate_line(account["id"], plan["id"], sim_type="ESIM")
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api.close_billing_cycle(cycle["id"], BS), 200)

    charges = validate_success(
        api.list_charges(BS, params={"billing_cycle_id": cycle["id"], "charge_type": "PLAN_BASE"}),
        200)
    subtotal = sum(c["amount_cents"] for c in charges)
    assert subtotal == 18888, f"round-per-line-then-sum subtotal must be 18888, got {subtotal}"


# ─── Queue A: dual_variant_calc ───────────────────────────────────────────

def test_cancel_forward_settlement_accelerates_full_eip(api):
    """PRD §3.5: "each installment plan on the line whose `status` is `ACTIVE` is
    driven to `PAID_OFF` with its `remaining_balance_cents` set to 0, and that
    outstanding balance is posted immediately as a single payoff charge." PRD
    §3.10: "simultaneously the entire `remaining_balance_cents` of each `ACTIVE`
    installment plan on the line is posted as a positive `EIP_PAYOFF` charge,
    settling the device immediately as if kept."

    Design: Difficulty/dual_variant_calc/cancel_settlement_forward_vs_chronological_on_line
    """
    account, plan, line, device, eip, _ = H.setup_cancel_ready_line()
    assert eip["remaining_balance_cents"] == 90000

    sub = H.make_subscriber_headers(account["id"])
    validate_success(api.cancel_line(line["id"], sub), 200)

    eip_after = validate_success(api.get_installment_plan(eip["id"], CA), 200)
    assert eip_after["status"] == "PAID_OFF"
    assert eip_after["remaining_balance_cents"] == 0

    charges = validate_success(api.list_charges(BS, params={"line_id": line["id"]}), 200)
    payoffs = [c for c in charges if c["charge_type"] == "EIP_PAYOFF"]
    assert any(c["amount_cents"] == 90000 for c in payoffs), \
        "forward variant posts the full 90000 remaining as one EIP_PAYOFF"


def test_cancel_forward_settlement_posts_unused_credit(api):
    """PRD §3.10: "The unused days are `days_in_cycle` minus the active days the
    line has accrued so far; the forward credit is the discounted base multiplied
    by those unused days divided by `days_in_cycle`, rounded half-up, and posted
    as a negative `CREDIT` charge; simultaneously the entire
    `remaining_balance_cents` of each `ACTIVE` installment plan on the line is
    posted as a positive `EIP_PAYOFF` charge, settling the device immediately as
    if kept."

    Design: Difficulty/dual_variant_calc/cancel_settlement_forward_vs_chronological_on_line
    """
    account, plan, line, device, eip, _ = H.setup_cancel_ready_line()
    sub = H.make_subscriber_headers(account["id"])
    validate_success(api.cancel_line(line["id"], sub), 200)

    charges = validate_success(api.list_charges(BS, params={"line_id": line["id"]}), 200)
    credits = [c for c in charges if c["charge_type"] == "CREDIT"]
    assert credits, "forward variant posts a negative CREDIT charge for the unused base"
    assert all(c["amount_cents"] < 0 for c in credits), "CREDIT amount is negative"


def test_group_discount_counts_only_active_lines(api):
    """PRD §3.10: "`active_line_count` is the count of lines on the account whose
    `status` is `ACTIVE` or `SUSPENDED` (lines in `PENDING_ACTIVATION` or
    `CANCELLED` are excluded)." "exactly two lines yields 0.05".

    Design: Difficulty/dual_variant_calc/group_discount_projected_vs_actual_on_account
    """
    account, plan = setup_account_plan()
    # Two lines reach ACTIVE; two remain PENDING_ACTIVATION (provisioned, no SIM/activate).
    provision_and_activate_line(account["id"], plan["id"])
    provision_and_activate_line(account["id"], plan["id"])
    for _ in range(2):
        ver = current_account_version(account["id"])
        validate_success(api.create_line(
            create_line_payload(account["id"], plan["id"], ver, sim_type="PHYSICAL"), CA), 201)

    acc = validate_success(api.get_account(account["id"], CA), 200)
    assert acc["active_line_count"] == 2, "PENDING_ACTIVATION lines excluded"
    assert acc["group_discount_pct"] == 0.05, "two active lines -> 0.05, not the 4-line 0.15"


# ─── Queue A: boundary_precision_check ────────────────────────────────────

def test_overage_zero_at_exact_included_mb(api):
    """PRD §3.10: "the overage megabytes is the line's `cycle_data_used_mb` minus
    the plan's `included_data_mb`, floored at zero; if that is zero the overage
    is zero cents."

    Design: Difficulty/boundary_precision_check/overage_zero_at_exact_included_mb
    """
    account, plan, line, cycle = setup_active_line_on_open_cycle(sim_type="ESIM")
    ingest_data_usage(line["id"], 20480, "2026-06-15T01:00:00Z")

    summary = validate_success(api.get_usage_summary(line["id"], CA), 200)
    assert summary["cycle_data_used_mb"] == 20480
    assert summary["overage_cents"] == 0, "used == included -> over_mb 0 -> no overage"


def test_group_discount_caps_at_fifth_line(api):
    """PRD §3.10: "exactly four lines yields 0.15; five or more lines yields 0.20,
    which is the cap."

    Design: Difficulty/boundary_precision_check/group_discount_cap_at_fifth_line
    """
    account, plan, lines = setup_n_active_lines(4, sim_type="ESIM")
    acc4 = validate_success(api.get_account(account["id"], CA), 200)
    assert acc4["active_line_count"] == 4
    assert acc4["group_discount_pct"] == 0.15

    provision_and_activate_line(account["id"], plan["id"], sim_type="ESIM")
    acc5 = validate_success(api.get_account(account["id"], CA), 200)
    assert acc5["active_line_count"] == 5
    assert acc5["group_discount_pct"] == 0.20, "capped at 0.20, not climbing further"


# ─── Queue B: calculations corners ────────────────────────────────────────

def test_eip_schedule_financed_and_monthly_computed(api):
    """PRD §3.6: "the financed amount `financed_cents` is the device's
    `retail_price_cents` minus the `down_payment_cents`. The per-cycle charge
    `monthly_installment_cents` is `financed_cents` divided by `term_months`,
    rounded up to the next whole cent". PRD §3.6: "The outstanding
    `remaining_balance_cents` starts equal to `financed_cents`, the
    `installments_paid` counter starts at 0".

    Design: Corner/calculations/eip_schedule_financed_and_monthly_computed
    """
    account, plan, line = H.setup_active_line(sim_type="PHYSICAL")
    device = create_device(retail_price_cents=99900, stock_count=5)

    eip = validate_success(api.create_installment_plan(
        create_installment_plan_payload(line["id"], device["id"],
                                        term_months=24, down_payment_cents=9900), CA), 201)
    assert eip["financed_cents"] == 90000
    assert eip["monthly_installment_cents"] == 3750  # ceil(90000/24)
    assert eip["remaining_balance_cents"] == 90000
    assert eip["installments_paid"] == 0


def test_overage_tier1_only_path(api):
    """PRD §3.10: "The tier-1 megabytes is the lesser of the total overage and
    the plan's `overage_tier1_cap_mb`". PRD §2.6: "Whenever a calculation in
    milli-cents must be converted to cents, the milli-cent total is divided by
    one thousand and rounded to the nearest whole cent using the round-half-up
    rule".

    Design: Corner/calculations/overage_tier2_straddle_correct_cents
    """
    account, plan, line, cycle = setup_active_line_on_open_cycle(sim_type="ESIM")
    ingest_data_usage(line["id"], 23000, "2026-06-15T01:00:00Z")

    summary = validate_success(api.get_usage_summary(line["id"], CA), 200)
    # over = 23000-20480 = 2520, all tier1 @ 1000 mc/MB -> 2,520,000 mc -> 2520 c
    assert summary["overage_cents"] == 2520


def test_usage_summary_aggregates_only_data_records(api):
    """PRD §3.9: "Ingesting a `DATA` record inside the open cycle recomputes the
    line's `cycle_data_used_mb`." PRD §2.5: "A line's `cycle_data_used_mb` is
    recomputed as data usage is ingested."

    Design: Corner/calculations/usage_summary_data_aggregates_multiple_records
    """
    account, plan, line, cycle = setup_active_line_on_open_cycle(sim_type="ESIM")
    ingest_data_usage(line["id"], 10000, "2026-06-15T01:00:00Z")
    ingest_data_usage(line["id"], 11000, "2026-06-15T02:00:00Z")
    validate_success(api.create_usage_record(
        {"line_id": line["id"], "usage_type": "VOICE", "data_mb": 0,
         "occurred_at": "2026-06-15T03:00:00Z"}, CA), 201)

    summary = validate_success(api.get_usage_summary(line["id"], CA), 200)
    assert summary["cycle_data_used_mb"] == 21000, "VOICE excluded; 10000+11000"
    # over = 21000-20480 = 520 MB @ tier1 -> 520 c
    assert summary["overage_cents"] == 520
