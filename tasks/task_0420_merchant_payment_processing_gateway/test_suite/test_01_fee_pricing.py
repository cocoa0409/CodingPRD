"""Processing-fee pricing: FLAT vs INTERCHANGE_PLUS, the tier branch, partial capture,
and immediate visibility of the pinned fee.

Covers difficulty queue (dual_variant_calc, combinatorial_formula) and corner calculation
+ consistency instances.
"""
from test_helpers import (
    validate_success,
    api_client,
    create_interchange_plus_fee_plan_payload,
    create_flat_fee_plan_payload,
    capture_payload,
    set_clock, create_flat_plan, create_interchange_plus_plan,
    create_approved_merchant, create_authorized_charge, create_captured_charge,
    open_and_settle_batch,
    make_merchant_user_headers,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]


def test_flat_fee_on_10000_capture_is_320(api):
    """PRD §3.4: "the percentage component is the capture amount multiplied by `flat_pct_bps`
    divided by 10000, rounded half-up to whole cents; the fee is that rounded percentage
    component plus `flat_fixed_cents`."

    Design: Difficulty/dual_variant_calc/flat_vs_interchange_plus_fee_on_identical_capture
    """
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    data = validate_success(api.capture_charge(charge["id"], capture_payload(10000), headers))
    # FLAT: round(10000*290/10000)=290 + 30 fixed = 320
    assert data["processing_fee_cents"] == 320, f"expected 320, got {data['processing_fee_cents']}"


def test_interchange_plus_fee_on_10000_capture_is_215(api):
    """PRD §3.4: "The interchange passthrough is the capture amount multiplied by the
    interchange rate of 165 basis points divided by 10000, rounded half-up to whole cents,
    plus a fixed interchange amount of 10 cents."

    Design: Difficulty/dual_variant_calc/flat_vs_interchange_plus_fee_on_identical_capture
    """
    plan = create_interchange_plus_plan(
        markup_pct_bps=30, markup_fixed_cents=10,
        volume_tier_threshold_cents=1000000, discounted_markup_pct_bps=20,
    )
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    data = validate_success(api.capture_charge(charge["id"], capture_payload(10000), headers))
    # interchange: round(10000*165/10000)=165 + 10 = 175; markup: round(10000*30/10000)=30 + 10 = 40
    # total = 215
    assert data["processing_fee_cents"] == 215, f"expected 215, got {data['processing_fee_cents']}"


def test_identical_capture_yields_different_fee_per_model(api):
    """PRD §3.4: "Because the two pricing models differ, an identical capture amount yields a
    different fee under a flat plan than under an interchange-plus plan."

    Design: Difficulty/dual_variant_calc/flat_vs_interchange_plus_fee_on_identical_capture
    """
    flat_plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    ip_plan = create_interchange_plus_plan(
        markup_pct_bps=30, markup_fixed_cents=10,
        volume_tier_threshold_cents=1000000, discounted_markup_pct_bps=20,
    )
    m_flat, _ = create_approved_merchant(fee_plan_id=flat_plan["id"], assigned_risk_band="LOW")
    m_ip, _ = create_approved_merchant(fee_plan_id=ip_plan["id"], assigned_risk_band="LOW")

    ch_flat = create_authorized_charge(m_flat["id"], auth_amount_cents=10000)
    ch_ip = create_authorized_charge(m_ip["id"], auth_amount_cents=10000)

    flat_fee = validate_success(
        api.capture_charge(ch_flat["id"], capture_payload(10000), make_merchant_user_headers(m_flat["id"]))
    )["processing_fee_cents"]
    ip_fee = validate_success(
        api.capture_charge(ch_ip["id"], capture_payload(10000), make_merchant_user_headers(m_ip["id"]))
    )["processing_fee_cents"]

    assert flat_fee == 320
    assert ip_fee == 215
    assert flat_fee != ip_fee, "identical capture must price differently under the two models"


