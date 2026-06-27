"""Settlement revenue computation and the commission split.

Covers queue-A difficulty instances (combinatorial settlement + commission eval order,
dual-variant commission basis, settle->commission cascade, interchange tier boundary,
settle blocked without disclosure, commission ceiling headroom void) and queue-B corner
instances (settled-run lockdown, empty-window settle, txn-already-settled, merchant suspended).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    provision_network, provision_armed_atm, create_atm,
    approve_fee_disclosure_for_atm, draft_fee_disclosure,
    seed_monthly_wd_count, set_clock,
    post_withdrawal, post_balance_inquiry, post_n_withdrawals,
    create_settlement_run, settle_run, get_commission_statement_for_run,
    setup_armed_atm_with_withdrawals, settle_atm_window,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SETTLE = TEST_USERS["settlement_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
TECH = TEST_USERS["field_tech_headers"]


# ============================================================================
# combinatorial_formula — tiered interchange + kind branch (queue A)
# ============================================================================

def test_settlement_tiered_interchange_with_kind_branch(api):
    """PRD §3.10: "The `interchange_revenue_cents` is the sum, over each swept withdrawal, of an
    interchange rate selected marginally by that withdrawal's own `monthly_seq`: a withdrawal whose
    `monthly_seq` is from 1 through 500 earns 35 cents, one whose `monthly_seq` is from 501 through
    2000 earns 42 cents, and one whose `monthly_seq` is 2001 or higher earns 50 cents."
    PRD §3.10: "Settling sweeps every `WITHDRAWAL` transaction on the run's machine whose creation
    time falls in the half-open window from `window_start` up to but not including `window_end` and
    whose `settlement_run_id` is still null — balance inquiries are never swept."
    PRD §3.10: "The `network_fee_cents` is a flat network charge of 8 cents per swept withdrawal"

    Design: Difficulty/combinatorial_formula/settlement_tiered_interchange_with_kind_branch
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498,
        num_withdrawals=5, num_balance_inquiries=2, clock="2026-01-10T00:00:00Z")
    run = create_settlement_run(net["atm"]["id"])
    settled = settle_run(run["id"])
    assert settled["withdrawal_count"] == 5  # 2 BALANCE_INQUIRY excluded
    assert settled["interchange_revenue_cents"] == 196  # 499,500@35 + 501,502,503@42
    assert settled["surcharge_revenue_cents"] == 1475
    assert settled["network_fee_cents"] == 40
    assert settled["net_operator_revenue_cents"] == 1631


def test_commission_eval_order_pct_then_ceiling(api):
    """PRD §3.11: "The percentage candidate, `pct_amount_cents`, is the `net_operator_revenue_cents`
    multiplied by the merchant's `commission_pct_bps`, divided by 10000, with the fractional part
    discarded (floored)."
    PRD §3.11: "The remaining headroom is the merchant's `commission_monthly_ceiling_cents` minus
    that month-to-date total, but never less than zero. The statement's `commission_cents` is then
    the smaller of the selected base and the remaining headroom"
    PRD §3.11: "Finally, `operator_keeps_cents` is the run's `net_operator_revenue_cents` minus the
    statement's `commission_cents`."

    Design: Difficulty/combinatorial_formula/commission_eval_order_pct_then_ceiling
    """
    # Merchant pct 5000bps, flat 0, ceiling 200, PCT_ONLY. Two ATMs share it.
    net = provision_armed_atm(
        surcharge_cents=295, jurisdiction_code="CA",
        merchant_overrides={"commission_pct_bps": 5000, "commission_flat_per_wd_cents": 0,
                            "commission_monthly_ceiling_cents": 200, "commission_basis": "PCT_ONLY"})
    atm1 = net["atm"]
    atm2 = create_atm(net["location"]["id"], serial_no="SN-CAP2", surcharge_cents=295,
                      note_denomination_cents=2000)
    approve_fee_disclosure_for_atm(atm2["id"], 295)

    set_clock("2026-01-10T00:00:00Z")
    # run1: atm1 (not seeded) -> 1 BALANCE_INQUIRY + 1 WITHDRAWAL (seq 1, tier1).
    post_balance_inquiry(atm1["id"])
    post_withdrawal(atm1["id"], amount_cents=2000)
    run1 = create_settlement_run(atm1["id"])
    settle_run(run1["id"])
    stmt1 = get_commission_statement_for_run(run1["id"])
    assert stmt1["commission_cents"] == 161  # net 322; floor(322*0.5)=161; under ceiling 200

    # run2: atm2 seeded 498 -> 5 WITHDRAWALs seqs 499..503.
    seed_monthly_wd_count(atm2["id"], 498)
    post_n_withdrawals(atm2["id"], 5, amount_cents=2000)
    run2 = create_settlement_run(atm2["id"])
    settle_run(run2["id"])
    stmt2 = get_commission_statement_for_run(run2["id"])
    assert stmt2["pct_amount_cents"] == 815       # floor(1631*0.5)
    assert stmt2["commission_cents"] == 39         # ceiling 200 - 161 already accrued
    assert stmt2["operator_keeps_cents"] == 1592   # 1631 - 39


