"""Breadth tests for the pricing tiers, bundle substitution, and clinical
reference-bound precision.
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
    make_patient_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]


# ---------------------------------------------------------------------------
# Corner/calculations/platform_tier1_just_below_threshold_no_discount
# ---------------------------------------------------------------------------
def test_platform_tier_just_below_threshold_no_discount(api):
    """PRD 3.3: "otherwise, when the subtotal is at least 20000 cents (two hundred
    dollars), the platform rate is 0.10; otherwise the rate is zero."

    Subtotal 19999 stays at 0%: estimated_total_cents == 19999.

    Design: Corner/calculations/platform_tier1_just_below_threshold_no_discount
    """
    off = fx.create_offering(api=api, test_code="Z199b", display_name="Below Tier", list_price_cents=19999, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["subtotal_cents"] == 19999
    assert cart_read["estimated_total_cents"] == 19999


# ---------------------------------------------------------------------------
# Corner/calculations/platform_tier2_at_50000_subtotal
# ---------------------------------------------------------------------------
def test_platform_tier2_at_exactly_50000_subtotal(api):
    """PRD 3.3: "When the subtotal is at least 50000 cents (five hundred dollars),
    the platform rate is 0.15; otherwise, when the subtotal is at least 20000 cents
    (two hundred dollars), the platform rate is 0.10; otherwise the rate is zero."
    PRD 3.3: "The platform discount is the subtotal multiplied by that rate, rounded
    half-up to a whole cent, and estimated_total_cents is the subtotal minus that
    rounded discount."

    Subtotal 50000 -> 50000 - round(50000*0.15)=7500 = 42500.

    Design: Corner/calculations/platform_tier2_at_50000_subtotal
    """
    off = fx.create_offering(api=api, test_code="Z50", display_name="Tier Two", list_price_cents=50000, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["estimated_total_cents"] == 42500


# ---------------------------------------------------------------------------
# Corner/calculations/bundle_substitution_replaces_member_sum
# ---------------------------------------------------------------------------
def test_bundle_substitution_replaces_member_sum(api):
    """PRD 3.3: "a bundle qualifies if every one of its member_test_codes still has
    an unmatched line available; when it qualifies, the bundle's bundle_price_cents
    is added to the running subtotal and those member lines' codes are consumed".
    PRD 3.1: "a bundle_price_cents greater than zero that substitutes for the sum
    of the members' list prices when every member is present in a cart."

    Cart {BA,BB,BC}@4000 each with bundle WB3@9000: subtotal 9000 (not 12000),
    below tier1 so estimated_total_cents 9000.

    Design: Corner/calculations/bundle_substitution_replaces_member_sum
    """
    off_ba = fx.create_offering(api=api, test_code="BA", display_name="BA", list_price_cents=4000, specimen_type="BLOOD")
    off_bb = fx.create_offering(api=api, test_code="BB", display_name="BB", list_price_cents=4000, specimen_type="BLOOD")
    off_bc = fx.create_offering(api=api, test_code="BC", display_name="BC", list_price_cents=4000, specimen_type="BLOOD")
    fx.create_bundle(["BA", "BB", "BC"], api=api, bundle_code="WB3", display_name="Wellness B3", bundle_price_cents=9000)
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    for off in (off_ba, off_bb, off_bc):
        fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["subtotal_cents"] == 9000
    assert cart_read["estimated_total_cents"] == 9000


# ---------------------------------------------------------------------------
# Corner/calculations/provisional_flag_reference_boundary_strict
# ---------------------------------------------------------------------------
def test_provisional_flag_reference_high_boundary_is_normal(api):
    """PRD 3.8: "otherwise the flag is ABNORMAL when a ref_low bound exists and v
    is strictly below it, or a ref_high bound exists and v is strictly above it;
    otherwise the flag is NORMAL. The critical bounds are inclusive and the
    reference bounds are strict, so a value exactly equal to ref_high is NORMAL."

    analyzer_value 100 == ref_high(100) is NORMAL (strict >).

    Design: Corner/calculations/provisional_flag_reference_boundary_strict
    """
    ctx = fx.setup_collected_line(
        fulfillment_mode="HOME_KIT",
        offering_overrides={
            "test_code": "BND", "display_name": "Boundary", "list_price_cents": 4000,
            "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100, "critical_high": 400,
        },
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    spec = ctx["specimen"]
    res = fx.process_specimen(spec["id"], 100, api=api)
    assert res["provisional_flag"] == "NORMAL"
