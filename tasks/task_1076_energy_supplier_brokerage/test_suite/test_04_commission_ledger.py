"""The commission ledger: estimation, tiered clamp, true-up, SoD, and the
forward-and-compensation invariant.

Queue A: the estimated-vs-actual dual variant, the combinatorial tiered
multiplier + clamp, the pinned per-month rounding order, and the conserved
commission-payable invariant. Queue B: min-floor clamp, SoD, no-actual-usage.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
import test_helpers.fixtures as fx


def _summary_total(api, ctx, account_id):
    data = validate_success(api.commission_summary(ctx["agent_headers"], params={"account_id": account_id}))
    return data["total_net_commission_cents"]


# ===========================================================================
# Difficulty: dual_variant_calc / commission_estimated_vs_actual_trueup
# ===========================================================================

def test_trueup_actual_gross_diverges_from_estimate(api):
    """PRD §3.5: "true_up_delta_cents is the actual gross minus the originally
    pinned gross_commission_cents (it may be negative); clawback_cents is the
    amount by which the original gross exceeds the actual gross, or 0 if the
    actual meets or beats the original; and net_commission_cents is set to the
    actual_gross_cents."

    Design: Difficulty/dual_variant_calc/commission_estimated_vs_actual_trueup
    """
    ctx = fx.setup_approved_statement(api)  # est 60000/adder5/term12; four 14985 actuals; APPROVED by mgr1
    stmt = get_success_data(api.true_up_statement(ctx["statement"]["id"], ctx["mgr2_headers"]))
    assert stmt["gross_commission_cents"] == 30000
    assert stmt["actual_gross_cents"] == 29972
    assert stmt["clawback_cents"] == 28
    assert stmt["net_commission_cents"] == 29972
    assert stmt["basis"] == "ACTUAL"
    assert stmt["status"] == "TRUED_UP"


def test_estimated_gross_pinned_before_trueup(api):
    """PRD §3.5: "Its gross_commission_cents is computed by the estimated-commission
    rule and pinned at creation. ... while the statement remains provisional or
    approved the net_commission_cents equals that gross."

    Design: Difficulty/dual_variant_calc/commission_estimated_vs_actual_trueup
    """
    ctx = fx.setup_approved_statement(api)  # statement APPROVED, not yet trued up
    stmt = get_success_data(api.get_commission_statement(ctx["statement"]["id"], ctx["mgr1_headers"]))
    assert stmt["basis"] == "ESTIMATED"
    assert stmt["gross_commission_cents"] == 30000
    assert stmt["net_commission_cents"] == 30000


# ===========================================================================
# Difficulty: combinatorial_formula / commission_tiered_multiplier_and_clamp
# ===========================================================================

def test_tiered_multiplier_applied_to_estimated_gross(api):
    """PRD §3.5: "a term multiplier is chosen from the requested term: it is 1.00
    when term_months is 12 or fewer, 1.10 when term_months is between 13 and 24
    inclusive, and 1.20 when term_months is 25 or more; the base amount is
    multiplied by this multiplier and rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/commission_tiered_multiplier_and_clamp
    """
    ctx = fx.setup_active_contract(api, est_usage=120000, term_months=24, adder=4)
    stmt = fx.get_provisional_statement(api, ctx)  # base 48000 * 1.10 = 52800
    assert stmt["gross_commission_cents"] == 52800


def test_tiered_gross_net_and_provisional_status(api):
    """PRD §3.5: "The resulting figure is the gross_commission_cents, and while the
    statement remains provisional or approved the net_commission_cents equals that
    gross."

    Design: Difficulty/combinatorial_formula/commission_tiered_multiplier_and_clamp
    """
    ctx = fx.setup_active_contract(api, est_usage=120000, term_months=24, adder=4)
    stmt = fx.get_provisional_statement(api, ctx)
    assert stmt["net_commission_cents"] == 52800
    assert stmt["status"] in ("PROVISIONAL", "APPROVED")  # created PROVISIONAL


# ===========================================================================
# Difficulty: combinatorial_formula / commission_actual_rounding_order_pinned
# ===========================================================================

def test_actual_gross_rounds_each_month_then_sums(api):
    """PRD §3.5: "For each such month it computes that month's cents as the month's
    usage_kwh times the contract's broker_adder_mills, divided by ten, rounded
    half-up — and only then does it sum the already-rounded monthly figures. This
    per-month-then-sum order is mandatory".

    Design: Difficulty/combinatorial_formula/commission_actual_rounding_order_pinned
    """
    ctx = fx.setup_approved_statement(api)  # four 14985 kWh actuals: round(7492.5)=7493 each, sum 29972
    stmt = get_success_data(api.true_up_statement(ctx["statement"]["id"], ctx["mgr2_headers"]))
    assert stmt["actual_gross_cents"] == 29972  # not 29970 (sum-then-round)


def test_actual_rounding_order_drives_clawback(api):
    """PRD §3.5: "clawback_cents is the amount by which the original gross exceeds
    the actual gross, or 0 if the actual meets or beats the original; and
    net_commission_cents is set to the actual_gross_cents."

    Design: Difficulty/combinatorial_formula/commission_actual_rounding_order_pinned
    """
    ctx = fx.setup_approved_statement(api)
    stmt = get_success_data(api.true_up_statement(ctx["statement"]["id"], ctx["mgr2_headers"]))
    assert stmt["clawback_cents"] == 28
    assert stmt["net_commission_cents"] == 29972


# ===========================================================================
# Difficulty: compensating_invariant / commission_payable_conserved_on_submit_then_drop
# ===========================================================================

def test_commission_payable_conserved_across_submit_then_drop(api):
    """PRD §3.5: "submitting an enrollment creates a provisional commission
    liability, and a subsequent utility rejection must exactly reverse it."
    PRD §3.5: "The commission-summary report aggregates, for an optional
    account_id filter, the total_net_commission_cents and the statement_count over
    that account's non-voided statements."

    Design: Difficulty/compensating_invariant/commission_payable_conserved_on_submit_then_drop
    """
    ctx = fx.setup_contract_approved(api, with_manager=True)  # est 60000 -> provisional gross 30000
    acct_id = ctx["account"]["id"]
    assert _summary_total(api, ctx, acct_id) == 0

    get_success_data(api.submit_enrollment(ctx["contract"]["id"], ctx["agent_headers"]))
    assert _summary_total(api, ctx, acct_id) == 30000

    contract = get_success_data(api.enrollment_result(ctx["contract"]["id"], {"result": "REJECT"}, ctx["ops_headers"]))
    assert _summary_total(api, ctx, acct_id) == 0
    assert contract["status"] == "DROPPED"


def test_dropped_enrollment_voids_statement_and_zeroes_net(api):
    """PRD §3.5: "the contract's provisional statement transitions
    PROVISIONAL → VOIDED, its net_commission_cents is set to 0, and the brokering
    agent's pipeline_commission_cents falls back to its pre-submission value."

    Design: Difficulty/compensating_invariant/commission_payable_conserved_on_submit_then_drop
    """
    ctx = fx.setup_contract_approved(api, with_manager=True)
    get_success_data(api.submit_enrollment(ctx["contract"]["id"], ctx["agent_headers"]))
    stmt = fx.get_provisional_statement(api, ctx)
    get_success_data(api.enrollment_result(ctx["contract"]["id"], {"result": "REJECT"}, ctx["ops_headers"]))

    voided = get_success_data(api.get_commission_statement(stmt["id"], ctx["agent_headers"]))
    assert voided["status"] == "VOIDED"
    assert voided["net_commission_cents"] == 0


# ===========================================================================
# Corner: min-floor clamp, SoD, no-actual-usage
# ===========================================================================

def test_estimated_commission_clamped_to_min_floor(api):
    """PRD §3.5: "that tiered amount is clamped to lie between a floor of 5,000
    cents ($50) and a ceiling of 5,000,000 cents ($50,000), taking the larger of
    the floor and the tiered amount, then the smaller of that and the ceiling".

    Design: Corner/calculations/estimated_commission_clamped_to_min_floor
    """
    ctx = fx.setup_active_contract(api, est_usage=1000, term_months=6, adder=4)
    stmt = fx.get_provisional_statement(api, ctx)  # base 400 -> clamped up to 5000
    assert stmt["gross_commission_cents"] == 5000


def test_same_manager_approve_and_trueup_rejected(api):
    """PRD §3.5: "the acting manager's X-User-ID must differ from the recorded
    approved_by_manager_id (else ERR_SEGREGATION_OF_DUTIES)".

    Design: Corner/rbac/sod_same_manager_approve_and_trueup_rejected
    """
    ctx = fx.setup_approved_statement(api)  # approved by mgr1, actual usage present
    resp = api.true_up_statement(ctx["statement"]["id"], ctx["mgr1_headers"])  # same manager
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    after = get_success_data(api.get_commission_statement(ctx["statement"]["id"], ctx["mgr1_headers"]))
    assert after["status"] == "APPROVED"


def test_trueup_without_actual_usage_rejected(api):
    """PRD §3.5: "at least one usage record with is_actual true must exist for the
    contract's account (else ERR_NO_ACTUAL_USAGE)".

    Design: Corner/errors/trueup_without_actual_usage_rejected
    """
    ctx = fx.setup_approved_statement(api, add_actuals=False)  # only the is_actual=false verify row
    resp = api.true_up_statement(ctx["statement"]["id"], ctx["mgr2_headers"])  # different manager
    validate_error(resp, ApiErrorId.ERR_NO_ACTUAL_USAGE.value)
    after = get_success_data(api.get_commission_statement(ctx["statement"]["id"], ctx["mgr2_headers"]))
    assert after["status"] == "APPROVED"
