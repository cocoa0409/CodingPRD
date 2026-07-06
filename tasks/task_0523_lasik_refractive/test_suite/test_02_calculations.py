"""Screening-submit computations, amortized financing, and dual-variant refunds.

Translates queue-A difficulty instances under dual_variant_calc and
combinatorial_formula, plus the queue-B cross-reference-link corner instances.
"""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS,
    make_optometrist_headers, make_surgeon_headers,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


def test_ablation_then_residual_pinned_order(api):
    """PRD §3.2: "form the product of the square of the optical zone in
    millimeters (a fixed 1.0 mm), the screening's own `refractive_error_diopters`,
    and the depth removed per diopter (a fixed 12.0 microns per diopter), then
    round that single product to the nearest whole micron using round-half-up,
    and store it as `ablation_depth_um`."
    PRD §3.2: "take `corneal_thickness_um`, subtract the fixed flap thickness of
    110 microns, then subtract `ablation_depth_um`, and store the whole-micron
    result as `residual_stromal_bed_um`."

    Design: Difficulty/combinatorial_formula/ablation_then_residual_ordered_dependency
    """
    od = fx.create_optometrist()
    pat = fx.create_patient()
    scr = fx.create_submitted_screening(
        od["id"], pat["id"], corneal_thickness_um=550, refractive_error_diopters=3.0,
    )
    # 1.0^2 * 3.0 * 12.0 = 36 ; 550 - 110 - 36 = 404
    assert scr["ablation_depth_um"] == 36
    assert scr["residual_stromal_bed_um"] == 404


def test_ablation_residual_second_input_set(api):
    """PRD §3.2: "form the product of the square of the optical zone in
    millimeters (a fixed 1.0 mm), the screening's own `refractive_error_diopters`,
    and the depth removed per diopter (a fixed 12.0 microns per diopter), then
    round that single product to the nearest whole micron using round-half-up,
    and store it as `ablation_depth_um`."
    PRD §3.2: "take `corneal_thickness_um`, subtract the fixed flap thickness of
    110 microns, then subtract `ablation_depth_um`, and store the whole-micron
    result as `residual_stromal_bed_um`."

    Design: Difficulty/combinatorial_formula/ablation_then_residual_ordered_dependency
    """
    od = fx.create_optometrist()
    pat = fx.create_patient()
    scr = fx.create_submitted_screening(
        od["id"], pat["id"], corneal_thickness_um=496, refractive_error_diopters=3.0,
    )
    # 1.0^2 * 3.0 * 12.0 = 36 ; 496 - 110 - 36 = 350
    assert scr["ablation_depth_um"] == 36
    assert scr["residual_stromal_bed_um"] == 350


def test_amortized_installment_compound_interest(api):
    """PRD §3.4: "Convert the annual rate to a decimal monthly rate by dividing
    `apr_bps` by 10000 and then by 12. If that monthly rate is zero, the raw
    installment is simply the principal divided by `term_months`. Otherwise, raise
    the quantity (one plus the monthly rate) to the power of `term_months` to
    obtain a growth factor, then the raw installment is the principal multiplied
    by the monthly rate multiplied by that growth factor, all divided by the
    growth factor minus one. Finally, round the raw installment **up** to a whole
    number of cents and store it as `monthly_installment_cents`."

    Design: Difficulty/combinatorial_formula/amortized_installment_three_input_nonlinear
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    plan = validate_success(api.create_financing(
        case["id"], {"down_payment_cents": 100000, "term_months": 12, "apr_bps": 1200}, COORD,
    ), expected_status=201)
    # principal 400000, r = 1200/10000/12 = 0.01, factor = 1.01^12 -> ceil = 35540
    assert plan["monthly_installment_cents"] == 35540


def test_amortized_installment_recorded_open_plan(api):
    """PRD §3.4: "For an open plan, the **amortized monthly installment** is
    computed once at creation from the financed principal, which is the package's
    `base_price_cents` minus the `down_payment_cents`."
    PRD §3.4: "Finally, round the raw installment **up** to a whole number of
    cents and store it as `monthly_installment_cents`."

    Design: Difficulty/combinatorial_formula/amortized_installment_three_input_nonlinear
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    plan = validate_success(api.create_financing(
        case["id"], {"down_payment_cents": 100000, "term_months": 12, "apr_bps": 1200}, COORD,
    ), expected_status=201)
    assert plan["status"] == "OPEN"
    assert plan["monthly_installment_cents"] == 35540


def test_financing_deposit_paid_vs_paid_in_full(api):
    """PRD §3.4: "When the down payment covers at least the deposit but is
    strictly less than the package's `base_price_cents`, an `OPEN` plan is
    created, its computed `monthly_installment_cents` is set, its
    `amount_settled_cents` is initialized to the down payment, and the case moves
    to `DEPOSIT_PAID`. When the down payment equals the package's
    `base_price_cents` exactly, the case is paid outright: the plan is created
    already `SETTLED` with `term_months` coerced to 1 and `amount_settled_cents`
    equal to the base price, and the case moves straight to `PAID_IN_FULL`."

    Design: Difficulty/dual_variant_calc/financing_deposit_paid_vs_paid_in_full_variant
    """
    cfg = fx.setup_config()
    base = cfg["package"]["base_price_cents"]
    case1, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    case2, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])

    plan1 = validate_success(api.create_financing(
        case1["id"], {"down_payment_cents": 100000, "term_months": 12, "apr_bps": 1200}, COORD,
    ), expected_status=201)
    plan2 = validate_success(api.create_financing(
        case2["id"], {"down_payment_cents": base, "term_months": 1, "apr_bps": 0}, COORD,
    ), expected_status=201)

    assert plan1["status"] == "OPEN"
    assert validate_success(api.get_case(case1["id"], COORD))["financial_status"] == "DEPOSIT_PAID"
    assert plan2["status"] == "SETTLED"
    assert validate_success(api.get_case(case2["id"], COORD))["financial_status"] == "PAID_IN_FULL"


