"""Error-condition suite: every guard reports its own documented error id.

Each test builds its own world from scratch, because the harness restarts the
server before every test: the database is empty and the logical clock sits at its
mandatory startup default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    CRO,
    CRO_SECOND_USER_ID,
    NON_EXISTENT_UUID,
    RSO,
    RSO_SECOND_USER_ID,
    RSO_USER_ID,
    LIAISON_SECOND_USER_ID,
    LIAISON_USER_ID,
    ApiErrorId,
    add_disclosure_item,
    add_personnel,
    assign_and_complete_training,
    begin_review,
    clear_project_security,
    create_access_grant,
    create_access_grant_payload,
    create_disclosure,
    create_incident,
    create_investigator,
    create_organization,
    create_project,
    create_support_statement,
    create_travel,
    investigate_incident,
    issue_plan_payload,
    make_agency_liaison_headers,
    make_conflict_review_official_headers,
    make_investigator_headers,
    make_research_security_officer_headers,
    notify_incident,
    read_investigator,
    read_project,
    read_travel,
    remove_personnel,
    require_plan,
    set_clock,
    set_grant_status,
    set_item_status,
    set_travel_status,
    setup_active_award,
    setup_disclosure_under_review,
    setup_restricted_investigator,
    setup_substantiated_incident,
    submit_disclosure,
    submit_travel,
    substantiate_incident,
    validate_error,
)

# --------------------------------------------------------------------------- #
# Private setup helpers (no test_helpers module is modified)
# --------------------------------------------------------------------------- #

_NOT_FOUND_READS = [
    ("get_investigator", ApiErrorId.ERR_INVESTIGATOR_NOT_FOUND),
    ("get_foreign_organization", ApiErrorId.ERR_ORGANIZATION_NOT_FOUND),
    ("get_project", ApiErrorId.ERR_PROJECT_NOT_FOUND),
    ("get_personnel", ApiErrorId.ERR_PERSONNEL_NOT_FOUND),
    ("get_disclosure", ApiErrorId.ERR_DISCLOSURE_NOT_FOUND),
    ("get_disclosure_item", ApiErrorId.ERR_DISCLOSURE_ITEM_NOT_FOUND),
    ("get_support_statement", ApiErrorId.ERR_SUPPORT_STATEMENT_NOT_FOUND),
    ("get_travel_registration", ApiErrorId.ERR_TRAVEL_REGISTRATION_NOT_FOUND),
    ("get_access_grant", ApiErrorId.ERR_ACCESS_GRANT_NOT_FOUND),
    ("get_security_incident", ApiErrorId.ERR_INCIDENT_NOT_FOUND),
    ("get_training_assignment", ApiErrorId.ERR_TRAINING_ASSIGNMENT_NOT_FOUND),
    ("get_subaward", ApiErrorId.ERR_SUBAWARD_NOT_FOUND),
]


def _setup_disclosure_under_review_by(
    reviewer_headers, investigator_id, item_overrides=None, organization_id=None
):
    """Open a disclosure, optionally attach one item, submit it and take it under
    review as ``reviewer_headers`` so that officer becomes reviewer_user_id."""
    disclosure = create_disclosure(investigator_id)
    if item_overrides is not None:
        add_disclosure_item(
            disclosure["id"],
            organization_id,
            investigator_id=investigator_id,
            **item_overrides,
        )
    submit_disclosure(disclosure["id"], investigator_id)
    return begin_review(disclosure["id"], headers=reviewer_headers)


def _setup_plan_required_disclosure():
    """A disclosure whose plan dimension sits at PLAN_REQUIRED, reviewed by cro-1.

    A DECLARED TALENT_PROGRAM item is the warranting trigger, and with no late
    items and no revision rounds the completeness_score stays at 100.
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    organization = create_organization(own_designation="NONE")
    disclosure = _setup_disclosure_under_review_by(
        CRO,
        investigator["id"],
        item_overrides={"item_type": "TALENT_PROGRAM", "annual_effort_hours": 100},
        organization_id=organization["id"],
    )
    disclosure = require_plan(disclosure["id"], headers=CRO)
    return investigator, disclosure