def test_interchange_plus_markup_stays_full_at_threshold_boundary(api):
    """PRD §3.4: "The platform markup uses an effective markup rate that depends on the
    merchant's settled volume so far this calendar month: if the merchant's prior settled
    volume in the current calendar month — defined as the sum of `captured_amount_cents` over
    this merchant's charges whose `settlement_status` is `SETTLED` and whose settle posting
    fell in the current calendar month, excluding the charge now being captured — strictly
    exceeds the plan's `volume_tier_threshold_cents`, then the effective markup rate is
    `discounted_markup_pct_bps`; otherwise it is `markup_pct_bps`."

    Design: Difficulty/combinatorial_formula/interchange_plus_fee_nonlinear_three_inputs_with_tier_branch
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_interchange_plus_plan(
        markup_pct_bps=30, markup_fixed_cents=10,
        volume_tier_threshold_cents=1000000, discounted_markup_pct_bps=20,
    )
    merchant, _ = create_approved_merchant(
        fee_plan_id=plan["id"], assigned_risk_band="LOW",
        merchant_overrides={"requested_monthly_volume_cents": 2000000},
    )
    version = merchant["version"]
    # Prior settled volume of EXACTLY 1000000 this month (not strictly > threshold).
    create_captured_charge(merchant["id"], auth_amount_cents=1000000)
    _, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-03-01")

    # Test capture of 20000 in the same month: markup stays at 30bps.
    test_charge = create_authorized_charge(merchant["id"], auth_amount_cents=20000)
    data = validate_success(
        api.capture_charge(test_charge["id"], capture_payload(20000), make_merchant_user_headers(merchant["id"]))
    )
    # interchange: round(20000*165/10000)=330 + 10 = 340; markup: round(20000*30/10000)=60 + 10 = 70
    # total = 410 (full markup, prior volume == threshold, not strictly greater)
    assert data["processing_fee_cents"] == 410, f"expected 410, got {data['processing_fee_cents']}"


def test_interchange_passthrough_and_markup_sum_round_then_add(api):
    """PRD §3.4: "The total interchange-plus fee is the interchange passthrough plus the
    markup component."
    PRD §3.4: "The markup component is the capture amount multiplied by that effective markup
    rate divided by 10000, rounded half-up to whole cents, plus `markup_fixed_cents`."

    Design: Difficulty/combinatorial_formula/interchange_plus_fee_nonlinear_three_inputs_with_tier_branch
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_interchange_plus_plan(
        markup_pct_bps=30, markup_fixed_cents=10,
        volume_tier_threshold_cents=1000000, discounted_markup_pct_bps=20,
    )
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    # No prior settled volume -> full markup 30bps.
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=20000)
    data = validate_success(
        api.capture_charge(charge["id"], capture_payload(20000), make_merchant_user_headers(merchant["id"]))
    )
    assert data["processing_fee_cents"] == 410, f"expected 410, got {data['processing_fee_cents']}"


# --- Corner: calculation correctness ---

def test_flat_fee_12345_capture_rounds_to_388(api):
    """PRD §3.4: "the percentage component is the capture amount multiplied by `flat_pct_bps`
    divided by 10000, rounded half-up to whole cents; the fee is that rounded percentage
    component plus `flat_fixed_cents`."

    Design: Corner/Calculations/corner_processing_fee_flat_correct_result
    """
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=12345)
    data = validate_success(
        api.capture_charge(charge["id"], capture_payload(12345), make_merchant_user_headers(merchant["id"]))
    )
    # round_half_up(12345*0.029)=358 + 30 = 388
    assert data["processing_fee_cents"] == 388, f"expected 388, got {data['processing_fee_cents']}"


def test_partial_capture_prices_on_captured_amount(api):
    """PRD §3.4: "In both variants the base is the capture amount being processed, and all
    amounts are integer cents."
    PRD §3.3: "On a successful capture the charge's `captured_amount_cents` is set to the
    captured amount, and the `processing_fee_cents` is computed once (see §3.4) and never
    recomputed; this fee is non-refundable."

    Design: Corner/Calculations/corner_processing_fee_partial_capture_uses_capture_amount
    """
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=10000)
    data = validate_success(
        api.capture_charge(charge["id"], capture_payload(6000), make_merchant_user_headers(merchant["id"]))
    )
    assert data["captured_amount_cents"] == 6000
    # fee computed on captured 6000: round(6000*0.029)=174 + 30 = 204
    assert data["processing_fee_cents"] == 204, f"expected 204, got {data['processing_fee_cents']}"


def test_pinned_fee_visible_in_capture_response_and_subsequent_get(api):
    """PRD §3.3: "the `processing_fee_cents` is computed once (see §3.4) and never recomputed".
    PRD §3.4: "the resulting fee is pinned onto the charge at capture."

    Design: Corner/Consistency Model/corner_immediate_capture_visible_in_response
    """
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    captured = validate_success(api.capture_charge(charge["id"], capture_payload(10000), headers))
    fetched = validate_success(api.get_charge(charge["id"], headers))
    assert captured["processing_fee_cents"] == 320
    assert fetched["processing_fee_cents"] == 320
    assert fetched["processing_fee_cents"] == captured["processing_fee_cents"]
