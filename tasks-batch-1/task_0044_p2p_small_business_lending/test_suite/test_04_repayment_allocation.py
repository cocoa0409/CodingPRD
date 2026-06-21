"""Scheduled-repayment allocation waterfall, servicing fee, pro-rata investor
distribution (largest-remainder), the scheduled-repayment cascade, and the
principal-conservation invariant on payoff.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_repayment_loan, setup_single_investor_repayment_loan,
    post_repayment, get_loan,
    list_repayment_allocations, list_investment_allocations,
    assess_late_fee, set_clock,
    ADMIN,
)


# =====================================================================
# Rule 1 — dual-variant calculation: SCHEDULED buckets vs RECOVERY whole-principal
# =====================================================================

def test_scheduled_repayment_fills_four_buckets_with_servicing_fee(api):
    """PRD §3.6: "The servicing fee `platform_fee_cents` is the interest bucket
    multiplied by the servicing rate of one percent (`0.01`), rounded to whole cents
    with round-half-up."
    PRD §3.6: "The principal recorded as `principal_paid_cents` is the sum of the
    scheduled-principal bucket and the prepayment bucket."

    Design: Difficulty/dual_variant_calc/repayment_allocation_scheduled_vs_recovery_variant
    """
    ctx = setup_repayment_loan([800_000, 400_000])  # X 800k, Y 400k, principal 1.2M
    rep = post_repayment(ctx["loan"]["id"], 600_000, kind="SCHEDULED")
    assert rep["late_fee_paid_cents"] == 0
    assert rep["interest_paid_cents"] == 5990
    assert rep["platform_fee_cents"] == 60
    assert rep["principal_paid_cents"] == 594010


def test_recovery_repayment_no_servicing_fee_whole_principal(api):
    """PRD §3.7: "A recovery repayment is handled very differently from a scheduled
    one: there are no late-fee, interest, or scheduled-principal buckets and no
    servicing fee is taken — the entire `amount_cents` is treated as principal
    recovery."

    Design: Difficulty/dual_variant_calc/repayment_allocation_scheduled_vs_recovery_variant
    """
    from test_helpers import drive_to_charged_off
    ctx = setup_repayment_loan([800_000, 400_000])
    drive_to_charged_off(ctx["loan"]["id"])
    rep = post_repayment(ctx["loan"]["id"], 600_000, kind="RECOVERY")
    assert rep["platform_fee_cents"] == 0, "recovery takes no servicing fee"
    assert rep["interest_paid_cents"] == 0
    assert rep["late_fee_paid_cents"] == 0
    assert rep["principal_paid_cents"] == 600_000, "entire recovery is principal"


# =====================================================================
# Rule 1 (instance 2) — investor net receipt: scheduled net-of-fee vs recovery full
# =====================================================================

def test_investor_net_interest_scheduled_is_net_of_servicing_fee(api):
    """PRD §3.6: "The net interest passed on to investors is the interest bucket
    minus that fee."
    PRD §3.6: "the net interest paid to that investment as `interest_amount_cents`."

    Design: Difficulty/dual_variant_calc/investor_net_receipt_scheduled_servicing_fee_vs_recovery_no_fee
    """
    ctx = setup_single_investor_repayment_loan()  # single investor 1,200,000
    rep = post_repayment(ctx["loan"]["id"], 103274, kind="SCHEDULED")
    assert rep["interest_paid_cents"] == 5990
    assert rep["platform_fee_cents"] == 60
    allocs = list_investment_allocations(ctx["investments"][0]["id"])
    # The allocation line for this repayment carries net interest 5930 (5990 - 60).
    matching = [a for a in allocs if a["repayment_id"] == rep["id"]]
    assert len(matching) == 1
    assert matching[0]["interest_amount_cents"] == 5930, "single investor nets 5990 - 60 fee"


def test_investor_recovery_receipt_full_amount_as_principal(api):
    """PRD §3.7: "One `RepaymentAllocation` line is created per investment, carrying
    only `principal_amount_cents` (a recovery line has no interest component)."

    Design: Difficulty/dual_variant_calc/investor_net_receipt_scheduled_servicing_fee_vs_recovery_no_fee
    """
    from test_helpers import drive_to_charged_off
    ctx = setup_single_investor_repayment_loan()
    drive_to_charged_off(ctx["loan"]["id"])
    rep = post_repayment(ctx["loan"]["id"], 5990, kind="RECOVERY")
    assert rep["platform_fee_cents"] == 0
    allocs = list_investment_allocations(ctx["investments"][0]["id"])
    matching = [a for a in allocs if a["repayment_id"] == rep["id"]]
    assert len(matching) == 1
    assert matching[0]["principal_amount_cents"] == 5990, "investor nets full recovery as principal"


# =====================================================================
# Rule 4b — depth-2 cascade: scheduled repayment -> loan + investments + allocations
# =====================================================================

def test_scheduled_repayment_cascades_to_investments_and_allocations(api):
    """PRD §3.6: "the loan's balances are updated ... `outstanding_principal_cents`
    is reduced by the principal recorded in `principal_paid_cents`"
    PRD §3.6: "As principal is distributed, each investment's
    `outstanding_principal_cents` is debited by its principal share"
    PRD §3.6: "Each scheduled repayment is split among the loan's `COMMITTED`
    investors and recorded as one `RepaymentAllocation` line per investment."

    Design: Difficulty/transitive_cascade/scheduled_repayment_cascade_loan_investment_allocation_depth2
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    rep = post_repayment(ctx["loan"]["id"], 103274, kind="SCHEDULED")
    loan = get_loan(ctx["loan"]["id"])
    assert loan["outstanding_principal_cents"] == 1_102_716
    invx = validate_success(api.get_investment(ctx["investments"][0]["id"], ADMIN), 200)
    invy = validate_success(api.get_investment(ctx["investments"][1]["id"], ADMIN), 200)
    assert invx["outstanding_principal_cents"] == 735_144, "X share 800k/1.2M of 97284 debited"
    assert invy["outstanding_principal_cents"] == 367_572, "Y share 400k/1.2M of 97284 debited"
    allocs = list_repayment_allocations(rep["id"])
    assert len(allocs) == 2, f"one allocation per investment, got {len(allocs)}"


