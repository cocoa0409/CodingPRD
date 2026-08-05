"""Benefit estimation, dual-variant estimate-vs-final, and coordination of benefits.

Difficulty instances: dual_variant_calc (x2), combinatorial_formula (x2).
"""
from test_helpers import validate_success, get_success_data, make_biller_headers, make_manager_headers
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# dual_variant_calc / estimate_vs_final_patient_portion
# --------------------------------------------------------------------------
def _crown_prophy_submitted(api):
    """Clock 2026-05-10; P1 plan; crown+prophy claim submitted. Returns (pid, claim)."""
    fx.set_clock(api, "2026-05-10T00:00:00Z")
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, deductible_cents=5000,
                       deductible_applies_to=["BASIC", "MAJOR"],
                       preventive_coinsurance_pct=100, basic_coinsurance_pct=80,
                       major_coinsurance_pct=50)
    fx.new_procedure(api, cdt_code="D2740", description="Crown", category="MAJOR",
                     ucr_fee_cents=120000)
    fx.new_procedure(api, cdt_code="D1110", description="Prophy", category="PREVENTIVE",
                     ucr_fee_cents=10000, frequency_limit_per_year=2)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000},
                          {"cdt_code": "D1110", "billed_fee_cents": 12000}],
                         service_date="2026-05-10")
    submitted = fx.submit_claim(api, claim["id"], submit_user="biller_alice")
    return patient["id"], submitted


def test_estimate_patient_portion_on_submit(api):
    """PRD §3.5: "After all lines, `estimated_patient_portion_cents` is
    `total_billed_cents` minus `estimated_insurance_cents`."

    Design: Difficulty/dual_variant_calc/estimate_vs_final_patient_portion
    """
    _pid, claim = _crown_prophy_submitted(api)
    assert claim["estimated_insurance_cents"] == 67500, \
        f"expected 67500, got {claim['estimated_insurance_cents']}"
    assert claim["estimated_patient_portion_cents"] == 74500, \
        f"expected 74500, got {claim['estimated_patient_portion_cents']}"


def test_final_settlement_differs_from_estimate(api):
    """PRD §3.6: "`paid_insurance_cents` becomes the sum of the paid amounts on
    the EOB lines ... `final_patient_portion_cents` becomes `total_billed_cents`
    minus `paid_insurance_cents`. Because the final settlement uses the carrier's
    actual paid amounts rather than the pre-service forecast,
    `final_patient_portion_cents` generally differs from the earlier
    `estimated_patient_portion_cents`."

    Design: Difficulty/dual_variant_calc/estimate_vs_final_patient_portion
    """
    pid, submitted = _crown_prophy_submitted(api)
    # EOB pays crown 52500 + prophy 10000 = 62500 (less than the 67500 estimate).
    fx.get_success_data(api.create_payment(
        {"patient_id": pid, "payer_type": "INSURANCE", "amount_cents": 62500,
         "claim_id": submitted["id"], "is_denial": False,
         "eob_lines": [{"cdt_code": "D2740", "allowed_cents": 110000,
                        "paid_cents": 52500, "deductible_applied_cents": 5000},
                       {"cdt_code": "D1110", "allowed_cents": 10000,
                        "paid_cents": 10000, "deductible_applied_cents": 0}]},
        make_manager_headers("mgr_bob")))
    claim = get_success_data(api.get_claim(submitted["id"], make_biller_headers()))
    assert claim["paid_insurance_cents"] == 62500, \
        f"expected 62500, got {claim['paid_insurance_cents']}"
    assert claim["final_patient_portion_cents"] == 79500, \
        f"expected 79500, got {claim['final_patient_portion_cents']}"
    assert claim["final_patient_portion_cents"] != claim["estimated_patient_portion_cents"]


