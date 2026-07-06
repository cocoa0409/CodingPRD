"""The billing ledger: dual estimate/final variants, the whole-vial drug line, the
copay waterfall with deductible/coinsurance/OOP-cap nesting.

Translates Queue A (Difficulty) rules: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    fixtures,
    assert_claim_ledger,
)

PHARM = TEST_USERS["pharmacist_headers"]
BILLER = TEST_USERS["biller_headers"]

# Vanco profile used across the dual-variant tests:
#   vial_size_mg=1000, awp_per_vial_cents=4250, therapy AMINOGLYCOSIDE_OR_VANCO
#   PayerPlan PA: per_diem 12500, awp_discount 0.18, coinsurance 0.20,
#                 deductible 30000, oop 50000
PA_PLAN = {
    "per_diem_rate_cents": {"AMINOGLYCOSIDE_OR_VANCO": 12500},
    "awp_discount_pct": 0.18,
    "coinsurance_pct": 0.20,
    "deductible_remaining_cents": 30000,
    "oop_max_remaining_cents": 50000,
}
VANCO_DRUG = {
    "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
    "vial_size_mg": 1000,
    "awp_per_vial_cents": 4250,
    "lot_total_vials": 100,
}


def _setup_order_admin4_sched7(api):
    """Vanco order, scheduled_days=7, daily_dose_mg=2000, with exactly 4 visits
    COMPLETED so administered_days=4; order is ACTIVE. Returns ctx."""
    return fixtures.setup_active_order_with_completed_visits(
        num_completed=4,
        scheduled_days=7,
        drug_overrides=VANCO_DRUG,
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )


# === dual_variant_calc / claim_estimate_vs_final_allowed_total_on_order ===
def test_claim_estimate_variant_bills_scheduled_days(api):
    """PRD 3.12: "Under `ESTIMATE` the billed-day count is the order's `scheduled_days`."
    PRD 3.12: "The claim's `allowed_total_cents` is the sum of `per_diem_cents` and `drug_allowed_cents`."

    Design: Difficulty/dual_variant_calc/claim_estimate_vs_final_allowed_total_on_order
    """
    ctx = _setup_order_admin4_sched7(api)
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    data = validate_success(api.get_claim(claim["id"], BILLER))
    assert data["variant"] == "ESTIMATE"
    assert data["billed_days"] == 7, f"ESTIMATE bills scheduled_days=7, got {data['billed_days']}"
    assert data["allowed_total_cents"] == 136290, f"got {data['allowed_total_cents']}"
    assert_claim_ledger(data)


def test_claim_final_variant_bills_administered_days_on_post(api):
    """PRD 3.12: "Under `FINAL` the billed-day count is the order's `administered_days`, which is the count of that order's visits in `COMPLETED`."
    PRD 3.12: "Posting the claim, moving `DRAFT` to `POSTED`, recomputes every figure under the `FINAL` variant, sets `variant` to `FINAL`"

    Design: Difficulty/dual_variant_calc/claim_estimate_vs_final_allowed_total_on_order
    """
    ctx = _setup_order_admin4_sched7(api)
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    posted = validate_success(api.post_claim(claim["id"], BILLER))
    assert posted["variant"] == "FINAL"
    assert posted["billed_days"] == 4, f"FINAL bills administered_days=4, got {posted['billed_days']}"
    assert posted["allowed_total_cents"] == 77880, f"got {posted['allowed_total_cents']}"
    assert_claim_ledger(posted)


# === dual_variant_calc / ae_severity_grade_vs_resume_scoring_on_adverse_event ===
def test_estimate_claim_reads_but_does_not_debit_accumulators(api):
    """PRD 3.12: "on creation the server computes the estimate figures and reads — but
    does not change — the payer plan's accumulators."
    PRD 2.10: "These accumulators are read but **not** changed while a claim is only an estimate."

    Design: Difficulty/dual_variant_calc/ae_severity_grade_vs_resume_scoring_on_adverse_event
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=1,
        drug_overrides=VANCO_DRUG,
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    data = validate_success(api.get_claim(claim["id"], BILLER))
    assert data["variant"] == "ESTIMATE"
    plan = validate_success(api.get_payer_plan(ctx["plan"]["id"], BILLER))
    assert plan["deductible_remaining_cents"] == 30000, "ESTIMATE must not debit the deductible"
    assert plan["oop_max_remaining_cents"] == 50000, "ESTIMATE must not debit the OOP max"


