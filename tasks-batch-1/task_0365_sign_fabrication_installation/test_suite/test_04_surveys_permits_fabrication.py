"""Site-survey safety gates, permit prerequisites, and work-order release gating.

Covers cross_entity_state_dependency (survey-passed gate), the survey/permit
validation corners, and the state-vs-safety priority pair.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_project, create_permitting_project, create_passed_survey,
    create_site_survey_payload, create_permit_payload, create_sign_project_payload,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
SURV = TEST_USERS["surveyor_headers"]
PC = TEST_USERS["permit_clerk_headers"]


# ═══ Queue A: cross_entity_state_dependency / work_order_release_requires_survey

def test_work_order_release_requires_passed_survey(api):
    """PRD §3.4: "Release is gated twice: a site survey in PASSED status must
    exist for the project, failing which the release is rejected with
    ERR_SURVEY_NOT_PASSED."

    Design: Difficulty/cross_entity_state_dependency/work_order_release_requires_survey_passed
    """
    project, proof, estimate = create_permitting_project(
        customer_name="Dep Co", site_address="12 Gate St")
    # Create a survey but leave it PENDING (undecided).
    get_success_data(api.create_site_survey(
        project["id"], create_site_survey_payload(
            measured_clearance_ft=30, overhead_obstruction=False,
            ground_bearing_ok=True), SURV))
    res = api.create_work_order(project["id"], SM)
    validate_error(res, "ERR_SURVEY_NOT_PASSED")


def test_work_order_release_succeeds_after_survey_passed(api):
    """PRD §3.4: "A ShopManager releases fabrication when the gates are satisfied,
    which drives the project from PERMITTING to FABRICATION and creates a
    fabrication work order in RELEASED."

    Design: Difficulty/cross_entity_state_dependency/work_order_release_requires_survey_passed
    """
    project, proof, estimate = create_permitting_project(
        customer_name="Dep2 Co", site_address="12 Gate St")
    create_passed_survey(project["id"])
    wo = validate_success(api.create_work_order(project["id"], SM), 201)
    assert wo["status"] == "RELEASED"
    project_after = validate_success(api.get_sign_project(project["id"], SM), 200)
    assert project_after["phase"] == "FABRICATION"


# ═══ Queue A: priority_pair_validation_conflict / state_before_safety_on_survey ═

def test_pass_already_failed_survey_returns_invalid_state_over_clearance(api):
    """PRD §3.9: "Then, for transition endpoints, the target resource must
    actually be in a state from which the transition is defined, yielding
    ERR_INVALID_STATE when it is not. Only after these structural checks do the
    business rules run: referential eligibility (ERR_REFERENCE_NOT_ELIGIBLE), the
    survey safety gates."

    Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_survey_decide
    """
    project = create_project(
        customer_name="Prio Co", site_address="8 Order Ave", placement_height_ft=20)
    survey = get_success_data(api.create_site_survey(
        project["id"], create_site_survey_payload(
            measured_clearance_ft=5, overhead_obstruction=False,
            ground_bearing_ok=True), SURV))
    # Decide FAIL first so the survey is terminal; the clearance (5 < 20) is also bad.
    api.decide_site_survey(project["id"], survey["id"], {"result": "FAIL"}, SURV)
    res = api.decide_site_survey(project["id"], survey["id"], {"result": "PASS"}, SURV)
    validate_error(res, "ERR_INVALID_STATE")


def test_pass_decision_blocked_on_terminal_survey(api):
    """PRD §3.3: "A pass drives the survey PENDING → PASSED." Combined with
    PRD §3.9: the state check yields ERR_INVALID_STATE for a transition not
    defined from the current (terminal FAILED) state.

    Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_survey_decide
    """
    project = create_project(
        customer_name="Prio2 Co", site_address="8 Order Ave", placement_height_ft=20)
    survey = get_success_data(api.create_site_survey(
        project["id"], create_site_survey_payload(
            measured_clearance_ft=5, overhead_obstruction=False,
            ground_bearing_ok=True), SURV))
    api.decide_site_survey(project["id"], survey["id"], {"result": "FAIL"}, SURV)
    # A second FAIL is equally undefined from FAILED -> still ERR_INVALID_STATE.
    res = api.decide_site_survey(project["id"], survey["id"], {"result": "PASS"}, SURV)
    validate_error(res, "ERR_INVALID_STATE")


# ═══ Queue B: corner validations ═════════════════════════════════════════════

def test_survey_pass_clearance_insufficient_rejected(api):
    """PRD §3.3: "the measured clearance must be at least the project's
    placement_height_ft, failing which the pass is rejected with
    ERR_CLEARANCE_INSUFFICIENT."

    Design: Corner/validations/survey_pass_clearance_insufficient_rejected
    """
    project = create_project(
        customer_name="Clr Co", site_address="19 Low St", placement_height_ft=10)
    survey = get_success_data(api.create_site_survey(
        project["id"], create_site_survey_payload(
            measured_clearance_ft=4, overhead_obstruction=False,
            ground_bearing_ok=True), SURV))
    res = api.decide_site_survey(project["id"], survey["id"], {"result": "PASS"}, SURV)
    validate_error(res, "ERR_CLEARANCE_INSUFFICIENT")


def test_survey_pass_monument_without_ground_bearing_rejected(api):
    """PRD §3.3: "if the project's sign_type is MONUMENT or PYLON, ground bearing
    must be confirmed, failing which the pass is rejected with
    ERR_GROUND_BEARING_FAILED."

    Design: Corner/validations/survey_pass_monument_without_ground_bearing_rejected
    """
    project = create_project(
        customer_name="Mon Co", site_address="20 Base St",
        sign_type="MONUMENT", placement_height_ft=4)
    survey = get_success_data(api.create_site_survey(
        project["id"], create_site_survey_payload(
            measured_clearance_ft=30, overhead_obstruction=False,
            ground_bearing_ok=False), SURV))
    res = api.decide_site_survey(project["id"], survey["id"], {"result": "PASS"}, SURV)
    validate_error(res, "ERR_GROUND_BEARING_FAILED")


def test_work_order_release_permit_not_approved_rejected(api):
    """PRD §3.4: "if the project requires permits, every required permit kind must
    be APPROVED and not EXPIRED, failing which the release is rejected with
    ERR_PERMIT_NOT_APPROVED."

    Design: Corner/validations/work_order_release_permit_not_approved_rejected
    """
    project, proof, estimate = create_permitting_project(
        customer_name="Perm Co", site_address="21 Gate St",
        jurisdiction_code="CITY_A")
    create_passed_survey(project["id"])
    permit = get_success_data(api.create_permit(
        project["id"], create_permit_payload(permit_kind="STRUCTURAL"), PC))
    api.submit_permit(project["id"], permit["id"], PC)  # only SUBMITTED, not APPROVED
    res = api.create_work_order(project["id"], SM)
    validate_error(res, "ERR_PERMIT_NOT_APPROVED")


def test_submit_permit_not_required_rejected(api):
    """PRD §3.3: "submitting a permit when permit_required is false is rejected
    with ERR_PERMIT_NOT_REQUIRED."

    Design: Corner/validations/submit_permit_not_required_rejected
    """
    project = validate_success(api.create_sign_project(create_sign_project_payload(
        customer_name="NoPerm Co", site_address="25 Free St",
        jurisdiction_code="COUNTY_C", sign_type="WALL",
        face_width_in=36, face_height_in=24, placement_height_ft=6), SM), 201)
    permit = get_success_data(api.create_permit(
        project["id"], create_permit_payload(permit_kind="STRUCTURAL"), PC))
    res = api.submit_permit(project["id"], permit["id"], PC)
    validate_error(res, "ERR_PERMIT_NOT_REQUIRED")
