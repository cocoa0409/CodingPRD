"""Pricing engine and per-visit charge calculations.

Covers the dual-variant quote/charge calculations, the combinatorial
round-per-component-then-sum rule, the deposit threshold boundary, and the
deposit waterfall + re-clean credit branches.
"""
from test_helpers import (
    api_client, validate_success,
    create_account_payload, create_property_payload, create_quote_payload,
    create_account, create_property, create_sent_quote,
    setup_completed_visit, setup_invoiced_visit, setup_requested_reclean,
    setup_visit_rescheduled_twice,
    post_deposit, TEST_USERS, make_customer_headers,
)

BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_quote_pane_count_vs_sqft_diverge_on_same_property(api):
    """PRD §3.1: "A property with both fields populated will generally yield a
    different total under each basis, which is exactly why the basis is an
    explicit input."

    Design: Difficulty/dual_variant_calc/quote_amount_pane_vs_sqft_diverge_on_same_property
    """
    account = create_account(region_code="NORTH")
    prop = create_property(account["id"], pane_count=60, glass_sqft=140.4,
                           stories=2, soft_wash_sqft=0)
    q_pane = validate_success(api.create_quote(
        create_quote_payload(account["id"], prop["id"],
                             pricing_basis="PANE_COUNT", addon_codes=["GUTTER"]), BILLING), 201)
    q_sqft = validate_success(api.create_quote(
        create_quote_payload(account["id"], prop["id"],
                             pricing_basis="SQ_FT", addon_codes=["GUTTER"]), BILLING), 201)

    assert q_pane["quoted_total_cents"] == 23000
    assert q_sqft["quoted_total_cents"] == 20190
    assert q_pane["quoted_total_cents"] != q_sqft["quoted_total_cents"]


def test_quote_sqft_basis_ignores_pane_count(api):
    """PRD §3.1: "Under the `SQ_FT` basis, the system ignores the pane count
    entirely, rounds the glass area up to the next whole square foot, and
    multiplies that whole number of square feet by 90 cents."

    Design: Difficulty/dual_variant_calc/quote_amount_pane_vs_sqft_diverge_on_same_property
    """
    account = create_account(region_code="NORTH")
    prop = create_property(account["id"], pane_count=60, glass_sqft=140.4,
                           stories=2, soft_wash_sqft=0)
    q_sqft = validate_success(api.create_quote(
        create_quote_payload(account["id"], prop["id"],
                             pricing_basis="SQ_FT", addon_codes=["GUTTER"]), BILLING), 201)
    # ceil(140.4)=141 * 90 = 12690 (above 9900 floor); + GUTTER 7500 = 20190
    assert q_sqft["base_price_cents"] == 12690
    assert q_sqft["addon_total_cents"] == 7500
    assert q_sqft["quoted_total_cents"] == 20190