def test_adverse_event_severity_score_weighted_sum(api):
    """PRD 3.9: "The score is the grade weighted by two, plus the reaction count weighted by one, plus the vital-instability flag weighted by three — that is, two times `severity_grade`, plus one times `reaction_count`, plus three times `vital_instability` — yielding an integer."

    Design: Difficulty/dual_variant_calc/ae_severity_grade_vs_resume_scoring_on_adverse_event
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=1,
        drug_overrides=VANCO_DRUG,
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    # grade3 react1 vital0 => 2*3 + 1*1 + 3*0 = 7
    ae = fixtures.report_adverse_event(
        ctx["order"]["id"], nurse_id=ctx["nurse"]["id"],
        severity_grade=3, reaction_count=1, vital_instability=0,
    )
    assert ae["severity_score"] == 7, f"2*3+1*1+3*0==7, got {ae['severity_score']}"


# === combinatorial_formula / copay_waterfall_three_input_nonlinear_with_oop_cap ===
def test_copay_waterfall_clamps_patient_responsibility_to_oop_cap(api):
    """PRD 3.12: "the deductible applied is the smaller of the plan's `deductible_remaining_cents` and the allowed total ... the coinsurance amount is the remainder multiplied by the plan's `coinsurance_pct`, rounded half up to whole cents ...
    the patient's responsibility is the smaller of that pre-cap amount and the plan's `oop_max_remaining_cents`."

    Design: Difficulty/combinatorial_formula/copay_waterfall_three_input_nonlinear_with_oop_cap
    """
    # allowed_total 136290; ded 30000 applied; after_ded 106290; coins round(106290*0.20)=21258;
    # pre-cap 30000+21258=51258 clamped to oop 50000; plan_paid 136290-50000=86290
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=7,
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    data = validate_success(api.get_claim(claim["id"], BILLER))
    assert data["allowed_total_cents"] == 136290, f"got {data['allowed_total_cents']}"
    assert data["patient_responsibility_cents"] == 50000, (
        f"clamped to OOP cap 50000, got {data['patient_responsibility_cents']}"
    )
    assert data["plan_paid_cents"] == 86290, f"got {data['plan_paid_cents']}"
    assert_claim_ledger(data)


def test_copay_waterfall_deductible_bucket_resolved_first(api):
    """PRD 3.12: "First, the deductible bucket absorbs first: the deductible applied is the smaller of the plan's `deductible_remaining_cents` and the allowed total ... The
    deductible bucket is always resolved before the coinsurance bucket, and the
    out-of-pocket cap is always applied last."

    Design: Difficulty/combinatorial_formula/copay_waterfall_three_input_nonlinear_with_oop_cap
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=7,
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    data = validate_success(api.get_claim(claim["id"], BILLER))
    # Patient responsibility (50000) exceeds the bare deductible (30000): the deductible
    # was absorbed first and coinsurance stacked on top before the OOP clamp.
    assert data["patient_responsibility_cents"] == 50000
    assert data["patient_responsibility_cents"] > 30000, (
        "deductible bucket alone is 30000; coinsurance must stack on top before the cap"
    )


# === combinatorial_formula / drug_line_whole_vial_ceiling_before_discount_rounding_order ===
def test_drug_line_whole_vial_ceiling_applied_before_discount(api):
    """PRD 3.12: "the billed vial count is the daily dose multiplied by the billed-day count, divided by the drug's `vial_size_mg`, rounded **up** to the next whole vial ...
    the gross amount is that whole vial count multiplied by the drug's `awp_per_vial_cents ... the allowed drug line is the gross amount multiplied by one minus the plan's `awp_discount_pct`, and this single discounted product is rounded half up to whole cents to become the drug line."

    Design: Difficulty/combinatorial_formula/drug_line_whole_vial_ceiling_before_discount_rounding_order
    """
    # daily=1500, sched=3, vial=1000 => ceil(4500/1000)=5 units; awp 4255; gross 21275;
    # *0.82 = 17445.5 -> round half up -> 17446 (not 17445)
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=3,
        drug_overrides={
            "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
            "vial_size_mg": 1000,
            "awp_per_vial_cents": 4255,
            "is_specialty": False,
        },
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 1500},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    data = validate_success(api.get_claim(claim["id"], BILLER))
    assert data["drug_allowed_cents"] == 17446, (
        f"ceil(4500/1000)=5 *4255=21275 *0.82=17445.5 round-half-up=17446, got {data['drug_allowed_cents']}"
    )


def test_drug_line_rounding_is_half_up_not_truncation(api):
    """PRD 2.5: "Where a calculation produces a fractional cent, it is rounded **half up** (a value at the exact half rounds away from zero to the next whole cent)."
    PRD 3.12: "this single discounted product is rounded half up to whole cents to
    become the drug line."

    Design: Difficulty/combinatorial_formula/drug_line_whole_vial_ceiling_before_discount_rounding_order
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=3,
        drug_overrides={
            "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
            "vial_size_mg": 1000,
            "awp_per_vial_cents": 4255,
            "is_specialty": False,
        },
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 1500},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    data = validate_success(api.get_claim(claim["id"], BILLER))
    # 17445.5 truncates to 17445; half-up gives 17446. Assert the half-up outcome.
    assert data["drug_allowed_cents"] != 17445, "truncation (17445) is wrong; half-up is required"
    assert data["drug_allowed_cents"] == 17446
