"""Grading (provisional vs final overall), subgrade constraints, finalize
precondition, authentication verdicts and the alteration-note guard.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_grade_assessment_payload, create_authentication_payload,
    make_customer_headers, TEST_USERS,
    setup_item_intake_logged, setup_item_graded,
    grade_item, finalize_assessment,
)


GRADER = TEST_USERS["grader_headers"]
AUTH = TEST_USERS["authenticator_headers"]


# ---------------------------------------------------------------------------
# Provisional vs final overall divergence on uneven subgrades
# ---------------------------------------------------------------------------
def test_provisional_overall_ignores_lowest_subgrade_cap(api):
    """PRD §3.4: "Multiply the raw value by two, take the floor to the nearest
    whole number, and divide by two; the result is the provisional overall
    rounded down to the nearest half point. The provisional grade deliberately
    does not apply the lowest-subgrade cap."

    Design: Difficulty/dual_variant_calc/grade_provisional_vs_final_diverge_on_uneven_subgrades
    """
    # Equal 2500 weights, subgrades 10/10/10/6 -> raw 9.0 -> provisional 9.0.
    customer, sl, gs, sub, item, ga = setup_item_graded(
        subgrades=(10, 10, 10, 6), email="c1@x.com",
    )
    assert ga["provisional_overall"] == 9.0, "provisional must be weighted-floored 9.0, ignoring the cap"


def test_final_overall_applies_lowest_subgrade_cap(api):
    """PRD §3.4: "the capped value is the lesser of the weighted-floored value and
    that smallest subgrade plus 1.5; finally, multiply the capped value by two,
    take the floor, and divide by two to land it back on the half-point lattice."

    Design: Difficulty/dual_variant_calc/grade_provisional_vs_final_diverge_on_uneven_subgrades
    """
    # 10/10/10/6: weighted 9.0; min 6 + 1.5 = 7.5; final = min(9.0, 7.5) = 7.5.
    customer, sl, gs, sub, item, ga = setup_item_graded(
        subgrades=(10, 10, 10, 6), finalized=True, email="c1b@x.com",
    )
    final = validate_success(api.get_grade_assessment(ga["id"], GRADER))
    assert final["provisional_overall"] == 9.0
    assert final["final_overall"] == 7.5, "lowest-subgrade+1.5 cap must pull final to 7.5"
    assert final["provisional_overall"] != final["final_overall"]


def test_final_overall_nonlinear_min_cap_three_inputs(api):
    """PRD §3.4: "the final overall falls below the provisional overall even
    though the inputs are identical, because the lowest-subgrade-plus-1.5 cap
    bites."

    Design: Difficulty/combinatorial_formula/final_grade_nonlinear_min_cap_three_inputs
    """
    customer, sl, gs, sub, item, ga = setup_item_graded(
        subgrades=(10, 10, 10, 6), email="c3@x.com",
    )
    finalize_assessment(ga["id"])
    final = validate_success(api.get_grade_assessment(ga["id"], GRADER))
    assert final["final_overall"] == 7.5, "final must be 7.5 from the cap, not 9.0 from the weighted mean"


def test_final_overall_no_cap_when_subgrades_even(api):
    """PRD §3.4: "the capped value is the lesser of the weighted-floored value and
    that smallest subgrade plus 1.5; finally, multiply the capped value by two,
    take the floor, and divide by two to land it back on the half-point lattice."

    Design: Difficulty/combinatorial_formula/final_grade_nonlinear_min_cap_three_inputs
    """
    # 9/9/9/9: weighted 9.0; min 9 + 1.5 = 10.5; final = min(9.0, 10.5) = 9.0.
    customer, sl, gs, sub, item, ga = setup_item_graded(
        subgrades=(9, 9, 9, 9), email="c3b@x.com",
    )
    finalize_assessment(ga["id"])
    final = validate_success(api.get_grade_assessment(ga["id"], GRADER))
    assert final["final_overall"] == 9.0, "even subgrades: cap does not bite, final equals weighted 9.0"


# ---------------------------------------------------------------------------
# Subgrade range constraint
# ---------------------------------------------------------------------------
def test_subgrade_above_max_grade_rejected(api):
    """PRD §3.4: "Each subgrade must lie within the inclusive range from 0 to the
    standard's `max_grade`; a subgrade below 0 or above `max_grade` is rejected
    with `ERR_SUBGRADE_OUT_OF_RANGE`."

    Design: Corner/calculations/subgrade_out_of_range_rejected
    """
    customer, sl, gs, sub, item = setup_item_intake_logged(email="e12@x.com")
    resp = api.create_grade_assessment(
        item["id"],
        create_grade_assessment_payload(gs["id"], centering=11, corners=9, edges=9, surface=9),
        GRADER,
    )
    validate_error(resp, ApiErrorId.ERR_SUBGRADE_OUT_OF_RANGE.value)


def test_subgrade_at_max_grade_accepted(api):
    """PRD §3.4: "Each subgrade must lie within the inclusive range from 0 to the
    standard's `max_grade`; a subgrade below 0 or above `max_grade` is rejected
    with `ERR_SUBGRADE_OUT_OF_RANGE`."

    Design: Corner/calculations/subgrade_out_of_range_rejected
    """
    # max_grade is 10; a subgrade of exactly 10 is inclusive and must be accepted.
    customer, sl, gs, sub, item = setup_item_intake_logged(email="e12b@x.com")
    resp = api.create_grade_assessment(
        item["id"],
        create_grade_assessment_payload(gs["id"], centering=10, corners=10, edges=10, surface=10),
        GRADER,
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Authentication requires a finalized assessment
# ---------------------------------------------------------------------------
def test_authenticate_before_finalize_rejected_invalid_state(api):
    """PRD §3.5: "Authentication is permitted only on an item in `GRADING` status
    that has an unsuperseded grade assessment whose `final_overall` is non-null."
    PRD §3.4: "An item must have an unsuperseded grade assessment whose
    `final_overall` has been computed before it can proceed to authentication."

    Design: Difficulty/cross_entity_state_dependency/authentication_requires_finalized_assessment_on_item
    """
    # Item GRADING with an UN-finalized assessment (final_overall still null).
    customer, sl, gs, sub, item, ga = setup_item_graded(subgrades=(9, 9, 9, 9), finalized=False, email="c14@x.com")
    resp = api.authenticate_item(item["id"], create_authentication_payload(verdict="GENUINE"), AUTH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_authenticate_after_finalize_succeeds(api):
    """PRD §3.5: "Once an item's active assessment has been finalized, an
    `Authenticator` runs an **authentication check** on it."
    PRD §3.5: "Running the check advances the item `GRADING → AUTHENTICATED`."

    Design: Difficulty/cross_entity_state_dependency/authentication_requires_finalized_assessment_on_item
    """
    customer, sl, gs, sub, item, ga = setup_item_graded(subgrades=(9, 9, 9, 9), finalized=True, email="c14b@x.com")
    resp = api.authenticate_item(item["id"], create_authentication_payload(verdict="GENUINE"), AUTH)
    validate_success(resp, expected_status=201)
    after = validate_success(api.get_item(item["id"], make_customer_headers(customer["id"])))
    assert after["status"] == "AUTHENTICATED"


# ---------------------------------------------------------------------------
# Alteration-note guard
# ---------------------------------------------------------------------------
def test_altered_verdict_without_note_rejected(api):
    """PRD §3.5: "When the verdict is `ALTERED` or `COUNTERFEIT`, the
    `alteration_note` is required and must be non-empty; a verdict of `ALTERED` or
    `COUNTERFEIT` submitted without an alteration note is rejected with
    `ERR_ALTERATION_NOTE_REQUIRED`."

    Design: Corner/validations/alteration_note_required_for_altered_verdict
    """
    customer, sl, gs, sub, item, ga = setup_item_graded(subgrades=(9, 9, 9, 9), finalized=True, email="e15@x.com")
    resp = api.authenticate_item(item["id"], create_authentication_payload(verdict="ALTERED"), AUTH)
    validate_error(resp, ApiErrorId.ERR_ALTERATION_NOTE_REQUIRED.value)
