"""Good-Faith-Estimate pricing at issue (the ESTIMATE variant).

Covers self-pay and percent-of-charge pricing, the non-linear OOP cap, the
load-bearing per-line rounding rule, the deductible-met boundary, and
read-after-write immediacy of the issue response.
"""
from test_helpers import fixtures


def _issue_insured(api, plan_over=None, gross=300000, flat=200000,
                   ded_met=0, oop_met=0):
    """Fresh patient (optionally pre-loaded accumulators) + ACTIVE FLAT-rate
    contract + single-line insured estimate; returns the issued estimate."""
    plan = fixtures.new_benefit_plan(api, **(plan_over or {}))
    patient = fixtures.new_patient(api, plan["id"])
    if ded_met or oop_met:
        fixtures.adjust_accumulators(api, patient["id"], ded_met, oop_met)
    contract = fixtures.new_active_contract(api)
    procedure = fixtures.new_procedure(api, gross_charge_cents=gross)
    fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], flat)
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                                     contract_id=contract["id"])
    fixtures.add_line(api, estimate["id"], procedure["id"])
    return fixtures.issue(api, estimate["id"])


# --------------------------------------------------------------------------
# Corner — self-pay and percent-of-charge pricing
# --------------------------------------------------------------------------
def test_self_pay_estimate_pricing(api):
    """PRD §3.4: "For a GFE_SELFPAY estimate a line's allowed_amount_cents is the
    procedure's gross_charge_cents multiplied by 0.65 (the gross charge less the
    35% self-pay discount), rounded half up to whole cents." PRD §3.4: "For a
    GFE_SELFPAY estimate the patient owes the entire allowed amount:
    patient_responsibility_cents equals allowed_amount_cents, while copay_cents
    and plan_paid_cents are both 0."

    Design: Corner/calculations/self_pay_estimate_pricing
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_SELFPAY")
    fixtures.add_line(api, estimate["id"], procedure["id"])
    issued = fixtures.issue(api, estimate["id"])
    assert issued["allowed_amount_cents"] == 195000
    assert issued["patient_responsibility_cents"] == 195000
    assert issued["plan_paid_cents"] == 0
    assert issued["copay_cents"] == 0


def test_percent_of_charge_rate_allowed(api):
    """PRD §3.4: "the allowed amount is that rate's flat_amount_cents when the
    rate is FLAT, or the procedure's gross_charge_cents multiplied by the rate's
    percent_of_charge rounded half up to whole cents when the rate is PERCENT."

    Design: Corner/calculations/percent_of_charge_rate_allowed
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api, methodology="PERCENT_OF_CHARGE")
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    fixtures.ingest_percent_rate(api, contract["id"], procedure["id"], 0.60)
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                                     contract_id=contract["id"])
    fixtures.add_line(api, estimate["id"], procedure["id"])
    issued = fixtures.issue(api, estimate["id"])
    assert issued["allowed_amount_cents"] == 180000
    assert issued["patient_responsibility_cents"] == 118500
    assert issued["plan_paid_cents"] == 61500


def test_issue_reflected_in_response(api):
    """PRD §3.4: "A successful issue advances the estimate from `DRAFT` to
    `ISSUED`, records `issued_at`, sets `responsibility_basis` to `ESTIMATE`, and
    increments the estimate's `version` by 1."

    Design: Corner/consistency_model/immediate_consistency_issue_reflected_in_response
    """
    issued = _issue_insured(api)
    assert issued["status"] == "ISSUED"
    assert issued["allowed_amount_cents"] == 200000
    assert issued["patient_responsibility_cents"] == 122500


# --------------------------------------------------------------------------
# Difficulty — non-linear OOP cap
# --------------------------------------------------------------------------
def test_oop_cap_binds_on_outer_min(api):
    """PRD §3.4: "the remaining out-of-pocket room is the plan's
    individual_oop_max_cents minus the patient's oop_met_cents as of the pricing
    clock, floored at 0; and patient_responsibility_cents is the smaller of the
    pre-cap responsibility and that remaining room."

    Design: Difficulty/combinatorial_formula/cf_estimate_nonlinear_oop_cap
    """
    # deductible fully met (100000) and oop near cap (480000 of 500000).
    issued = _issue_insured(api, ded_met=100000, oop_met=480000)
    assert issued["patient_responsibility_cents"] == 20000


