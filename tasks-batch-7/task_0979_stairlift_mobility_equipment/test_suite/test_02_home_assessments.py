"""Home assessment measurement rules, approval safety gates, and supersede cascades."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error,
    ApiErrorId, MEASURE_STRAIGHT, MODEL_STRAIGHT,
    set_clock, create_catalog_model, create_customer, schedule_assessment,
    measure_assessment, approve_assessment, setup_approved_assessment,
    setup_measured_assessment, create_draft_quote, get_quote,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Measurement range and geometry gates
# ---------------------------------------------------------------------------

def test_home_assessment_measurement_invalid_range_returns_error(api):
    """PRD §3.1: "the vertical `stair_rise_mm` (at least 500 and at most 6000
    millimetres)" and "Any range or geometry violation is rejected with
    `ERR_INVALID_MEASUREMENT` (422)."
    PRD §3.1: "Measurement is only permitted while the assessment is
    `SCHEDULED`; any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/entities/home_assessment_measurement_invalid_range_returns_error
    """
    set_clock()
    customer = create_customer(full_name="Range Rita")
    assessment = schedule_assessment(customer["id"], "2026-06-05")
    res = api.measure_home_assessment(
        assessment["id"],
        dict(MEASURE_STRAIGHT, stair_rise_mm=300),
        ASSESSOR)
    validate_error(res, ApiErrorId.ERR_INVALID_MEASUREMENT)
    after = validate_success(api.get_home_assessment(assessment["id"], ASSESSOR), 200)
    assert after["status"] == "SCHEDULED"


def test_measurement_geometric_constraint_curved_run_too_short(api):
    """PRD §3.1: "All measurement fields must be present and inside their
    ranges, and a geometric safety minimum applies to curved staircases: for
    `CURVED`, the `stair_run_mm` must be at least twice the `stair_rise_mm`."
    PRD §3.1: "Any range or geometry violation is rejected with
    `ERR_INVALID_MEASUREMENT` (422)."

    Design: Corner/state_machines/measurement_geometric_constraint_curved_run_too_short
    """
    set_clock()
    customer = create_customer(full_name="Curve Carl")
    assessment = schedule_assessment(customer["id"])
    # rise 2800 requires run >= 5600 for CURVED; 5000 is inside the raw range
    # (500..12000) so only the geometric rule fails.
    res = api.measure_home_assessment(
        assessment["id"],
        dict(MEASURE_STRAIGHT, staircase_kind="CURVED", stair_rise_mm=2800,
             stair_run_mm=5000),
        ASSESSOR)
    validate_error(res, ApiErrorId.ERR_INVALID_MEASUREMENT)


# ---------------------------------------------------------------------------
# Supersede cascades (transitive)
# ---------------------------------------------------------------------------

def test_measured_assessment_superseded_cascades_to_draft_quote(api):
    """PRD §3.1: "Scheduling is disruptive by design: if the same customer
    already has an assessment in `SCHEDULED` or `MEASURED`, the older one is
    pushed to `SUPERSEDED` by cascade, an `ASSESS_SUPERSEDED` audit event is
    appended, and — critically — when a `MEASURED` assessment is superseded
    this way, any quote still in `DRAFT` or `ISSUED` that was built on it is
    also cascaded to `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/assessment_supersede_two_hop_cascade
    """
    set_clock()
    create_catalog_model()
    base = setup_measured_assessment()
    quote = create_draft_quote(base["customer"]["id"], base["assessment"]["id"])
    assert quote["status"] == "DRAFT"

    res = api.create_home_assessment(
        base["customer"]["id"], {"scheduled_date": "2026-06-15"}, ASSESSOR)
    second = validate_success(res, 201)

    first_after = validate_success(
        api.get_home_assessment(base["assessment"]["id"], ASSESSOR), 200)
    assert first_after["status"] == "SUPERSEDED"
    quote_after = get_quote(quote["id"])
    assert quote_after["status"] == "SUPERSEDED"
    assert second["status"] == "SCHEDULED"


def test_scheduled_assessment_superseded_by_new_assessment(api):
    """PRD §3.1: "Scheduling is disruptive by design: if the same customer
    already has an assessment in `SCHEDULED` or `MEASURED`, the older one is
    pushed to `SUPERSEDED` by cascade, an `ASSESS_SUPERSEDED` audit event is
    appended, and — critically — when a `MEASURED` assessment is superseded
    this way, any quote still in `DRAFT` or `ISSUED` that was built on it is
    also cascaded to `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/assessment_supersede_two_hop_cascade
    """
    set_clock()
    customer = create_customer(full_name="Supersede Two")
    first = schedule_assessment(customer["id"], "2026-06-02")
    res = api.create_home_assessment(
        customer["id"], {"scheduled_date": "2026-06-15"}, ASSESSOR)
    second = validate_success(res, 201)

    first_after = validate_success(
        api.get_home_assessment(first["id"], ASSESSOR), 200)
    assert first_after["status"] == "SUPERSEDED"
    assert second["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Approval: state gate vs safety gates
# ---------------------------------------------------------------------------

def test_approve_scheduled_assessment_returns_invalid_state(api):
    """PRD §2.8: "4. State permission — the target resource is in a state that
    permits the requested transition — failure yields `ERR_INVALID_STATE`
    (409)." precedes "5. Assessment safety and geometry gates on approval
    (stair width versus the model's minimum, power source, landing clearance)
    ... (422)" in the fixed global order, and "the first failing check wins".
    PRD §3.1: "An `AssessmentReviewer` approves a `MEASURED` assessment against
    a target catalog model pinned as `model_code` in the request."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
    """
    set_clock()
    # Model minimum (900) exceeds any width the assessor could have submitted;
    # the assessment is still SCHEDULED, so the state gate must win.
    create_catalog_model(model_code="SL-STRAIGHT-100", min_stair_width_mm=900)
    customer = create_customer(full_name="Conflict Chris")
    assessment = schedule_assessment(customer["id"], "2026-06-05")
    res = api.approve_home_assessment(
        assessment["id"], {"model_code": "SL-STRAIGHT-100"}, REVIEWER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_home_assessment(assessment["id"], ASSESSOR), 200)
    assert after["status"] == "SCHEDULED"


def test_approve_stair_too_narrow_returns_safety_error(api):
    """PRD §3.1: "the measured `stair_width_mm` must be at least the model's
    `min_stair_width_mm`, otherwise `ERR_STAIR_TOO_NARROW`"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
    """
    set_clock()
    create_catalog_model(model_code="SL-STRAIGHT-100", min_stair_width_mm=900)
    customer = create_customer(full_name="Narrow Ned")
    assessment = schedule_assessment(customer["id"])
    measure_assessment(assessment["id"])  # stair_width_mm == 800 < 900
    res = api.approve_home_assessment(
        assessment["id"], {"model_code": "SL-STRAIGHT-100"}, REVIEWER)
    validate_error(res, ApiErrorId.ERR_STAIR_TOO_NARROW)
    after = validate_success(api.get_home_assessment(assessment["id"], ASSESSOR), 200)
    assert after["status"] == "MEASURED"
