"""Role authority, segregation of duties and stale-view protection.

Every test builds its own world from scratch: the server is restarted before each
test, so the database starts empty and the logical clock sits at its mandatory
startup default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    CRO,
    CRO_SECOND,
    DEFAULT_CLOCK,
    LIAISON,
    NON_EXISTENT_UUID,
    RSO,
    RSO_SECOND,
    ApiErrorId,
    add_disclosure_item,
    add_personnel,
    assert_version_advanced,
    assign_training,
    begin_review,
    build_user_headers,
    certify_disclosure,
    create_access_grant_payload,
    create_disclosure,
    create_disclosure_item_payload,
    create_disclosure_payload,
    create_foreign_organization_payload,
    create_incident,
    create_investigator,
    create_investigator_payload,
    create_organization,
    create_project,
    create_subaward_payload,
    create_training_assignment_payload,
    get_success_data,
    issue_plan_payload,
    make_investigator_headers,
    read_disclosure,
    read_disclosure_item,
    read_investigator,
    read_organization,
    read_project,
    require_plan,
    set_item_status,
    submit_disclosure,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Local setup helpers
# --------------------------------------------------------------------------- #


def _setup_role_gate_world() -> dict:
    """One record behind each exclusive write endpoint the sweep addresses."""
    investigator = create_investigator()
    project = create_project(title="Survey Methodology Core", agency_code="NSF")
    assignment = assign_training(
        investigator["id"],
        course_code="INSIDER_THREAT",
        due_on="2026-12-01T00:00:00Z",
    )
    incident = create_incident(investigator["id"], discovered_on="2026-07-15T00:00:00Z")
    disclosure = create_disclosure(investigator["id"])
    return {
        "investigator_id": investigator["id"],
        "project_id": project["id"],
        "assignment_id": assignment["id"],
        "incident_id": incident["id"],
        "disclosure_id": disclosure["id"],
    }


def _setup_shared_operation_world() -> dict:
    """An investigator holding one PROPOSED roster row of 3.00 person-months."""
    investigator = create_investigator(institutional_base_effort_pct=0)
    project = create_project(title="Vector Surveillance Network", agency_code="NIH")
    personnel = add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="CO_PI",
        committed_person_months=3.00,
        activate=False,
    )
    return {
        "investigator_id": investigator["id"],
        "project_id": project["id"],
        "personnel_id": personnel["id"],
    }


# --------------------------------------------------------------------------- #
# Exclusive operations are closed to every other role
# --------------------------------------------------------------------------- #

_EXCLUSIVE_OPERATION_CASES = [
    (
        "register_investigator_as_security_officer",
        lambda api, world: api.create_investigator(create_investigator_payload(), RSO),
    ),
    (
        "drive_award_status_as_security_officer",
        lambda api, world: api.set_award_status(
            world["project_id"], {"to_status": "ACTIVATION_PENDING"}, RSO
        ),
    ),
    (
        "request_area_access_as_conflict_review_official",
        lambda api, world: api.create_access_grant(
            create_access_grant_payload(
                world["project_id"],
                world["investigator_id"],
                read_project(world["project_id"])["version"],
            ),
            CRO,
        ),
    ),
    (
        "notify_the_sponsor_as_security_officer",
        lambda api, world: api.notify_incident(
            world["incident_id"],
            {
                "agency_notified_on": DEFAULT_CLOCK,
                "notification_reference": "AG-X",
            },
            RSO,
        ),
    ),
    (
        "submit_a_disclosure_as_security_officer",
        lambda api, world: api.submit_disclosure(world["disclosure_id"], RSO),
    ),
    (
        "waive_training_as_system_admin",
        lambda api, world: api.waive_training_assignment(world["assignment_id"], ADMIN),
    ),
    (
        "propose_a_subaward_as_agency_liaison",
        lambda api, world: api.create_subaward(
            create_subaward_payload(world["project_id"], NON_EXISTENT_UUID), LIAISON
        ),
    ),
    (
        "set_the_logical_clock_as_agency_liaison",
        lambda api, world: api.set_clock({"current_utc": "2026-09-01T00:00:00Z"}, LIAISON),
    ),
    (
        "read_an_investigator_under_an_undeclared_role",
        lambda api, world: api.get_investigator(
            world["investigator_id"], build_user_headers("auditor-1", "Auditor")
        ),
    ),
]


@pytest.mark.parametrize(
    "operation",
    [case[1] for case in _EXCLUSIVE_OPERATION_CASES],
    ids=[case[0] for case in _EXCLUSIVE_OPERATION_CASES],
)
def test_exclusive_operation_refused_to_an_unauthorised_role(api, operation):
    """PRD §2.1: "A request whose `X-User-Role` is not one of those five, or whose
    role is not among the roles authorised for the endpoint being called, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_attempted_by_the_wrong_role_returns_403_forbidden
    """
    world = _setup_role_gate_world()

    validate_error(
        operation(api, world), ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403
    )

    # Role admissibility is the second step of the evaluation order, so the
    # refused request left every addressed record exactly as it was: neither the
    # unknown organization_id of the subaward attempt nor the freshly read
    # expected_project_version of the grant attempt was ever reached.
    assert read_disclosure(world["disclosure_id"])["review_status"] == "DRAFT"
    project = read_project(world["project_id"])
    assert project["award_status"] == "PROPOSED"
    assignment = get_success_data(
        api.get_training_assignment(world["assignment_id"], RSO)
    )
    assert assignment["waived_on"] is None
    assert assignment["status"] == "ASSIGNED"


# --------------------------------------------------------------------------- #
# Shared operations accept either authorised role
# --------------------------------------------------------------------------- #


def _shared_register_organization_as_admin(api, world):
    response = api.create_foreign_organization(
        create_foreign_organization_payload(
            legal_name="Admin Filed Institute", country_code="BR", org_type="INSTITUTE"
        ),
        ADMIN,
    )
    organization = validate_success(response, expected_status=201)
    assert organization["legal_name"] == "Admin Filed Institute"


def _shared_register_organization_as_security_officer(api, world):
    response = api.create_foreign_organization(
        create_foreign_organization_payload(
            legal_name="Officer Filed Institute",
            country_code="BR",
            org_type="INSTITUTE",
        ),
        RSO,
    )
    organization = validate_success(response, expected_status=201)
    assert organization["legal_name"] == "Officer Filed Institute"


def _shared_assign_training_as_admin(api, world):
    response = api.create_training_assignment(
        create_training_assignment_payload(
            world["investigator_id"],
            course_code="RESEARCH_SECURITY_BASE",
            due_on="2026-12-01T00:00:00Z",
        ),
        ADMIN,
    )
    assignment = validate_success(response, expected_status=201)
    assert assignment["course_code"] == "RESEARCH_SECURITY_BASE"


def _shared_assign_training_as_security_officer(api, world):
    response = api.create_training_assignment(
        create_training_assignment_payload(
            world["investigator_id"],
            course_code="EXPORT_CONTROL",
            due_on="2026-12-01T00:00:00Z",
        ),
        RSO,
    )
    assignment = validate_success(response, expected_status=201)
    assert assignment["course_code"] == "EXPORT_CONTROL"


def _shared_activate_personnel_as_security_officer(api, world):
    response = api.set_personnel_status(
        world["personnel_id"], {"to_status": "ACTIVE"}, RSO
    )
    personnel = validate_success(response)
    assert personnel["status"] == "ACTIVE"
    # 3.00 person-months over 12 months is 25.00 percent of a full year.
    investigator = read_investigator(world["investigator_id"])
    assert investigator["committed_effort_pct"] == pytest.approx(25.00, abs=0.01)


def _shared_officer_opens_a_disclosure_for_the_researcher(api, world):
    current = read_investigator(world["investigator_id"])
    response = api.create_disclosure(
        create_disclosure_payload(world["investigator_id"], current["version"]), RSO
    )
    disclosure = validate_success(response, expected_status=201)
    assert disclosure["investigator_id"] == world["investigator_id"]
    assert disclosure["review_status"] == "DRAFT"
    assert disclosure["reviewer_user_id"] is None


def _shared_officer_files_a_disclosure_item(api, world):
    disclosure = create_disclosure(world["investigator_id"])
    organization = create_organization(
        legal_name="Officer Filed Institute", country_code="BR", org_type="INSTITUTE"
    )
    response = api.create_disclosure_item(
        disclosure["id"],
        create_disclosure_item_payload(
            organization["id"],
            item_type="VISITING_SCHOLAR",
            start_date="2026-05-01T00:00:00Z",
            annual_effort_hours=20,
            is_paid=False,
        ),
        RSO,
    )
    item = validate_success(response, expected_status=201)
    assert item["status"] == "DECLARED"
    # VISITING_SCHOLAR base 10 times the NONE exposure multiplier 1.0, unpaid.
    assert item["item_risk_points"] == 10
    # A DECLARED item is outside the VERIFIED scoring set, so the score stays 0.
    assert read_investigator(world["investigator_id"])["risk_score"] == 0


def _shared_researcher_withdraws_the_officer_filed_item(api, world):
    disclosure = create_disclosure(world["investigator_id"])
    organization = create_organization(
        legal_name="Officer Filed Institute", country_code="BR", org_type="INSTITUTE"
    )
    item = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        headers=RSO,
        item_type="VISITING_SCHOLAR",
        start_date="2026-05-01T00:00:00Z",
        annual_effort_hours=20,
    )
    response = api.set_disclosure_item_status(
        item["id"],
        {"to_status": "WITHDRAWN"},
        make_investigator_headers(world["investigator_id"]),
    )
    withdrawn = validate_success(response)
    assert withdrawn["status"] == "WITHDRAWN"
    assert read_disclosure(disclosure["id"])["item_count"] == 0


_SHARED_OPERATION_CASES = [
    ("register_an_organization_as_system_admin", _shared_register_organization_as_admin),
    (
        "register_an_organization_as_security_officer",
        _shared_register_organization_as_security_officer,
    ),
    ("assign_a_course_as_system_admin", _shared_assign_training_as_admin),
    ("assign_a_course_as_security_officer", _shared_assign_training_as_security_officer),
    (
        "activate_a_roster_row_as_security_officer",
        _shared_activate_personnel_as_security_officer,
    ),
    (
        "open_a_disclosure_for_another_investigator_as_security_officer",
        _shared_officer_opens_a_disclosure_for_the_researcher,
    ),
    ("file_a_disclosure_item_as_security_officer", _shared_officer_files_a_disclosure_item),
    (
        "withdraw_an_own_declared_item_as_the_researcher",
        _shared_researcher_withdraws_the_officer_filed_item,
    ),
]


@pytest.mark.parametrize(
    "operation",
    [case[1] for case in _SHARED_OPERATION_CASES],
    ids=[case[0] for case in _SHARED_OPERATION_CASES],
)
def test_shared_operation_accepted_from_either_authorised_role(api, operation):
    """PRD §2.1: "Every read endpoint in the system is available to all five
    roles; write authority is role-scoped, as summarised in §4."

    Design: Corner/rbac/shared_operations_accept_either_authorized_role
    """
    world = _setup_shared_operation_world()
    operation(api, world)


# --------------------------------------------------------------------------- #
# Segregation of duties binds the user, not the role
# --------------------------------------------------------------------------- #


def test_segregation_of_duties_bars_the_reviewing_user_not_their_role(api):
    """PRD §2.1: "`ERR_SEGREGATION_OF_DUTIES` guards the two separations of duty
    the office is built around: the user issuing or waiving a management plan
    must not be the disclosure's stored `reviewer_user_id`, and the user
    recording a sponsor notification must not be the incident's stored
    `lead_investigator_user_id`."

    Design: Corner/rbac/segregation_of_duties_binds_the_user_not_the_role
    """
    investigator = create_investigator(institutional_base_effort_pct=90)
    organization = create_organization(
        legal_name="Global Scholars Programme",
        country_code="CN",
        org_type="TALENT_PROGRAM",
    )
    disclosure = create_disclosure(investigator["id"])
    item = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="TALENT_PROGRAM",
        start_date="2026-03-01T00:00:00Z",
        annual_effort_hours=60,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    # cro-1 takes the review, so cro-1 becomes the stored reviewer_user_id.
    reviewed = begin_review(disclosure["id"], headers=CRO)
    assert reviewed["reviewer_user_id"] == "cro-1"
    set_item_status(item["id"], "VERIFIED", headers=CRO)
    assert read_investigator(investigator["id"])["risk_score"] == 30
    require_plan(disclosure["id"], headers=CRO)
    assert read_disclosure(disclosure["id"])["plan_status"] == "PLAN_REQUIRED"

    plan_payload = issue_plan_payload(
        plan_effort_cap_pct=95,
        plan_required_actions=["REDUCE_OUTSIDE_EFFORT", "QUARTERLY_ATTESTATION"],
        plan_effective_from="2026-09-01T00:00:00Z",
        plan_expires_on="2027-08-31T00:00:00Z",
    )

    # The reviewing user may not write the plan that manages the disclosure.
    validate_error(
        api.plan_disclosure(disclosure["id"], plan_payload, CRO),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )

    # A second official in the very same role may, because the bar is on the user.
    issued = validate_success(
        api.plan_disclosure(disclosure["id"], plan_payload, CRO_SECOND)
    )
    assert issued["plan_status"] == "PLAN_ISSUED"
    assert issued["plan_approver_user_id"] == "cro-2"
    assert issued["reviewer_user_id"] == "cro-1"

    acknowledged = validate_success(
        api.plan_disclosure(
            disclosure["id"],
            {"action": "ACKNOWLEDGE"},
            make_investigator_headers(investigator["id"]),
        )
    )
    assert acknowledged["plan_status"] == "PLAN_ACKNOWLEDGED"
    assert acknowledged["plan_acknowledged_at"] is not None
    with_credit = read_investigator(investigator["id"])
    assert with_credit["risk_score"] == 10
    assert with_credit["disclosure_posture"] == "CLEAR"

    # TERMINATE declares no segregation precondition at all, so the reviewing
    # user may end the plan they were barred from issuing.
    terminated = validate_success(
        api.plan_disclosure(disclosure["id"], {"action": "TERMINATE"}, CRO)
    )
    assert terminated["plan_status"] == "PLAN_TERMINATED"
    without_credit = read_investigator(investigator["id"])
    assert without_credit["risk_score"] == 30
    assert without_credit["disclosure_posture"] == "REVIEW_REQUIRED"

    # PLAN_TERMINATED is not a resolved plan state, so termination is no escape.
    validate_error(
        api.review_disclosure(disclosure["id"], {"action": "CERTIFY"}, CRO),
        ApiErrorId.ERR_PLAN_NOT_RESOLVED.value,
        expected_status=409,
    )


# --------------------------------------------------------------------------- #
# Stale-view protection on parent-scoped writes
# --------------------------------------------------------------------------- #


def test_disclosure_create_against_a_stale_investigator_version_is_refused(api):
    """PRD §2.7: "`POST /disclosures` requires `expected_investigator_version`,
    carrying the client's last observed `version` of the target `Investigator`. A
    new disclosure for the same reporting cycle legitimately supersedes its
    predecessor, so no state precondition can catch a client that is working from
    a stale view: the request would succeed while discarding a disclosure the
    client never saw. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/disclosure_create_with_a_stale_investigator_version_returns_412
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    stale = read_investigator(investigator["id"])
    project = create_project(title="Organoid Imaging", agency_code="NIH")

    # The activation recomputes committed_effort_pct, which is a mutation of the
    # investigator record and therefore advances the version the client holds.
    add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=3.00,
    )
    moved = read_investigator(investigator["id"])
    assert moved["committed_effort_pct"] == pytest.approx(25.00, abs=0.01)
    assert_version_advanced(stale, moved, "investigator")

    validate_error(
        api.create_disclosure(
            create_disclosure_payload(investigator["id"], stale["version"]),
            make_investigator_headers(investigator["id"]),
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )
    _rows, meta = validate_paginated(
        api.list_disclosures(RSO, {"investigator_id": investigator["id"]})
    )
    assert meta["total_count"] == 0

    # Re-reading the parent makes the identical payload succeed.
    fresh = read_investigator(investigator["id"])
    disclosure = validate_success(
        api.create_disclosure(
            create_disclosure_payload(investigator["id"], fresh["version"]),
            make_investigator_headers(investigator["id"]),
        ),
        expected_status=201,
    )
    assert disclosure["review_status"] == "DRAFT"
    assert disclosure["plan_status"] == "NOT_REQUIRED"

    after = read_investigator(investigator["id"])
    assert after["version"] == fresh["version"] + 1
    assert after["committed_effort_pct"] == pytest.approx(25.00, abs=0.01)


def test_designation_write_against_a_stale_organization_version_is_refused(api):
    """PRD §2.7: "`POST /foreign-organizations/{organization_id}/designate`
    requires `expected_organization_version`, carrying the client's last observed
    `version` of the target `ForeignOrganization`. A designation write is an
    unconditional overwrite of `own_designation`, so a stale writer would clobber
    a designation change it never observed together with the entire subaward and
    project cascade that change produced. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/designation_write_with_a_stale_organization_version_returns_412
    """
    organization = create_organization(
        legal_name="Alpha Instruments", country_code="SG", org_type="COMPANY"
    )
    parent = create_organization(
        legal_name="Beta Holdings", country_code="SG", org_type="COMPANY"
    )
    stale = read_organization(organization["id"])

    # An ownership write on the same row carries no version field of its own, yet
    # it advances the organization's version.
    validate_success(
        api.set_organization_ownership(
            organization["id"],
            {"parent_organization_id": parent["id"], "parent_ownership_pct": 60.00},
            RSO,
        )
    )
    assert_version_advanced(
        stale, read_organization(organization["id"]), "organization"
    )

    designate_payload = {
        "own_designation": "SDN",
        "designated_on": DEFAULT_CLOCK,
        "expected_organization_version": stale["version"],
    }
    validate_error(
        api.designate_organization(organization["id"], designate_payload, RSO_SECOND),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )
    unchanged = read_organization(organization["id"])
    assert unchanged["own_designation"] == "NONE"
    assert unchanged["parent_organization_id"] == parent["id"]

    designated = validate_success(
        api.designate_organization(
            organization["id"],
            dict(designate_payload, expected_organization_version=unchanged["version"]),
            RSO_SECOND,
        )
    )
    assert designated["own_designation"] == "SDN"
    assert designated["effective_designation"] == "SDN"
    assert designated["effective_designation_depth"] == 0
    assert designated["version"] == unchanged["version"] + 1
    # The retry did not clobber the ownership edit it never observed.
    assert designated["parent_organization_id"] == parent["id"]
    assert designated["parent_ownership_pct"] == pytest.approx(60.00, abs=0.01)


# --------------------------------------------------------------------------- #
# Derived-field reconciliation after a contributing row leaves
# --------------------------------------------------------------------------- #


def test_risk_score_reconciles_after_the_talent_program_item_is_withdrawn(api):
    """PRD §3.3: "The owning `Investigator` may withdraw their own declared item
    (`DECLARED → WITHDRAWN`) only while the parent disclosure's review status is
    `DRAFT` or `RETURNED_FOR_REVISION`, and only if `X-User-ID` matches the owning
    investigator, else `ERR_NOT_RESOURCE_OWNER`; withdrawal recomputes the
    parent's `completeness_score` and then the investigator's `risk_score` and
    `disclosure_posture`."

    Design: Corner/cross_cutting_complexity_layers/risk_score_reconciles_after_the_source_item_is_withdrawn
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    organization = create_organization(
        legal_name="Tianjin Analysis Centre", country_code="CN", org_type="INSTITUTE"
    )
    disclosure = create_disclosure(investigator["id"])
    appointment = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="FOREIGN_APPOINTMENT",
        start_date="2026-01-01T00:00:00Z",
        annual_effort_hours=40,
        is_paid=False,
    )
    talent = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="TALENT_PROGRAM",
        start_date="2026-02-01T00:00:00Z",
        annual_effort_hours=80,
        is_paid=False,
    )
    # Unpaid items on a NONE counterparty carry their base weight unchanged.
    assert appointment["item_risk_points"] == 12
    assert talent["item_risk_points"] == 30

    before = read_investigator(investigator["id"])
    # Both items are DECLARED, so neither is in the VERIFIED scoring set yet.
    assert before["risk_score"] == 0
    assert before["outside_effort_pct"] == pytest.approx(0.00, abs=0.01)
    assert before["disclosure_posture"] == "CLEAR"
    assert read_disclosure(disclosure["id"])["item_count"] == 2

    withdrawn = validate_success(
        api.set_disclosure_item_status(
            talent["id"],
            {"to_status": "WITHDRAWN"},
            make_investigator_headers(investigator["id"]),
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    after_withdrawal = read_disclosure(disclosure["id"])
    assert after_withdrawal["item_count"] == 1
    assert after_withdrawal["completeness_score"] == 100
    assert after_withdrawal["completeness_tier"] == "A"
    surviving = read_disclosure_item(appointment["id"])
    assert surviving["status"] == "DECLARED"
    assert surviving["item_risk_points"] == 12
    reconciled = read_investigator(investigator["id"])
    assert reconciled["risk_score"] == 0
    assert reconciled["disclosure_posture"] == "CLEAR"

    # Certification moves every item still in DECLARED to VERIFIED, so only the
    # surviving relationship enters the score -- the withdrawn one leaves no
    # high-water mark of 42.
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    certify_disclosure(disclosure["id"])

    final = read_investigator(investigator["id"])
    assert final["risk_score"] == 12
    assert final["outside_effort_pct"] == pytest.approx(1.92, abs=0.01)
    assert final["total_commitment_pct"] == pytest.approx(1.92, abs=0.01)
    assert final["disclosure_posture"] == "CLEAR"
    assert read_disclosure_item(appointment["id"])["status"] == "VERIFIED"
    assert read_disclosure_item(talent["id"])["status"] == "WITHDRAWN"
