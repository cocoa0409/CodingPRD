"""Property registration and derived life-safety metrics.

Depth (queue A): occupant load net-vs-gross, required-fire-flow min/max tiers,
required-exits boundary at 50. Breadth (queue B): full computed-field creation,
fire-flow minimum clamp.
"""
from test_helpers import (
    validate_success, assert_property,
    create_property_payload, create_property,
    TEST_USERS,
)

FIRE_MARSHAL = TEST_USERS["fire_marshal_headers"]


# ─── Difficulty/dual_variant_calc/occupant_load_net_vs_gross ───────────────
def test_posted_occupant_load_uses_net_area(api, fire_marshal_headers):
    """PRD §3.1: "The posted occupant load is the gross floor area multiplied by a
    net-area ratio of 0.85, that product divided by the occupancy factor, and the
    result taken to the floor (rounded down to a whole number of people)."

    Design: Difficulty/dual_variant_calc/occupant_load_net_vs_gross
    """
    res = api.create_property(create_property_payload(
        address="2 B St", occupancy_classification="EDUCATIONAL",
        construction_type="TYPE_III", total_floor_area_sqft=2000, stories=1),
        fire_marshal_headers)
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["occupant_load"] == 85, f"posted (net) occupant_load expected 85, got {prop['occupant_load']}"


def test_design_occupant_load_uses_gross_area(api, fire_marshal_headers):
    """PRD §3.1: "uses the gross-area method: the gross floor area divided by the
    same occupancy factor, taken to the floor. Because it omits the 0.85 net-area
    ratio, it is always at least as large as the posted occupant load."

    Design: Difficulty/dual_variant_calc/occupant_load_net_vs_gross
    """
    res = api.create_property(create_property_payload(
        address="2 B St", occupancy_classification="EDUCATIONAL",
        construction_type="TYPE_III", total_floor_area_sqft=2000, stories=1),
        fire_marshal_headers)
    prop = validate_success(res, 201)
    assert prop["design_occupant_load"] == 100, \
        f"design (gross) occupant_load expected 100, got {prop['design_occupant_load']}"
    assert prop["design_occupant_load"] != prop["occupant_load"]


# ─── Difficulty/combinatorial_formula/required_fire_flow_min_max_tiers ──────
def test_required_fire_flow_combines_area_construction_hazard(api, fire_marshal_headers):
    """PRD §3.1: "Start from a raw value equal to the gross floor area multiplied by
    a flow coefficient of 0.09, multiplied by a construction factor, multiplied by an
    occupancy hazard multiplier."

    Design: Difficulty/combinatorial_formula/required_fire_flow_min_max_tiers
    """
    prop = create_property(occupancy_classification="FACTORY", construction_type="TYPE_V",
                           total_floor_area_sqft=20000, stories=2, address="3 C St")
    assert prop["required_fire_flow_gpm"] == 3500, \
        f"required_fire_flow_gpm expected 3500, got {prop['required_fire_flow_gpm']}"


def test_required_fire_flow_rounded_up_to_250(api, fire_marshal_headers):
    """PRD §3.1: "Finally round the clamped value up to the nearest multiple of 250 gpm."

    Design: Difficulty/combinatorial_formula/required_fire_flow_min_max_tiers
    """
    prop = create_property(occupancy_classification="FACTORY", construction_type="TYPE_V",
                           total_floor_area_sqft=20000, stories=2, address="3 C St")
    ff = prop["required_fire_flow_gpm"]
    # raw = 20000 * 0.09 * 1.5 * 1.25 = 3375, clamped unchanged, rounded UP to 3500.
    assert ff % 250 == 0, f"required_fire_flow_gpm must be a multiple of 250, got {ff}"
    assert ff == 3500 and ff > 3375, f"clamped 3375 must round UP to 3500, got {ff}"


# ─── Difficulty/boundary_precision_check/occupant_load_exit_threshold_50 ────
def test_required_exits_below_fifty_is_one(api, fire_marshal_headers):
    """PRD §3.1: "anything below 50 requires 1 exit. Thus 49 occupants require one
    exit and 50 occupants require two."

    Design: Difficulty/boundary_precision_check/occupant_load_exit_threshold_50
    """
    prop = create_property(occupancy_classification="EDUCATIONAL", construction_type="TYPE_III",
                           total_floor_area_sqft=1176, stories=1, address="11 K St")
    assert prop["occupant_load"] == 49, f"occupant_load expected 49, got {prop['occupant_load']}"
    assert prop["required_exits"] == 1, f"required_exits expected 1 at load 49, got {prop['required_exits']}"


def test_required_exits_at_fifty_is_two(api, fire_marshal_headers):
    """PRD §3.1: "from 50 up to but not including 500 requires 2 exits" and "50
    occupants require two."

    Design: Difficulty/boundary_precision_check/occupant_load_exit_threshold_50
    """
    prop = create_property(occupancy_classification="EDUCATIONAL", construction_type="TYPE_III",
                           total_floor_area_sqft=1177, stories=1, address="12 L St")
    assert prop["occupant_load"] == 50, f"occupant_load expected 50, got {prop['occupant_load']}"
    assert prop["required_exits"] == 2, f"required_exits expected 2 at load 50, got {prop['required_exits']}"


# ─── Corner/entities/corner_create_property_success_with_computed_fields ────
def test_create_property_returns_all_computed_fields(api, fire_marshal_headers):
    """PRD §3.1: "On registration, and again on every amendment, the server computes
    four derived fields and stores them on the property."

    Design: Corner/entities/corner_create_property_success_with_computed_fields
    """
    res = api.create_property(create_property_payload(
        address="20 T St", occupancy_classification="BUSINESS",
        construction_type="TYPE_II", total_floor_area_sqft=3000, stories=1),
        fire_marshal_headers)
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["occupant_load"] == 17
    assert prop["design_occupant_load"] == 20
    assert prop["required_exits"] == 1
    assert prop["required_fire_flow_gpm"] == 500


# ─── Corner/calculations/corner_required_fire_flow_min_clamp_500 ────────────
def test_required_fire_flow_clamped_up_to_minimum(api, fire_marshal_headers):
    """PRD §3.1: "Clamp that raw value into the closed range from a floor of 500 gpm
    to a ceiling of 8000 gpm — that is, take the larger of the raw value and 500, then
    the smaller of that and 8000."

    Design: Corner/calculations/corner_required_fire_flow_min_clamp_500
    """
    prop = create_property(occupancy_classification="BUSINESS", construction_type="TYPE_I",
                           total_floor_area_sqft=1000, stories=1, address="28 BB St")
    assert prop["required_fire_flow_gpm"] == 500, \
        f"raw 54 gpm must clamp up to floor 500, got {prop['required_fire_flow_gpm']}"
