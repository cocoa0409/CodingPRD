"""Subdivision impact fees: tiered gross, prior-payment credit, provisional vs final,
plat-submission precondition, and payment gating (PRD §3.8, §2.10)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    plat_payload, pay_payload,
    make_applicant_headers,
    seed_fee_schedule,
    build_accepted, build_effective_subdivision_with_plat, build_recorded_plat,
    record_plat, impact_fee_of,
)
from test_helpers import api_client as api


# --- Provisional vs final divergence --------------------------------------

def test_provisional_and_final_fee_diverge_on_record():
    """PRD §3.8: "the final fee is recomputed by the identical gross-then-credit procedure
    using the recorded quantities; the final figure may diverge from the provisional one
    when the recorded quantities differ from the declared ones."
    PRD §3.8: "The assessment's authoritative total_fee_cents equals provisional_fee_cents
    while PROVISIONAL and equals final_fee_cents once ASSESSED."

    Design: Difficulty/dual_variant_calc/impact_fee_provisional_vs_final_diverge
    """
    ctx = build_effective_subdivision_with_plat(declared_lot_count=4, declared_gross_acres=10)
    assert ctx["assessment"]["provisional_fee_cents"] == 2152500
    record_plat(ctx["plat"]["id"], recorded_lot_count=6, recorded_gross_acres=10)
    fee = impact_fee_of(ctx["plat"]["id"])
    assert fee["final_fee_cents"] == 2677500, f"final fee must be 2677500, got {fee['final_fee_cents']}"
    assert fee["total_fee_cents"] == 2677500, f"total must equal final once ASSESSED, got {fee['total_fee_cents']}"


def test_provisional_differs_from_final_fee():
    """PRD §3.8: "the final figure may diverge from the provisional one when the recorded
    quantities differ from the declared ones."
    PRD §3.8: "That net figure is what is stored as the assessment's fee at each stage:
    provisional_fee_cents while the assessment is PROVISIONAL, and final_fee_cents once it
    becomes ASSESSED."

    Design: Difficulty/dual_variant_calc/impact_fee_provisional_vs_final_diverge
    """
    ctx = build_effective_subdivision_with_plat(declared_lot_count=4, declared_gross_acres=10)
    record_plat(ctx["plat"]["id"], recorded_lot_count=6, recorded_gross_acres=10)
    fee = impact_fee_of(ctx["plat"]["id"])
    assert fee["provisional_fee_cents"] == 2152500
    assert fee["final_fee_cents"] == 2677500
    assert fee["provisional_fee_cents"] != fee["final_fee_cents"], \
        "recorded quantities differ, so provisional and final must diverge"


# --- Combinatorial gross fee (three road tiers + affordable discount) ------

def test_gross_fee_spans_three_road_tiers_with_affordable_discount():
    """PRD §3.8: "the first 5 acres are charged at road_fee_tier1_per_acre_cents; the
    acreage above 5 acres and up to 20 acres — that is, the portion between the 5-acre and
    20-acre boundaries, a band of at most 15 acres — is charged at road_fee_tier2_per_acre_cents;
    and any acreage beyond 20 acres is charged at road_fee_tier3_per_acre_cents."
    PRD §3.8: "The gross fee is the lesser of fee_cap_cents and the sum of the discounted
    subtotal and the administrative surcharge, and it is recorded on the assessment as
    gross_fee_cents."

    Design: Difficulty/combinatorial_formula/impact_fee_gross_three_tiers_mode_a
    """
    ctx = build_effective_subdivision_with_plat(
        declared_lot_count=8, declared_gross_acres=25, affordable_housing=True)
    assert ctx["assessment"]["gross_fee_cents"] == 3570000, \
        f"gross fee across three tiers with affordable discount must be 3570000, got {ctx['assessment']['gross_fee_cents']}"


def test_provisional_equals_gross_when_no_prior_credit():
    """PRD §3.8: "The net fee is the gross fee minus the applied credit. That net figure is
    what is stored as the assessment's fee at each stage: provisional_fee_cents while the
    assessment is PROVISIONAL, and final_fee_cents once it becomes ASSESSED."

    Design: Difficulty/combinatorial_formula/impact_fee_gross_three_tiers_mode_a
    """
    ctx = build_effective_subdivision_with_plat(
        declared_lot_count=8, declared_gross_acres=25, affordable_housing=True)
    assert ctx["assessment"]["provisional_fee_cents"] == 3570000, \
        "with no prior payment the net provisional equals the gross fee"


# --- Prior-payment credit keyed on gross ----------------------------------

def test_credit_cap_keyed_on_gross_not_net():
    """PRD §3.8: "The prior-payment credit is derived from the gross fee, computed strictly
    after it and never from the net figure. The credit cap is the gross fee multiplied by
    credit_pct, rounded half up to whole cents; the credit applied, recorded as credit_cents,
    is the smaller of that cap and the plat's prior_paid_fee_cents."

    Design: Difficulty/combinatorial_formula/impact_fee_credit_cap_keyed_on_gross_mode_c
    """
    ctx = build_effective_subdivision_with_plat(
        declared_lot_count=4, declared_gross_acres=10, prior_paid_fee_cents=300000)
    assert ctx["assessment"]["gross_fee_cents"] == 2152500
    assert ctx["assessment"]["credit_cents"] == 215250, \
        f"credit cap = round(gross*0.10) = 215250, got {ctx['assessment']['credit_cents']}"


def test_net_provisional_after_credit():
    """PRD §3.8: "The net fee is the gross fee minus the applied credit. That net figure is
    what is stored as the assessment's fee at each stage: provisional_fee_cents while the
    assessment is PROVISIONAL, and final_fee_cents once it becomes ASSESSED."

    Design: Difficulty/combinatorial_formula/impact_fee_credit_cap_keyed_on_gross_mode_c
    """
    ctx = build_effective_subdivision_with_plat(
        declared_lot_count=4, declared_gross_acres=10, prior_paid_fee_cents=300000)
    assert ctx["assessment"]["provisional_fee_cents"] == 1937250, \
        f"net provisional = gross 2152500 - credit 215250 = 1937250, got {ctx['assessment']['provisional_fee_cents']}"


# --- Tier boundary at exactly 5 acres -------------------------------------

def test_gross_fee_at_five_acre_tier_boundary():
    """PRD §3.8: "the first 5 acres are charged at road_fee_tier1_per_acre_cents; the acreage
    above 5 acres and up to 20 acres ... is charged at road_fee_tier2_per_acre_cents".
    PRD §3.8: "The administrative surcharge is then the discounted subtotal multiplied by
    admin_pct, rounded half up to whole cents."

    Design: Corner/calculations/impact_fee_tier_boundary_five_acres
    """
    ctx = build_effective_subdivision_with_plat(declared_lot_count=1, declared_gross_acres=5)
    assert ctx["assessment"]["gross_fee_cents"] == 892500, \
        f"at exactly 5 acres only tier1 road applies: gross = 892500, got {ctx['assessment']['gross_fee_cents']}"


# --- Payment gating -------------------------------------------------------

def test_pay_provisional_fee_rejected():
    """PRD §3.8: "a payment attempted while the assessment is not ASSESSED is refused with
    ERR_FEE_NOT_ASSESSED, and an amount that does not match is refused with
    ERR_FEE_AMOUNT_MISMATCH."

    Design: Corner/validations/pay_provisional_fee_returns_fee_not_assessed
    """
    ctx = build_effective_subdivision_with_plat(declared_lot_count=4, declared_gross_acres=10)
    headers = make_applicant_headers(ctx["applicant"]["id"])
    resp = api.pay_impact_fee(ctx["assessment"]["id"], pay_payload(2152500), headers)
    validate_error(resp, ApiErrorId.ERR_FEE_NOT_ASSESSED)


def test_pay_wrong_amount_rejected():
    """PRD §3.8: "The payment names an amount_cents that must equal the assessment's
    total_fee_cents exactly ... an amount that does not match is refused with
    ERR_FEE_AMOUNT_MISMATCH."

    Design: Corner/validations/pay_wrong_amount_returns_fee_amount_mismatch
    """
    ctx = build_recorded_plat(declared_lot_count=4, declared_gross_acres=10,
                              recorded_lot_count=4, recorded_gross_acres=10)
    headers = make_applicant_headers(ctx["applicant"]["id"])
    resp = api.pay_impact_fee(ctx["assessment"]["id"], pay_payload(999), headers)
    validate_error(resp, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH)


# --- Plat submission precondition -----------------------------------------

def test_plat_on_accepted_application_rejected():
    """PRD §3.8: "Only a SUBDIVISION application that has reached EFFECTIVE may be platted ...
    A plat against an application that is not a SUBDIVISION in EFFECTIVE state is refused with
    ERR_APPLICATION_NOT_EFFECTIVE."

    Design: Difficulty/cross_entity_state_dependency/plat_submission_requires_application_effective
    """
    ctx = build_accepted(app_type="SUBDIVISION", clock=None)
    fee_schedule = seed_fee_schedule()
    headers = make_applicant_headers(ctx["applicant"]["id"])
    resp = api.create_plat(plat_payload(ctx["app"]["id"], fee_schedule["id"]), headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_EFFECTIVE)


def test_no_plat_created_when_application_not_effective(clerk_headers):
    """PRD §3.8: "A plat against an application that is not a SUBDIVISION in EFFECTIVE state
    is refused with ERR_APPLICATION_NOT_EFFECTIVE."

    Design: Difficulty/cross_entity_state_dependency/plat_submission_requires_application_effective
    """
    ctx = build_accepted(app_type="SUBDIVISION", clock=None)
    fee_schedule = seed_fee_schedule()
    headers = make_applicant_headers(ctx["applicant"]["id"])
    api.create_plat(plat_payload(ctx["app"]["id"], fee_schedule["id"]), headers)
    resp = api.list_plats(clerk_headers, params={"application_id": ctx["app"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, "a rejected plat submission must not persist any plat"
