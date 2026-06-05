"""Enrollment branch decision, the eligibility gauntlet, and validation-priority conflicts.

Covers corner-design validations (emergency contact, authorization completeness, duplicate,
rained-out, age-mismatch), corner state_machines (initial CONFIRMED branch), corner
calculations (age eligibility read), the difficulty cross_entity_state_dependency instance
(enroll requires session OPEN), and the difficulty priority_pair_validation_conflict
instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_program_payload,
    create_session_payload,
    create_authorization_form_payload,
    create_enrollment_payload,
    make_guardian_headers,
    # fixtures
    create_guardian,
    create_child,
    add_emergency_contact,
    add_approved_form,
    setup_eligible_child,
    setup_open_session_with_offering,
    get_offering,
    enroll_child,
)

DIRECTOR = TEST_USERS["program_director_headers"]


# ---------------------------------------------------------------------------
# Initial state: fresh enrollment lands CONFIRMED with a seat (corner)
# ---------------------------------------------------------------------------
def test_fresh_enrollment_with_seat_lands_confirmed(api):
    """PRD §3.4: "when a seat is available the enrollment lands CONFIRMED, and when the
    week is already full it lands WAITLISTED."
    PRD §3.4: "A provisional line tuition is computed and stored on
    provisional_tuition_cents". (AFTERSCHOOL base 15000, no scholarship, no surcharge.)

    Design: Corner/state_machines/new_enrollment_starts_in_confirmed_when_seat_available
    """
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    scene = setup_open_session_with_offering(
        program_overrides={"name": "Init Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 15000},
    )
    gh = make_guardian_headers(gid)
    resp = api.create_enrollment(
        create_enrollment_payload(eligible["child"]["id"], scene["offering"]["id"], scene["offering"]["version"]),
        gh,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "CONFIRMED", f"expected CONFIRMED, got {data['status']}"
    assert data["provisional_tuition_cents"] == 15000, (
        f"AFTERSCHOOL base 15000 with no scholarship expected 15000, got {data['provisional_tuition_cents']}"
    )


# ---------------------------------------------------------------------------
# Age eligibility computed read (corner calculation)
# ---------------------------------------------------------------------------
def test_age_eligibility_read_reflects_computed_age_below_min(api):
    """PRD §3.4: "Take the reference year minus the birth year; then, if the reference
    date's month-and-day falls before the child's birth month-and-day, subtract one year".
    A child born 2019-01-01 is age 7 as of 2026-06-01.

    Design: Corner/calculations/age_eligibility_below_group_min_flagged
    """
    guardian = create_guardian()
    gh = make_guardian_headers(guardian["id"])
    child = create_child(guardian["id"], first_name="Yng", birth_date="2019-01-01")
    program = api_client.create_program(
        create_program_payload(name="El Camp", program_type="CAMP", min_age=5, max_age=12), DIRECTOR
    ).json()["data"]
    session = api_client.create_session(
        create_session_payload(program["id"], title="El", age_group_min=8, age_group_max=10), DIRECTOR
    ).json()["data"]
    resp = api.get_child_age_eligibility(child["id"], gh, params={"session_id": session["id"]})
    data = validate_success(resp, 200)
    assert data["age_years"] == 7, f"expected computed age 7, got {data['age_years']}"


# ---------------------------------------------------------------------------
# Eligibility-gauntlet validations (corner)
# ---------------------------------------------------------------------------
def test_enroll_without_emergency_contact_rejected(api):
    """PRD §3.4: "The child must have at least one emergency contact on file, or
    ERR_NO_EMERGENCY_CONTACT."

    Design: Corner/validations/enroll_without_emergency_contact_rejected
    """
    guardian = create_guardian()
    gid = guardian["id"]
    child = create_child(gid, first_name="Ne")
    add_approved_form(gid, child["id"], "MEDICAL")
    add_approved_form(gid, child["id"], "PICKUP")
    # No emergency contact.
    scene = setup_open_session_with_offering(program_overrides={"name": "Ne Camp"})
    gh = make_guardian_headers(gid)
    resp = api.create_enrollment(
        create_enrollment_payload(child["id"], scene["offering"]["id"], scene["offering"]["version"]), gh
    )
    validate_error(resp, ApiErrorId.ERR_NO_EMERGENCY_CONTACT.value)


def test_enroll_with_only_medical_approved_rejected(api):
    """PRD §3.4: "The child must hold both an APPROVED authorization form of type MEDICAL
    and an APPROVED form of type PICKUP; lacking either yields ERR_AUTHORIZATION_INCOMPLETE."

    Design: Corner/validations/enroll_authorization_incomplete_only_medical_approved
    """
    guardian = create_guardian()
    gid = guardian["id"]
    gh = make_guardian_headers(gid)
    child = create_child(gid, first_name="Ai")
    add_emergency_contact(gid, child["id"])
    add_approved_form(gid, child["id"], "MEDICAL")
    # PICKUP submitted but NOT approved.
    api_client.create_authorization_form(
        create_authorization_form_payload(child["id"], "PICKUP"), gh
    )
    scene = setup_open_session_with_offering(program_overrides={"name": "Ai Camp"})
    resp = api.create_enrollment(
        create_enrollment_payload(child["id"], scene["offering"]["id"], scene["offering"]["version"]), gh
    )
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_INCOMPLETE.value)


def test_duplicate_enrollment_same_offering_rejected(api):
    """PRD §3.4: "There must be no existing non-WITHDRAWN enrollment for the same
    child-and-week pair, or the request is a duplicate and is rejected with
    ERR_DUPLICATE_ENROLLMENT."

    Design: Corner/validations/duplicate_enrollment_same_offering_rejected
    """
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    gh = make_guardian_headers(gid)
    scene = setup_open_session_with_offering(program_overrides={"name": "Du Camp"})
    enroll_child(gid, eligible["child"]["id"], scene["offering"]["id"], scene["offering"]["version"])
    # Second enroll for the same (child, offering).
    ver = get_offering(scene["offering"]["id"])["version"]
    resp = api.create_enrollment(
        create_enrollment_payload(eligible["child"]["id"], scene["offering"]["id"], ver), gh
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)


# ---------------------------------------------------------------------------
# Cross-entity state dependency (difficulty): enroll requires session OPEN
# ---------------------------------------------------------------------------
def test_enroll_into_scheduled_session_rejected_session_not_open(api):
    """PRD §3.4: "The target week's parent session must be OPEN; otherwise
    ERR_SESSION_NOT_OPEN."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_session_open
    """
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    gh = make_guardian_headers(gid)
    # Build a PUBLISHED program with a SCHEDULED (never-opened) session and an offering.
    program = api_client.create_program(create_program_payload(name="Sched Camp"), DIRECTOR).json()["data"]
    session = api_client.create_session(create_session_payload(program["id"], title="Sc7"), DIRECTOR).json()["data"]
    offering = api_client.create_weekly_offering(
        {"session_id": session["id"], "week_start": "2026-06-08"}, DIRECTOR
    ).json()["data"]
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    # Session left SCHEDULED.
    resp = api.create_enrollment(
        create_enrollment_payload(eligible["child"]["id"], offering["id"], offering["version"]), gh
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN.value)


# ---------------------------------------------------------------------------
# Priority-pair validation conflict (difficulty)
# ---------------------------------------------------------------------------
def test_session_not_open_outranks_authorization_incomplete(api):
    """PRD §2.10: "the global ordering is: first authentication ... then the target
    resource being in a legal state for the requested transition (ERR_INVALID_STATE), then
    the operation's own business rules".
    PRD §3.4: "The target week's parent session must be OPEN; otherwise
    ERR_SESSION_NOT_OPEN. ... The child must hold both an APPROVED authorization form of
    type MEDICAL and an APPROVED form of type PICKUP; lacking either yields
    ERR_AUTHORIZATION_INCOMPLETE." (Session check precedes authorization check.)

    Design: Difficulty/priority_pair_validation_conflict/session_not_open_beats_authorization_incomplete
    """
    guardian = create_guardian()
    gid = guardian["id"]
    gh = make_guardian_headers(gid)
    child = create_child(gid, first_name="Ey")
    add_emergency_contact(gid, child["id"])
    # No approved authorization forms at all.
    program = api_client.create_program(create_program_payload(name="P5 Camp"), DIRECTOR).json()["data"]
    session = api_client.create_session(create_session_payload(program["id"], title="P5s"), DIRECTOR).json()["data"]
    offering = api_client.create_weekly_offering(
        {"session_id": session["id"], "week_start": "2026-06-08"}, DIRECTOR
    ).json()["data"]
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(session["id"], DIRECTOR), 200)
    validate_success(api_client.close_session(session["id"], DIRECTOR), 200)  # now CLOSED
    ver = get_offering(offering["id"])["version"]
    resp = api.create_enrollment(create_enrollment_payload(child["id"], offering["id"], ver), gh)
    # Both session-not-open and authorization-incomplete fail; session check wins.
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN.value)


def test_not_resource_owner_outranks_age_out_of_group(api):
    """PRD §2.10: "then existence of every referenced resource (ERR_NOT_FOUND), then
    guardian ownership of the referenced child/enrollment/form (ERR_NOT_RESOURCE_OWNER),
    then the target resource being in a legal state ... then the operation's own business
    rules".
    PRD §3.4: "The acting guardian must own the child (the child's guardian_id must equal
    X-User-ID), or the request is rejected with ERR_NOT_RESOURCE_OWNER. ... The child's
    age, computed as of the session's reference date, must fall within the session's age
    group; an age outside the group yields ERR_AGE_OUT_OF_GROUP." (Ownership precedes age.)

    Design: Difficulty/priority_pair_validation_conflict/not_resource_owner_beats_age_out_of_group
    """
    owner = create_guardian()
    owner_id = owner["id"]
    # Owner's child is age 3 (out of group [8,10]) and fully authorized.
    eligible = setup_eligible_child(
        guardian_id=owner_id, child_overrides={"first_name": "Tot", "birth_date": "2023-01-01"}
    )
    other = create_guardian()
    scene = setup_open_session_with_offering(
        program_overrides={"name": "Own Camp"},
        session_overrides={"age_group_min": 8, "age_group_max": 10},
    )
    # A different guardian attempts the enroll of the owner's child.
    other_gh = make_guardian_headers(other["id"])
    ver = get_offering(scene["offering"]["id"])["version"]
    resp = api.create_enrollment(
        create_enrollment_payload(eligible["child"]["id"], scene["offering"]["id"], ver), other_gh
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
