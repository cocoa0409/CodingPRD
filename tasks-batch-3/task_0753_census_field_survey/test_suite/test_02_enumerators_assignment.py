"""Enumerator lifecycle, case assignment, supersede, OCC, and the
Case -> Enumerator activation dependency.

Translates queue-A cross_entity_state_dependency (assignment leg) and queue-B
instances from state_machines, entities, cross_cutting, and consistency_model.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_assignment_payload,
    assert_enumerator,
    assert_case_assignment,
    create_open_project,
    create_open_area,
    create_active_enumerator,
    create_hired_enumerator,
    create_applicant_enumerator,
    add_case,
    assign_case,
    setup_assigned_case,
)

ADMIN = TEST_USERS["survey_admin_headers"]
SUPERVISOR = TEST_USERS["field_supervisor_headers"]


def test_assignment_blocked_by_hired_enumerator_not_active(api):
    """PRD §3.4: "Assignment is permitted only when the parent area is `IN_FIELD`
    (otherwise `ERR_AREA_NOT_IN_FIELD`) and the target enumerator is `ACTIVE`
    (otherwise `ERR_ENUMERATOR_NOT_ACTIVE`), and only when `expected_case_version`
    matches the case's current `version` (otherwise `ERR_STALE_CASE_VERSION`)."

    Design: Difficulty/cross_entity_state_dependency/assignment_blocked_by_enumerator_not_active
    """
    proj = create_open_project()
    area = create_open_area(proj["id"])
    en = create_hired_enumerator(proj["id"])  # HIRED, not yet ACTIVE
    case = add_case(area["id"])
    res = api.create_assignment(
        case["id"], create_assignment_payload(en["id"], case["version"]), SUPERVISOR)
    validate_error(res, "ERR_ENUMERATOR_NOT_ACTIVE", expected_status=409)


def test_assignment_blocked_by_applicant_enumerator_not_active(api):
    """PRD §3.4: "the target enumerator is `ACTIVE` (otherwise
    `ERR_ENUMERATOR_NOT_ACTIVE`)".

    An APPLICANT enumerator (an earlier non-ACTIVE source state) is likewise an
    illegal assignment target, surfacing the same Case -> Enumerator gate.

    Design: Difficulty/cross_entity_state_dependency/assignment_blocked_by_enumerator_not_active
    """
    proj = create_open_project()
    area = create_open_area(proj["id"])
    en = create_applicant_enumerator(proj["id"])  # APPLICANT, never hired
    case = add_case(area["id"])
    res = api.create_assignment(
        case["id"], create_assignment_payload(en["id"], case["version"]), SUPERVISOR)
    validate_error(res, "ERR_ENUMERATOR_NOT_ACTIVE", expected_status=409)


def test_assign_nonexistent_enumerator_returns_not_found(api):
    """PRD §2.6: "an `enumerator_id` on an assignment, a `reviewer_enumerator_id`
    on a reinterview, and an `enumerator_id` on a pay line that reference no
    enumerator all fail with `ERR_ENUMERATOR_NOT_FOUND`."

    Design: Corner/entities/assign_nonexistent_enumerator_returns_not_found
    """
    proj = create_open_project()
    area = create_open_area(proj["id"])
    case = add_case(area["id"])
    res = api.create_assignment(
        case["id"], create_assignment_payload(NON_EXISTENT_UUID, case["version"]), SUPERVISOR)
    validate_error(res, "ERR_ENUMERATOR_NOT_FOUND", expected_status=404)


def test_assignment_effect_visible_immediately(api):
    """PRD §3.4: "The first assignment on an `UNASSIGNED` case moves it to
    `ASSIGNED`, creates the `ACTIVE` assignment, sets the case's
    `assigned_enumerator_id` to the enumerator, and increments the case's
    `version` by one".

    Design: Corner/consistency_model/assignment_effect_visible_immediately
    """
    ctx = setup_assigned_case()
    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "ASSIGNED"
    assert case["assigned_enumerator_id"] == ctx["enumerator"]["id"]


def test_reassign_supersede_bumps_case_version(api):
    """PRD §3.4: "A subsequent assignment on a case already in `ASSIGNED` is a
    reassignment: the prior `ACTIVE` assignment is moved to `SUPERSEDED`, a new
    `ACTIVE` assignment is created, the case's `assigned_enumerator_id` is updated
    to the new enumerator, the case stays in `ASSIGNED`, and its `version` again
    increments by one."

    Design: Corner/cross_cutting/reassign_supersede_bumps_case_version
    """
    proj = create_open_project()
    area = create_open_area(proj["id"])
    en1 = create_active_enumerator(proj["id"], full_name="E1")
    en2 = create_active_enumerator(proj["id"], full_name="E2")
    case = add_case(area["id"])
    asg1 = assign_case(case["id"], en1["id"], case["version"])
    case_v2 = validate_success(api.get_case(case["id"], ADMIN), 200)["version"]

    res = api.create_assignment(
        case["id"], create_assignment_payload(en2["id"], case_v2), SUPERVISOR)
    validate_success(res, 201)

    assignments, _ = validate_paginated(api.list_assignments(case["id"], ADMIN))
    superseded = next(a for a in assignments if a["id"] == asg1["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert_case_assignment(superseded)

    case_after = validate_success(api.get_case(case["id"], ADMIN), 200)
    assert case_after["assigned_enumerator_id"] == en2["id"]
    # PRD §2.4/§3.4: version increments by one per mutation; here one reassignment
    # advances it from the re-observed case_v2.
    assert case_after["version"] == case_v2 + 1


def test_reassign_stale_case_version_returns_412(api):
    """PRD §2.7: "If that value does not equal the case's current `version` —
    because another writer has advanced it since the client last read the case,
    for instance through an earlier assignment or a logged attempt — the request
    is rejected with `ERR_STALE_CASE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting/reassign_stale_case_version_returns_412
    """
    proj = create_open_project()
    area = create_open_area(proj["id"])
    en1 = create_active_enumerator(proj["id"], full_name="E1")
    en2 = create_active_enumerator(proj["id"], full_name="E2")
    case = add_case(area["id"])
    stale_version = case["version"]
    assign_case(case["id"], en1["id"], stale_version)  # advances Case.version

    res = api.create_assignment(
        case["id"], create_assignment_payload(en2["id"], stale_version), SUPERVISOR)
    validate_error(res, "ERR_STALE_CASE_VERSION", expected_status=412)


def test_suspend_enumerator_releases_assignment(api):
    """PRD §3.3: "Every `ACTIVE` case assignment held by that enumerator is moved
    to `RELEASED`, and each affected case has its `assigned_enumerator_id` cleared
    to null."

    Design: Corner/state_machines/suspend_enumerator_releases_assignment
    """
    ctx = setup_assigned_case()
    res = api.suspend_enumerator(ctx["enumerator"]["id"], ADMIN)
    en_after = validate_success(res, 200)
    assert en_after["status"] == "SUSPENDED"
    assert_enumerator(en_after)

    case_after = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case_after["assigned_enumerator_id"] is None

    assignments, _ = validate_paginated(api.list_assignments(ctx["case"]["id"], ADMIN))
    released = next(a for a in assignments if a["id"] == ctx["assignment"]["id"])
    assert released["status"] == "RELEASED"