def test_visit_charge_diverges_from_estimate_after_two_reschedules(api):
    """PRD §3.5: "If the visit's `reschedule_count` is at least 2, a goodwill
    discount of 10 percent of the gross — rounded half-up to whole cents — is
    subtracted from the gross; with fewer than two reschedules no discount applies."

    Design: Difficulty/dual_variant_calc/visit_charge_estimate_vs_actual_diverge_on_reschedule
    """
    account, prop, agreement, visit, crew = setup_visit_rescheduled_twice(
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    assert agreement["per_visit_price_cents"] == 23000
    completed = validate_success(api.complete_visit(visit["id"], TEST_USERS["field_crew_headers"]), 200)
    assert completed["reschedule_count"] == 2
    # gross = 23000 (no add-ons attached); discount = round(23000*0.10)=2300; charge=20700
    assert completed["charge_amount_cents"] == 20700


def test_visit_charge_actual_differs_from_agreement_snapshot(api):
    """PRD §3.5: "the same visit can complete at a different cents value than its
    estimate."

    Design: Difficulty/dual_variant_calc/visit_charge_estimate_vs_actual_diverge_on_reschedule
    """
    account, prop, agreement, visit, crew = setup_visit_rescheduled_twice(
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    completed = validate_success(api.complete_visit(visit["id"], TEST_USERS["field_crew_headers"]), 200)
    assert completed["charge_amount_cents"] != agreement["per_visit_price_cents"]


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_quote_rounds_highrise_and_softwash_per_component_then_sums(api):
    """PRD §3.1: "If `SOFT_WASH` is requested, the soft-wash line is the property's
    soft-wash square footage multiplied by 25 cents and rounded half-up to whole
    cents, and that rounded line is then raised to a floor of 12,000 cents."

    Design: Difficulty/combinatorial_formula/quote_amount_round_per_component_then_sum_softwash_highrise
    """
    account = create_account(region_code="EAST")
    prop = create_property(account["id"], pane_count=80, glass_sqft=100.0,
                           stories=4, soft_wash_sqft=400.0)
    quote = create_sent_quote(account["id"], prop["id"],
                              pricing_basis="PANE_COUNT", addon_codes=["SOFT_WASH"])
    # base PANE = 20*300 + 30*250 + 30*200 = 19500; high-rise +round(19500*0.20)=3900 -> 23400
    assert quote["base_price_cents"] == 23400
    # soft-wash = max(round(400*25)=10000, 12000) = 12000
    assert quote["addon_total_cents"] == 12000
    assert quote["quoted_total_cents"] == 35400


def test_quote_high_rise_surcharge_applied_at_three_stories(api):
    """PRD §3.1: "When the property's `stories` count is at least 3, a surcharge
    equal to 20 percent of the base — rounded to whole cents, half-up — is added
    to the base; below 3 stories no surcharge applies."

    Design: Difficulty/combinatorial_formula/quote_amount_round_per_component_then_sum_softwash_highrise
    """
    account = create_account(region_code="EAST")
    prop = create_property(account["id"], pane_count=80, glass_sqft=100.0,
                           stories=4, soft_wash_sqft=400.0)
    quote = create_sent_quote(account["id"], prop["id"],
                              pricing_basis="PANE_COUNT", addon_codes=["SOFT_WASH"])
    # raw base 19500 + 20% surcharge 3900 = 23400
    assert quote["base_price_cents"] == 23400


def test_visit_charge_adds_addon_delta_with_no_reschedule_discount(api):
    """PRD §3.5: "To that base is added the sum of the `charge_cents` of every
    `VisitAddOn` currently attached to the visit, producing a gross figure."

    Design: Difficulty/combinatorial_formula/visit_charge_three_input_conditional_discount_branch
    """
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        add_on_codes=["GUTTER"], after_photo_count=1)
    # base 23000 + GUTTER add-on 7500 = 30500; reschedule_count 0 -> no discount
    assert visit["reschedule_count"] == 0
    assert visit["charge_amount_cents"] == 30500


def test_visit_addon_gutter_charge_is_flat_7500(api):
    """PRD §3.5: "a `GUTTER` add-on is a flat 7,500 cents".

    Design: Difficulty/combinatorial_formula/visit_charge_three_input_conditional_discount_branch
    """
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        add_on_codes=["GUTTER"], after_photo_count=1)
    data, _ = _list(api.list_visit_add_ons(visit["id"], BILLING))
    assert len(data) == 1
    assert data[0]["addon_code"] == "GUTTER"
    assert data[0]["charge_cents"] == 7500