def test_oop_cap_components_and_plan_share(api):
    """PRD §3.4: "a pre-cap responsibility is formed as the estimate's
    deductible_applied_cents plus its coinsurance_cents plus that copay ... The
    plan's share, plan_paid_cents, is the estimate's allowed_amount_cents minus
    patient_responsibility_cents."

    Design: Difficulty/combinatorial_formula/cf_estimate_nonlinear_oop_cap
    """
    issued = _issue_insured(api, ded_met=100000, oop_met=480000)
    assert issued["deductible_applied_cents"] == 0
    assert issued["coinsurance_cents"] == 40000
    assert issued["plan_paid_cents"] == 180000


# --------------------------------------------------------------------------
# Difficulty — per-line coinsurance rounding order
# --------------------------------------------------------------------------
def _issue_two_line_rounding(api):
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    fixtures.adjust_accumulators(api, patient["id"], 100000, 0)  # deductible met
    contract = fixtures.new_active_contract(api)
    proc_a = fixtures.new_procedure(api, code="70450", gross_charge_cents=300000)
    fixtures.ingest_flat_rate(api, contract["id"], proc_a["id"], 100003)
    proc_b = fixtures.new_procedure(api, code="74177", gross_charge_cents=300000)
    fixtures.ingest_flat_rate(api, contract["id"], proc_b["id"], 100003)
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                                     contract_id=contract["id"])
    fixtures.add_line(api, estimate["id"], proc_a["id"])
    fixtures.add_line(api, estimate["id"], proc_b["id"])
    return fixtures.issue(api, estimate["id"])


def test_per_line_rounding_sums_rounded_values(api):
    """PRD §2.5: "per-line coinsurance is rounded to whole cents for each line
    individually, and the already-rounded line values are then summed to produce
    the estimate-level coinsurance. The system never sums unrounded line
    coinsurance and rounds once at the end."

    Design: Difficulty/combinatorial_formula/cf_line_rounding_order
    """
    issued = _issue_two_line_rounding(api)
    # round_half_up(100003 * 0.20) = 20001 per line; 20001 + 20001 = 40002
    # (sum-then-round would give round_half_up(200006 * 0.20) = 40001).
    assert issued["coinsurance_cents"] == 40002


def test_per_line_rounding_rollup(api):
    """PRD §3.4: "The estimate's allowed_amount_cents is the sum of the line
    allowed amounts." PRD §3.4: "patient_responsibility_cents is the smaller of
    the pre-cap responsibility and that remaining room."

    Design: Difficulty/combinatorial_formula/cf_line_rounding_order
    """
    issued = _issue_two_line_rounding(api)
    assert issued["allowed_amount_cents"] == 200006
    assert issued["patient_responsibility_cents"] == 42502  # 40002 coins + 2500 copay
    assert issued["plan_paid_cents"] == 157504


# --------------------------------------------------------------------------
# Difficulty — deductible-met exact boundary
# --------------------------------------------------------------------------
def test_deductible_exactly_met_boundary(api):
    """PRD §3.4: "the remaining deductible is the plan's
    individual_deductible_cents minus that running figure, floored at 0; the
    line's deductible_applied_cents is the smaller of the line's
    allowed_amount_cents and that remaining deductible."

    Design: Difficulty/boundary_precision_check/bpc_deductible_met_exact_boundary
    """
    # dm == D (100000): remaining deductible 0 -> PR = coins 40000 + copay 2500.
    issued = _issue_insured(api, ded_met=100000, oop_met=0)
    assert issued["patient_responsibility_cents"] == 42500


def test_deductible_one_cent_short_boundary(api):
    """PRD §3.4: "the line's deductible_applied_cents is the smaller of the
    line's allowed_amount_cents and that remaining deductible ... the line's
    coinsurance_cents is the plan's coinsurance_rate applied to the line's
    allowed amount less its deductible portion, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/bpc_deductible_met_exact_boundary
    """
    # dm == D-1 (99999): remaining deductible 1 -> deductible_applied 1,
    # coins round_half_up((200000-1)*0.20)=40000, copay 2500 -> PR 42501.
    issued = _issue_insured(api, ded_met=99999, oop_met=0)
    assert issued["patient_responsibility_cents"] == 42501
