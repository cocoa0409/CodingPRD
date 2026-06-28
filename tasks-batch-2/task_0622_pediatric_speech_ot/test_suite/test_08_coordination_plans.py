"""External-program coordination: early-intervention (IFSP) and school (IEP)
coordination plans, plus home programs and parent training.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_coordination_plan_payload, create_home_program_payload, TEST_USERS,
    make_therapist_headers, set_clock, create_child, get_child,
    setup_active_care,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_ifsp_activation_age_ineligible_rejected(api):
    """PRD §3.7: "for an `IFSP` plan only — only when the child's
    `age_months_at_intake` is below 36 months (otherwise
    `ERR_IFSP_AGE_INELIGIBLE`)."

    Design: Corner/state_machines/ifsp_age_ineligible_blocks_activation
    """
    set_clock("2026-06-01T00:00:00Z")
    # DOB 2022-01-01 under a 2026-06-01 clock -> 53 months (>= 36).
    child = create_child(full_name="Older Kid", date_of_birth="2022-01-01")
    cp = get_success_data(api.create_coordination_plan(
        create_coordination_plan_payload(child["id"], plan_type="IFSP",
                                          jurisdiction="Lead Agency",
                                          review_due_time="2026-12-01T00:00:00Z"), ADMIN))
    res = api.activate_coordination_plan(cp["id"], ADMIN)
    validate_error(res, "ERR_IFSP_AGE_INELIGIBLE")


def test_second_active_coordination_plan_conflicts(api):
    """PRD §3.7: "but only when the child has no other coordination plan already
    in `ACTIVE` or `TRANSITIONING` status (otherwise `ERR_COORDINATION_CONFLICT`)".
    PRD §3.7: "Activation sets the child's `coordination_program` to
    `EARLY_INTERVENTION` for an `IFSP` plan or `SCHOOL` for an `IEP` plan."

    Design: Corner/state_machines/coordination_conflict_second_active_plan_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    child = create_child(full_name="Coord Kid", date_of_birth="2024-06-01")  # 24 months
    cp1 = get_success_data(api.create_coordination_plan(
        create_coordination_plan_payload(child["id"], plan_type="IFSP",
                                          jurisdiction="Lead Agency",
                                          review_due_time="2026-12-01T00:00:00Z"), ADMIN))
    validate_success(api.activate_coordination_plan(cp1["id"], ADMIN), 200)
    cp2 = get_success_data(api.create_coordination_plan(
        create_coordination_plan_payload(child["id"], plan_type="IEP",
                                          jurisdiction="District 7",
                                          review_due_time="2027-06-01T00:00:00Z"), ADMIN))
    res = api.activate_coordination_plan(cp2["id"], ADMIN)
    validate_error(res, "ERR_COORDINATION_CONFLICT")
    assert get_child(child["id"])["coordination_program"] == "EARLY_INTERVENTION"


def test_begin_transition_on_iep_not_applicable(api):
    """PRD §3.7: "A `ClinicAdmin` may begin the early-intervention-to-school
    transition on a coordination plan that is `ACTIVE` (otherwise
    `ERR_COORDINATION_NOT_ACTIVE`) and whose `plan_type` is `IFSP`, since only
    early-intervention plans transition to school (otherwise
    `ERR_TRANSITION_NOT_APPLICABLE`)".

    Design: Corner/state_machines/begin_transition_on_iep_not_applicable
    """
    set_clock("2026-06-01T00:00:00Z")
    child = create_child(full_name="IEP Kid", date_of_birth="2024-06-01")
    cp = get_success_data(api.create_coordination_plan(
        create_coordination_plan_payload(child["id"], plan_type="IEP",
                                          jurisdiction="District 7",
                                          review_due_time="2027-06-01T00:00:00Z"), ADMIN))
    validate_success(api.activate_coordination_plan(cp["id"], ADMIN), 200)
    res = api.begin_transition_coordination_plan(cp["id"], ADMIN)
    validate_error(res, "ERR_TRANSITION_NOT_APPLICABLE")


def test_home_program_activation_requires_parent_training(api):
    """PRD §3.9: "A `Therapist` activates an `ASSIGNED` home program (otherwise
    `ERR_HOME_PROGRAM_NOT_ASSIGNED`), but only when `parent_training_completed` is
    true — the parent must finish training before activation (otherwise
    `ERR_PARENT_TRAINING_INCOMPLETE`)".

    Design: Corner/state_machines/home_program_activate_requires_parent_training
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="OT")
    th_headers = make_therapist_headers(ctx["therapist"]["id"])
    hp = get_success_data(api.create_home_program(
        ctx["plan"]["id"],
        create_home_program_payload(title="Daily oral-motor drills", weekly_target_sessions=5),
        th_headers))
    assert hp["status"] == "ASSIGNED"
    assert hp["parent_training_completed"] is False
    res = api.activate_home_program(hp["id"], th_headers)
    validate_error(res, "ERR_PARENT_TRAINING_INCOMPLETE")
