"""Damage assessment repair-vs-replace decision: boundary precision and the
deterministic computed recommendation (PRD 3.2)."""
from test_helpers import validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADVISOR = fx.ADVISOR


def _open_work_order():
    cust, veh = fx.setup_customer_and_vehicle()
    wo = fx.create_work_order(cust["id"], veh["id"])
    return wo


# ---------------------------------------------------------------------------
# Difficulty rule 6 — crack_length_150mm_boundary_repair_vs_replace
# ---------------------------------------------------------------------------
def test_crack_exactly_150mm_is_repair(api):
    """PRD 3.2: "the longest crack is strictly greater than 150 millimetres".
    PRD 3.2: "a crack of exactly 150 millimetres is repairable, an edge distance
    of exactly 12 millimetres is repairable, and a chip count of exactly three is
    repairable — only values past those thresholds force a replacement."

    Design: Difficulty/boundary_precision_check/crack_length_150mm_boundary_repair_vs_replace
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=1, longest_crack_mm=150, in_driver_primary_view=False, edge_distance_mm=80),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPAIR", (
        f"crack exactly 150 mm must be REPAIR, got {data['recommendation']}")


def test_crack_just_over_150mm_is_replace(api):
    """PRD 3.2: "the longest crack is strictly greater than 150 millimetres" forces
    REPLACE.
    PRD 3.2: "only values past those thresholds force a replacement."

    Design: Difficulty/boundary_precision_check/crack_length_150mm_boundary_repair_vs_replace
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=1, longest_crack_mm=150.1, in_driver_primary_view=False, edge_distance_mm=80),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPLACE", (
        f"crack 150.1 mm must be REPLACE, got {data['recommendation']}")


# ---------------------------------------------------------------------------
# Corner calculations — chip_count_3_boundary_repair
# ---------------------------------------------------------------------------
def test_chip_count_exactly_3_is_repair(api):
    """PRD 3.2: "the chip count is strictly greater than three" forces REPLACE,
    and PRD 3.2: "a chip count of exactly three is repairable".

    Design: Corner/calculations/chip_count_3_boundary_repair
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=3, longest_crack_mm=10, in_driver_primary_view=False, edge_distance_mm=90),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPAIR", (
        f"chip_count 3 must be REPAIR, got {data['recommendation']}")


def test_chip_count_4_is_replace(api):
    """PRD 3.2: "the chip count is strictly greater than three" forces a REPLACE
    recommendation.

    Design: Corner/calculations/chip_count_3_boundary_repair
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=4, longest_crack_mm=10, in_driver_primary_view=False, edge_distance_mm=90),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPLACE", (
        f"chip_count 4 must be REPLACE, got {data['recommendation']}")


# ---------------------------------------------------------------------------
# Corner calculations — edge_distance_12mm_boundary_repair
# ---------------------------------------------------------------------------
def test_edge_distance_exactly_12mm_is_repair(api):
    """PRD 3.2: "the nearest damage is strictly less than 12 millimetres from the
    edge, where a crack near the edge propagates" forces REPLACE; PRD 3.2: "an edge
    distance of exactly 12 millimetres is repairable".

    Design: Corner/calculations/edge_distance_12mm_boundary_repair
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=1, longest_crack_mm=10, in_driver_primary_view=False, edge_distance_mm=12),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPAIR", (
        f"edge_distance 12 mm must be REPAIR, got {data['recommendation']}")


def test_edge_distance_just_under_12mm_is_replace(api):
    """PRD 3.2: "the nearest damage is strictly less than 12 millimetres from the
    edge" forces a REPLACE recommendation.

    Design: Corner/calculations/edge_distance_12mm_boundary_repair
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=1, longest_crack_mm=10, in_driver_primary_view=False, edge_distance_mm=11.9),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPLACE", (
        f"edge_distance 11.9 mm must be REPLACE, got {data['recommendation']}")


# ---------------------------------------------------------------------------
# Corner entities — damage_assessment_recommendation_is_computed_not_input
# ---------------------------------------------------------------------------
def test_recommendation_is_server_computed_repair(api):
    """PRD 3.2: "From these four measurements the server computes a recommendation
    and stores the assessment in DRAFT status."
    PRD 3.2: "if none hold, the recommendation is REPAIR."

    Design: Corner/entities/damage_assessment_recommendation_is_computed_not_input
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=1, longest_crack_mm=10, in_driver_primary_view=False, edge_distance_mm=90),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPAIR", (
        f"clearly repairable reading must compute REPAIR, got {data['recommendation']}")
    assert data["status"] == "DRAFT", f"new assessment must be DRAFT, got {data['status']}"


def test_recommendation_driver_primary_view_forces_replace(api):
    """PRD 3.2: "A damage in the driver's primary view always forces a replacement
    regardless of the measured dimensions."

    Design: Corner/entities/damage_assessment_recommendation_is_computed_not_input
    """
    wo = _open_work_order()
    resp = api.create_damage_assessment(
        wo["id"],
        f.create_damage_assessment_payload(
            chip_count=0, longest_crack_mm=5, in_driver_primary_view=True, edge_distance_mm=90),
        ADVISOR)
    data = validate_success(resp, 201)
    assert data["recommendation"] == "REPLACE", (
        f"damage in driver primary view must force REPLACE, got {data['recommendation']}")
