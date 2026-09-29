"""Non-linear status paths and the synchronous cascades they set off.

Every test builds its own world from scratch: the harness restarts the server
before each test, so the database is empty and the logical clock sits at its
mandatory startup default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    LIAISON,
    RSO,
    RSO_USER_ID,
    DEFAULT_CLOCK,
    ApiErrorId,
    add_disclosure_item,
    add_personnel,
    assign_and_complete_training,
    begin_review,
    certify_disclosure,
    clear_project_security,
    create_access_grant,
    create_disclosure,
    create_incident,
    create_investigator,
    create_organization,
    create_project,
    create_subaward,
    investigate_incident,
    make_investigator_headers,
    notify_incident,
    read_access_grant,
    read_disclosure,
    read_disclosure_item,
    read_incident,
    read_investigator,
    read_organization,
    read_project,
    read_subaward,
    return_for_revision,
    screen_subaward,
    set_award_status,
    set_clock,
    set_grant_status,
    set_item_status,
    setup_active_award,
    setup_certified_investigator,
    setup_disclosure_under_review,
    setup_owned_organization_pair,
    setup_project_with_active_pi,
    submit_disclosure,
    substantiate_incident,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Local setup helpers
# --------------------------------------------------------------------------- #

def _setup_disclosure_after_first_revision_round():
    """One investigator whose disclosure has completed a single revision round and
    sits back in UNDER_REVIEW, carrying one VERIFIED FOREIGN_APPOINTMENT item on a
    NONE-designated organization.

    Returns (investigator, disclosure, item).
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(institutional_base_effort_pct=0)
    organization = create_organization(own_designation="NONE")
    disclosure, created = setup_disclosure_under_review(
        investigator["id"],
        items=[
            {
                "item_type": "FOREIGN_APPOINTMENT",
                "annual_effort_hours": 0,
                "is_paid": False,
            }
        ],
        organization_id=organization["id"],
    )
    item = set_item_status(created[0]["id"], "VERIFIED")
    return_for_revision(disclosure["id"])
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    return investigator, read_disclosure(disclosure["id"]), item


def _run_second_revision_round(disclosure_id, investigator_id):
    """Return the disclosure for a second round of revision and resume its review."""
    return_for_revision(disclosure_id)
    resumed = read_disclosure(disclosure_id)
    submit_disclosure(disclosure_id, investigator_id)
    begin_review(disclosure_id)
    return resumed


def _setup_project_awaiting_activation():
    """A project in ACTIVATION_PENDING with an ACTIVE PI who holds no disclosure at
    all, no controlled area (capacity 0) and security still PENDING_CLEARANCE.

    Returns (project, investigator).
    """
    set_clock(DEFAULT_CLOCK)
    project, investigator, _personnel = setup_project_with_active_pi(
        investigator_overrides={"institutional_base_effort_pct": 0},
        committed_person_months=2.00,
        title="Thin Film Program",
        agency_code="DOE",
        sensitivity_level="STANDARD",
        award_amount_cents=50_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2029-08-31T00:00:00Z",
        controlled_area_capacity=0,
    )
    set_award_status(project["id"], "ACTIVATION_PENDING")
    return read_project(project["id"]), investigator


