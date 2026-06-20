"""Ceiling-price computation (STANDARD vs PENNY), the eligibility cascade, effective
ceiling selection, and dispense line-cost pricing.

Design sources: Difficulty/dual_variant_calc/ceiling_price_standard_vs_penny_on_drug_product,
Difficulty/boundary_precision_check/penny_pricing_boundary_ura_equals_amp_on_ceiling_endpoint,
Difficulty/combinatorial_formula/eligibility_determination_multi_prong_branching_mode_a,
and several Corner/calculations + Corner/endpoints instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_covered_entity_payload, create_drug_product_payload,
    create_ceiling_price_payload, create_prescriber_payload,
    create_patient_payload, create_dispense_payload,
    create_and_approve_covered_entity, create_drug_product, create_prescriber,
    create_patient, add_ceiling_price, create_drug_with_published_ceiling,
    setup_dispensable_scenario, record_dispense,
)

CO = TEST_USERS["compliance_officer_headers"]
HRSA = TEST_USERS["hrsa_auditor_headers"]
PHARM = TEST_USERS["pharmacy_operator_headers"]


# ---------------------------------------------------------------------------
# Ceiling-price STANDARD vs PENNY (dual-variant calculation)
# ---------------------------------------------------------------------------
def test_ceiling_price_standard_variant_amp_minus_ura(api):
    """PRD §3.3: "When the Unit Rebate Amount is strictly less than the Average
    Manufacturer Price, the ceiling price per unit is the Average Manufacturer Price minus
    the Unit Rebate Amount, and `pricing_variant` is `STANDARD`."

    Design: Difficulty/dual_variant_calc/ceiling_price_standard_vs_penny_on_drug_product
    """
    dp = create_drug_product(ndc="00001-0001-01", drug_name="AlphaStandard",
                             wac_price_per_unit_cents=5000)
    cpr = validate_success(
        api.create_ceiling_price(
            dp["id"], create_ceiling_price_payload(amp_per_unit_cents=4000,
                                                   ura_per_unit_cents=1500, is_published=True), CO), 201)
    assert cpr["ceiling_price_per_unit_cents"] == 2500
    assert cpr["pricing_variant"] == "STANDARD"


def test_ceiling_price_penny_variant_when_ura_equals_amp(api):
    """PRD §3.3: "When the Unit Rebate Amount is greater than or equal to the Average
    Manufacturer Price — the boundary is inclusive, so equality yields penny pricing rather
    than a zero ceiling — the ceiling price per unit is forced to the penny floor of exactly
    1 cent, and `pricing_variant` is `PENNY`."

    Design: Difficulty/dual_variant_calc/ceiling_price_standard_vs_penny_on_drug_product
    """
    dp = create_drug_product(ndc="00002-0002-02", drug_name="BetaPenny",
                             wac_price_per_unit_cents=5000)
    cpr = validate_success(
        api.create_ceiling_price(
            dp["id"], create_ceiling_price_payload(amp_per_unit_cents=3000,
                                                   ura_per_unit_cents=3000, is_published=True), CO), 201)
    assert cpr["ceiling_price_per_unit_cents"] == 1
    assert cpr["pricing_variant"] == "PENNY"


def test_penny_boundary_ura_equals_amp_is_penny(api):
    """PRD §3.3: "When the Unit Rebate Amount is greater than or equal to the Average
    Manufacturer Price — the boundary is inclusive, so equality yields penny pricing rather
    than a zero ceiling — the ceiling price per unit is forced to the penny floor of exactly
    1 cent, and `pricing_variant` is `PENNY`."

    Design: Difficulty/boundary_precision_check/penny_pricing_boundary_ura_equals_amp_on_ceiling_endpoint
    """
    dp = create_drug_product(ndc="00014-0014-14", drug_name="XiBoundEq",
                             wac_price_per_unit_cents=5000)
    cpr = validate_success(
        api.create_ceiling_price(
            dp["id"], create_ceiling_price_payload(amp_per_unit_cents=3000,
                                                   ura_per_unit_cents=3000, is_published=True), CO), 201)
    assert cpr["ceiling_price_per_unit_cents"] == 1
    assert cpr["pricing_variant"] == "PENNY"


def test_penny_boundary_ura_one_below_amp_is_standard(api):
    """PRD §3.3: "When the Unit Rebate Amount is strictly less than the Average
    Manufacturer Price, the ceiling price per unit is the Average Manufacturer Price minus
    the Unit Rebate Amount, and `pricing_variant` is `STANDARD`."

    Design: Difficulty/boundary_precision_check/penny_pricing_boundary_ura_equals_amp_on_ceiling_endpoint
    """
    dp = create_drug_product(ndc="00015-0015-15", drug_name="OmicronBoundLt",
                             wac_price_per_unit_cents=5000)
    cpr = validate_success(
        api.create_ceiling_price(
            dp["id"], create_ceiling_price_payload(amp_per_unit_cents=3000,
                                                   ura_per_unit_cents=2999, is_published=True), CO), 201)
    assert cpr["ceiling_price_per_unit_cents"] == 1
    assert cpr["pricing_variant"] == "STANDARD"


# ---------------------------------------------------------------------------
# Eligibility cascade (combinatorial formula, mode a)
# ---------------------------------------------------------------------------
def test_all_prongs_pass_classifies_340b(api):
    """PRD §3.5: "If all five prongs pass, the dispense is `CLASSIFIED_340B` with reason
    `ELIGIBLE_340B`."

    Design: Difficulty/combinatorial_formula/eligibility_determination_multi_prong_branching_mode_a
    """
    scenario = setup_dispensable_scenario()
    dispense = record_dispense(scenario, quantity_units=4)
    assert dispense["classification_status"] == "CLASSIFIED_340B"
    assert dispense["eligibility_reason"] == "ELIGIBLE_340B"


def test_referral_only_prescriber_classifies_wac_ineligible_prescriber(api):
    """PRD §3.5: "Otherwise, if the prescriber's `relationship_type` is neither `EMPLOYED`
    nor `CONTRACTED` (that is, it is `REFERRAL_ONLY` or `EXTERNAL`), the dispense is
    `CLASSIFIED_WAC` with reason `INELIGIBLE_PRESCRIBER`."

    Design: Difficulty/combinatorial_formula/eligibility_determination_multi_prong_branching_mode_a
    """
    ce = create_and_approve_covered_entity(medicaid_billing_mode="CARVE_OUT")
    drug = create_drug_with_published_ceiling(amp=4000, ura=1500, wac_price_per_unit_cents=6000)
    emp = create_prescriber(ce["id"], relationship_type="EMPLOYED")
    ref = create_prescriber(ce["id"], relationship_type="REFERRAL_ONLY")
    pat = create_patient(ce["id"], medicaid_ffs_enrolled=False)

    ok = validate_success(
        api.create_dispense(create_dispense_payload(
            ce["id"], pat["id"], emp["id"], drug["id"], quantity_units=4, quarter="2026Q2"), PHARM), 201)
    bad = validate_success(
        api.create_dispense(create_dispense_payload(
            ce["id"], pat["id"], ref["id"], drug["id"], quantity_units=4, quarter="2026Q2"), PHARM), 201)
    assert ok["classification_status"] == "CLASSIFIED_340B"
    assert ok["eligibility_reason"] == "ELIGIBLE_340B"
    assert bad["classification_status"] == "CLASSIFIED_WAC"
    assert bad["eligibility_reason"] == "INELIGIBLE_PRESCRIBER"


def test_carve_out_medicaid_patient_classifies_wac(api):
    """PRD §3.5: "Otherwise, if the patient's `medicaid_ffs_enrolled` is `true` and the
    covered entity's `medicaid_billing_mode` is `CARVE_OUT`, the dispense is `CLASSIFIED_WAC`
    with reason `CARVED_OUT_MEDICAID`."

    Design: Corner/calculations/wac_dispense_line_cost_uses_wac_price
    """
    scenario = setup_dispensable_scenario(
        wac_price_per_unit_cents=4000, amp=4000, ura=1500,
        medicaid_billing_mode="CARVE_OUT", patient_overrides={"medicaid_ffs_enrolled": True})
    dispense = record_dispense(scenario, quantity_units=7)
    assert dispense["classification_status"] == "CLASSIFIED_WAC"
    assert dispense["eligibility_reason"] == "CARVED_OUT_MEDICAID"
    assert dispense["applied_price_per_unit_cents"] == 4000
    assert dispense["line_cost_cents"] == 28000


def test_unregistered_child_site_classifies_wac(api):
    """PRD §3.5: "Otherwise, when the dispense names a `child_site_id` and that child
    site's `registered` flag is `false`, the dispense is `CLASSIFIED_WAC` with reason
    `INELIGIBLE_UNREGISTERED_SITE`."

    Design: Corner/endpoints/unregistered_child_site_dispense_classifies_wac
    """
    ce = create_and_approve_covered_entity(medicaid_billing_mode="CARVE_OUT")
    cs = validate_success(
        api.create_child_site(
            ce["id"], {"site_name": "Unreg Site", "service_address": "3 Pine Rd", "registered": False}, CO), 201)
    drug = create_drug_with_published_ceiling(amp=4000, ura=1500)
    presc = create_prescriber(ce["id"], relationship_type="EMPLOYED")
    pat = create_patient(ce["id"], medicaid_ffs_enrolled=False)
    dispense = validate_success(
        api.create_dispense(create_dispense_payload(
            ce["id"], pat["id"], presc["id"], drug["id"], quantity_units=4,
            quarter="2026Q2", child_site_id=cs["id"]), PHARM), 201)
    assert dispense["classification_status"] == "CLASSIFIED_WAC"
    assert dispense["eligibility_reason"] == "INELIGIBLE_UNREGISTERED_SITE"


# ---------------------------------------------------------------------------
# Effective ceiling selection (published over provisional) and pricing
# ---------------------------------------------------------------------------
def test_effective_ceiling_prefers_published_over_provisional(api):
    """PRD §3.3: "If at least one is published, the effective record is the most recently
    created published record (the one with the latest `created_at`), and the variant is
    reported as `FINAL`; a later provisional estimate never overrides a published price."

    Design: Corner/calculations/effective_ceiling_prefers_published_over_provisional
    """
    dp = create_drug_product(drug_name="Eff Drug", wac_price_per_unit_cents=6000)
    add_ceiling_price(dp["id"], quarter="2026Q2", amp_per_unit_cents=5000,
                      ura_per_unit_cents=1500, is_published=False)
    pub = add_ceiling_price(dp["id"], quarter="2026Q2", amp_per_unit_cents=4000,
                            ura_per_unit_cents=1500, is_published=True)
    eff = validate_success(
        api.get_effective_ceiling(dp["id"], HRSA, params={"quarter": "2026Q2"}), 200)
    assert eff["id"] == pub["id"]
    assert eff["ceiling_price_per_unit_cents"] == 2500


def test_provisional_only_dispense_prices_provisional_ceiling(api):
    """PRD §3.3: "If none is published but provisional records exist, the effective record
    is the most recently created provisional record by `created_at`, and the variant is
    reported as `PROVISIONAL`."

    Design: Corner/calculations/provisional_only_dispense_prices_provisional_ceiling
    """
    ce = create_and_approve_covered_entity(medicaid_billing_mode="CARVE_OUT")
    dp = create_drug_product(drug_name="Prov Drug", wac_price_per_unit_cents=6000)
    add_ceiling_price(dp["id"], quarter="2026Q2", amp_per_unit_cents=3600,
                      ura_per_unit_cents=1100, is_published=False)
    presc = create_prescriber(ce["id"], relationship_type="EMPLOYED")
    pat = create_patient(ce["id"], medicaid_ffs_enrolled=False)
    dispense = validate_success(
        api.create_dispense(create_dispense_payload(
            ce["id"], pat["id"], presc["id"], dp["id"], quantity_units=3, quarter="2026Q2"), PHARM), 201)
    assert dispense["classification_status"] == "CLASSIFIED_340B"
    assert dispense["applied_price_per_unit_cents"] == 2500
    assert dispense["line_cost_cents"] == 7500


def test_dispense_classification_visible_in_create_response(api):
    """PRD §3.5: "The `line_cost_cents` is `applied_price_per_unit_cents` multiplied by
    `quantity_units` — an exact integer-cent product."

    Design: Corner/consistency_model/immediate_visibility_dispense_classification_in_create_response
    """
    scenario = setup_dispensable_scenario(amp=4000, ura=1500)
    dispense = record_dispense(scenario, quantity_units=8)
    assert dispense["classification_status"] == "CLASSIFIED_340B"
    assert dispense["line_cost_cents"] == 20000  # 2500 * 8


def test_dispense_340b_without_ceiling_rejected(api):
    """PRD §3.5: "When the cascade lands on `CLASSIFIED_340B`, the dispense must be
    priceable: there must be an effective ceiling-price record (published or provisional)
    for the `(drug_product_id, quarter)` pair. If none exists, the dispense is rejected
    with `ERR_NO_CEILING_PRICE` (HTTP 409)."

    Design: Corner/validations/dispense_340b_without_any_ceiling_rejected
    """
    ce = create_and_approve_covered_entity(medicaid_billing_mode="CARVE_OUT")
    dp = create_drug_product(drug_name="NoCeil Drug")  # no ceiling record
    presc = create_prescriber(ce["id"], relationship_type="EMPLOYED")
    pat = create_patient(ce["id"], medicaid_ffs_enrolled=False)
    resp = api.create_dispense(create_dispense_payload(
        ce["id"], pat["id"], presc["id"], dp["id"], quantity_units=4, quarter="2026Q2"), PHARM)
    validate_error(resp, ApiErrorId.ERR_NO_CEILING_PRICE.value, expected_status=409)