# ===========================================================================
# Queue A — boundary_precision_check (deposit threshold)
# ===========================================================================
def test_deposit_required_at_exactly_threshold_total(api):
    """PRD §3.1: "When `quoted_total_cents` is at least 30,000 cents, the
    `required_deposit_cents` is 25 percent of the quoted total, rounded half-up
    to whole cents."

    Design: Difficulty/boundary_precision_check/deposit_threshold_at_exactly_30000_requires_deposit
    """
    account = create_account(region_code="NORTH")
    p95 = create_property(account["id"], pane_count=95, glass_sqft=100.0,
                          stories=2, soft_wash_sqft=0)
    q95 = create_sent_quote(account["id"], p95["id"],
                            pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    # 20*300 + 30*250 + 45*200 = 22500; + GUTTER 7500 = 30000; deposit round(30000*0.25)=7500
    assert q95["quoted_total_cents"] == 30000
    assert q95["required_deposit_cents"] == 7500


def test_deposit_not_required_just_below_threshold_total(api):
    """PRD §3.1: "When the quoted total is below 30,000 cents, no deposit is
    required and `required_deposit_cents` is 0."

    Design: Difficulty/boundary_precision_check/deposit_threshold_at_exactly_30000_requires_deposit
    """
    account = create_account(region_code="NORTH")
    p94 = create_property(account["id"], pane_count=94, glass_sqft=100.0,
                          stories=2, soft_wash_sqft=0)
    q94 = create_sent_quote(account["id"], p94["id"],
                            pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    # 20*300 + 30*250 + 44*200 = 22300; + GUTTER 7500 = 29800 (< 30000) -> deposit 0
    assert q94["quoted_total_cents"] == 29800
    assert q94["required_deposit_cents"] == 0


# ===========================================================================
# Queue B — calculations
# ===========================================================================
def test_invoice_settlement_applies_held_deposit(api):
    """PRD §3.7: "A deposit that is consumed in full transitions to `APPLIED`; a
    deposit only partially consumed remains `HELD`. The total consumed becomes
    `deposit_applied_cents`, and the `net_due_cents` is the invoice amount minus
    the applied deposit, which by construction is never negative."

    Design: Corner/calculations/invoice_settlement_applies_deposit_oldest_first
    """
    # Maple agreement: per_visit 35400 (pane=80,stories=4,SOFT_WASH); HELD deposit 9000.
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        region_code="EAST", schedule_kind="ONE_TIME", crew_skills=["SOFT_WASH", "HIGH_RISE"],
        deposit_cents=9000,
        property_overrides={"pane_count": 80, "glass_sqft": 100.0, "stories": 4, "soft_wash_sqft": 400.0},
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["SOFT_WASH"]},
        after_photo_count=1)
    invoice = validate_success(api.create_invoice({"visit_id": visit["id"]}, BILLING), 201)
    assert invoice["amount_cents"] == 35400
    assert invoice["deposit_applied_cents"] == 9000
    assert invoice["net_due_cents"] == 26400


def test_reclean_partial_credit_with_two_after_photos(api):
    """PRD §3.8: "When two or more after photos are on file, the work is considered
    well-documented and earns only a partial credit of 50 percent of the visit's
    `charge_amount_cents`, rounded half-up to whole cents."

    Design: Corner/calculations/reclean_partial_credit_when_two_after_photos
    """
    account, prop, agreement, visit, reclean = setup_requested_reclean(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        after_photo_count=2)
    # visit charge 23000; 2 AFTER photos -> partial = round(23000*0.5) = 11500
    approved = validate_success(api.approve_reclean_request(reclean["id"], BILLING), 200)
    assert approved["status"] == "APPROVED"
    assert approved["credit_cents"] == 11500


def test_reclean_full_credit_with_one_after_photo(api):
    """PRD §3.8: "When exactly one after photo is on file, the work is considered
    thinly documented and earns a full credit equal to the visit's entire
    `charge_amount_cents`."

    Design: Corner/calculations/reclean_full_credit_when_one_after_photo
    """
    account, prop, agreement, visit, reclean = setup_requested_reclean(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        after_photo_count=1)
    # visit charge 23000; exactly 1 AFTER photo -> full credit = 23000
    approved = validate_success(api.approve_reclean_request(reclean["id"], BILLING), 200)
    assert approved["status"] == "APPROVED"
    assert approved["credit_cents"] == 23000


def _list(res):
    body = res.json()
    return body["data"], body["meta"]