def test_scheduled_repayment_advances_loan_outstanding(api):
    """PRD §3.6: "`outstanding_principal_cents` is reduced by the principal recorded
    in `principal_paid_cents` (scheduled principal plus prepayment)."

    Design: Difficulty/transitive_cascade/scheduled_repayment_cascade_loan_investment_allocation_depth2
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    post_repayment(ctx["loan"]["id"], 103274, kind="SCHEDULED")
    loan = get_loan(ctx["loan"]["id"])
    # principal_paid 97284 -> outstanding 1,200,000 - 97284 = 1,102,716
    assert loan["outstanding_principal_cents"] == 1_102_716


# =====================================================================
# Rule 9a — compensating invariant: principal disbursed == principal returned
# =====================================================================

def test_payoff_returns_exactly_disbursed_principal(api):
    """PRD §3.6: "Across the loan's life this preserves the compensating invariant
    that principal disbursed to the borrower equals principal returned to the
    investors."
    PRD §3.6: "the loan transitions from `REPAYMENT` to `PAID_OFF`"

    Design: Difficulty/compensating_invariant/principal_conservation_disbursed_equals_returned_on_payoff
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    rep = post_repayment(ctx["loan"]["id"], 1_205_990, kind="SCHEDULED")
    loan = get_loan(ctx["loan"]["id"])
    assert loan["status"] == "PAID_OFF"
    assert loan["outstanding_principal_cents"] == 0
    allocs = list_repayment_allocations(rep["id"])
    total_principal = sum(a["principal_amount_cents"] for a in allocs)
    assert total_principal == 1_200_000, \
        f"sum of returned principal must equal disbursed 1,200,000, got {total_principal}"