# ============================================================================
# dual_variant_calc — commission basis GREATER_OF vs PCT_ONLY (queue A)
# ============================================================================

def test_commission_greater_of_vs_pct_only_diverge(api):
    """PRD §3.11: "under `GREATER_OF` the base is the larger of `pct_amount_cents` and
    `flat_amount_cents`; under `PCT_ONLY` the base is `pct_amount_cents` and the flat candidate is
    ignored even when it would be larger"
    PRD §3.11: "The flat candidate, `flat_amount_cents`, is the merchant's
    `commission_flat_per_wd_cents` multiplied by the run's `withdrawal_count`."

    Design: Difficulty/dual_variant_calc/commission_greater_of_vs_pct_only_diverge
    """
    common = {"commission_pct_bps": 1500, "commission_flat_per_wd_cents": 120,
              "commission_monthly_ceiling_cents": 50_000}
    net_g = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498, num_withdrawals=5,
        clock="2026-01-10T00:00:00Z",
        merchant_overrides={**common, "commission_basis": "GREATER_OF"})
    net_p = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498, num_withdrawals=5,
        merchant_overrides={**common, "commission_basis": "PCT_ONLY"})

    settled_g, stmt_g = settle_atm_window(net_g["atm"]["id"])
    settled_p, stmt_p = settle_atm_window(net_p["atm"]["id"])

    assert settled_g["net_operator_revenue_cents"] == 1631
    assert settled_p["net_operator_revenue_cents"] == 1631
    assert stmt_g["commission_cents"] == 600   # flat 120*5=600 > pct floor(1631*0.15)=244
    assert stmt_p["commission_cents"] == 244   # pct only; flat 600 ignored


# ============================================================================
# transitive_cascade — settle -> txn binding + commission cascade (queue A)
# ============================================================================

def test_settle_cascade_depth2_txn_commission(api):
    """PRD §3.10: "As the run settles, every swept transaction has its `settlement_run_id` bound to
    this run, which is what protects it from being double-counted by a later run."
    PRD §3.11: "Settling a run does not stop at the operator's books — it cascades to generate a
    **commission statement** for the host merchant, born `ACCRUED`."
    PRD §3.11: "the system resolves the `site_merchant_id` from the run's machine through its
    location."

    Design: Difficulty/transitive_cascade/settle_cascade_depth2_txn_commission
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498, num_withdrawals=5,
        clock="2026-01-10T00:00:00Z")
    run = create_settlement_run(net["atm"]["id"])
    settle_run(run["id"])

    bound = validate_success(api.list_transactions(
        headers=SETTLE, params={"settlement_run_id": run["id"]}))
    assert len(bound) == 5
    assert all(t["settlement_run_id"] == run["id"] for t in bound)

    statements = validate_success(api.list_commission_statements(
        headers=SETTLE, params={"settlement_run_id": run["id"]}))
    assert len(statements) == 1
    assert statements[0]["status"] == "ACCRUED"
    assert statements[0]["site_merchant_id"] == net["merchant"]["id"]


# ============================================================================
# boundary_precision_check — interchange tier flip at seq 500/501 (queue A)
# ============================================================================

def test_interchange_tier_boundary_seq_500_vs_501(api):
    """PRD §3.10: "a withdrawal whose `monthly_seq` is from 1 through 500 earns 35 cents, one whose
    `monthly_seq` is from 501 through 2000 earns 42 cents"
    PRD §3.6: "The monthly sequence, `monthly_seq`, is the machine's current `monthly_wd_count` plus
    one — that is, the one-based position of this withdrawal among the machine's withdrawals this
    calendar month — and it pins the interchange tier this withdrawal will eventually settle at."

    Design: Difficulty/boundary_precision_check/interchange_tier_boundary_seq_500_vs_501
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=100, jurisdiction_code="CA", seed_count=499, num_withdrawals=2,
        clock="2026-01-10T00:00:00Z")
    run = create_settlement_run(net["atm"]["id"])
    settled = settle_run(run["id"])
    assert settled["interchange_revenue_cents"] == 77   # seq 500@35 + seq 501@42
    assert settled["net_operator_revenue_cents"] == 261  # surcharge 200 + 77 - network 16


