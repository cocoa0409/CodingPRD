"""Intake (duplicate-intake guard) and the compound submission posture that is
derived from child item states.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_intake_payload,
    make_customer_headers, TEST_USERS,
    setup_item_intake_logged, setup_item_graded,
    grade_item,
)


RECEIVER = TEST_USERS["receiver_headers"]


# ---------------------------------------------------------------------------
# Duplicate intake guard
# ---------------------------------------------------------------------------
def test_duplicate_intake_on_item_rejected(api):
    """PRD §3.3: "Logging intake is permitted only while the parent submission is
    in either `SUBMITTED` or `RECEIVING` status, and only when no intake record
    already exists for that item; a second intake attempt on the same item is
    rejected with `ERR_DUPLICATE_INTAKE`."

    Design: Difficulty/resource_temporal_overlap/duplicate_intake_blocks_second_intake_on_item
    """
    customer, sl, gs, sub, item = setup_item_intake_logged(email="c16@x.com", title="Card N")
    resp = api.log_intake(item["id"], create_intake_payload(matches_declaration=True), RECEIVER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INTAKE.value)


def test_first_intake_succeeds_second_rejected(api):
    """PRD §3.3: "only when no intake record already exists for that item; a
    second intake attempt on the same item is rejected with
    `ERR_DUPLICATE_INTAKE`."

    Design: Difficulty/resource_temporal_overlap/duplicate_intake_blocks_second_intake_on_item
    """
    # setup_item_intake_logged already logged the first intake; verify the item
    # advanced, then prove the second intake is the one that fails.
    customer, sl, gs, sub, item = setup_item_intake_logged(email="c16b@x.com", title="Card N2")
    cust_headers = make_customer_headers(customer["id"])
    logged = validate_success(api.get_item(item["id"], cust_headers))
    assert logged["status"] == "INTAKE_LOGGED", "first intake must have advanced the item"
    resp = api.log_intake(item["id"], create_intake_payload(matches_declaration=True), RECEIVER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INTAKE.value)


# ---------------------------------------------------------------------------
# Compound posture derived from children
# ---------------------------------------------------------------------------
def test_submission_posture_becomes_in_grading_when_child_grades(api):
    """PRD §3.4: "Creating the first assessment on an item advances it
    `INTAKE_LOGGED → GRADING`, and when the first item of a submission enters
    `GRADING` the parent posture moves `RECEIVING → IN_GRADING`."

    Design: Difficulty/non_linear_state_machine/submission_compound_posture_derived_from_children
    """
    customer, sl, gs, sub, item = setup_item_intake_logged(email="c6@x.com", title="Card E")
    grade_item(item["id"], gs["id"], 9, 9, 9, 9)
    cust_headers = make_customer_headers(customer["id"])
    after = validate_success(api.get_submission(sub["id"], cust_headers))
    assert after["status"] == "IN_GRADING", "parent posture must auto-derive to IN_GRADING"


def test_submission_posture_is_receiving_after_first_intake(api):
    """PRD §3.3: "When the first item of a submission is logged, the parent
    posture moves `SUBMITTED → RECEIVING`; logging further items leaves the posture
    unchanged."

    Design: Difficulty/non_linear_state_machine/submission_compound_posture_derived_from_children
    """
    # After the sole item is intake-logged (but not yet graded) the posture is
    # RECEIVING — the precursor state from which grading derives IN_GRADING.
    customer, sl, gs, sub, item = setup_item_intake_logged(email="c6b@x.com", title="Card E2")
    cust_headers = make_customer_headers(customer["id"])
    after = validate_success(api.get_submission(sub["id"], cust_headers))
    assert after["status"] == "RECEIVING", "first intake must move posture SUBMITTED -> RECEIVING"
