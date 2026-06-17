"""Estimate pricing arithmetic, change-order re-pricing deltas, and permit fees.

Queue A (difficulty) instances get two tests each; queue B (corner) get one.
All expected cent values are copied verbatim from the design indices.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_project_with_approved_proof, create_permitting_project,
    create_estimate_payload, create_change_order_payload, create_sign_project_payload,
    create_permit_payload,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
PC = TEST_USERS["permit_clerk_headers"]


# ═══ Queue A: combinatorial_formula / estimate_total_nonlinear_three_input ═════

def test_estimate_total_acrylic_illuminated_rush_nonlinear(api):
    """PRD §3.2: "If the project is illuminated, an illumination surcharge of
    fifteen percent of the subtotal is taken, rounded half up to whole cents...
    The rush surcharge, if the project carries the rush flag, is twenty percent —
    but it is computed on the illumination-inflated base, meaning the subtotal
    plus the illumination surcharge, again rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/estimate_total_nonlinear_three_input_interaction
    """
    project, proof = create_project_with_approved_proof(
        color_count=4, customer_name="Lit Co", site_address="5 Glow Ave",
        sign_type="WALL", face_width_in=48, face_height_in=36,
        placement_height_ft=6, illuminated=True, rush=True)
    est = validate_success(api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="ACRYLIC"), SM), 201)
    assert est["area_sqft"] == 12
    assert est["subtotal_cents"] == 53700
    assert est["surcharge_cents"] == 20406
    assert est["total_cents"] == 74106


def test_estimate_total_components_sum_to_total(api):
    """PRD §3.2: "The subtotal_cents is the sum of material_cost_cents and
    labor_cost_cents." "The surcharge_cents is the sum of the illumination and
    rush surcharges, and the estimate's total_cents is subtotal_cents plus
    surcharge_cents."

    Design: Difficulty/combinatorial_formula/estimate_total_nonlinear_three_input_interaction
    """
    project, proof = create_project_with_approved_proof(
        color_count=4, customer_name="Lit2 Co", site_address="5 Glow Ave",
        sign_type="WALL", face_width_in=48, face_height_in=36,
        placement_height_ft=6, illuminated=True, rush=True)
    est = validate_success(api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="ACRYLIC"), SM), 201)
    assert est["subtotal_cents"] == est["material_cost_cents"] + est["labor_cost_cents"]
    assert est["total_cents"] == est["subtotal_cents"] + est["surcharge_cents"]


# ═══ Queue A: combinatorial_formula / surcharge_pinned_rounding_order ═════════

def test_surcharge_pinned_rounding_illum_before_rush(api):
    """PRD §3.2: "Surcharges then stack on the subtotal in a pinned order:
    illumination first, then rush."

    Design: Difficulty/combinatorial_formula/surcharge_pinned_rounding_order_illum_before_rush
    """
    project, proof = create_project_with_approved_proof(
        color_count=4, customer_name="Order Co", site_address="7 Round Rd",
        sign_type="WALL", face_width_in=48, face_height_in=36,
        placement_height_ft=6, illuminated=True, rush=True)
    est = validate_success(api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="ACRYLIC"), SM), 201)
    assert est["surcharge_cents"] == 20406
    assert est["total_cents"] == 74106


def test_surcharge_equals_subtotal_plus_total_consistency(api):
    """PRD §3.2: "The rush surcharge... is computed on the illumination-inflated
    base, meaning the subtotal plus the illumination surcharge, again rounded
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/surcharge_pinned_rounding_order_illum_before_rush
    """
    project, proof = create_project_with_approved_proof(
        color_count=4, customer_name="Order2 Co", site_address="7 Round Rd",
        sign_type="WALL", face_width_in=48, face_height_in=36,
        placement_height_ft=6, illuminated=True, rush=True)
    est = validate_success(api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="ACRYLIC"), SM), 201)
    # illum = round(53700*0.15)=8055; rush = round((53700+8055)*0.20)=12351
    assert est["surcharge_cents"] == 8055 + 12351


# ═══ Queue A: dual_variant_calc / estimate_provisional_vs_change_order_rescope ═

def test_dual_variant_estimate_total_vs_change_order_delta(api):
    """PRD §3.6: "At proposal, the system computes the signed delta_total_cents by
    re-pricing the entire sign under the proposed scope and subtracting the
    accepted estimate's total."

    Design: Difficulty/dual_variant_calc/estimate_provisional_vs_change_order_rescope_on_estimate_domain
    """
    project, proof, estimate = create_permitting_project(
        color_count=3, substrate="ALUMINUM",
        customer_name="Acme", site_address="1 Main St",
        sign_type="WALL", face_width_in=36, face_height_in=24, placement_height_ft=6)
    assert estimate["total_cents"] == 24300

    co = validate_success(api.create_change_order(
        project["id"], create_change_order_payload(
            reason="wider face", new_face_width_in=60), SM), 201)
    assert co["delta_total_cents"] == 7200


def test_dual_variant_change_order_delta_equals_rescope_minus_baseline(api):
    """PRD §3.6: "The resulting re-scoped total minus the accepted estimate's
    total_cents is the delta — which can be negative when downgrading."

    Design: Difficulty/dual_variant_calc/estimate_provisional_vs_change_order_rescope_on_estimate_domain
    """
    project, proof, estimate = create_permitting_project(
        color_count=3, substrate="ALUMINUM",
        customer_name="Acme2", site_address="1 Main St",
        sign_type="WALL", face_width_in=36, face_height_in=24, placement_height_ft=6)
    co = validate_success(api.create_change_order(
        project["id"], create_change_order_payload(
            reason="wider face", new_face_width_in=60), SM), 201)
    # re-quote 31500 minus accepted baseline 24300 == 7200
    assert co["delta_total_cents"] == estimate["total_cents"] + 7200 - 24300


# ═══ Queue B: corner calculations ════════════════════════════════════════════

def test_estimate_total_steel_no_surcharge(api):
    """PRD §3.2: "The material_cost_cents is area_sqft multiplied by
    material_rate_cents_per_sqft." "color labor is color_count times 4500 cents,
    and this color-labor amount is then scaled by a substrate labor multiplier —
    1.00 for ALUMINUM, 1.25 for ACRYLIC, and 1.50 for STEEL." "The subtotal_cents
    is the sum of material_cost_cents and labor_cost_cents."

    Design: Corner/calculations/estimate_total_steel_no_surcharge_correct_result
    """
    project, proof = create_project_with_approved_proof(
        color_count=2, customer_name="Steel Co", site_address="14 Heavy St",
        sign_type="WALL", face_width_in=60, face_height_in=48, placement_height_ft=6)
    est = validate_success(api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="STEEL"), SM), 201)
    assert est["area_sqft"] == 20
    assert est["material_cost_cents"] == 68000
    assert est["labor_cost_cents"] == 13500
    assert est["total_cents"] == 81500


def test_area_sqft_ceil_boundary_exactly_one(api):
    """PRD §3.2: "the billed area area_sqft is the sign-face area in square inches
    — face_width_in multiplied by face_height_in — divided by 144 and then
    rounded up to the next whole square foot."

    Design: Corner/calculations/area_sqft_ceil_boundary_exactly_one
    """
    project, proof = create_project_with_approved_proof(
        color_count=1, customer_name="Ceil Co", site_address="15 Edge St",
        sign_type="WALL", face_width_in=12, face_height_in=12, placement_height_ft=6)
    est = validate_success(api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="ALUMINUM"), SM), 201)
    assert est["area_sqft"] == 1
    assert est["material_cost_cents"] == 1800


def test_change_order_substrate_downgrade_negative_delta(api):
    """PRD §3.6: "The resulting re-scoped total minus the accepted estimate's
    total_cents is the delta — which can be negative when downgrading, for example
    from STEEL to ALUMINUM."

    Design: Corner/calculations/change_order_substrate_delta_negative_downgrade
    """
    project, proof, estimate = create_permitting_project(
        color_count=2, substrate="STEEL",
        customer_name="Down Co", site_address="16 Cut St",
        sign_type="WALL", face_width_in=60, face_height_in=48, placement_height_ft=6)
    assert estimate["total_cents"] == 81500
    co = validate_success(api.create_change_order(
        project["id"], create_change_order_payload(
            reason="cheaper material", new_substrate="ALUMINUM"), SM), 201)
    assert co["delta_total_cents"] == -36500


def test_permit_fee_city_b_structural_lookup(api):
    """PRD §3.3: "A STRUCTURAL permit costs 25000 cents in CITY_A, 32000 cents in
    CITY_B, and 0 cents in COUNTY_C."

    Design: Corner/calculations/permit_fee_city_b_structural_lookup
    """
    project = validate_success(api.create_sign_project(create_sign_project_payload(
        customer_name="Fee Co", site_address="17 Hall St",
        jurisdiction_code="CITY_B", sign_type="WALL",
        face_width_in=36, face_height_in=24, placement_height_ft=6), SM), 201)
    permit = validate_success(api.create_permit(
        project["id"], create_permit_payload(permit_kind="STRUCTURAL"), PC), 201)
    assert permit["fee_cents"] == 32000
