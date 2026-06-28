"""Depth tests for the two-variant pricing engine: forward-looking cart estimate
vs chronological order invoice, per-line round-then-sum, and the pinned HSA
capture-split evaluation order.

All expected values are copied verbatim from the design index; none recomputed.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/pricing_cart_estimate_vs_order_final_invoice_diverge
# ---------------------------------------------------------------------------
def test_cart_estimate_includes_bundle_with_tier_discount(api):
    """PRD 3.3: "Starting from the multiset of the cart's line test codes, a
    bundle qualifies if every one of its member_test_codes still has an unmatched
    line available; when it qualifies, the bundle's bundle_price_cents is added
    to the running subtotal and those member lines' codes are consumed so no
    later bundle or line reuses them."
    PRD 3.3: "When the subtotal is at least 50000 cents (five hundred dollars),
    the platform rate is 0.15; otherwise, when the subtotal is at least 20000
    cents (two hundred dollars), the platform rate is 0.10; otherwise the rate
    is zero."

    Bundle WELLNESS3 {A,B,C}@9000 + standalone D@30000: subtotal 9000+30000=39000
    -> tier1 10% -> 39000 - 3900 = 35100.

    Design: Difficulty/dual_variant_calc/pricing_cart_estimate_vs_order_final_invoice_diverge
    """
    off_a = fx.create_offering(api=api, test_code="A", display_name="Test A", list_price_cents=4000, specimen_type="BLOOD")
    off_b = fx.create_offering(api=api, test_code="B", display_name="Test B", list_price_cents=4000, specimen_type="BLOOD")
    off_c = fx.create_offering(api=api, test_code="C", display_name="Test C", list_price_cents=4000, specimen_type="BLOOD")
    off_d = fx.create_offering(api=api, test_code="D", display_name="Test D", list_price_cents=30000, specimen_type="BLOOD")
    fx.create_bundle(["A", "B", "C"], api=api, bundle_code="WELLNESS3", display_name="Wellness 3", bundle_price_cents=9000)
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    for off in (off_a, off_b, off_c, off_d):
        fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)

    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["estimated_total_cents"] == 35100, (
        f"Expected forward-looking estimate 35100, got {cart_read['estimated_total_cents']}"
    )


def test_order_invoice_voids_partial_bundle_diverges_from_estimate(api):
    """PRD 3.6: "Bundle substitution runs only over the billable resulted lines,
    so a bundle's flat bundle_price_cents applies only when all of its members
    are RESULTED — a partially-resulted bundle instead bills its resulted members
    individually at line price, using each line's unit_list_price_cents and
    repeat_discount_applied."
    PRD 3.6: "It is recomputed every time an order line reaches RESULTED through
    a result release and every time a specimen is rejected, and it writes the
    order's invoiced_total_cents, hsa_applied_cents, and patient_due_cents."

    With only D (30000) resulted and A,B,C rejected, the WELLNESS3 bundle voids;
    invoice over {D} = 30000 -> tier1 10% -> 27000, diverging from the 35100 cart
    estimate.

    Design: Difficulty/dual_variant_calc/pricing_cart_estimate_vs_order_final_invoice_diverge
    """
    off_a = fx.create_offering(api=api, test_code="A", display_name="Test A", list_price_cents=4000, specimen_type="BLOOD", home_kit_eligible=True)
    off_b = fx.create_offering(api=api, test_code="B", display_name="Test B", list_price_cents=4000, specimen_type="BLOOD", home_kit_eligible=True)
    off_c = fx.create_offering(api=api, test_code="C", display_name="Test C", list_price_cents=4000, specimen_type="BLOOD", home_kit_eligible=True)
    off_d = fx.create_offering(api=api, test_code="D", display_name="Test D", list_price_cents=30000, specimen_type="BLOOD", home_kit_eligible=True)
    fx.create_bundle(["A", "B", "C"], api=api, bundle_code="WELLNESS3", display_name="Wellness 3", bundle_price_cents=9000)
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    for off in (off_a, off_b, off_c, off_d):
        fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    order = fx.checkout(cart["id"], patient["id"], "HOME_KIT", api=api)
    fx.ship_home_kit(order["id"], patient["id"], "CA", api=api)
    lines = fx.order_lines_for(order["id"], api=api)
    # lines are created in cart-line order: A, B, C, D
    line_d = next(l for l in lines if l["test_code"] == "D")
    lines_abc = [l for l in lines if l["test_code"] in ("A", "B", "C")]

    # Reject A, B, C specimens; result D.
    for l in lines_abc:
        spec = fx.collect_line(l["id"], api=api)
        get_success_data(api.reject_specimen(spec["id"], LAB))
    spec_d = fx.collect_line(line_d["id"], api=api)
    res_d = fx.process_specimen(spec_d["id"], 5, api=api)
    get_success_data(api.release_lab_result(res_d["id"], LAB2))

    order_after = validate_success(api.get_order(order["id"], ADMIN))
    assert order_after["invoiced_total_cents"] == 27000, (
        f"Expected chronological invoice 27000, got {order_after['invoiced_total_cents']}"
    )
    # Estimate (35100) diverges from chronological invoice (27000).
    assert order_after["invoiced_total_cents"] != 35100


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/per_line_repeat_discount_rounds_then_sums_mode_b
# ---------------------------------------------------------------------------
def test_repeat_discount_rounds_per_line_then_sums(api):
    """PRD 3.3: "If the line's repeat_discount_applied is true, the line's net
    price is the base multiplied by one minus the repeat discount rate of 0.15
    — that is, fifteen percent off — rounded half-up to a whole cent at this
    point, per line."
    PRD 3.3: "The rounding happens per line and the results are then summed; it
    is never summed first and rounded once."

    Two repeat-eligible RPT lines @110: round_half_up(110*0.85)=94 each -> sum 188
    (sum-then-round would yield 187).

    Design: Difficulty/combinatorial_formula/per_line_repeat_discount_rounds_then_sums_mode_b
    """
    off_rpt = fx.create_offering(api=api, test_code="RPT", display_name="Repeat Cheap", list_price_cents=110, specimen_type="URINE")
    patient = fx.create_patient(api=api, state_code="CA")
    # Establish prior RELEASED RPT history so the repeat discount qualifies.
    fx.give_patient_released_result(patient["id"], off_rpt["id"], analyzer_value=1, api=api)

    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    line1 = fx.add_cart_line(cart["id"], patient["id"], off_rpt["id"], api=api)
    fx.add_cart_line(cart["id"], patient["id"], off_rpt["id"], api=api)

    assert line1["repeat_discount_applied"] is True, "first RPT line should be repeat-eligible"
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["subtotal_cents"] == 188, f"Expected round-then-sum subtotal 188, got {cart_read['subtotal_cents']}"
    assert cart_read["estimated_total_cents"] == 188, (
        f"Expected estimated_total_cents 188 (below tier1), got {cart_read['estimated_total_cents']}"
    )


def test_repeat_eligible_line_flag_set_from_history(api):
    """PRD 3.2: "This flag is set true when, at the moment the line is added, the
    patient already has a RELEASED lab result for the same test_code whose release
    falls within the lookback window — that is, within the 365 days immediately
    before the cart was created."

    Design: Difficulty/combinatorial_formula/per_line_repeat_discount_rounds_then_sums_mode_b
    """
    off_rpt = fx.create_offering(api=api, test_code="RPT", display_name="Repeat Cheap", list_price_cents=110, specimen_type="URINE")
    patient = fx.create_patient(api=api, state_code="CA")
    fx.give_patient_released_result(patient["id"], off_rpt["id"], analyzer_value=1, api=api)

    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    line1 = fx.add_cart_line(cart["id"], patient["id"], off_rpt["id"], api=api)
    assert line1["repeat_discount_applied"] is True


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/hsa_capture_split_pinned_eval_order_mode_c
# ---------------------------------------------------------------------------
def test_hsa_capture_split_pinned_evaluation_order(api):
    """PRD 3.6: "The platform-discounted total is computed first (the third step
    above). The HSA draw, hsa_applied_cents, is then the smaller of the patient's
    remaining hsa_balance_cents and that discounted total — and is zero unless the
    fund source is HSA_FSA. Finally patient_due_cents is the discounted total
    minus hsa_applied_cents."
    PRD 3.7: "On capture the Payment status becomes CAPTURED and its
    captured_amount_cents is set to the order's final patient_due_cents. When the
    fund source is HSA_FSA, the patient's hsa_balance_cents is reduced by the
    order's hsa_applied_cents and the payment's hsa_drawn_cents records that same
    draw."

    Single D4@30000 line, HSA balance 20000: invoice 27000, hsa_applied
    min(20000,27000)=20000, due 27000-20000=7000, hsa_balance debited to 0.

    Design: Difficulty/combinatorial_formula/hsa_capture_split_pinned_eval_order_mode_c
    """
    ctx = fx.setup_order_with_fund_source(
        fund_source="HSA_FSA",
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "D4", "display_name": "Test D4", "list_price_cents": 30000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA", "hsa_balance_cents": 20000},
        api=api,
    )
    patient, order, line = ctx["patient"], ctx["order"], ctx["order_line"]
    spec = fx.collect_line(line["id"], api=api)
    res = fx.process_specimen(spec["id"], 5, api=api)
    get_success_data(api.release_lab_result(res["id"], LAB2))

    order_completed = validate_success(api.get_order(order["id"], make_patient_headers(patient["id"])))
    captured = validate_success(
        api.capture_payment(
            order["id"],
            {"expected_order_version": order_completed["version"]},
            make_patient_headers(patient["id"]),
        )
    )
    assert captured["invoiced_total_cents"] == 27000
    assert captured["hsa_applied_cents"] == 20000
    assert captured["patient_due_cents"] == 7000

    patient_after = validate_success(api.get_patient(patient["id"], make_patient_headers(patient["id"])))
    assert patient_after["hsa_balance_cents"] == 0, (
        f"Expected hsa_balance debited to 0, got {patient_after['hsa_balance_cents']}"
    )


def test_hsa_capture_split_invoice_total_after_tier_discount(api):
    """PRD 3.6: "The per-line repeat discount of 0.15 is rounded half-up per line
    and summed; the platform tier discount applies the 0.15 rate at a subtotal of
    at least 50000 cents and the 0.10 rate at a subtotal of at least 20000 cents,
    rounded half-up; and HSA funds are then applied."

    D4@30000 single resulted line: invoice 30000 - round(30000*0.10)=3000 = 27000.

    Design: Difficulty/combinatorial_formula/hsa_capture_split_pinned_eval_order_mode_c
    """
    ctx = fx.setup_order_with_fund_source(
        fund_source="HSA_FSA",
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "D4", "display_name": "Test D4", "list_price_cents": 30000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA", "hsa_balance_cents": 20000},
        api=api,
    )
    patient, order, line = ctx["patient"], ctx["order"], ctx["order_line"]
    spec = fx.collect_line(line["id"], api=api)
    res = fx.process_specimen(spec["id"], 5, api=api)
    get_success_data(api.release_lab_result(res["id"], LAB2))

    order_after = validate_success(api.get_order(order["id"], make_patient_headers(patient["id"])))
    assert order_after["invoiced_total_cents"] == 27000