def test_payoff_principal_split_matches_each_investor_share(api):
    """PRD §3.6: "The split is pro-rata by each investor's share of the original
    funded principal."
    PRD §3.6: "the principal returned to that investment as `principal_amount_cents`"

    Design: Difficulty/compensating_invariant/principal_conservation_disbursed_equals_returned_on_payoff
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    post_repayment(ctx["loan"]["id"], 1_205_990, kind="SCHEDULED")
    x_allocs = list_investment_allocations(ctx["investments"][0]["id"])
    y_allocs = list_investment_allocations(ctx["investments"][1]["id"])
    x_total = sum(a["principal_amount_cents"] for a in x_allocs)
    y_total = sum(a["principal_amount_cents"] for a in y_allocs)
    assert x_total == 800_000, f"X must recover its full 800,000 principal, got {x_total}"
    assert y_total == 400_000, f"Y must recover its full 400,000 principal, got {y_total}"


# =====================================================================
# Corner — calculations: waterfall ordering, largest-remainder tie-break
# =====================================================================

def test_waterfall_late_fee_then_interest_then_principal(api):
    """PRD §3.6: "A scheduled repayment is allocated through a strict four-bucket
    waterfall, filled in a fixed, non-negotiable order, with each bucket consuming
    from the cash that the prior buckets left behind."

    Design: Corner/calculations/waterfall_late_fee_first_then_interest_then_principal
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_single_investor_repayment_loan()  # built with funded_at 2026-06-01
    set_clock("2026-07-02T00:00:00.000Z")
    assess_late_fee(ctx["loan"]["id"])  # late fee 5164 at period 1
    rep = post_repayment(ctx["loan"]["id"], 50_000, kind="SCHEDULED")
    assert rep["late_fee_paid_cents"] == 5164
    assert rep["interest_paid_cents"] == 5990
    assert rep["platform_fee_cents"] == 60
    assert rep["principal_paid_cents"] == 38846  # 50000 - 5164 - 5990


def test_distribute_pro_rata_largest_remainder_tiebreak_created_at(api):
    """PRD §3.6: "those leftover cents are handed out one cent each to the
    investments ranked by the largest fractional part of their raw share. Ties in
    the fractional part are broken by the investment's creation timestamp, oldest
    first — never by `id`."

    Design: Corner/calculations/distribute_pro_rata_largest_remainder_tiebreak_created_at
    """
    # loan 1,000,168 funded equally by E1 (created first) then E2.
    ctx = setup_repayment_loan([500_084, 500_084],
                               requested_principal_cents=1_000_168)
    rep = post_repayment(ctx["loan"]["id"], 86_076, kind="SCHEDULED")
    assert rep["interest_paid_cents"] == 4993
    assert rep["platform_fee_cents"] == 50  # net interest 4943 (odd)
    e1_allocs = [a for a in list_investment_allocations(ctx["investments"][0]["id"])
                 if a["repayment_id"] == rep["id"]]
    e2_allocs = [a for a in list_investment_allocations(ctx["investments"][1]["id"])
                 if a["repayment_id"] == rep["id"]]
    assert len(e1_allocs) == 1 and len(e2_allocs) == 1
    # Net interest 4943 splits 2471.5/2471.5; the remainder cent goes to E1 (earlier).
    assert e1_allocs[0]["interest_amount_cents"] == 2472, "E1 (earlier created) wins the remainder cent"
    assert e2_allocs[0]["interest_amount_cents"] == 2471


# =====================================================================
# Corner — entities: allocation rows are append-only (no version field)
# =====================================================================

def test_repayment_allocation_rows_have_no_version_field(api):
    """PRD §2.4: "an allocation line is immutable once written, so it carries only
    `id` and `created_at` — it has neither an `updated_at` field nor a `version`
    field."

    Design: Corner/entities/repayment_allocation_immutable_no_version_field
    """
    from test_helpers import assert_repayment_allocation
    ctx = setup_repayment_loan([800_000, 400_000])
    rep = post_repayment(ctx["loan"]["id"], 103274, kind="SCHEDULED")
    allocs = list_repayment_allocations(rep["id"])
    assert len(allocs) == 2
    for a in allocs:
        assert_repayment_allocation(a)
        assert "version" not in a
        assert "updated_at" not in a


# =====================================================================
# Corner — validations: payment exceeds payoff
# =====================================================================

def test_scheduled_payment_exceeds_payoff_rejected(api):
    """PRD §3.6: "Its `amount_cents` may not exceed the loan's **total payoff** —
    the sum of the outstanding late fees, the remaining interest due, and the
    outstanding principal — and an over-payment is rejected with
    `ERR_PAYMENT_EXCEEDS_PAYOFF`."

    Design: Corner/validations/scheduled_payment_exceeds_payoff_rejected
    """
    ctx = setup_single_investor_repayment_loan()  # total payoff 1,205,990
    resp = api.create_repayment(
        ctx["loan"]["id"],
        {"loan_id": ctx["loan"]["id"], "amount_cents": 1_300_000, "kind": "SCHEDULED"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_PAYOFF.value, 422)
