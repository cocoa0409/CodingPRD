"""Health-compliance dimension and kindergarten transition gating
(PRD §3.7, §3.8).

Depth coverage for the independent status/health dimensions and the transition
completion gate on enrollment health; breadth coverage for the insufficient-visits
prerequisite and home-visit re-completion.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_active_enrollment,
    add_immunization_screening, update_screening,
    add_completed_home_visit, add_transition_plan,
    create_home_visit_payload,
)

ES = TEST_USERS["enrollment_specialist_headers"]
PA = TEST_USERS["program_admin_headers"]
FSW = TEST_USERS["family_services_worker_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / enrollment_status_and_health_dimensions_independent
# ---------------------------------------------------------------------------
def test_overdue_immunization_sets_health_non_compliant_status_unchanged(api):
    """PRD §3.7: "Every enrollment carries a health-compliance dimension,
    `health_compliance_status`, that evolves independently of its lifecycle `status`."
    PRD §3.7: "it becomes `NON_COMPLIANT` when any `IMMUNIZATION` screening is `OVERDUE`
    (whether the enrollment was previously `PENDING` or `COMPLIANT`)".

    Design: Difficulty/non_linear_state_machine/enrollment_status_and_health_dimensions_independent
    """
    b = setup_active_enrollment()
    hs = add_immunization_screening(b["enrollment"]["id"])
    update_screening(hs["id"], "OVERDUE")
    data = validate_success(api.get_enrollment(b["enrollment"]["id"], ES))
    assert data["status"] == "ACTIVE"
    assert data["health_compliance_status"] == "NON_COMPLIANT"


def test_resolved_immunization_returns_health_compliant_status_unchanged(api):
    """PRD §3.7: "it returns from `NON_COMPLIANT` to `COMPLIANT` when no `IMMUNIZATION`
    screening remains `OVERDUE` and all screenings are `UP_TO_DATE` or `EXEMPT`".

    Design: Difficulty/non_linear_state_machine/enrollment_status_and_health_dimensions_independent
    """
    b = setup_active_enrollment()
    hs = add_immunization_screening(b["enrollment"]["id"])
    update_screening(hs["id"], "OVERDUE")
    update_screening(hs["id"], "UP_TO_DATE", completed_date="2026-03-16")
    data = validate_success(api.get_enrollment(b["enrollment"]["id"], ES))
    assert data["status"] == "ACTIVE"
    assert data["health_compliance_status"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / transition_complete_gated_by_enrollment_compliant
# ---------------------------------------------------------------------------
def test_transition_complete_blocked_when_health_pending(api):
    """PRD §3.8: "Completing a transition plan is a `ProgramAdmin` action that requires
    the plan to be in `DRAFT` (otherwise `ERR_INVALID_STATE`) and further requires the
    linked enrollment to be `ACTIVE` with `health_compliance_status` `COMPLIANT` and to
    have at least two `COMPLETED` home visits; if the health status is not `COMPLIANT` or
    fewer than two completed home visits exist, completion is rejected with
    `ERR_TRANSITION_PREREQ_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/transition_complete_gated_by_enrollment_compliant
    """
    b = setup_active_enrollment()
    enr_id = b["enrollment"]["id"]
    add_completed_home_visit(enr_id, "2026-04-01")
    add_completed_home_visit(enr_id, "2026-04-08")
    tp = add_transition_plan(enr_id)
    resp = api.complete_transition_plan(tp["id"], PA)
    validate_error(resp, ApiErrorId.ERR_TRANSITION_PREREQ_NOT_MET)


def test_transition_complete_succeeds_when_compliant_and_two_visits(api):
    """PRD §3.8: "On successful completion the plan advances from `DRAFT` to `COMPLETED`
    and drives the enrollment from `ACTIVE` to the terminal `COMPLETED_TRANSITION`, which
    lowers the cohort's `filled_slots` (recomputed) and increments `AgeCohort.version` by
    one."

    Design: Difficulty/cross_entity_state_dependency/transition_complete_gated_by_enrollment_compliant
    """
    b = setup_active_enrollment()
    enr_id = b["enrollment"]["id"]
    hs = add_immunization_screening(enr_id)
    update_screening(hs["id"], "UP_TO_DATE", completed_date="2026-03-16")  # health COMPLIANT
    add_completed_home_visit(enr_id, "2026-04-01")
    add_completed_home_visit(enr_id, "2026-04-08")
    tp = add_transition_plan(enr_id)
    plan = validate_success(api.complete_transition_plan(tp["id"], PA))
    assert plan["status"] == "COMPLETED"
    enr = validate_success(api.get_enrollment(enr_id, ES))
    assert enr["status"] == "COMPLETED_TRANSITION"


# ---------------------------------------------------------------------------
# Corner: validations / transition_prereq_insufficient_visits_returns_error
# ---------------------------------------------------------------------------
def test_transition_complete_blocked_with_one_completed_visit(api):
    """PRD §3.8: "further requires the linked enrollment to be `ACTIVE` with
    `health_compliance_status` `COMPLIANT` and to have at least two `COMPLETED` home
    visits; if the health status is not `COMPLIANT` or fewer than two completed home
    visits exist, completion is rejected with `ERR_TRANSITION_PREREQ_NOT_MET`."

    Design: Corner/validations/transition_prereq_insufficient_visits_returns_error
    """
    b = setup_active_enrollment()
    enr_id = b["enrollment"]["id"]
    hs = add_immunization_screening(enr_id)
    update_screening(hs["id"], "UP_TO_DATE", completed_date="2026-03-10")  # health COMPLIANT
    add_completed_home_visit(enr_id, "2026-04-01")  # only ONE completed visit
    tp = add_transition_plan(enr_id)
    resp = api.complete_transition_plan(tp["id"], PA)
    validate_error(resp, ApiErrorId.ERR_TRANSITION_PREREQ_NOT_MET)


# ---------------------------------------------------------------------------
# Corner: state_machines / home_visit_complete_twice_returns_invalid_state
# ---------------------------------------------------------------------------
def test_complete_already_completed_home_visit_returns_invalid_state(api):
    """PRD §3.8: "Marking a home visit completed, another `FamilyServicesWorker` action,
    advances it from `SCHEDULED` to `COMPLETED` and requires the visit to be `SCHEDULED`;
    against a non-`SCHEDULED` visit it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/home_visit_complete_twice_returns_invalid_state
    """
    b = setup_active_enrollment()
    hv = validate_success(
        api.create_home_visit(
            create_home_visit_payload(b["enrollment"]["id"], "2026-04-01", "13:00", "14:00"),
            FSW),
        expected_status=201)
    validate_success(api.complete_home_visit(hv["id"], FSW))
    resp = api.complete_home_visit(hv["id"], FSW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