# --------------------------------------------------------------------------
# dual_variant_calc / cob_standard_vs_non_duplication
# --------------------------------------------------------------------------
def _cob_setup(api):
    """Primary crown claim adjudicated (paid 57500); two secondary claims (STANDARD
    and NON_DUPLICATION) off the same primary, both created DRAFT. Returns
    (pid, c_std_id, c_non_id)."""
    patient = fx.new_patient(api)
    pa = fx.new_plan(api, payer_name="PrimaryCo", plan_name="PA",
                     annual_maximum_cents=150000, deductible_cents=5000,
                     major_coinsurance_pct=50, cob_method="STANDARD")
    sstd = fx.new_plan(api, payer_name="SecStd", plan_name="S_STD",
                       annual_maximum_cents=150000, deductible_cents=5000,
                       major_coinsurance_pct=50, cob_method="STANDARD")
    snon = fx.new_plan(api, payer_name="SecNon", plan_name="S_NON",
                       annual_maximum_cents=150000, deductible_cents=5000,
                       major_coinsurance_pct=50, cob_method="NON_DUPLICATION")
    fx.new_procedure(api, cdt_code="D2740", description="Crown", category="MAJOR",
                     ucr_fee_cents=120000)
    covp = fx.new_coverage(api, patient["id"], pa["id"], priority="PRIMARY",
                           subscriber_id="SA")
    fx.new_verification(api, covp)
    covs1 = fx.new_coverage(api, patient["id"], sstd["id"], priority="SECONDARY",
                            subscriber_id="SB")
    fx.new_verification(api, covs1)
    covs2 = fx.new_coverage(api, patient["id"], snon["id"], priority="SECONDARY",
                            subscriber_id="SC")
    fx.new_verification(api, covs2)
    c0 = fx.new_claim(api, patient["id"], covp["id"],
                      [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    fx.submit_claim(api, c0["id"], submit_user="biller_alice")
    fx.post_insurance_eob(api, patient["id"], c0["id"], amount_cents=57500,
                          allowed_cents=120000, paid_cents=57500,
                          deductible_applied_cents=5000, post_user="mgr_bob")
    c1 = fx.new_claim(api, patient["id"], covs1["id"],
                      [{"cdt_code": "D2740", "billed_fee_cents": 130000}],
                      primary_claim_id=c0["id"])
    c2 = fx.new_claim(api, patient["id"], covs2["id"],
                      [{"cdt_code": "D2740", "billed_fee_cents": 130000}],
                      primary_claim_id=c0["id"])
    return patient["id"], c1["id"], c2["id"]


def test_secondary_standard_cob_benefit(api):
    """PRD §3.5: "If the secondary plan's `cob_method` is `STANDARD`, the
    secondary benefit is the lesser of the normal benefit and the post-primary
    remainder."

    Design: Difficulty/dual_variant_calc/cob_standard_vs_non_duplication
    """
    _pid, c_std, _c_non = _cob_setup(api)
    submitted = fx.submit_claim(api, c_std, submit_user="biller_alice")
    assert submitted["estimated_insurance_cents"] == 57500, \
        f"expected 57500 (STANDARD), got {submitted['estimated_insurance_cents']}"


def test_secondary_non_duplication_cob_benefit(api):
    """PRD §3.5: "If it is `NON_DUPLICATION`, the secondary benefit is the greater
    of 0 and the normal benefit minus what the primary already paid — which is
    frequently 0."

    Design: Difficulty/dual_variant_calc/cob_standard_vs_non_duplication
    """
    _pid, _c_std, c_non = _cob_setup(api)
    submitted = fx.submit_claim(api, c_non, submit_user="biller_alice")
    assert submitted["estimated_insurance_cents"] == 0, \
        f"expected 0 (NON_DUPLICATION), got {submitted['estimated_insurance_cents']}"


# --------------------------------------------------------------------------
# combinatorial_formula / tiered_nonlinear_estimate_mode_a
# --------------------------------------------------------------------------
def test_tiered_nonlinear_estimate_value(api):
    """PRD §3.5: "the line's allowed amount is the lesser of its `billed_fee_cents`
    and the procedure's `ucr_fee_cents` ... If the procedure's category is among
    the plan's `deductible_applies_to` set, the system takes a deductible bite
    equal to the lesser of the remaining deductible and the allowed amount."

    Design: Difficulty/combinatorial_formula/tiered_nonlinear_estimate_mode_a
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, deductible_cents=5000,
                       deductible_applies_to=["BASIC", "MAJOR"],
                       preventive_coinsurance_pct=100, basic_coinsurance_pct=80,
                       major_coinsurance_pct=50)
    fx.new_procedure(api, cdt_code="D2740", description="Crown", category="MAJOR",
                     ucr_fee_cents=120000)
    fx.new_procedure(api, cdt_code="D1110", description="Prophy", category="PREVENTIVE",
                     ucr_fee_cents=10000, frequency_limit_per_year=2)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000},
                          {"cdt_code": "D1110", "billed_fee_cents": 12000}])
    submitted = fx.submit_claim(api, claim["id"], submit_user="biller_alice")
    assert submitted["estimated_insurance_cents"] == 67500, \
        f"expected 67500, got {submitted['estimated_insurance_cents']}"


def test_tiered_nonlinear_total_billed(api):
    """PRD §3.5: "On creation the system computes `total_billed_cents` as the sum
    of the line `billed_fee_cents` values."

    Design: Difficulty/combinatorial_formula/tiered_nonlinear_estimate_mode_a
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, deductible_cents=5000,
                       deductible_applies_to=["BASIC", "MAJOR"],
                       major_coinsurance_pct=50)
    fx.new_procedure(api, cdt_code="D2740", description="Crown", category="MAJOR",
                     ucr_fee_cents=120000)
    fx.new_procedure(api, cdt_code="D1110", description="Prophy", category="PREVENTIVE",
                     ucr_fee_cents=10000, frequency_limit_per_year=2)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000},
                          {"cdt_code": "D1110", "billed_fee_cents": 12000}])
    assert claim["total_billed_cents"] == 142000, \
        f"expected 142000, got {claim['total_billed_cents']}"


