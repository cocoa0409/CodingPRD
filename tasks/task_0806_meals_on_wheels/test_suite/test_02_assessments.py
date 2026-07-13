"""Nutritional/functional assessment computation and lifecycle tests."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_client_payload, create_assessment_payload,
    assert_assessment,
    TEST_USERS,
)
from test_helpers.fixtures import intake_client, create_finalized_assessment

INTAKE = TEST_USERS["intake_coordinator_headers"]
NUTRITION = TEST_USERS["nutritionist_headers"]


def test_nutrition_risk_moderate_at_five_points(api):
    """PRD §3.2: "The nutritional risk band, `nutrition_risk_category`, is `HIGH` when
    `nutrition_determine_points` is at least 6, `MODERATE` when it is at least 3 but below
    6 (so a total of 5 is `MODERATE` and `HIGH` begins exactly at 6), and `GOOD` otherwise."

    Design: Difficulty/boundary_precision_check/nutrition_high_risk_threshold_exact_six
    """
    client = intake_client(api)
    resp = api.create_assessment(client["id"], create_assessment_payload(nutrition_determine_points=5), NUTRITION)
    data = validate_success(resp, 201)
    assert_assessment(data)
    assert data["nutrition_risk_category"] == "MODERATE", "5 points is MODERATE (below HIGH_MIN 6)"


def test_nutrition_risk_high_at_exactly_six_points(api):
    """PRD §3.2: "The nutritional risk band, `nutrition_risk_category`, is `HIGH` when
    `nutrition_determine_points` is at least 6, `MODERATE` when it is at least 3 but below
    6 (so a total of 5 is `MODERATE` and `HIGH` begins exactly at 6), and `GOOD` otherwise."

    Design: Difficulty/boundary_precision_check/nutrition_high_risk_threshold_exact_six
    """
    client = intake_client(api)
    resp = api.create_assessment(client["id"], create_assessment_payload(nutrition_determine_points=6), NUTRITION)
    data = validate_success(resp, 201)
    assert data["nutrition_risk_category"] == "HIGH", "HIGH begins exactly at 6"


def test_functional_level_partial_at_four_dependent_at_five(api):
    """PRD §3.2: "The functional band, `functional_level`, is `DEPENDENT` when `adl_score`
    is at least 5, `PARTIAL` when it is at least 2 but below 5, and `INDEPENDENT` otherwise."

    Design: Corner/calculations/functional_level_dependent_threshold_at_five
    """
    client = intake_client(api)
    lvl4 = validate_success(
        api.create_assessment(client["id"], create_assessment_payload(adl_score=4), NUTRITION), 201
    )
    assert lvl4["functional_level"] == "PARTIAL"
    lvl5 = validate_success(
        api.create_assessment(client["id"], create_assessment_payload(adl_score=5), NUTRITION), 201
    )
    assert lvl5["functional_level"] == "DEPENDENT"


def test_finalize_already_finalized_assessment_rejected(api):
    """PRD §3.2: "finalization is allowed only from `DRAFT`, and attempting it on any other
    status yields `ERR_ASSESSMENT_NOT_DRAFT` (HTTP 409)."

    Design: Corner/state_machines/assessment_finalize_from_finalized_returns_invalid
    """
    client = intake_client(api)
    finalized = create_finalized_assessment(api, client["id"])
    resp = api.finalize_assessment(finalized["id"], NUTRITION)
    validate_error(resp, "ERR_ASSESSMENT_NOT_DRAFT", 409)


def test_assessments_listable_by_client(api):
    """PRD §3.2: "A client's assessments can be listed and filtered by `status`."

    Design: Corner/endpoints/assessments_reverse_reachable_by_client
    """
    client = intake_client(api)
    created = validate_success(
        api.create_assessment(client["id"], create_assessment_payload(), NUTRITION), 201
    )
    resp = api.list_client_assessments(client["id"], NUTRITION)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == created["id"]
