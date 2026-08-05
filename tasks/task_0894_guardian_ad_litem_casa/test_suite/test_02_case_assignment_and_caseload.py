"""Case intake, volunteer appointment, caseload conservation, and optimistic
concurrency on the case version.

Queue A (Difficulty): cross_entity_state_dependency (assign target must be
ACTIVE) and compensating_invariant (active_case_count conserved).
Queue B (Corner): case creation validation, caseload cap, OCC, immediacy.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NIL_UUID,
    set_clock,
    create_supervisor,
    create_case,
    register_volunteer,
    onboard_active_volunteer,
    make_supervisor_headers,
    setup_active_volunteer_assigned_case,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ------------------------- Difficulty: assign requires target volunteer ACTIVE
def test_assign_screening_volunteer_rejected_not_active(api):
    """PRD 3.3: "the target volunteer's `status` is `ACTIVE`, else
    `ERR_VOLUNTEER_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/assign_requires_target_volunteer_active
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    sup = create_supervisor(api)
    vol = register_volunteer(api)
    get_success_data(api.start_screening(vol["id"], ADMIN))  # now SCREENING, not ACTIVE
    case = create_case(api, sup["id"])
    resp = api.create_assignment(
        case["id"],
        {"volunteer_id": vol["id"], "expected_case_version": case["version"]},
        make_supervisor_headers(sup["id"]))
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE.value)


def test_assign_screening_volunteer_leaves_case_intake(api):
    """PRD 3.3: "the target volunteer's `status` is `ACTIVE`, else
    `ERR_VOLUNTEER_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/assign_requires_target_volunteer_active
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    sup = create_supervisor(api)
    vol = register_volunteer(api)
    get_success_data(api.start_screening(vol["id"], ADMIN))
    case = create_case(api, sup["id"])
    sup_headers = make_supervisor_headers(sup["id"])
    api.create_assignment(
        case["id"],
        {"volunteer_id": vol["id"], "expected_case_version": case["version"]},
        sup_headers)
    after = get_success_data(api.get_case(case["id"], sup_headers))
    assert after["status"] == "INTAKE", "rejected appointment must leave case in INTAKE"


# -------------------------- Difficulty: active_case_count conserved round trip
def test_active_case_count_increments_on_assign(api):
    """PRD 2.7: "It starts at 0, never falls below 0, increases by one when an
    appointment is created, and decreases by one whenever one of that volunteer's
    active assignments ends (by manual end, supersession, case close, or the
    deactivation cascade)."

    Design: Difficulty/compensating_invariant/caseload_count_conserved_by_assign_then_end
    """
    base = setup_active_volunteer_assigned_case(api)
    vol = get_success_data(api.get_volunteer(base["volunteer_id"], ADMIN))
    assert vol["active_case_count"] == 1, "count must be 1 after a single assignment"


def test_active_case_count_restored_after_end(api):
    """PRD 2.7: "An appointment followed by its compensating end returns the
    counter to its starting value."

    Design: Difficulty/compensating_invariant/caseload_count_conserved_by_assign_then_end
    """
    base = setup_active_volunteer_assigned_case(api)
    get_success_data(api.end_assignment(
        base["case_id"], base["assignment_id"], {"reason": "manual"}, base["supervisor_headers"]))
    vol = get_success_data(api.get_volunteer(base["volunteer_id"], ADMIN))
    assert vol["active_case_count"] == 0, "count must return to 0 after the assignment ends"


# ----------------------------------------------------- Corner: case validation
def test_create_case_missing_supervisor_id_rejected(api):
    """PRD 2.10: "Field validity and concurrency — required fields present, enums
    valid, ordering and sign constraints satisfied, and expected_case_version
    matching, else ERR_VALIDATION (400) or ERR_STALE_CASE_VERSION (412)."

    Design: Corner/entities/create_case_missing_required_field_returns_400
    """
    resp = api.create_case(
        {"child_initials": "J.D.", "child_dob": "2018-04-01", "jurisdiction": "CA-ALAMEDA"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_case_unknown_supervisor_rejected(api):
    """PRD 2.9: "the system validates identifiers left to right and rejects on the
    first identifier that does not resolve, using the not-found error for that
    resource: ERR_VOLUNTEER_NOT_FOUND, ERR_SUPERVISOR_NOT_FOUND, ..."

    Design: Corner/entities/create_case_unknown_supervisor_returns_404
    """
    resp = api.create_case(
        {"child_initials": "J.D.", "child_dob": "2018-04-01",
         "jurisdiction": "CA-ALAMEDA", "supervisor_id": NIL_UUID}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SUPERVISOR_NOT_FOUND.value)


def test_assign_over_caseload_cap_rejected(api):
    """PRD 3.3: "the target volunteer's `active_case_count` is strictly below their
    `max_caseload`, else `ERR_CASELOAD_EXCEEDED`".

    Design: Corner/validations/assign_caseload_exceeded_returns_409
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    sup = create_supervisor(api)
    vol = onboard_active_volunteer(api, max_caseload=1)
    sup_headers = make_supervisor_headers(sup["id"])
    c1 = create_case(api, sup["id"], child_initials="A.A.")
    get_success_data(api.create_assignment(
        c1["id"], {"volunteer_id": vol["id"], "expected_case_version": c1["version"]}, sup_headers))
    c2 = create_case(api, sup["id"], child_initials="B.B.")
    resp = api.create_assignment(
        c2["id"], {"volunteer_id": vol["id"], "expected_case_version": c2["version"]}, sup_headers)
    validate_error(resp, ApiErrorId.ERR_CASELOAD_EXCEEDED.value)


# NOTE: Deleted test_stale_case_version_on_second_assignment_rejected and
# test_fresh_case_version_supersedes_prior_assignment — non-uniquely-derivable
# (PRD self-contradiction). PRD 3.3 states appointment's FIRST global-order gate is
# "the case is in INTAKE or UNASSIGNED, else ERR_INVALID_STATE", but a prior ACTIVE
# assignment only exists on an ASSIGNED case; the SUPERSEDED path (and the OCC
# stale-version check reached only after that gate) is thus unreachable for a
# second assignment. Both tests appoint twice on the same case, so a PRD-faithful
# impl correctly returns ERR_INVALID_STATE. The scaffold Case state machine carries
# the same contradiction (precond Case.status in {INTAKE,UNASSIGNED} + side-effect
# "prior ACTIVE assignment -> ENDED SUPERSEDED").


# ---------------------------------------------- Corner: immediate consistency
def test_assignment_visible_immediately_same_session(api):
    """PRD 3.3: "The case's owning `Supervisor` appoints a volunteer, advancing the
    case `INTAKE → ASSIGNED` (or `UNASSIGNED → ASSIGNED`)."

    Design: Corner/consistency_model/immediate_assignment_visible_same_session
    """
    base = setup_active_volunteer_assigned_case(api)
    fetched = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert fetched["status"] == "ASSIGNED"