# --------------------------------------------------------------------------
# combinatorial_formula / per_line_rounding_order_mode_b
# --------------------------------------------------------------------------
def _rounding_submitted(api):
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, payer_name="Rnd", plan_name="P2",
                       annual_maximum_cents=1000000, deductible_cents=0,
                       deductible_applies_to=[], major_coinsurance_pct=50)
    fx.new_procedure(api, cdt_code="D2000A", description="MajA", category="MAJOR",
                     ucr_fee_cents=12345)
    fx.new_procedure(api, cdt_code="D2000B", description="MajB", category="MAJOR",
                     ucr_fee_cents=6789)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov, verified_annual_maximum_cents=1000000,
                        verified_deductible_cents=0)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2000A", "billed_fee_cents": 12345},
                          {"cdt_code": "D2000B", "billed_fee_cents": 6789}])
    return fx.submit_claim(api, claim["id"], submit_user="biller_alice")


def test_per_line_rounding_estimate(api):
    """PRD §2.5: "The benefit estimate is deliberately computed **per line and
    then summed**: each procedure line's benefit is rounded half up before it is
    added into the running total, rather than summing exact values and rounding
    once at the end."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_mode_b
    """
    claim = _rounding_submitted(api)
    # round(6172.5)+round(3394.5) = 6173+3395 = 9568 (not sum-then-round 9567).
    assert claim["estimated_insurance_cents"] == 9568, \
        f"expected 9568, got {claim['estimated_insurance_cents']}"


def test_per_line_rounding_patient_portion(api):
    """PRD §3.5: "After all lines, `estimated_patient_portion_cents` is
    `total_billed_cents` minus `estimated_insurance_cents`."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_mode_b
    """
    claim = _rounding_submitted(api)
    assert claim["estimated_patient_portion_cents"] == 9566, \
        f"expected 9566, got {claim['estimated_patient_portion_cents']}"