def _setup_award_active_with_grant():
    """An ACTIVE award carrying one ACTIVE controlled-access grant."""
    project, investigator, _disclosure = setup_active_award(
        sensitivity_level="CONTROLLED", controlled_area_capacity=1
    )
    grant = create_access_grant(project["id"], investigator["id"])
    grant = set_grant_status(grant["id"], "ACTIVE")
    return project, investigator, grant


def _setup_approved_trip():
    """An APPROVED zero-flag conference trip departing 2026-09-10, returning 2026-09-20."""
    investigator = create_investigator()
    registration = create_travel(
        investigator["id"],
        destination_country_code="KR",
        depart_on="2026-09-10T00:00:00Z",
        return_on="2026-09-20T00:00:00Z",
    )
    submit_travel(registration["id"], investigator["id"])
    registration = set_travel_status(registration["id"], "APPROVED")
    return investigator, registration


def _setup_requested_grant_without_roster():
    """A REQUESTED grant on a security-CLEARED project that has no personnel rows."""
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project(
        sensitivity_level="CONTROLLED", controlled_area_capacity=2
    )
    assign_and_complete_training(
        investigator["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    clear_project_security(project["id"])
    grant = create_access_grant(project["id"], investigator["id"])
    return investigator, project, grant


def _suspend_investigator(investigator_id):
    """Drive an incident to AGENCY_NOTIFIED so the investigator's posture is SUSPENDED."""
    _investigator_id, incident = setup_substantiated_incident(
        investigator_id=investigator_id, lead_investigator_user_id=RSO_USER_ID
    )
    notify_incident(incident["id"])
    investigator = read_investigator(investigator_id)
    assert investigator["disclosure_posture"] == "SUSPENDED", (
        "an agency-notified incident must leave the investigator SUSPENDED, "
        f"got {investigator['disclosure_posture']}"
    )
    return investigator


# --------------------------------------------------------------------------- #
# Path existence: every entity family owns its own 404
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "reader_name,expected_error",
    _NOT_FOUND_READS,
    ids=[name for name, _ in _NOT_FOUND_READS],
)
def test_every_entity_family_reports_its_own_not_found_code(
    api, reader_name, expected_error
):
    """PRD §2.8: "The not-found codes are `ERR_INVESTIGATOR_NOT_FOUND`,
    `ERR_ORGANIZATION_NOT_FOUND` (covering `organization_id`,
    `parent_organization_id`, `foreign_organization_id` and
    `host_organization_id`), `ERR_PROJECT_NOT_FOUND` (covering `project_id` and
    `required_for_project_id`), `ERR_PERSONNEL_NOT_FOUND`,
    `ERR_DISCLOSURE_NOT_FOUND`, `ERR_DISCLOSURE_ITEM_NOT_FOUND`,
    `ERR_SUPPORT_STATEMENT_NOT_FOUND`, `ERR_TRAVEL_REGISTRATION_NOT_FOUND`,
    `ERR_ACCESS_GRANT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_TRAINING_ASSIGNMENT_NOT_FOUND` and `ERR_SUBAWARD_NOT_FOUND` — all HTTP
    404."

    Design: Corner/errors/every_entity_type_reports_its_own_not_found_code
    """
    response = getattr(api, reader_name)(NON_EXISTENT_UUID, RSO)
    validate_error(response, expected_error.value, expected_status=404)


# --------------------------------------------------------------------------- #
# Identity checks outrank the transition check
# --------------------------------------------------------------------------- #

def test_foreign_investigator_submitting_another_disclosure_is_not_the_resource_owner(api):
    """PRD §2.8: "Resource ownership for `Investigator`-role callers — `X-User-ID`
    equals the target investigator's `id`, or the owning investigator of the
    target disclosure, disclosure item or travel registration. This applies to
    `POST /disclosures`, `POST /disclosures/{disclosure_id}/items`, `POST
    /disclosures/{disclosure_id}/submit`, the `ACKNOWLEDGE` action of `POST
    /disclosures/{disclosure_id}/plan`, `POST /disclosure-items/{item_id}/status`,
    `POST /travel-registrations` and `POST
    /travel-registrations/{registration_id}/status`. Failure is
    `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/errors/resource_owner_and_assigned_reviewer_checks_outrank_the_transition_check
    """
    owner = create_investigator(institutional_base_effort_pct=0)
    stranger = create_investigator(institutional_base_effort_pct=0)
    organization = create_organization(own_designation="NONE")
    disclosure, _items = setup_disclosure_under_review(
        owner["id"],
        items=[{"item_type": "FOREIGN_APPOINTMENT", "annual_effort_hours": 40}],
        organization_id=organization["id"],
    )

    # The disclosure is UNDER_REVIEW, so submission is also an undeclared
    # transition; the ownership check is the earlier one and must answer.
    response = api.submit_disclosure(
        disclosure["id"], make_investigator_headers(stranger["id"])
    )
    validate_error(
        response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
    )


def test_second_officer_cannot_certify_a_disclosure_reviewed_by_another(api):
    """PRD §3.4: "The caller must be the stored `reviewer_user_id`, else
    `ERR_NOT_ASSIGNED_REVIEWER`."

    Design: Corner/errors/resource_owner_and_assigned_reviewer_checks_outrank_the_transition_check
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    organization = create_organization(own_designation="NONE")
    disclosure, _items = setup_disclosure_under_review(
        investigator["id"],
        items=[{"item_type": "FOREIGN_APPOINTMENT", "annual_effort_hours": 40}],
        organization_id=organization["id"],
    )

    response = api.review_disclosure(
        disclosure["id"],
        {"action": "CERTIFY"},
        make_research_security_officer_headers(RSO_SECOND_USER_ID),
    )
    validate_error(
        response, ApiErrorId.ERR_NOT_ASSIGNED_REVIEWER.value, expected_status=403
    )


# --------------------------------------------------------------------------- #
# Incident lead identity, segregation of duties and the notification date
# --------------------------------------------------------------------------- #

def test_only_the_stored_lead_may_substantiate_an_incident(api):
    """PRD §3.8: "Substantiation, `INVESTIGATING → SUBSTANTIATED`, likewise
    requires the caller to be the stored lead, else `ERR_NOT_INCIDENT_LEAD`."

    Design: Corner/errors/incident_notification_guards_cover_lead_identity_segregation_and_date
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    incident = create_incident(investigator["id"])
    investigate_incident(
        incident["id"], lead_investigator_user_id=RSO_SECOND_USER_ID
    )

    response = api.set_incident_status(
        incident["id"],
        {"to_status": "SUBSTANTIATED"},
        make_research_security_officer_headers(RSO_USER_ID),
    )
    validate_error(
        response, ApiErrorId.ERR_NOT_INCIDENT_LEAD.value, expected_status=403
    )


def test_the_incident_lead_may_never_transmit_the_sponsor_notification(api):
    """PRD §3.8: "The caller's `X-User-ID` must differ from the stored
    `lead_investigator_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — the officer
    who ran the investigation may not also certify to the sponsor that it was
    reported."

    Design: Corner/errors/incident_notification_guards_cover_lead_identity_segregation_and_date
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    incident = create_incident(investigator["id"])
    investigate_incident(incident["id"], lead_investigator_user_id=LIAISON_USER_ID)
    substantiate_incident(
        incident["id"], headers=make_research_security_officer_headers(LIAISON_USER_ID)
    )

    response = api.notify_incident(
        incident["id"],
        {
            "agency_notified_on": "2026-08-10T00:00:00Z",
            "notification_reference": "AG-2026-0001",
        },
        make_agency_liaison_headers(LIAISON_USER_ID),
    )
    validate_error(
        response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )


def test_notification_cannot_predate_the_substantiation_date(api):
    """PRD §3.8: "And `agency_notified_on` must fall on or after the date of
    `substantiated_at`, else `ERR_INVALID_NOTIFICATION_DATE` (HTTP 422)."

    Design: Corner/errors/incident_notification_guards_cover_lead_identity_segregation_and_date
    """
    set_clock()
    investigator = create_investigator(institutional_base_effort_pct=0)
    incident = create_incident(investigator["id"])
    investigate_incident(incident["id"], lead_investigator_user_id=LIAISON_USER_ID)
    substantiate_incident(
        incident["id"], headers=make_research_security_officer_headers(LIAISON_USER_ID)
    )

    # substantiated_at is the logical clock, 2026-08-01; a 2026-07-25 notification
    # predates it.
    response = api.notify_incident(
        incident["id"],
        {
            "agency_notified_on": "2026-07-25T00:00:00Z",
            "notification_reference": "AG-2026-0001",
        },
        make_agency_liaison_headers(LIAISON_SECOND_USER_ID),
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_NOTIFICATION_DATE.value, expected_status=422
    )


# --------------------------------------------------------------------------- #
# The management-plan dimension: warrant, resolution, segregation and window
# --------------------------------------------------------------------------- #

def test_requiring_a_plan_without_a_conflict_trigger_is_not_warranted(api):
    """PRD §3.4: "It demands that the disclosure's `review_status` be
    `UNDER_REVIEW`, else `ERR_INVALID_DISCLOSURE_TRANSITION`; that the caller be
    the stored `reviewer_user_id`, else `ERR_NOT_ASSIGNED_REVIEWER`; and that a
    conflict-of-commitment trigger actually be present — meaning the
    investigator's `total_commitment_pct` exceeds 100, **or** the disclosure
    carries an item whose `item_type` is `TALENT_PROGRAM` with `status` of
    `DECLARED` or `VERIFIED`, **or** the investigator's `risk_score` is at least
    30. If none of those three holds, the action is refused with
    `ERR_PLAN_NOT_WARRANTED`."

    Design: Corner/errors/plan_issue_guards_cover_warrant_resolution_segregation_and_window
    """
    investigator = create_investigator(institutional_base_effort_pct=90)
    organization = create_organization(own_designation="NONE")
    disclosure = _setup_disclosure_under_review_by(
        CRO,
        investigator["id"],
        item_overrides={
            "item_type": "FOREIGN_APPOINTMENT",
            "annual_effort_hours": 40,
            "is_paid": False,
        },
        organization_id=organization["id"],
    )

    # total_commitment_pct is 90.00, risk_score is 0 and no TALENT_PROGRAM item
    # exists, so no trigger is present.
    response = api.review_disclosure(
        disclosure["id"], {"action": "REQUIRE_PLAN"}, CRO
    )
    validate_error(
        response, ApiErrorId.ERR_PLAN_NOT_WARRANTED.value, expected_status=409
    )


def test_certification_is_blocked_while_the_plan_is_only_required(api):
    """PRD §3.4: "The `plan_status` must be one of `NOT_REQUIRED`, `PLAN_WAIVED`
    or `PLAN_ACKNOWLEDGED`, else `ERR_PLAN_NOT_RESOLVED` — so a disclosure
    sitting at `PLAN_REQUIRED`, `PLAN_ISSUED` or `PLAN_TERMINATED` cannot be
    certified."

    Design: Corner/errors/plan_issue_guards_cover_warrant_resolution_segregation_and_window
    """
    _investigator, disclosure = _setup_plan_required_disclosure()
    assert disclosure["plan_status"] == "PLAN_REQUIRED"
    assert disclosure["completeness_score"] == 100

    response = api.review_disclosure(disclosure["id"], {"action": "CERTIFY"}, CRO)
    validate_error(
        response, ApiErrorId.ERR_PLAN_NOT_RESOLVED.value, expected_status=409
    )


def test_the_reviewing_official_may_not_issue_the_plan(api):
    """PRD §3.4: "The acting `X-User-ID` must differ from the disclosure's
    `reviewer_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — the officer who
    reviewed the disclosure may not also write the plan that manages it."

    Design: Corner/errors/plan_issue_guards_cover_warrant_resolution_segregation_and_window
    """
    _investigator, disclosure = _setup_plan_required_disclosure()

    # CRO is cro-1, the stored reviewer_user_id from BEGIN_REVIEW.
    response = api.plan_disclosure(disclosure["id"], issue_plan_payload(), CRO)
    validate_error(
        response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )


def test_a_plan_window_that_does_not_advance_is_refused(api):
    """PRD §3.4: "All four plan fields must be present, else
    `ERR_INVALID_REQUEST`; and `plan_expires_on` must fall strictly after
    `plan_effective_from`, else `ERR_INVALID_PLAN_WINDOW`."

    Design: Corner/errors/plan_issue_guards_cover_warrant_resolution_segregation_and_window
    """
    _investigator, disclosure = _setup_plan_required_disclosure()

    response = api.plan_disclosure(
        disclosure["id"],
        issue_plan_payload(
            plan_effective_from="2026-09-01T00:00:00Z",
            plan_expires_on="2026-09-01T00:00:00Z",
        ),
        make_conflict_review_official_headers(CRO_SECOND_USER_ID),
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_PLAN_WINDOW.value, expected_status=422
    )


# --------------------------------------------------------------------------- #
# Award closure gates
# --------------------------------------------------------------------------- #

def test_closing_an_award_with_a_live_access_grant_is_refused(api):
    """PRD §3.9: "No access grant on the project may have a `status` of
    `REQUESTED`, `ACTIVE` or `SUSPENDED`, else `ERR_ACCESS_GRANTS_OPEN` — every
    grant must already be `REVOKED`."

    Design: Corner/errors/project_closure_guards_open_grants_then_open_incidents
    """
    project, _investigator, grant = _setup_award_active_with_grant()
    assert grant["status"] == "ACTIVE"

    response = api.set_award_status(project["id"], {"to_status": "CLOSED"}, ADMIN)
    validate_error(
        response, ApiErrorId.ERR_ACCESS_GRANTS_OPEN.value, expected_status=409
    )


def test_closing_an_award_with_an_open_incident_is_refused(api):
    """PRD §3.9: "And the project's `open_incident_count` must be 0, else
    `ERR_OPEN_INCIDENTS`."

    Design: Corner/errors/project_closure_guards_open_grants_then_open_incidents
    """
    project, investigator, grant = _setup_award_active_with_grant()
    set_grant_status(grant["id"], "REVOKED")
    create_incident(
        investigator["id"],
        incident_type="UNREPORTED_TRAVEL",
        project_id=project["id"],
    )
    assert read_project(project["id"])["open_incident_count"] == 1

    response = api.set_award_status(project["id"], {"to_status": "CLOSED"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_OPEN_INCIDENTS.value, expected_status=409)


# --------------------------------------------------------------------------- #
# The funding dimension needs an ACTIVE PI and cannot skip ACTIVATION_PENDING
# --------------------------------------------------------------------------- #

def test_activation_pending_requires_an_active_principal_investigator(api):
    """PRD §3.9: "Moving `PROPOSED → ACTIVATION_PENDING` requires at least one
    personnel row on the project whose `role_on_project` is `PI` and whose
    `status` is `ACTIVE`, else `ERR_PI_REQUIRED`; it recomputes
    `activation_blockers`."

    Design: Corner/errors/award_activation_pending_without_an_active_pi_rejected
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project()
    add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=3.00,
        activate=False,
    )

    response = api.set_award_status(
        project["id"], {"to_status": "ACTIVATION_PENDING"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_PI_REQUIRED.value, expected_status=409)


def test_an_award_cannot_jump_from_proposed_straight_to_active(api):
    """PRD §3.9: "Any award-status transition not declared from the project's
    current funding state is refused with `ERR_INVALID_PROJECT_TRANSITION`, the
    same error the security dimension uses."

    Design: Corner/errors/award_activation_pending_without_an_active_pi_rejected
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project()
    add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=3.00,
        activate=False,
    )

    response = api.set_award_status(project["id"], {"to_status": "ACTIVE"}, ADMIN)
    validate_error(
        response, ApiErrorId.ERR_INVALID_PROJECT_TRANSITION.value, expected_status=409
    )


# --------------------------------------------------------------------------- #
# Travel timing reads the logical clock
# --------------------------------------------------------------------------- #

def test_a_trip_cannot_be_completed_before_its_return_date(api):
    """PRD §3.7: "`APPROVED → COMPLETED` is an officer act permitted only once
    the logical clock is on or after `return_on`, else `ERR_TRAVEL_NOT_ENDED`; it
    releases the window as well."

    Design: Corner/errors/travel_completion_and_cancellation_respect_the_logical_clock
    """
    set_clock()
    _investigator, registration = _setup_approved_trip()

    # The clock is 2026-08-01, well before the 2026-09-20 return.
    response = api.set_travel_status(
        registration["id"], {"to_status": "COMPLETED"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_TRAVEL_NOT_ENDED.value, expected_status=409
    )


def test_a_trip_cannot_be_cancelled_once_the_clock_reaches_departure(api):
    """PRD §3.7: "`APPROVED → CANCELLED` may be requested by the traveller or by
    an officer, but only while the logical clock is strictly before `depart_on`,
    else `ERR_TRAVEL_ALREADY_STARTED`; it too releases the window."

    Design: Corner/errors/travel_completion_and_cancellation_respect_the_logical_clock
    """
    set_clock()
    investigator, registration = _setup_approved_trip()
    set_clock("2026-09-15T00:00:00Z")

    response = api.set_travel_status(
        registration["id"],
        {"to_status": "CANCELLED"},
        make_investigator_headers(investigator["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_TRAVEL_ALREADY_STARTED.value, expected_status=409
    )


def test_a_zero_length_registration_cannot_be_submitted(api):
    """PRD §3.7: "Submission, `DRAFT → SUBMITTED`, is the traveller's own act:
    `X-User-ID` must equal the registration's investigator, else
    `ERR_NOT_RESOURCE_OWNER`; `depart_on` must fall strictly before `return_on`,
    else `ERR_INVALID_TRAVEL_WINDOW`; and the trip must not collide with the
    traveller's other commitments."

    Design: Corner/errors/travel_completion_and_cancellation_respect_the_logical_clock
    """
    set_clock()
    investigator = create_investigator()
    registration = create_travel(
        investigator["id"],
        destination_country_code="JP",
        depart_on="2026-10-01T00:00:00Z",
        return_on="2026-10-01T00:00:00Z",
        purpose="TEACHING",
        carries_institutional_device=False,
    )
    assert registration["status"] == "DRAFT"

    response = api.set_travel_status(
        registration["id"],
        {"to_status": "SUBMITTED"},
        make_investigator_headers(investigator["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_TRAVEL_WINDOW.value, expected_status=422
    )


# --------------------------------------------------------------------------- #
# Controlled-access grants: roster, uniqueness and terminal revocation
# --------------------------------------------------------------------------- #

def test_a_grant_cannot_activate_without_an_active_personnel_row(api):
    """PRD §3.7: "The grant's investigator must hold an `ACTIVE` personnel row on
    the grant's project, else `ERR_PERSONNEL_NOT_ACTIVE`."

    Design: Corner/errors/grant_activation_requires_an_active_personnel_row
    """
    _investigator, project, grant = _setup_requested_grant_without_roster()

    response = api.set_access_grant_status(grant["id"], {"to_status": "ACTIVE"}, RSO)
    validate_error(
        response, ApiErrorId.ERR_PERSONNEL_NOT_ACTIVE.value, expected_status=409
    )
    assert read_project(project["id"])["active_grant_count"] == 0


def test_a_second_unrevoked_grant_for_the_same_pair_is_a_duplicate(api):
    """PRD §3.7: "Only one unrevoked grant may exist for a given project and
    investigator pair; a second is refused with `ERR_DUPLICATE_ACCESS_GRANT`."

    Design: Corner/errors/grant_activation_requires_an_active_personnel_row
    """
    investigator, project, _grant = _setup_requested_grant_without_roster()

    # The parent version guard is checked before uniqueness, so read the project
    # immediately before the guarded write.
    current = read_project(project["id"])
    response = api.create_access_grant(
        create_access_grant_payload(
            project["id"],
            investigator["id"],
            current["version"],
            valid_from="2027-01-01T00:00:00Z",
            valid_until="2027-06-01T00:00:00Z",
        ),
        RSO,
    )
    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_ACCESS_GRANT.value, expected_status=409
    )


def test_a_revoked_grant_can_never_be_activated_again(api):
    """PRD §3.7: "Any grant transition not declared above, including anything out
    of `REVOKED`, is refused with `ERR_INVALID_GRANT_TRANSITION`."

    Design: Corner/errors/grant_activation_requires_an_active_personnel_row
    """
    _investigator, _project, grant = _setup_requested_grant_without_roster()
    revoked = set_grant_status(grant["id"], "REVOKED")
    assert revoked["status"] == "REVOKED"

    response = api.set_access_grant_status(grant["id"], {"to_status": "ACTIVE"}, RSO)
    validate_error(
        response, ApiErrorId.ERR_INVALID_GRANT_TRANSITION.value, expected_status=409
    )


# --------------------------------------------------------------------------- #
# Support-statement reconciliation preconditions
# --------------------------------------------------------------------------- #

def test_a_first_reconcile_needs_a_certified_disclosure(api):
    """PRD §3.5: "A first reconcile out of `SUBMITTED` requires that the
    investigator hold at least one disclosure whose review status is `CERTIFIED`,
    else `ERR_NO_CERTIFIED_DISCLOSURE`; re-runs from `RECONCILED` or from
    `INCONSISTENT` carry no precondition at all."

    Design: Corner/errors/support_statement_supersession_and_duplicate_guards_use_different_keys
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project(agency_code="NIH")
    statement = create_support_statement(
        investigator["id"],
        project["id"],
        agency_code="NIH",
        document_type="CURRENT_AND_PENDING",
        declared_person_months=2.00,
        declared_appointment_count=1,
    )
    assert statement["status"] == "SUBMITTED"

    response = api.reconcile_support_statement(
        statement["id"], {"variant": "STRICT_AGENCY"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_NO_CERTIFIED_DISCLOSURE.value, expected_status=409
    )


# --------------------------------------------------------------------------- #
# Terminal child rows reject undeclared transitions with their own codes
# --------------------------------------------------------------------------- #

def test_a_verified_item_cannot_be_disputed_again(api):
    """PRD §3.3: "`WITHDRAWN` is terminal; any transition requested out of it, or
    any item transition not declared above, is refused with
    `ERR_INVALID_ITEM_TRANSITION`."

    Design: Corner/errors/terminal_child_rows_reject_undeclared_transitions
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    organization = create_organization(own_designation="NONE")
    disclosure = create_disclosure(investigator["id"])
    item = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="OUTSIDE_SUPPORT",
        in_kind_value_cents=500000,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    verified = set_item_status(item["id"], "VERIFIED")
    assert verified["status"] == "VERIFIED"

    response = api.set_disclosure_item_status(
        item["id"], {"to_status": "DISPUTED"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_ITEM_TRANSITION.value, expected_status=409
    )


def test_a_removed_personnel_row_cannot_be_reactivated(api):
    """PRD §3.2: "`REMOVED` is terminal: any further transition request on that
    row is refused with `ERR_INVALID_PERSONNEL_TRANSITION`."

    Design: Corner/errors/terminal_child_rows_reject_undeclared_transitions
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project()
    personnel = add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="CO_PI",
        committed_person_months=2.00,
    )
    removed = remove_personnel(personnel["id"])
    assert removed["status"] == "REMOVED"

    response = api.set_personnel_status(
        personnel["id"], {"to_status": "ACTIVE"}, ADMIN
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_PERSONNEL_TRANSITION.value, expected_status=409
    )
    assert read_investigator(investigator["id"])["committed_effort_pct"] == 0.00


def test_a_denied_trip_cannot_be_approved(api):
    """PRD §3.7: "`DENIED`, `CANCELLED` and `COMPLETED` are terminal, and any
    travel transition not declared above is refused with
    `ERR_INVALID_TRAVEL_TRANSITION`."

    Design: Corner/errors/terminal_child_rows_reject_undeclared_transitions
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    registration = create_travel(
        investigator["id"],
        destination_country_code="IT",
        depart_on="2026-11-01T00:00:00Z",
        return_on="2026-11-08T00:00:00Z",
        purpose="COLLABORATION",
    )
    submit_travel(registration["id"], investigator["id"])
    denied = set_travel_status(registration["id"], "DENIED")
    assert denied["status"] == "DENIED"

    response = api.set_travel_status(
        registration["id"], {"to_status": "APPROVED"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_TRAVEL_TRANSITION.value, expected_status=409
    )


# --------------------------------------------------------------------------- #
# The escort tier demands an acknowledged management plan
# --------------------------------------------------------------------------- #

def test_escort_tier_travel_without_an_acknowledged_plan_is_refused(api):
    """PRD §3.7: "And if the tier is `LOANER_PLUS_ESCORT` specifically, the
    traveller must hold a disclosure whose `plan_status` is `PLAN_ACKNOWLEDGED`,
    else `ERR_MANAGEMENT_PLAN_REQUIRED`."

    Design: Corner/errors/escort_tier_travel_requires_an_acknowledged_plan
    """
    set_clock()
    investigator, host_organization, _disclosure, _item = (
        setup_restricted_investigator()
    )
    assert read_investigator(investigator["id"])["disclosure_posture"] == "RESTRICTED"
    project = create_project(
        sensitivity_level="RESTRICTED", controlled_area_capacity=2
    )
    assign_and_complete_training(
        investigator["id"], course_code="FOREIGN_TRAVEL_BRIEF"
    )

    registration = create_travel(
        investigator["id"],
        destination_country_code="CN",
        depart_on="2026-10-05T00:00:00Z",
        return_on="2026-10-15T00:00:00Z",
        purpose="COLLABORATION",
        project_id=project["id"],
        host_organization_id=host_organization["id"],
        carries_institutional_device=True,
    )
    submit_travel(registration["id"], investigator["id"])

    # All four risk flags are raised, so the tier is LOANER_PLUS_ESCORT and the
    # completed briefing alone is no longer sufficient.
    submitted = read_travel(registration["id"])
    assert submitted["risk_flag_count"] == 4
    assert submitted["device_requirement_tier"] == "LOANER_PLUS_ESCORT"
    assert submitted["briefing_required"] is True

    response = api.set_travel_status(
        registration["id"], {"to_status": "APPROVED"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_MANAGEMENT_PLAN_REQUIRED.value, expected_status=409
    )
    assert read_travel(registration["id"])["device_decision_recorded_at"] is None


# --------------------------------------------------------------------------- #
# A SUSPENDED posture blocks three unrelated writes with one code
# --------------------------------------------------------------------------- #

def test_a_suspended_investigator_cannot_submit_a_disclosure(api):
    """PRD §3.3: "It carries a disclosure from `DRAFT → SUBMITTED` or, after a
    round of revision, from `RETURNED_FOR_REVISION → SUBMITTED`, and both paths
    are guarded identically: `X-User-ID` must equal the disclosure's
    `investigator_id`, else `ERR_NOT_RESOURCE_OWNER`; the investigator's
    `disclosure_posture` must not be `SUSPENDED`, else
    `ERR_INVESTIGATOR_SUSPENDED`; and no item on the disclosure may be in
    `DISPUTED`, else `ERR_DISPUTED_ITEMS_OPEN`."

    Design: Corner/errors/suspended_investigator_cannot_submit_be_activated_or_be_cleared
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    _suspend_investigator(investigator["id"])

    # Record keeping still works: only the transition is gated.
    disclosure = create_disclosure(investigator["id"])
    assert disclosure["review_status"] == "DRAFT"

    response = api.submit_disclosure(
        disclosure["id"], make_investigator_headers(investigator["id"])
    )
    validate_error(
        response, ApiErrorId.ERR_INVESTIGATOR_SUSPENDED.value, expected_status=409
    )


def test_a_suspended_investigator_cannot_be_activated_on_a_roster(api):
    """PRD §3.2: "The investigator's `disclosure_posture` must not be
    `SUSPENDED`, else `ERR_INVESTIGATOR_SUSPENDED`."

    Design: Corner/errors/suspended_investigator_cannot_submit_be_activated_or_be_cleared
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project(
        sensitivity_level="CONTROLLED", controlled_area_capacity=2
    )
    personnel = add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="SENIOR_PERSONNEL",
        committed_person_months=1.00,
        activate=False,
    )
    _suspend_investigator(investigator["id"])

    response = api.set_personnel_status(
        personnel["id"], {"to_status": "ACTIVE"}, ADMIN
    )
    validate_error(
        response, ApiErrorId.ERR_INVESTIGATOR_SUSPENDED.value, expected_status=409
    )


def test_a_project_cannot_be_cleared_while_an_active_member_is_suspended(api):
    """PRD §3.6: "Initial clearance, `PENDING_CLEARANCE → CLEARED`, requires two
    things: no subaward on the project may be in `PENDING`, `FLAGGED` or
    `BLOCKED`, else `ERR_SUBAWARD_SCREENING_OPEN`; and no investigator holding an
    `ACTIVE` personnel row on the project may have a `disclosure_posture` of
    `SUSPENDED`, else `ERR_INVESTIGATOR_SUSPENDED`."

    Design: Corner/errors/suspended_investigator_cannot_submit_be_activated_or_be_cleared
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project(
        sensitivity_level="CONTROLLED", controlled_area_capacity=2
    )
    add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=6.00,
    )
    _suspend_investigator(investigator["id"])

    response = api.set_security_status(project["id"], {"to_status": "CLEARED"}, RSO)
    validate_error(
        response, ApiErrorId.ERR_INVESTIGATOR_SUSPENDED.value, expected_status=409
    )
    assert read_project(project["id"])["security_status"] == "PENDING_CLEARANCE"