# ============================================================================
# cross_entity_state_dependency — settle blocked without disclosure (queue A)
# ============================================================================

def test_settle_blocked_without_approved_fee_disclosure(api):
    """PRD §3.10: "Settlement is gated by two preconditions: the machine must have an approved fee
    disclosure, or settlement is rejected with `ERR_NO_FEE_DISCLOSURE`"

    Design: Difficulty/cross_entity_state_dependency/settle_blocked_without_approved_fee_disclosure
    """
    net = provision_network(jurisdiction_code="CA", surcharge_cents=100, note_denomination_cents=2000)
    # Only a DRAFT disclosure exists (never approved) -> ATM not armed.
    draft_fee_disclosure(net["atm"]["id"], 100, ack_text_present=True)
    run = create_settlement_run(net["atm"]["id"])
    resp = api.settle_run(run["id"], headers=SETTLE)
    validate_error(resp, ApiErrorId.ERR_NO_FEE_DISCLOSURE, expected_status=422)
    fresh = validate_success(api.get_settlement_run(run["id"], headers=SETTLE))
    assert fresh["status"] == "DRAFT"


# ============================================================================
# compensating_invariant — ceiling headroom accrue then void (queue A)
# ============================================================================

def test_commission_ceiling_headroom_accrue_then_void(api):
    """PRD §3.11: "Alternatively the officer **voids** an `ACCRUED` statement, moving it to its
    terminal `VOIDED` status; voiding frees ceiling headroom by removing that statement's
    `commission_cents` from the merchant's month-to-date commission, so a subsequent statement in
    the same month sees more remaining headroom."
    PRD §3.11: "The statement's `commission_cents` is then the smaller of the selected base and the
    remaining headroom"

    Design: Difficulty/compensating_invariant/commission_ceiling_headroom_accrue_then_void
    """
    net = provision_armed_atm(
        surcharge_cents=295, jurisdiction_code="CA",
        merchant_overrides={"commission_pct_bps": 5000, "commission_flat_per_wd_cents": 0,
                            "commission_monthly_ceiling_cents": 200, "commission_basis": "PCT_ONLY"})
    atm1 = net["atm"]
    atm2 = create_atm(net["location"]["id"], serial_no="SN-HEADROOM2", surcharge_cents=295,
                      note_denomination_cents=2000)
    approve_fee_disclosure_for_atm(atm2["id"], 295)

    set_clock("2026-01-10T00:00:00Z")
    post_withdrawal(atm1["id"], amount_cents=2000)
    run1 = create_settlement_run(atm1["id"])
    settle_run(run1["id"])
    stmt1 = get_commission_statement_for_run(run1["id"])
    assert stmt1["commission_cents"] == 161  # consumes headroom

    seed_monthly_wd_count(atm2["id"], 498)
    post_n_withdrawals(atm2["id"], 5, amount_cents=2000)
    run2 = create_settlement_run(atm2["id"])

    # Void run1's statement -> frees 161 headroom; ceiling back to full 200.
    voided = validate_success(api.void_commission_statement(stmt1["id"], headers=SETTLE))
    assert voided["status"] == "VOIDED"
    settle_run(run2["id"])
    stmt2 = get_commission_statement_for_run(run2["id"])
    assert stmt2["commission_cents"] == 200  # pct 815 capped at full ceiling 200 (not 39)