def _setup_two_incidents_on_one_investigator():
    """Two incidents for one investigator. Incident one links a CERTIFIED disclosure
    carrying a live INCIDENT_REMEDIATION item and is SUBSTANTIATED; incident two
    links no disclosure and is already AGENCY_NOTIFIED.

    Returns (investigator, disclosure, incident_one, incident_two).
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(institutional_base_effort_pct=0)
    organization = create_organization(own_designation="NONE")
    disclosure = create_disclosure(
        investigator["id"],
        cycle_label="2026-EVENT-01",
        disclosure_type="EVENT_DRIVEN",
    )
    incident_one = create_incident(
        investigator["id"],
        incident_type="UNDISCLOSED_APPOINTMENT",
        discovered_on="2026-07-20T00:00:00Z",
        summary="Unreported appointment at a foreign institute.",
        disclosure_id=disclosure["id"],
    )
    incident_two = create_incident(
        investigator["id"],
        incident_type="UNREPORTED_TRAVEL",
        discovered_on="2026-07-22T00:00:00Z",
        summary="Unregistered trip discovered in expense records.",
    )
    add_disclosure_item(
        disclosure["id"],
        organization["id"],
        headers=RSO,
        item_type="FOREIGN_APPOINTMENT",
        start_date="2024-10-01T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
        source="INCIDENT_REMEDIATION",
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    certify_disclosure(disclosure["id"])

    investigate_incident(incident_one["id"], lead_investigator_user_id=RSO_USER_ID)
    incident_one = substantiate_incident(incident_one["id"])
    investigate_incident(incident_two["id"], lead_investigator_user_id=RSO_USER_ID)
    incident_two = substantiate_incident(incident_two["id"])
    incident_two = notify_incident(
        incident_two["id"],
        agency_notified_on=DEFAULT_CLOCK,
        notification_reference="DOE-OIG-2026-0917",
    )
    return investigator, disclosure, incident_one, incident_two


def _setup_critical_incident_under_investigation():
    """An ACTIVE, RESTRICTED award with an ACTIVE grant for its PI, plus an incident
    on both the project and the PI's disclosure sitting in INVESTIGATING.

    Returns (investigator, project, grant, incident).
    """
    set_clock(DEFAULT_CLOCK)
    project, investigator, disclosure = setup_active_award(
        committed_person_months=3.00,
        title="Fast Reactor Instrumentation",
        agency_code="DOE",
        sensitivity_level="RESTRICTED",
        award_amount_cents=250_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2029-08-31T00:00:00Z",
        controlled_area_capacity=1,
    )
    grant = create_access_grant(project["id"], investigator["id"])
    grant = set_grant_status(grant["id"], "ACTIVE")
    incident = create_incident(
        investigator["id"],
        incident_type="UNDISCLOSED_TALENT_PROGRAM",
        discovered_on="2026-07-28T00:00:00Z",
        summary="Undisclosed foreign talent program membership.",
        disclosure_id=disclosure["id"],
        project_id=project["id"],
    )
    investigate_incident(incident["id"], lead_investigator_user_id=RSO_USER_ID)
    return investigator, read_project(project["id"]), grant, incident


def _setup_transitively_screened_award():
    """A parent organization holding 60.00 percent of a child, a subaward to that
    child already screened CLEARED under OWNERSHIP_TRANSITIVE, the project security
    CLEARED and one ACTIVE controlled-access grant on it.

    Returns (parent, child, project, subaward, grant).
    """
    set_clock(DEFAULT_CLOCK)
    parent, child = setup_owned_organization_pair(
        parent_designation="NONE",
        child_designation="NONE",
        ownership_pct=60.00,
    )
    investigator, _disclosure = setup_certified_investigator()
    project = create_project(
        title="Photonic Sensing Testbed",
        agency_code="NSF",
        sensitivity_level="STANDARD",
        award_amount_cents=90_000_000,
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
    assign_and_complete_training(
        investigator["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    subaward = create_subaward(
        project["id"],
        child["id"],
        scope="Optical component fabrication.",
        amount_cents=12_000_000,
    )
    subaward = screen_subaward(subaward["id"], "OWNERSHIP_TRANSITIVE")
    clear_project_security(project["id"])
    grant = create_access_grant(project["id"], investigator["id"])
    grant = set_grant_status(grant["id"], "ACTIVE")
    return parent, child, read_project(project["id"]), subaward, grant


def _designate_sdn(api, organization_id):
    """Designate an organization SDN, reading its current version immediately first."""
    current = read_organization(organization_id)
    return api.designate_organization(
        organization_id,
        {
            "own_designation": "SDN",
            "designated_on": DEFAULT_CLOCK,
            "expected_organization_version": current["version"],
        },
        RSO,
    )


# --------------------------------------------------------------------------- #
# The disclosure review loop and its reject gate
# --------------------------------------------------------------------------- #

def test_rejection_after_a_single_revision_round_is_too_early(api):
    """PRD §3.4: "`REJECT` carries the disclosure from `UNDER_REVIEW → REJECTED`
    and is available only to the stored `reviewer_user_id`. It additionally
    requires that `revision_round` be at least 2 — the office must have given the
    investigator two chances before abandoning the record — else
    `ERR_REJECT_TOO_EARLY`."

    Design: Difficulty/non_linear_state_machine/disclosure_revision_cycle_gates_reject_until_second_round
    """
    _investigator, disclosure, _item = _setup_disclosure_after_first_revision_round()
    assert disclosure["review_status"] == "UNDER_REVIEW"
    assert disclosure["revision_round"] == 1

    response = api.review_disclosure(disclosure["id"], {"action": "REJECT"}, RSO)
    validate_error(response, ApiErrorId.ERR_REJECT_TOO_EARLY.value, expected_status=409)

    unchanged = read_disclosure(disclosure["id"])
    assert unchanged["review_status"] == "UNDER_REVIEW"
    assert unchanged["revision_round"] == 1


def test_second_revision_round_carries_the_round_counter_and_admits_rejection(api):
    """PRD §3.4: "`RETURN_FOR_REVISION` carries the disclosure from `UNDER_REVIEW →
    RETURNED_FOR_REVISION` and is likewise restricted to the stored
    `reviewer_user_id`; it increments `revision_round` by one and recomputes
    `completeness_score` and `completeness_tier`, and because the revision penalty
    grows with each round, a return can move the disclosure into a lower tier.
    `RETURNED_FOR_REVISION → SUBMITTED` closes the cycle, which a disclosure may
    traverse any number of times."

    Design: Difficulty/non_linear_state_machine/disclosure_revision_cycle_gates_reject_until_second_round
    """
    investigator, disclosure, _item = _setup_disclosure_after_first_revision_round()

    returned = _run_second_revision_round(disclosure["id"], investigator["id"])
    assert returned["review_status"] == "RETURNED_FOR_REVISION"
    assert returned["revision_round"] == 2
    # Raw score 100 - 6 * 2 = 88 selects tier B, whose penalty of 5 leaves 83.
    assert returned["completeness_score"] == 83
    assert returned["completeness_tier"] == "B"

    response = api.review_disclosure(disclosure["id"], {"action": "REJECT"}, RSO)
    rejected = validate_success(response, expected_status=200)
    assert rejected["review_status"] == "REJECTED"
    assert rejected["revision_round"] == 2
    assert rejected["completeness_score"] == 83
    assert rejected["completeness_tier"] == "B"


def test_rejection_pulls_verified_items_out_of_the_risk_input_set(api):
    """PRD §3.4: "On rejection, every item whose `status` is `DECLARED` or
    `DISPUTED` transitions to `WITHDRAWN`; because those items have left the
    scoring set, the investigator's `outside_effort_pct`, `total_commitment_pct`
    and `risk_score` are recomputed; and because `risk_score` changed,
    `disclosure_posture` is recomputed."

    Design: Difficulty/non_linear_state_machine/disclosure_revision_cycle_gates_reject_until_second_round
    """
    investigator, disclosure, item = _setup_disclosure_after_first_revision_round()
    before = read_investigator(investigator["id"])
    assert before["risk_score"] == 12

    _run_second_revision_round(disclosure["id"], investigator["id"])
    response = api.review_disclosure(disclosure["id"], {"action": "REJECT"}, RSO)
    validate_success(response, expected_status=200)

    # A VERIFIED item is neither DECLARED nor DISPUTED, so it survives untouched.
    assert read_disclosure_item(item["id"])["status"] == "VERIFIED"
    after = read_investigator(investigator["id"])
    assert after["risk_score"] == 0
    assert after["disclosure_posture"] == "CLEAR"


def test_rejected_disclosure_is_locked_against_further_transitions(api):
    """PRD §3.3: "`CERTIFIED`, `REJECTED` and `SUPERSEDED` are the three terminal
    review states; a review action requested against a record already in one of
    them is refused with `ERR_INVALID_DISCLOSURE_TRANSITION`."

    Design: Difficulty/non_linear_state_machine/disclosure_revision_cycle_gates_reject_until_second_round
    """
    investigator, disclosure, _item = _setup_disclosure_after_first_revision_round()
    _run_second_revision_round(disclosure["id"], investigator["id"])
    validate_success(
        api.review_disclosure(disclosure["id"], {"action": "REJECT"}, RSO),
        expected_status=200,
    )

    review_again = api.review_disclosure(
        disclosure["id"], {"action": "RETURN_FOR_REVISION"}, RSO
    )
    validate_error(
        review_again,
        ApiErrorId.ERR_INVALID_DISCLOSURE_TRANSITION.value,
        expected_status=409,
    )

    resubmit = api.submit_disclosure(
        disclosure["id"], make_investigator_headers(investigator["id"])
    )
    validate_error(
        resubmit,
        ApiErrorId.ERR_INVALID_DISCLOSURE_TRANSITION.value,
        expected_status=409,
    )
    assert read_disclosure(disclosure["id"])["review_status"] == "REJECTED"


# --------------------------------------------------------------------------- #
# The two independent award dimensions and the activation gate
# --------------------------------------------------------------------------- #

def test_activation_is_blocked_while_security_clearance_is_outstanding(api):
    """PRD §3.9: "Moving `ACTIVATION_PENDING → ACTIVE` requires
    `activation_blockers` to be empty, else `ERR_ACTIVATION_BLOCKED`, whose
    message names the first code in the ordered list — which is why the ordering
    above is fixed rather than incidental; on success it recomputes
    `open_incident_count` and `controlled_area_posture`."

    Design: Difficulty/non_linear_state_machine/project_award_and_security_dimensions_advance_independently
    """
    project, _investigator = _setup_project_awaiting_activation()
    assert project["award_status"] == "ACTIVATION_PENDING"
    assert project["activation_blockers"] == [
        "SECURITY_NOT_CLEARED",
        "DISCLOSURE_NOT_CERTIFIED",
    ]

    response = api.set_award_status(project["id"], {"to_status": "ACTIVE"}, ADMIN)
    error = validate_error(
        response, ApiErrorId.ERR_ACTIVATION_BLOCKED.value, expected_status=409
    )
    assert "SECURITY_NOT_CLEARED" in error["message"]
    assert read_project(project["id"])["award_status"] == "ACTIVATION_PENDING"


def test_initial_security_clearance_records_officer_action_and_recomputes_blockers(api):
    """PRD §3.6: "Initial clearance, `PENDING_CLEARANCE → CLEARED`, requires two
    things: no subaward on the project may be in `PENDING`, `FLAGGED` or
    `BLOCKED`, else `ERR_SUBAWARD_SCREENING_OPEN`; and no investigator holding an
    `ACTIVE` personnel row on the project may have a `disclosure_posture` of
    `SUSPENDED`, else `ERR_INVESTIGATOR_SUSPENDED`. On success
    `security_status_reason` becomes `OFFICER_ACTION`, and both
    `activation_blockers` and `controlled_area_posture` are recomputed."

    Design: Difficulty/non_linear_state_machine/project_award_and_security_dimensions_advance_independently
    """
    project, _investigator = _setup_project_awaiting_activation()

    response = api.set_security_status(project["id"], {"to_status": "CLEARED"}, RSO)
    cleared = validate_success(response, expected_status=200)
    assert cleared["security_status"] == "CLEARED"
    assert cleared["security_status_reason"] == "OFFICER_ACTION"
    assert cleared["activation_blockers"] == ["DISCLOSURE_NOT_CERTIFIED"]


def test_security_clearance_leaves_the_funding_dimension_where_it_stood(api):
    """PRD §3.2: "The two dimensions evolve independently and only meet at the
    activation gate."

    Design: Difficulty/non_linear_state_machine/project_award_and_security_dimensions_advance_independently
    """
    project, _investigator = _setup_project_awaiting_activation()
    validate_success(
        api.set_security_status(project["id"], {"to_status": "CLEARED"}, RSO),
        expected_status=200,
    )

    after_clearance = read_project(project["id"])
    assert after_clearance["security_status"] == "CLEARED"
    assert after_clearance["award_status"] == "ACTIVATION_PENDING"

    response = api.set_award_status(project["id"], {"to_status": "ACTIVE"}, ADMIN)
    error = validate_error(
        response, ApiErrorId.ERR_ACTIVATION_BLOCKED.value, expected_status=409
    )
    assert "DISCLOSURE_NOT_CERTIFIED" in error["message"]
    assert read_project(project["id"])["award_status"] == "ACTIVATION_PENDING"


def test_zero_capacity_project_stays_locked_down_across_the_clearance_move(api):
    """PRD §2.11: "A project's `controlled_area_posture` is one of `OPEN`,
    `RESTRICTED` or `LOCKED_DOWN`, evaluated top-down in this order: if the
    project's `security_status` is `SUSPENDED` or `TERMINATED`, the posture is
    `LOCKED_DOWN`; otherwise if its `controlled_area_capacity` is 0, the posture
    is `LOCKED_DOWN`; otherwise if its `active_grant_count` is greater than or
    equal to its `controlled_area_capacity`, the posture is `RESTRICTED`;
    otherwise the posture is `OPEN`."

    Design: Difficulty/non_linear_state_machine/project_award_and_security_dimensions_advance_independently
    """
    project, _investigator = _setup_project_awaiting_activation()
    assert project["controlled_area_capacity"] == 0
    assert project["controlled_area_posture"] == "LOCKED_DOWN"

    cleared = validate_success(
        api.set_security_status(project["id"], {"to_status": "CLEARED"}, RSO),
        expected_status=200,
    )
    assert cleared["security_status"] == "CLEARED"
    assert cleared["active_grant_count"] == 0
    assert cleared["controlled_area_posture"] == "LOCKED_DOWN"


# --------------------------------------------------------------------------- #
# Incident closure as a join of the notification and remediation legs
# --------------------------------------------------------------------------- #

def test_notified_incident_without_remediation_cannot_close(api):
    """PRD §3.8: "Closure is a join point: both the notification branch and the
    remediation branch must be complete. `AGENCY_NOTIFIED → CLOSED` requires the
    incident's remediation leg to be finished — the incident's `disclosure_id`
    must not be null, the disclosure it names must have a `review_status` of
    `CERTIFIED`, and that disclosure must carry at least one item whose `source`
    is `INCIDENT_REMEDIATION` and whose `status` is not `WITHDRAWN` — else
    `ERR_REMEDIATION_INCOMPLETE`."

    Design: Difficulty/non_linear_state_machine/incident_closure_requires_both_branch_legs_to_converge
    """
    _investigator, _disclosure, _incident_one, incident_two = (
        _setup_two_incidents_on_one_investigator()
    )
    assert incident_two["status"] == "AGENCY_NOTIFIED"

    response = api.set_incident_status(
        incident_two["id"], {"to_status": "CLOSED"}, RSO
    )
    validate_error(
        response, ApiErrorId.ERR_REMEDIATION_INCOMPLETE.value, expected_status=409
    )
    assert read_incident(incident_two["id"])["status"] == "AGENCY_NOTIFIED"


def test_substantiated_incident_cannot_skip_agency_notification(api):
    """PRD §3.8: "The other approach to closure is declared purely so the join is
    explicit: `SUBSTANTIATED → CLOSED` is **always** rejected, with
    `ERR_AGENCY_NOTIFICATION_REQUIRED`, because a substantiated incident can never
    skip agency notification."

    Design: Difficulty/non_linear_state_machine/incident_closure_requires_both_branch_legs_to_converge
    """
    _investigator, _disclosure, incident_one, _incident_two = (
        _setup_two_incidents_on_one_investigator()
    )
    assert incident_one["status"] == "SUBSTANTIATED"

    response = api.set_incident_status(
        incident_one["id"], {"to_status": "CLOSED"}, RSO
    )
    validate_error(
        response,
        ApiErrorId.ERR_AGENCY_NOTIFICATION_REQUIRED.value,
        expected_status=409,
    )
    assert read_incident(incident_one["id"])["status"] == "SUBSTANTIATED"


def test_prior_substantiated_incident_surcharges_the_second_severity_freeze(api):
    """PRD §3.8: "Then the system counts the investigator's **other** incidents —
    excluding this one — whose `finding` is `SUBSTANTIATED`, multiplies that count
    by 10, caps the product at 20, and adds the result; so one prior adds 10, two
    priors add 20, and three or more priors still add only 20. The total is stored
    as `severity_points`, and `severity` is banded off it with inclusive floors:
    below 20 is `LOW`, below 40 is `MODERATE`, below 60 is `HIGH`, and 60 or above
    is `CRITICAL`. The floors bite exactly where they are written — an
    `UNREPORTED_TRAVEL` incident on an active, `RESTRICTED` project scores 15 plus
    15 plus 10 for exactly 40 points and is therefore `HIGH`, while one point less
    would be `MODERATE`. Finally `notification_due_on` is set to
    `substantiated_at` plus the window the band earns: 60 days for `LOW`, 30 for
    `MODERATE`, 10 for `HIGH` and 5 for `CRITICAL`. Both `severity_points` and
    `notification_due_on` are frozen at this instant; a later change to the
    project's `award_status`, or a later incident added to the investigator's
    history, never moves an existing deadline."

    Design: Difficulty/non_linear_state_machine/incident_closure_requires_both_branch_legs_to_converge
    """
    _investigator, _disclosure, incident_one, incident_two = (
        _setup_two_incidents_on_one_investigator()
    )

    # UNDISCLOSED_APPOINTMENT with no project and no prior substantiated incident.
    first = read_incident(incident_one["id"])
    assert first["severity_points"] == 20
    assert first["severity"] == "MODERATE"
    assert first["notification_due_on"].startswith("2026-08-31")

    # UNREPORTED_TRAVEL at 15 points plus one 10-point prior-incident surcharge.
    second = read_incident(incident_two["id"])
    assert second["severity_points"] == 25
    assert second["severity"] == "MODERATE"
    assert second["notification_due_on"].startswith("2026-08-31")


def test_notification_leg_records_an_on_time_sponsor_notification(api):
    """PRD §3.8: "On success the incident moves to `AGENCY_NOTIFIED`,
    `agency_notified_on` and `notification_reference` are stored, and
    `notified_late` is set to whether `agency_notified_on` is later than the frozen
    `notification_due_on`. That comparison is by date, so a notification landing
    exactly on `notification_due_on` is on time and `notified_late` stays false."

    Design: Difficulty/non_linear_state_machine/incident_closure_requires_both_branch_legs_to_converge
    """
    _investigator, _disclosure, incident_one, _incident_two = (
        _setup_two_incidents_on_one_investigator()
    )

    response = api.notify_incident(
        incident_one["id"],
        {
            "agency_notified_on": DEFAULT_CLOCK,
            "notification_reference": "DOE-OIG-2026-0918",
        },
        LIAISON,
    )
    notified = validate_success(response, expected_status=200)
    assert notified["status"] == "AGENCY_NOTIFIED"
    assert notified["notification_reference"] == "DOE-OIG-2026-0918"
    assert notified["notified_late"] is False


def test_incident_closes_once_notification_and_remediation_both_landed(api):
    """PRD §3.8: "On success `closed_at` is set to the current logical clock,
    `finding` deliberately **stays** `SUBSTANTIATED` so that the closed incident
    keeps contributing its 10-point prior-incident surcharge to any later
    incident, the project's `open_incident_count` is recomputed, and the
    investigator's `disclosure_posture` is recomputed but stays `SUSPENDED`,
    because the agency-notification history is permanent."

    Design: Difficulty/non_linear_state_machine/incident_closure_requires_both_branch_legs_to_converge
    """
    investigator, _disclosure, incident_one, _incident_two = (
        _setup_two_incidents_on_one_investigator()
    )
    notify_incident(
        incident_one["id"],
        agency_notified_on=DEFAULT_CLOCK,
        notification_reference="DOE-OIG-2026-0918",
    )

    response = api.set_incident_status(
        incident_one["id"], {"to_status": "CLOSED"}, RSO
    )
    closed = validate_success(response, expected_status=200)
    assert closed["status"] == "CLOSED"
    assert closed["finding"] == "SUBSTANTIATED"

    subject = read_investigator(investigator["id"])
    assert subject["disclosure_posture"] == "SUSPENDED"
    assert subject["substantiated_incident_count"] == 2


# --------------------------------------------------------------------------- #
# One critical substantiation, four cascade hops
# --------------------------------------------------------------------------- #

def test_critical_substantiation_freezes_points_band_and_deadline(api):
    """PRD §3.8: "It begins from the incident type: 20 points for
    `UNDISCLOSED_APPOINTMENT`, 40 for `UNDISCLOSED_TALENT_PROGRAM`, 15 for
    `UNREPORTED_TRAVEL`, 35 for `RESTRICTED_ENTITY_COLLABORATION` and 30 for
    `DEVICE_COMPROMISE`. Three surcharges may follow. If a `project_id` is present
    and that project's `award_status` is `ACTIVE`, 15 points are added. If a
    `project_id` is present and that project's `sensitivity_level` is
    `RESTRICTED`, 10 further points are added."

    Design: Difficulty/transitive_cascade/critical_incident_cascades_posture_grants_counts_and_project_security
    """
    _investigator, project, _grant, incident = (
        _setup_critical_incident_under_investigation()
    )
    assert project["award_status"] == "ACTIVE"
    assert project["sensitivity_level"] == "RESTRICTED"

    response = api.set_incident_status(
        incident["id"], {"to_status": "SUBSTANTIATED"}, RSO
    )
    substantiated = validate_success(response, expected_status=200)
    assert substantiated["severity_points"] == 65
    assert substantiated["severity"] == "CRITICAL"
    assert substantiated["notification_due_on"].startswith("2026-08-06")


def test_critical_finding_drives_the_investigator_posture_to_suspended(api):
    """PRD §3.8: "Because a substantiated finding now exists, the investigator's
    `disclosure_posture` is recomputed, which takes them to `RESTRICTED` — or all
    the way to `SUSPENDED` when the frozen `severity` is `CRITICAL`."

    Design: Difficulty/transitive_cascade/critical_incident_cascades_posture_grants_counts_and_project_security
    """
    investigator, _project, _grant, incident = (
        _setup_critical_incident_under_investigation()
    )
    assert read_investigator(investigator["id"])["disclosure_posture"] == "CLEAR"

    validate_success(
        api.set_incident_status(incident["id"], {"to_status": "SUBSTANTIATED"}, RSO),
        expected_status=200,
    )

    subject = read_investigator(investigator["id"])
    assert subject["disclosure_posture"] == "SUSPENDED"
    assert subject["substantiated_incident_count"] == 1


def test_posture_hop_suspends_the_grant_before_the_project_cascade_reaches_it(api):
    """PRD §3.8: "Because that posture has left `CLEAR`/`REVIEW_REQUIRED`, every
    access grant belonging to that investigator whose `status` is `REQUESTED` or
    `ACTIVE` transitions to `SUSPENDED` with a `status_reason` of
    `INVESTIGATOR_RESTRICTED`, spanning every project the investigator holds
    access on. Because those grants left `ACTIVE`, each affected project's
    `active_grant_count` is recomputed and then its `controlled_area_posture`."

    Design: Difficulty/transitive_cascade/critical_incident_cascades_posture_grants_counts_and_project_security
    """
    _investigator, project, grant, incident = (
        _setup_critical_incident_under_investigation()
    )
    assert project["active_grant_count"] == 1
    assert project["controlled_area_posture"] == "RESTRICTED"
    assert read_access_grant(grant["id"])["status"] == "ACTIVE"

    validate_success(
        api.set_incident_status(incident["id"], {"to_status": "SUBSTANTIATED"}, RSO),
        expected_status=200,
    )

    suspended_grant = read_access_grant(grant["id"])
    assert suspended_grant["status"] == "SUSPENDED"
    assert suspended_grant["status_reason"] == "INVESTIGATOR_RESTRICTED"
    assert read_project(project["id"])["active_grant_count"] == 0


def test_critical_severity_suspends_the_security_dimension_of_the_award(api):
    """PRD §3.8: "And when the `severity` is `CRITICAL`, one further hop fires:
    every project that has an `ACTIVE` personnel row for that investigator and
    whose `security_status` is `CLEARED` is suspended with a
    `security_status_reason` of `INCIDENT_NOTIFICATION`, which drags its own
    grant-suspension cascade behind it."

    Design: Difficulty/transitive_cascade/critical_incident_cascades_posture_grants_counts_and_project_security
    """
    _investigator, project, _grant, incident = (
        _setup_critical_incident_under_investigation()
    )
    assert project["security_status"] == "CLEARED"

    validate_success(
        api.set_incident_status(incident["id"], {"to_status": "SUBSTANTIATED"}, RSO),
        expected_status=200,
    )

    after = read_project(project["id"])
    assert after["security_status"] == "SUSPENDED"
    assert after["security_status_reason"] == "INCIDENT_NOTIFICATION"
    assert after["controlled_area_posture"] == "LOCKED_DOWN"
    assert after["activation_blockers"] == [
        "SECURITY_NOT_CLEARED",
        "INVESTIGATOR_SUSPENDED",
    ]
    assert after["award_status"] == "ACTIVE"
    assert after["open_incident_count"] == 1


# --------------------------------------------------------------------------- #
# A parent designation reaching a grant three entities away
# --------------------------------------------------------------------------- #

def test_parent_designation_imputes_through_the_controlling_hop(api):
    """PRD §3.1: "Because the organization's designation changed,
    `effective_designation` and `effective_designation_depth` are recomputed for
    every descendant reachable through hops of at least 50 percent ownership."

    Design: Difficulty/transitive_cascade/parent_designation_change_cascades_through_ownership_to_grants
    """
    parent, child, _project, _subaward, _grant = _setup_transitively_screened_award()
    assert read_organization(child["id"])["effective_designation"] == "NONE"

    designated = validate_success(_designate_sdn(api, parent["id"]), expected_status=200)
    assert designated["effective_designation"] == "SDN"
    assert designated["effective_designation_depth"] == 0

    imputed = read_organization(child["id"])
    assert imputed["own_designation"] == "NONE"
    assert imputed["effective_designation"] == "SDN"
    assert imputed["effective_designation_depth"] == 1


def test_affected_subaward_is_rescreened_under_its_stored_variant(api):
    """PRD §3.1: "Because those descendant designations changed, every subaward
    whose counterparty is an affected organization and whose `status` is `CLEARED`
    or `FLAGGED` transitions to `BLOCKED`, and that subaward's
    `screening_designation`, `screening_matched_organization_id`,
    `screening_match_depth` and `screening_risk_points` are re-derived under the
    `applied_screening_variant` already stored on it — the variant is not
    re-chosen."

    Design: Difficulty/transitive_cascade/parent_designation_change_cascades_through_ownership_to_grants
    """
    parent, _child, _project, subaward, _grant = _setup_transitively_screened_award()
    assert subaward["status"] == "CLEARED"
    assert subaward["applied_screening_variant"] == "OWNERSHIP_TRANSITIVE"
    assert subaward["screening_risk_points"] == 0

    validate_success(_designate_sdn(api, parent["id"]), expected_status=200)

    rescreened = read_subaward(subaward["id"])
    assert rescreened["status"] == "BLOCKED"
    assert rescreened["applied_screening_variant"] == "OWNERSHIP_TRANSITIVE"
    assert rescreened["screening_designation"] == "SDN"
    assert rescreened["screening_match_depth"] == 1
    assert rescreened["screening_matched_organization_id"] == parent["id"]
    # Base of 40 plus 10 multiplied by the SDN strictness rank of 5.
    assert rescreened["screening_risk_points"] == 90


def test_blocked_subaward_suspends_the_project_security_dimension(api):
    """PRD §3.1: "Because subawards became `BLOCKED`, each affected project whose
    `security_status` is `CLEARED` transitions to `SUSPENDED` with a
    `security_status_reason` of `SUBAWARD_BLOCKED`, and gains `SUBAWARD_BLOCKED`
    in its `activation_blockers`."

    Design: Difficulty/transitive_cascade/parent_designation_change_cascades_through_ownership_to_grants
    """
    parent, _child, project, _subaward, _grant = _setup_transitively_screened_award()
    assert project["security_status"] == "CLEARED"

    validate_success(_designate_sdn(api, parent["id"]), expected_status=200)

    after = read_project(project["id"])
    assert after["security_status"] == "SUSPENDED"
    assert after["security_status_reason"] == "SUBAWARD_BLOCKED"
    assert after["activation_blockers"] == [
        "SECURITY_NOT_CLEARED",
        "SUBAWARD_BLOCKED",
    ]


def test_project_suspension_hop_suspends_the_access_grant(api):
    """PRD §3.1: "Because those projects were suspended, their access grants in
    `REQUESTED` or `ACTIVE` transition to `SUSPENDED` with a `status_reason` of
    `PROJECT_SUSPENDED`, and each affected project's `active_grant_count` and
    `controlled_area_posture` are recomputed."

    Design: Difficulty/transitive_cascade/parent_designation_change_cascades_through_ownership_to_grants
    """
    parent, _child, project, _subaward, grant = _setup_transitively_screened_award()
    assert read_access_grant(grant["id"])["status"] == "ACTIVE"
    assert project["active_grant_count"] == 1

    validate_success(_designate_sdn(api, parent["id"]), expected_status=200)

    suspended_grant = read_access_grant(grant["id"])
    assert suspended_grant["status"] == "SUSPENDED"
    assert suspended_grant["status_reason"] == "PROJECT_SUSPENDED"

    after = read_project(project["id"])
    assert after["active_grant_count"] == 0
    assert after["controlled_area_posture"] == "LOCKED_DOWN"


def test_designation_write_increments_the_organization_version_by_one(api):
    """PRD §3.1: "Attaching or changing a designation supplies a new
    `own_designation`, its `designated_on` instant, and the
    `expected_organization_version` demanded by §2.7; on success the
    organization's `version` increments by one and its `effective_designation` is
    resolved again."

    Design: Difficulty/transitive_cascade/parent_designation_change_cascades_through_ownership_to_grants
    """
    parent, _child, _project, _subaward, _grant = _setup_transitively_screened_award()
    before = read_organization(parent["id"])

    response = api.designate_organization(
        parent["id"],
        {
            "own_designation": "SDN",
            "designated_on": DEFAULT_CLOCK,
            "expected_organization_version": before["version"],
        },
        RSO,
    )
    designated = validate_success(response, expected_status=200)
    assert designated["version"] == before["version"] + 1
    assert designated["own_designation"] == "SDN"
    assert designated["effective_designation"] == "SDN"
