"""Lifecycle and status-machine behaviour: initial states, declared transitions,
terminal-state lockdown, and the cascades a transition fires.

Every test builds its own world from an empty database, with the logical clock
pinned to its mandatory startup default before anything else happens.
"""

import pytest

from test_helpers import (
    ADMIN,
    DEFAULT_CLOCK,
    RSO,
    RSO_USER_ID,
    ApiErrorId,
    add_personnel,
    assign_and_complete_training,
    assign_training,
    clear_project_security,
    create_access_grant,
    create_disclosure_payload,
    create_incident,
    create_investigator,
    create_organization,
    create_project,
    create_subaward,
    create_travel,
    get_success_data,
    make_investigator_headers,
    read_access_grant,
    read_disclosure,
    read_incident,
    read_investigator,
    read_project,
    read_subaward,
    read_travel,
    screen_subaward,
    set_clock,
    set_grant_status,
    suspend_project_security,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Local setup helpers -- only for shapes no framework fixture provides.
# --------------------------------------------------------------------------- #

def _setup_loaner_tier_registration():
    """A SUBMITTED registration whose device tier is LOANER_REQUIRED on three flags:
    a high-risk destination, an ENTITY_LIST host and a RESTRICTED project.

    Returns (investigator, registration).
    """
    investigator = create_investigator(
        full_name="Ivan Jelic", home_department="Physics"
    )
    host = create_organization(
        legal_name="Listed Host Institute",
        country_code="CN",
        org_type="INSTITUTE",
        own_designation="ENTITY_LIST",
        designated_on="2025-06-01T00:00:00Z",
    )
    project = create_project(
        title="Restricted Optics Program",
        agency_code="DOD",
        sensitivity_level="RESTRICTED",
        award_amount_cents=90_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2029-08-31T00:00:00Z",
        controlled_area_capacity=2,
    )
    registration = create_travel(
        investigator["id"],
        destination_country_code="CN",
        depart_on="2026-09-10T00:00:00Z",
        return_on="2026-09-20T00:00:00Z",
        purpose="COLLABORATION",
        project_id=project["id"],
        host_organization_id=host["id"],
        carries_institutional_device=True,
    )
    return investigator, registration


def _setup_two_seat_area(controlled_area_capacity):
    """A security-CLEARED project with two investigators holding ACTIVE personnel
    rows and a COMPLETED controlled-area course each.

    Returns (project, investigator_a, investigator_b).
    """
    investigator_a = create_investigator(
        full_name="Rosa Tan", home_department="Robotics"
    )
    investigator_b = create_investigator(
        full_name="Sam Ubaldi",
        appointment_type="RESEARCH_STAFF",
        home_department="Robotics",
    )
    project = create_project(
        title="Shared Clean Room",
        agency_code="DOE",
        sensitivity_level="CONTROLLED",
        award_amount_cents=60_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2028-08-31T00:00:00Z",
        controlled_area_capacity=controlled_area_capacity,
    )
    add_personnel(
        project["id"],
        investigator_a["id"],
        role_on_project="PI",
        committed_person_months=1.00,
    )
    add_personnel(
        project["id"],
        investigator_b["id"],
        role_on_project="KEY_PERSON",
        committed_person_months=1.00,
    )
    assign_and_complete_training(
        investigator_a["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    assign_and_complete_training(
        investigator_b["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    clear_project_security(project["id"])
    return read_project(project["id"]), investigator_a, investigator_b


# --------------------------------------------------------------------------- #
# Initial states
# --------------------------------------------------------------------------- #

def test_new_disclosure_starts_in_draft_with_no_management_plan(api):
    """PRD §3.3: "The new record is created in review status `DRAFT` with plan
    status `NOT_REQUIRED`, `revision_round` at 0, `item_count` at 0,
    `late_item_count` at 0, `undisclosed_item_count` at 0, `completeness_score` at
    100, `completeness_tier` of `A`, and `submitted_at`, `certified_at`,
    `reviewer_user_id`, `plan_effort_cap_pct`, `plan_effective_from`,
    `plan_expires_on`, `plan_approver_user_id` and `plan_acknowledged_at` all null,
    with `plan_required_actions` an empty list."

    Design: Corner/state_machines/disclosure_created_row_starts_in_draft_with_no_plan
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(
        full_name="Hana Iversen", home_department="Chemistry"
    )
    # The parent's version is read immediately before the guarded write.
    parent = read_investigator(investigator["id"])

    response = api.create_disclosure(
        create_disclosure_payload(
            investigator["id"],
            parent["version"],
            cycle_label="2026-ANNUAL",
            disclosure_type="ANNUAL",
        ),
        make_investigator_headers(investigator["id"]),
    )
    validate_success(response, expected_status=201)
    disclosure = get_success_data(response)

    assert disclosure["review_status"] == "DRAFT"
    assert disclosure["plan_status"] == "NOT_REQUIRED"
    assert disclosure["revision_round"] == 0
    assert disclosure["item_count"] == 0
    assert disclosure["late_item_count"] == 0
    assert disclosure["undisclosed_item_count"] == 0
    assert disclosure["completeness_score"] == 100
    assert disclosure["completeness_tier"] == "A"
    assert disclosure["submitted_at"] is None
    assert disclosure["certified_at"] is None
    assert disclosure["reviewer_user_id"] is None
    assert disclosure["plan_effort_cap_pct"] is None
    assert disclosure["plan_effective_from"] is None
    assert disclosure["plan_expires_on"] is None
    assert disclosure["plan_approver_user_id"] is None
    assert disclosure["plan_acknowledged_at"] is None
    assert disclosure["plan_required_actions"] == []


# --------------------------------------------------------------------------- #
# Declared transitions and the work they do
# --------------------------------------------------------------------------- #

def test_travel_submission_lands_on_loaner_tier_from_three_flags(api):
    """PRD §3.7: "The `device_requirement_tier` is then read off the flag count in
    this exact order, with the no-device short-circuit evaluated first: if
    `carries_institutional_device` is false **and** the flag count is exactly 0, the
    tier is `NONE`; otherwise if the flag count is 1 or fewer, the tier is
    `STANDARD`; otherwise if the flag count is 3 or fewer, the tier is
    `LOANER_REQUIRED`; otherwise, at 4 flags, the tier is `LOANER_PLUS_ESCORT`. The
    bands are inclusive on both ends — one flag is `STANDARD`, two and three are
    `LOANER_REQUIRED`, four is `LOANER_PLUS_ESCORT` — and declining to carry an
    institutional device only reaches `NONE` when there are no flags at all.
    `briefing_required` is true precisely when the tier is `LOANER_REQUIRED` or
    `LOANER_PLUS_ESCORT`."

    Design: Corner/state_machines/travel_submission_computes_three_risk_flags_and_loaner_tier
    """
    set_clock(DEFAULT_CLOCK)
    investigator, registration = _setup_loaner_tier_registration()
    assert read_investigator(investigator["id"])["disclosure_posture"] == "CLEAR"

    response = api.set_travel_status(
        registration["id"],
        {"to_status": "SUBMITTED"},
        make_investigator_headers(investigator["id"]),
    )
    validate_success(response, expected_status=200)
    submitted = get_success_data(response)

    assert submitted["status"] == "SUBMITTED"
    # CN destination, ENTITY_LIST host and a RESTRICTED project raise three flags;
    # the traveller's CLEAR posture raises none.
    assert submitted["risk_flag_count"] == 3
    assert submitted["device_requirement_tier"] == "LOANER_REQUIRED"
    assert submitted["briefing_required"] is True
    assert submitted["device_decision_recorded_at"] is None


def test_travel_approval_refused_until_the_foreign_travel_brief_is_complete(api):
    """PRD §3.7: "If the `device_requirement_tier` is `LOANER_REQUIRED` or
    `LOANER_PLUS_ESCORT`, the traveller must hold a training assignment for
    `FOREIGN_TRAVEL_BRIEF` that is `COMPLETED` or `WAIVED`, else
    `ERR_TRAVEL_BRIEFING_REQUIRED`."

    Design: Corner/state_machines/travel_approval_without_briefing_rejected
    """
    set_clock(DEFAULT_CLOCK)
    investigator, registration = _setup_loaner_tier_registration()
    investigator_headers = make_investigator_headers(investigator["id"])
    submitted = get_success_data(
        api.set_travel_status(
            registration["id"], {"to_status": "SUBMITTED"}, investigator_headers
        )
    )
    assert submitted["device_requirement_tier"] == "LOANER_REQUIRED"

    refused = api.set_travel_status(
        registration["id"], {"to_status": "APPROVED"}, RSO
    )
    validate_error(
        refused, ApiErrorId.ERR_TRAVEL_BRIEFING_REQUIRED.value, expected_status=409
    )
    assert read_travel(registration["id"])["status"] == "SUBMITTED"

    assignment = assign_training(
        investigator["id"],
        course_code="FOREIGN_TRAVEL_BRIEF",
        due_on="2026-12-01T00:00:00Z",
    )
    completed = get_success_data(
        api.complete_training_assignment(assignment["id"], investigator_headers)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["completed_on"] is not None

    approved_response = api.set_travel_status(
        registration["id"], {"to_status": "APPROVED"}, RSO
    )
    validate_success(approved_response, expected_status=200)
    approved = get_success_data(approved_response)
    assert approved["status"] == "APPROVED"
    assert approved["device_decision_recorded_at"] is not None
    assert approved["risk_flag_count"] == 3
    assert approved["device_requirement_tier"] == "LOANER_REQUIRED"


def test_removing_an_active_roster_row_revokes_its_grant_and_releases_effort(api):
    """PRD §3.2: "Removing an `ACTIVE` row — `ACTIVE → REMOVED`, with `to_status`
    set to `REMOVED` — carries no preconditions and recomputes
    `committed_effort_pct`, `total_commitment_pct` and `overcommitment_pct` so that
    the conserved effort quantity returns to exactly its pre-activation value; it
    then revokes every access grant belonging to that same project and investigator
    whose `status` is `REQUESTED`, `ACTIVE` or `SUSPENDED`, stamping each with a
    `status_reason` of `PERSONNEL_REMOVED`; because grants left `ACTIVE`, the
    project's `active_grant_count` is recomputed and then its
    `controlled_area_posture`; and finally `activation_blockers` are recomputed."

    Design: Corner/state_machines/personnel_removal_revokes_grant_and_releases_effort
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(
        full_name="Lena Moreau", home_department="Materials"
    )
    project = create_project(
        title="Controlled Alloys Study",
        agency_code="DOE",
        sensitivity_level="CONTROLLED",
        award_amount_cents=50_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2028-08-31T00:00:00Z",
        controlled_area_capacity=1,
    )
    personnel = add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=1.00,
    )
    assign_and_complete_training(
        investigator["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    clear_project_security(project["id"])
    grant = create_access_grant(project["id"], investigator["id"])
    set_grant_status(grant["id"], "ACTIVE")

    before_investigator = read_investigator(investigator["id"])
    assert before_investigator["committed_effort_pct"] == pytest.approx(8.33, abs=0.01)
    assert before_investigator["total_commitment_pct"] == pytest.approx(
        108.33, abs=0.01
    )
    assert before_investigator["overcommitment_pct"] == pytest.approx(8.33, abs=0.01)
    before_project = read_project(project["id"])
    assert before_project["activation_blockers"] == ["DISCLOSURE_NOT_CERTIFIED"]
    assert before_project["active_grant_count"] == 1

    response = api.set_personnel_status(
        personnel["id"], {"to_status": "REMOVED"}, ADMIN
    )
    validate_success(response, expected_status=200)
    assert get_success_data(response)["status"] == "REMOVED"

    revoked = read_access_grant(grant["id"])
    assert revoked["status"] == "REVOKED"
    assert revoked["status_reason"] == "PERSONNEL_REMOVED"
    assert revoked["revoked_at"] is not None

    after_project = read_project(project["id"])
    assert after_project["active_grant_count"] == 0
    assert after_project["controlled_area_posture"] == "OPEN"
    assert after_project["activation_blockers"] == ["PERSONNEL_MISSING_PI"]

    after_investigator = read_investigator(investigator["id"])
    assert after_investigator["committed_effort_pct"] == pytest.approx(0.00, abs=0.01)
    assert after_investigator["total_commitment_pct"] == pytest.approx(100.00, abs=0.01)
    assert after_investigator["overcommitment_pct"] == pytest.approx(0.00, abs=0.01)


# --------------------------------------------------------------------------- #
# Undeclared transitions and terminal-state lockdown
# --------------------------------------------------------------------------- #

def test_reported_incident_cannot_jump_straight_to_closed(api):
    """PRD §3.8: "`CLOSED` and `UNSUBSTANTIATED` are both terminal, and any incident
    transition not declared above — including anything at all out of those two
    states — is refused with `ERR_INVALID_INCIDENT_TRANSITION`."

    Design: Corner/state_machines/incident_cannot_close_from_reported
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(
        full_name="Mira Novak", home_department="Statistics"
    )
    incident = create_incident(
        investigator["id"],
        incident_type="UNREPORTED_TRAVEL",
        discovered_on="2026-07-20T00:00:00Z",
        summary="Trip to a listed host was never registered.",
    )
    assert incident["status"] == "REPORTED"

    response = api.set_incident_status(
        incident["id"], {"to_status": "CLOSED"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_INCIDENT_TRANSITION.value, expected_status=409
    )

    unchanged = read_incident(incident["id"])
    assert unchanged["status"] == "REPORTED"
    assert unchanged["finding"] == "NONE"
    assert unchanged["severity"] is None
    assert unchanged["closed_at"] is None

    subject = read_investigator(investigator["id"])
    assert subject["disclosure_posture"] == "CLEAR"
    assert subject["substantiated_incident_count"] == 0


def test_unsubstantiated_incident_cannot_be_reopened(api):
    """PRD §3.8: "`CLOSED` and `UNSUBSTANTIATED` are both terminal, and any incident
    transition not declared above — including anything at all out of those two
    states — is refused with `ERR_INVALID_INCIDENT_TRANSITION`."

    Design: Corner/state_machines/incident_cannot_reopen_after_unsubstantiated
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(
        full_name="Nadia Ortiz", home_department="Economics"
    )
    incident = create_incident(
        investigator["id"],
        incident_type="DEVICE_COMPROMISE",
        discovered_on="2026-07-25T00:00:00Z",
        summary="Laptop flagged at return; forensics pending.",
    )
    dismissed = get_success_data(
        api.set_incident_status(
            incident["id"], {"to_status": "UNSUBSTANTIATED"}, RSO
        )
    )
    assert dismissed["status"] == "UNSUBSTANTIATED"

    response = api.set_incident_status(
        incident["id"],
        {"to_status": "INVESTIGATING", "lead_investigator_user_id": RSO_USER_ID},
        RSO,
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_INCIDENT_TRANSITION.value, expected_status=409
    )

    locked = read_incident(incident["id"])
    assert locked["status"] == "UNSUBSTANTIATED"
    assert locked["finding"] == "UNSUBSTANTIATED"
    assert locked["lead_investigator_user_id"] is None
    assert locked["severity_points"] is None

    subject = read_investigator(investigator["id"])
    assert subject["disclosure_posture"] == "CLEAR"
    assert subject["risk_score"] == 0
    assert subject["substantiated_incident_count"] == 0


def test_submitting_an_already_submitted_disclosure_is_refused(api):
    """PRD §2.8: "Transition declaration — the target record is in a state from
    which the requested transition is declared, including the lockdown of terminal
    states. Applies to every status or action endpoint; failure is the entity's
    transition error at HTTP 409: `ERR_INVALID_DISCLOSURE_TRANSITION`,
    `ERR_INVALID_ITEM_TRANSITION`, `ERR_INVALID_PROJECT_TRANSITION`,
    `ERR_INVALID_PERSONNEL_TRANSITION`, `ERR_INVALID_STATEMENT_TRANSITION`,
    `ERR_INVALID_TRAVEL_TRANSITION`, `ERR_INVALID_GRANT_TRANSITION`,
    `ERR_INVALID_INCIDENT_TRANSITION` or `ERR_INVALID_SUBAWARD_TRANSITION`."

    Design: Corner/state_machines/disclosure_submit_twice_second_call_rejected
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(
        full_name="Omar Pereira", home_department="History"
    )
    parent = read_investigator(investigator["id"])
    investigator_headers = make_investigator_headers(investigator["id"])
    disclosure = get_success_data(
        api.create_disclosure(
            create_disclosure_payload(investigator["id"], parent["version"]),
            investigator_headers,
        )
    )
    first = get_success_data(
        api.submit_disclosure(disclosure["id"], investigator_headers)
    )
    assert first["review_status"] == "SUBMITTED"
    stamped_at = first["submitted_at"]
    assert stamped_at is not None

    # Move the clock so a second stamp would be visibly different.
    set_clock("2026-08-05T00:00:00Z")

    response = api.submit_disclosure(disclosure["id"], investigator_headers)
    validate_error(
        response,
        ApiErrorId.ERR_INVALID_DISCLOSURE_TRANSITION.value,
        expected_status=409,
    )

    unchanged = read_disclosure(disclosure["id"])
    assert unchanged["review_status"] == "SUBMITTED"
    assert unchanged["submitted_at"] == stamped_at
    assert unchanged["revision_round"] == 0
    assert unchanged["completeness_score"] == 100


def test_completing_a_resolved_training_assignment_twice_is_refused(api):
    """PRD §3.9: "Both operations refuse to act twice: if the assignment already has
    either `completed_on` or `waived_on` set, the call fails with
    `ERR_TRAINING_ALREADY_RESOLVED`."

    Design: Corner/state_machines/training_complete_twice_second_call_rejected
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(
        full_name="Priya Raman", home_department="Engineering"
    )
    investigator_headers = make_investigator_headers(investigator["id"])
    assignment = assign_training(
        investigator["id"],
        course_code="EXPORT_CONTROL",
        due_on="2026-08-20T00:00:00Z",
        headers=ADMIN,
    )
    completed = get_success_data(
        api.complete_training_assignment(assignment["id"], investigator_headers)
    )
    resolved_at = completed["completed_on"]
    assert resolved_at is not None

    # The clock moves past due_on; completed_on was tested before the deadline.
    set_clock("2026-09-15T00:00:00Z")

    second_complete = api.complete_training_assignment(
        assignment["id"], investigator_headers
    )
    validate_error(
        second_complete,
        ApiErrorId.ERR_TRAINING_ALREADY_RESOLVED.value,
        expected_status=409,
    )
    later_waive = api.waive_training_assignment(assignment["id"], RSO)
    validate_error(
        later_waive,
        ApiErrorId.ERR_TRAINING_ALREADY_RESOLVED.value,
        expected_status=409,
    )

    unchanged = get_success_data(
        api.get_training_assignment(assignment["id"], ADMIN)
    )
    assert unchanged["completed_on"] == resolved_at
    assert unchanged["waived_on"] is None
    assert unchanged["status"] == "COMPLETED"
    assert read_investigator(investigator["id"])["training_compliant"] is True


# --------------------------------------------------------------------------- #
# Cascades driven by a single status write
# --------------------------------------------------------------------------- #

def test_security_termination_revokes_grants_and_terminates_subawards(api):
    """PRD §3.6: "Security termination is admissible from `CLEARED → TERMINATED` and
    from `SUSPENDED → TERMINATED`, neither with preconditions, and the two behave
    identically: every access grant on the project whose `status` is `REQUESTED`,
    `ACTIVE` or `SUSPENDED` transitions to `REVOKED` with a `status_reason` of
    `PROJECT_TERMINATED`; because grants left `ACTIVE`, the project's
    `active_grant_count` is recomputed and then its `controlled_area_posture`; and
    every subaward on the project whose `status` is not already `TERMINATED`
    transitions to `TERMINATED`."

    Design: Corner/state_machines/project_termination_cascades_grants_and_subawards
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(
        full_name="Quinn Salazar", home_department="Aerospace"
    )
    organization = create_organization(
        legal_name="Clean Partner University",
        country_code="JP",
        org_type="UNIVERSITY",
        own_designation="NONE",
    )
    project = create_project(
        title="Terminating Program",
        agency_code="NASA",
        sensitivity_level="CONTROLLED",
        award_amount_cents=40_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2028-08-31T00:00:00Z",
        controlled_area_capacity=1,
    )
    add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=2.00,
    )
    subaward = create_subaward(
        project["id"],
        organization["id"],
        scope="Ground-station data reduction",
        amount_cents=5_000_000,
    )
    subaward = screen_subaward(subaward["id"], "DIRECT_MATCH")
    assign_and_complete_training(
        investigator["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    clear_project_security(project["id"])
    grant = create_access_grant(project["id"], investigator["id"])
    set_grant_status(grant["id"], "ACTIVE")

    before_subaward = read_subaward(subaward["id"])
    assert before_subaward["status"] == "CLEARED"
    assert before_subaward["screening_designation"] == "NONE"
    assert before_subaward["screening_risk_points"] == 0
    before_project = read_project(project["id"])
    assert before_project["active_grant_count"] == 1
    assert before_project["controlled_area_posture"] == "RESTRICTED"

    response = api.set_security_status(
        project["id"], {"to_status": "TERMINATED"}, RSO
    )
    validate_success(response, expected_status=200)
    terminated = get_success_data(response)
    assert terminated["security_status"] == "TERMINATED"
    assert terminated["controlled_area_posture"] == "LOCKED_DOWN"

    revoked = read_access_grant(grant["id"])
    assert revoked["status"] == "REVOKED"
    assert revoked["status_reason"] == "PROJECT_TERMINATED"
    assert revoked["revoked_at"] is not None
    assert read_subaward(subaward["id"])["status"] == "TERMINATED"

    after_project = read_project(project["id"])
    assert after_project["active_grant_count"] == 0
    assert after_project["activation_blockers"] == [
        "SECURITY_NOT_CLEARED",
        "DISCLOSURE_NOT_CERTIFIED",
    ]


def test_reclearance_restores_only_grants_suspended_by_the_project(api):
    """PRD §3.6: "On success `security_status_reason` becomes `OFFICER_ACTION`, and a
    **conditional** restore runs: every access grant on the project whose `status`
    is `SUSPENDED` **and** whose `status_reason` is exactly `PROJECT_SUSPENDED` is
    revisited in ascending `created_at` order, and each one either returns to
    `ACTIVE` if the capacity projection still admits it, or else transitions to
    `REVOKED` with a `status_reason` of `CAPACITY_UNAVAILABLE`. Grants that were
    suspended for `INVESTIGATOR_RESTRICTED` or `OFFICER_ACTION` are deliberately
    **not** restored."

    Design: Corner/state_machines/project_reclearance_restores_only_project_suspended_grants
    """
    set_clock(DEFAULT_CLOCK)
    project, investigator_a, investigator_b = _setup_two_seat_area(
        controlled_area_capacity=2
    )
    grant_a = create_access_grant(project["id"], investigator_a["id"])
    set_grant_status(grant_a["id"], "ACTIVE")
    grant_b = create_access_grant(project["id"], investigator_b["id"])
    set_grant_status(grant_b["id"], "ACTIVE")
    # The officer suspends the second grant on their own authority.
    set_grant_status(grant_b["id"], "SUSPENDED")
    suspend_project_security(project["id"])

    before_a = read_access_grant(grant_a["id"])
    assert before_a["status"] == "SUSPENDED"
    assert before_a["status_reason"] == "PROJECT_SUSPENDED"
    before_b = read_access_grant(grant_b["id"])
    assert before_b["status"] == "SUSPENDED"
    assert before_b["status_reason"] == "OFFICER_ACTION"
    before_project = read_project(project["id"])
    assert before_project["active_grant_count"] == 0
    assert before_project["controlled_area_posture"] == "LOCKED_DOWN"

    response = api.set_security_status(
        project["id"], {"to_status": "CLEARED"}, RSO
    )
    validate_success(response, expected_status=200)
    cleared = get_success_data(response)
    assert cleared["security_status"] == "CLEARED"
    assert cleared["security_status_reason"] == "OFFICER_ACTION"

    restored = read_access_grant(grant_a["id"])
    assert restored["status"] == "ACTIVE"
    assert restored["status_reason"] == "NONE"
    assert restored["activated_at"] is not None

    untouched = read_access_grant(grant_b["id"])
    assert untouched["status"] == "SUSPENDED"
    assert untouched["status_reason"] == "OFFICER_ACTION"

    after_project = read_project(project["id"])
    assert after_project["active_grant_count"] == 1
    assert after_project["controlled_area_posture"] == "OPEN"


def test_restore_that_no_longer_fits_capacity_is_revoked_instead_of_failing(api):
    """PRD §3.7: "Where an officer's own restore request would exceed capacity it is
    refused with `ERR_AREA_CAPACITY_EXCEEDED`; where the system's restore cascade
    would exceed capacity the grant is instead sent to `REVOKED` with a
    `status_reason` of `CAPACITY_UNAVAILABLE` rather than the request failing."

    Design: Corner/state_machines/restore_that_no_longer_fits_capacity_is_revoked
    """
    set_clock(DEFAULT_CLOCK)
    project, investigator_a, investigator_b = _setup_two_seat_area(
        controlled_area_capacity=1
    )
    grant_a = create_access_grant(project["id"], investigator_a["id"])
    set_grant_status(grant_a["id"], "ACTIVE")
    # The clock moves so the second grant's created_at is strictly later, which
    # fixes the ascending created_at order the restore sweep walks.
    set_clock("2026-08-02T00:00:00Z")
    # Capacity is not enforced when a grant is merely requested.
    grant_b = create_access_grant(project["id"], investigator_b["id"])
    suspend_project_security(project["id"])

    before_a = read_access_grant(grant_a["id"])
    assert before_a["status"] == "SUSPENDED"
    assert before_a["status_reason"] == "PROJECT_SUSPENDED"
    before_b = read_access_grant(grant_b["id"])
    assert before_b["status"] == "SUSPENDED"
    assert before_b["status_reason"] == "PROJECT_SUSPENDED"
    assert read_project(project["id"])["active_grant_count"] == 0

    response = api.set_security_status(
        project["id"], {"to_status": "CLEARED"}, RSO
    )
    validate_success(response, expected_status=200)

    # The older grant is swept first and no longer fits beside its suspended peer.
    degraded = read_access_grant(grant_a["id"])
    assert degraded["status"] == "REVOKED"
    assert degraded["status_reason"] == "CAPACITY_UNAVAILABLE"
    assert degraded["revoked_at"] is not None

    admitted = read_access_grant(grant_b["id"])
    assert admitted["status"] == "ACTIVE"
    assert admitted["status_reason"] == "NONE"

    after_project = read_project(project["id"])
    assert after_project["active_grant_count"] == 1
    assert after_project["controlled_area_posture"] == "RESTRICTED"