# ============================================================================
# state_machines / calculations / validations (queue B)
# ============================================================================

def test_settle_already_settled_run_returns_invalid_state(api):
    """PRD §3.10: "The officer then **settles** it, moving it from `DRAFT` to its terminal,
    immutable `SETTLED` status."
    PRD §2.6: "Among those, any attempt to drive an entity through a transition that is not defined
    from its current state — settling a run that is already `SETTLED`, acknowledging a ticket that
    is not `OPEN`, approving a disclosure that is not `DRAFT`, and the like — is rejected with
    `ERR_INVALID_STATE`, the generic guard that backs every state machine described below."

    Design: Corner/state_machines/settle_already_settled_run_returns_invalid_state
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", num_withdrawals=1, clock="2026-01-10T00:00:00Z")
    run = create_settlement_run(net["atm"]["id"])
    settle_run(run["id"])
    resp = api.settle_run(run["id"], headers=SETTLE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_settlement_zero_withdrawals_empty_window(api):
    """PRD §3.10: "The `net_operator_revenue_cents` is therefore the `surcharge_revenue_cents` plus
    the `interchange_revenue_cents` minus the `network_fee_cents`."
    PRD §3.10: "Settling sweeps every `WITHDRAWAL` transaction on the run's machine whose creation
    time falls in the half-open window from `window_start` up to but not including `window_end` and
    whose `settlement_run_id` is still null — balance inquiries are never swept."

    Design: Corner/calculations/settlement_zero_withdrawals_empty_window
    """
    net = provision_armed_atm(surcharge_cents=295, jurisdiction_code="CA")
    set_clock("2026-01-10T00:00:00Z")
    post_balance_inquiry(net["atm"]["id"])  # only a balance inquiry
    run = create_settlement_run(net["atm"]["id"])
    settled = settle_run(run["id"])
    assert settled["withdrawal_count"] == 0
    assert settled["net_operator_revenue_cents"] == 0
    assert settled["status"] == "SETTLED"


def test_settle_overlapping_run_txn_already_settled_rejected(api):
    """PRD §3.10: "none of the withdrawals the run is about to sweep may already be bound to another
    settlement run, or it is rejected with `ERR_TXN_ALREADY_SETTLED`."

    Design: Corner/validations/settle_overlapping_run_txn_already_settled_rejected
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", num_withdrawals=1, clock="2026-01-10T00:00:00Z")
    run_a = create_settlement_run(net["atm"]["id"])
    settle_run(run_a["id"])
    # Run B over the same window re-sweeps the already-bound withdrawal.
    run_b = create_settlement_run(net["atm"]["id"])
    resp = api.settle_run(run_b["id"], headers=SETTLE)
    validate_error(resp, ApiErrorId.ERR_TXN_ALREADY_SETTLED, expected_status=409)


def test_pay_commission_merchant_suspended_rejected(api):
    """PRD §3.11: "A `SettlementOfficer` later **pays** an `ACCRUED` statement, moving it to its
    terminal `PAID` status; payment requires the merchant's `payout_status` to be `ACTIVE`, and an
    attempt to pay a statement whose merchant is suspended is rejected with
    `ERR_MERCHANT_SUSPENDED`."

    Design: Corner/validations/pay_commission_merchant_suspended_rejected
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", num_withdrawals=1, clock="2026-01-10T00:00:00Z")
    run = create_settlement_run(net["atm"]["id"])
    settle_run(run["id"])
    stmt = get_commission_statement_for_run(run["id"])
    validate_success(api.suspend_site_merchant(net["merchant"]["id"], headers=ADMIN))
    resp = api.pay_commission_statement(stmt["id"], headers=SETTLE)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_SUSPENDED, expected_status=409)
