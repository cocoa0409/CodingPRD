"""Dual-variant reimbursement (provisional vs realized) and firm commission
(charge-based vs collection-based, round-per-claim-then-sum).

Translates the dual_variant_calc and the billing-fee combinatorial_formula
difficulty instances.
"""
from test_helpers import (
    validate_success, make_account_manager_headers, make_biller_headers,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()


def _setup_paid_claim_billed_23000(api):
    """Accepted claim (billed 23000, allowed 15000, provisional PR 7400, ER 7600),
    then an ERA posting of insurance_paid 7000 with ERA PR 8000 that drives it to PAID.
    Returns the refreshed PAID claim dict and the practice id."""
    ctx = fx.setup_accepted_claim(
        api, prices={"99213": 10000, "93000": 5000},
        deductible_remaining_cents=3000, coinsurance_pct=0.20, copay_cents=2000,
        lines=[{"cpt_code": "99213", "units": 1, "charge_amount_cents": 15000},
               {"cpt_code": "93000", "units": 1, "charge_amount_cents": 8000}],
        coder_user_id="coder-1", biller_user_id="biller-1")
    rem = fx.new_remittance(api, ctx["payer"]["id"], total_amount_cents=7000, remittance_ref="RA-1")
    fx.new_posting(api, rem["id"], ctx["claim"]["id"], ctx["claim_version"],
                   insurance_paid_cents=7000, patient_responsibility_cents=8000,
                   adjustment_cents=8000)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    return claim, ctx["practice"]["id"]


# ---- Difficulty: dual_variant_calc / expected reimbursement provisional vs realized ----
def test_expected_reimbursement_frozen_at_provisional_value(api):
    """PRD §3.3: "sets `expected_reimbursement_cents` to the claim's
    `allowed_amount_cents` minus its `patient_responsibility_cents`"
    PRD §2.9: "monetary figures ... are derived fields, recomputed whenever an event
    changes their inputs (scrubbing, each payment posting or reversal, and each
    patient-statement payment or write-off), following the reconciliation identity
    defined in §3.6."

    Design: Difficulty/dual_variant_calc/claim_expected_reimbursement_provisional_vs_realized
    """
    claim, _ = _setup_paid_claim_billed_23000(api)
    assert claim["expected_reimbursement_cents"] == 7600, claim["expected_reimbursement_cents"]


def test_realized_insurance_paid_diverges_from_expected_reimbursement(api):
    """PRD §3.6: "`insurance_paid_cents` is the sum of `insurance_paid_cents` across the
    claim's `POSTED` postings."
    PRD §3.6: "When a posting drives a claim's `outstanding_balance_cents` to zero or
    below while the claim is `ACCEPTED`, the claim moves automatically from `ACCEPTED`
    to `PAID`."

    Design: Difficulty/dual_variant_calc/claim_expected_reimbursement_provisional_vs_realized
    """
    claim, _ = _setup_paid_claim_billed_23000(api)
    assert claim["insurance_paid_cents"] == 7000, claim["insurance_paid_cents"]
    assert claim["status"] == "PAID", claim["status"]
    assert claim["expected_reimbursement_cents"] != claim["insurance_paid_cents"]


# ---- Difficulty: dual_variant_calc / billing fee charge-based vs collection-based ----
def test_billing_fee_charge_based_over_gross_charges(api):
    """PRD §3.8: "The **charge-based** figure, `charge_based_fee_cents`, is computed by
    taking each wire claim, multiplying its `billed_amount_cents` by the practice's
    `billing_fee_pct`, rounding that product half-up to a whole cent, and summing those
    per-claim rounded amounts."

    Design: Difficulty/dual_variant_calc/practice_billing_fee_charge_based_vs_collection_based
    """
    _, practice_id = _setup_paid_claim_billed_23000(api)
    data = validate_success(api.get_practice_billing_fee(practice_id, AM), 200)
    assert data["charge_based_fee_cents"] == 1380, data["charge_based_fee_cents"]


def test_billing_fee_collection_based_over_realized_payments(api):
    """PRD §3.8: "The **collection-based** figure, `collection_based_fee_cents`, is
    computed the same way but over only the claims that have realized an insurance
    payment — those in `PAID` or `CLOSED` — multiplying each such claim's
    `insurance_paid_cents` by `billing_fee_pct`, rounding each product half-up per
    claim, and summing."

    Design: Difficulty/dual_variant_calc/practice_billing_fee_charge_based_vs_collection_based
    """
    _, practice_id = _setup_paid_claim_billed_23000(api)
    data = validate_success(api.get_practice_billing_fee(practice_id, AM), 200)
    assert data["collection_based_fee_cents"] == 420, data["collection_based_fee_cents"]
    assert data["charge_based_fee_cents"] != data["collection_based_fee_cents"]


# ---- Difficulty: combinatorial_formula / billing fee round-per-claim-then-sum ----
def _setup_two_submitted_claims_billed_1250(api):
    ctx = fx.setup_billing_context(api, billing_fee_pct=0.05, prices={"99213": 1000},
                                   credential="approved", enrollment="active")
    for _ in range(2):
        claim = fx.new_claim(api, ctx["practice"]["id"], ctx["provider"]["id"],
                             ctx["payer"]["id"], deductible_remaining_cents=0,
                             coinsurance_pct=0.20, copay_cents=0)
        fx.add_claim_line(api, claim["id"], cpt_code="99213", units=1, charge_amount_cents=1250)
        fx.scrub_claim(api, claim["id"], "coder-2")
        fx.submit_claim(api, claim["id"], "biller-2")
    return ctx["practice"]["id"]


def test_billing_fee_rounds_each_claim_before_summing(api):
    """PRD §3.8: "In both variants the half-up rounding is applied to each claim's
    commission before the amounts are summed, never by summing first and rounding once."

    Design: Difficulty/combinatorial_formula/billing_fee_round_per_claim_then_sum
    """
    practice_id = _setup_two_submitted_claims_billed_1250(api)
    data = validate_success(api.get_practice_billing_fee(practice_id, AM), 200)
    assert data["charge_based_fee_cents"] == 126, data["charge_based_fee_cents"]


def test_billing_fee_collection_zero_without_payments(api):
    """PRD §3.8: "The **collection-based** figure, `collection_based_fee_cents`, is
    computed the same way but over only the claims that have realized an insurance
    payment — those in `PAID` or `CLOSED`"

    Design: Difficulty/combinatorial_formula/billing_fee_round_per_claim_then_sum
    """
    practice_id = _setup_two_submitted_claims_billed_1250(api)
    data = validate_success(api.get_practice_billing_fee(practice_id, AM), 200)
    assert data["collection_based_fee_cents"] == 0, data["collection_based_fee_cents"]