def test_financing_settled_plan_coerces_term_and_settled_amount(api):
    """PRD §3.4: "the plan is created already `SETTLED` with `term_months` coerced
    to 1 and `amount_settled_cents` equal to the base price, and the case moves
    straight to `PAID_IN_FULL`."

    Design: Difficulty/dual_variant_calc/financing_deposit_paid_vs_paid_in_full_variant
    """
    cfg = fx.setup_config()
    base = cfg["package"]["base_price_cents"]
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    plan = validate_success(api.create_financing(
        case["id"], {"down_payment_cents": base, "term_months": 1, "apr_bps": 0}, COORD,
    ), expected_status=201)
    assert plan["status"] == "SETTLED"
    assert plan["amount_settled_cents"] == base


def test_refund_payout_pro_rata_variant(api):
    """PRD §3.9: "Under `PRO_RATA`, the payout is the settled amount minus the
    package's non-refundable `deposit_cents`, floored at zero so it is never
    negative."

    Design: Difficulty/dual_variant_calc/refund_payout_pro_rata_vs_deposit_forfeit
    """
    ctx = fx.setup_healed_with_pending_refund()  # PRO_RATA default package, base 500000, deposit 50000
    paid = validate_success(api.adjudicate_refund_claim(
        ctx["claim"]["id"], {"decision": "PAY"}, COORD,
    ))
    # settled 500000 - deposit 50000 = 450000
    assert paid["refund_amount_cents"] == 450000


def test_refund_payout_deposit_forfeit_variant(api):
    """PRD §3.9: "Under `DEPOSIT_FORFEIT`, the payout is the settled amount minus
    the package's `deposit_cents` and minus a fixed guarantee-processing fee of
    25000 cents, again floored at zero; this variant is the larger clawback
    because it also withholds the processing fee."

    Design: Difficulty/dual_variant_calc/refund_payout_pro_rata_vs_deposit_forfeit
    """
    # Build a DEPOSIT_FORFEIT-package case end to end.
    pkg = fx.create_package(refund_mode="DEPOSIT_FORFEIT")
    suite = fx.create_suite()
    surgeon = fx.create_surgeon()
    od = fx.create_optometrist()
    case, patient = fx.create_planned_case(pkg["id"], od["id"], surgeon["id"])
    fx.fund_case_in_full(case["id"], pkg["base_price_cents"])
    fx.set_clock("2026-06-01T12:00:00Z")
    fresh = validate_success(api.get_case(case["id"], COORD))
    fx.create_booking(case["id"], suite["id"], surgeon["id"], fresh["version"])
    validate_success(api.create_consent(
        case["id"], {"drops_regimen_started": True, "signed_by_patient_id": patient["id"]},
        fx.make_patient_headers(patient["id"]),
    ), expected_status=201)
    validate_success(api.operate_case(case["id"], make_surgeon_headers(surgeon["id"])))
    fx.set_clock("2026-07-02T00:00:00Z")
    validate_success(api.heal_case(case["id"], {"final_uncorrected_va": 0.5}, make_surgeon_headers(surgeon["id"])))
    claim = validate_success(api.create_refund_claim({"case_id": case["id"]}, COORD), expected_status=201)
    paid = validate_success(api.adjudicate_refund_claim(claim["id"], {"decision": "PAY"}, COORD))
    # settled 500000 - deposit 50000 - fee 25000 = 425000
    assert paid["refund_amount_cents"] == 425000


def test_fk_reverse_list_case_bookings(api):
    """PRD §2.9: "Several read paths address a child collection through a parent
    (for example, a case's bookings ...)."
    PRD §3.5: "A successful booking is created with status `ACTIVE`, the case
    advances to `SCHEDULED`, and the case's `version` increments by one."

    Design: Corner/endpoints/fk_reverse_list_case_bookings
    """
    ctx = fx.setup_scheduled_case(pay_in_full=True)
    data, _ = validate_paginated(api.list_case_bookings(ctx["case"]["id"], COORD))
    assert len(data) == 1
    assert data[0]["status"] == "ACTIVE"


def test_fk_reverse_list_patient_screenings(api):
    """PRD §2.9: "Several read paths address a child collection through a parent
    (for example, ... or a patient's screenings)."

    Design: Corner/endpoints/fk_reverse_list_patient_screenings
    """
    od = fx.create_optometrist()
    pat = fx.create_patient()
    validate_success(api.create_screening(
        fx.F.create_screening_payload(pat["id"], od["id"]),
        make_optometrist_headers(od["id"]),
    ), expected_status=201)
    data, _ = validate_paginated(api.list_patient_screenings(pat["id"], COORD))
    assert len(data) == 1
