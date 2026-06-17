"""Per-tree hazard scoring, tier bucketing, and the dbh boundary
(PRD §3.3). Assessment recomputes per-tree scores, sets work-order
hazard_level, and is immediately visible in the response.

Difficulty: combinatorial_formula (tree hazard), boundary_precision_check
(dbh 18-inch boundary). Corner: computed hazard_score, immediate consistency.
"""
from test_helpers import (
    validate_success,
    api_client,
    create_service_area,
    create_work_order,
    add_tree,
    TEST_USERS,
)


# ─── combinatorial_formula / tree_hazard_score_three_input_nonlinear ───


def test_hazard_score_three_input_nonlinear_severe(api):
    """PRD §3.3: "A single tree's hazard score is the sum of three
    contributions." PRD §3.3: "a tree at least 36 inches in diameter
    contributes 50 points" PRD §3.3: "The **lean contribution** takes the
    lean in degrees, divides it by 5 and rounds that quotient down to a whole
    number, multiplies the result by 10, and then caps the total at 30"
    PRD §3.3: "The **decay contribution** is 20 points when `has_visible_decay`
    is true and 0 otherwise."

    Design: Difficulty/combinatorial_formula/tree_hazard_score_three_input_nonlinear
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB", site_address="3 Pine St")
    tree = add_tree(wo["id"], species="Fir", dbh_inches=36, lean_degrees=10,
                    has_visible_decay=True)
    assessed = validate_success(
        api.assess_work_order(wo["id"], TEST_USERS["arborist_headers"]), 200,
    )
    # 50 (dbh>=36) + 20 (floor(10/5)*10=20, capped 30) + 20 (decay) = 90
    fetched_tree = validate_success(
        api.get_tree(wo["id"], tree["id"], TEST_USERS["arborist_headers"]), 200,
    )
    assert fetched_tree["hazard_score"] == 90
    assert fetched_tree["hazard_tier"] == "SEVERE"
    assert assessed["hazard_level"] == "SEVERE"


def test_hazard_tier_severe_threshold_at_70(api):
    """PRD §3.3: "a score of 70 or more is `SEVERE`, a score of at least 40
    but under 70 is `MODERATE`, and anything below 40 is `LOW`."

    Design: Difficulty/combinatorial_formula/tree_hazard_score_three_input_nonlinear
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    # dbh 40 (50) + lean 15 (floor(15/5)*10=30) + decay (20) = 100 SEVERE
    tree = add_tree(wo["id"], species="Oak", dbh_inches=40, lean_degrees=15,
                    has_visible_decay=True)
    validate_success(api.assess_work_order(wo["id"], TEST_USERS["arborist_headers"]), 200)
    fetched = validate_success(
        api.get_tree(wo["id"], tree["id"], TEST_USERS["arborist_headers"]), 200,
    )
    assert fetched["hazard_score"] == 100
    assert fetched["hazard_tier"] == "SEVERE"


# ─── boundary_precision_check / hazard_tier_dbh_18_inch_boundary ───


def test_hazard_dbh_boundary_at_18_lands_moderate(api):
    """PRD §3.3: "a tree that is at least 18 inches but under 36 contributes
    30 points" PRD §3.3: "The boundary is inclusive at the lower edge — a tree
    of exactly 18.0 inches lands in the 30-point band, while 17.999 inches
    falls to the 10-point band." PRD §3.3: "The boundary at 40 is inclusive —
    a score of exactly 40 is `MODERATE`, not `LOW`."

    Design: Difficulty/boundary_precision_check/hazard_tier_dbh_18_inch_boundary
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB", site_address="13 Edge St")
    tree = add_tree(wo["id"], species="Elm", dbh_inches=18.0, lean_degrees=10)
    validate_success(api.assess_work_order(wo["id"], TEST_USERS["arborist_headers"]), 200)
    fetched = validate_success(
        api.get_tree(wo["id"], tree["id"], TEST_USERS["arborist_headers"]), 200,
    )
    # dbh 18.0 -> 30 + lean 10 -> 20 = 50 MODERATE (and 40 boundary is MODERATE)
    assert fetched["hazard_score"] == 50
    assert fetched["hazard_tier"] == "MODERATE"


def test_hazard_dbh_boundary_below_18_lands_low(api):
    """PRD §3.3: "The boundary is inclusive at the lower edge — a tree of
    exactly 18.0 inches lands in the 30-point band, while 17.999 inches falls
    to the 10-point band." PRD §3.3: "and anything below 40 is `LOW`."

    Design: Difficulty/boundary_precision_check/hazard_tier_dbh_18_inch_boundary
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB", site_address="14 Edge St")
    tree = add_tree(wo["id"], species="Elm", dbh_inches=17.999, lean_degrees=10)
    validate_success(api.assess_work_order(wo["id"], TEST_USERS["arborist_headers"]), 200)
    fetched = validate_success(
        api.get_tree(wo["id"], tree["id"], TEST_USERS["arborist_headers"]), 200,
    )
    # dbh 17.999 -> 10 + lean 10 -> 20 = 30 LOW
    assert fetched["hazard_score"] == 30
    assert fetched["hazard_tier"] == "LOW"


# ─── Corner: computed hazard_score + immediate consistency ───


def test_computed_hazard_score_ignores_client_supplied_value(api):
    """PRD §3.3: "anything thinner contributes 10 points." PRD §3.2: "Two
    computed fields ride along on each tree: its `hazard_score` and its
    `hazard_tier`, both of which are filled in by the assessment described
    next." PRD §3.3: "(The per-tree score is also computed when a tree is
    first added while the work order is still `DRAFT`.)"

    Design: Corner/entities/computed_hazard_score_ignores_client_supplied_value
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    res = api.create_tree(
        wo["id"],
        {"species": "Dogwood", "dbh_inches": 10, "hazard_score": 999},
        TEST_USERS["arborist_headers"],
    )
    tree = validate_success(res, 201)
    assert tree["hazard_score"] == 10
    assert tree["hazard_tier"] == "LOW"


def test_assess_hazard_level_visible_in_same_response(api):
    """PRD §3.3: "it recomputes a per-tree `hazard_score` for every child
    tree, derives each tree's `hazard_tier`, sets the work order's
    `hazard_level` to the maximum tier across all its trees, recomputes
    `requires_permit`, and increments the work order's `version` by one."

    Design: Corner/consistency_model/immediate_assess_visible_in_same_response
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Oak", dbh_inches=40, lean_degrees=15,
                    has_visible_decay=True)
    assessed = validate_success(
        api.assess_work_order(wo["id"], TEST_USERS["arborist_headers"]), 200,
    )
    assert assessed["hazard_level"] == "SEVERE"
    fetched = validate_success(
        api.get_tree(wo["id"], tree["id"], TEST_USERS["arborist_headers"]), 200,
    )
    assert fetched["hazard_score"] == 100
