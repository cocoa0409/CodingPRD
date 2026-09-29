"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database. Helpers use the lenient
``get_success_data`` validator so a broken precondition surfaces as a clear setup
failure rather than a confusing assertion inside the test body.

Three creates carry a parent version guard (``POST /disclosures``,
``POST /controlled-access-grants`` and the designate endpoint). The helpers below
always read the parent immediately before those writes, because a recomputation of
a derived field is itself a mutation and advances the parent's version between its
creation and the guarded write.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_access_grant_payload,
    create_disclosure_item_payload,
    create_disclosure_payload,
    create_foreign_organization_payload,
    create_investigator_payload,
    create_personnel_payload,
    create_project_payload,
    create_security_incident_payload,
    create_subaward_payload,
    create_support_statement_payload,
    create_training_assignment_payload,
    create_travel_registration_payload,
    issue_plan_payload,
)
from .test_users import TEST_USERS, make_investigator_headers

ADMIN = TEST_USERS["system_admin_headers"]
RSO = TEST_USERS["rso_headers"]
RSO_SECOND = TEST_USERS["rso_second_headers"]
CRO = TEST_USERS["cro_headers"]
CRO_SECOND = TEST_USERS["cro_second_headers"]
LIAISON = TEST_USERS["liaison_headers"]


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #

def set_clock(current_utc: str = DEFAULT_CLOCK) -> dict:
    """Pin the logical clock. Before any client sets it the clock reads DEFAULT_CLOCK."""
    return get_success_data(
        api_client.set_clock({"current_utc": current_utc}, ADMIN)
    )


# --------------------------------------------------------------------------- #
# Tier 1 -- single-entity creates and simple state progressions
# --------------------------------------------------------------------------- #

def create_investigator(**overrides) -> dict:
    """Register one investigator. Pass institutional_base_effort_pct=0 to isolate
    committed and outside effort in commitment arithmetic."""
    return get_success_data(
        api_client.create_investigator(create_investigator_payload(**overrides), ADMIN)
    )


def read_investigator(investigator_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_investigator(investigator_id, headers or ADMIN)
    )


def create_organization(**overrides) -> dict:
    return get_success_data(
        api_client.create_foreign_organization(
            create_foreign_organization_payload(**overrides), RSO
        )
    )


def read_organization(organization_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_foreign_organization(organization_id, headers or RSO)
    )


def designate_organization(
    organization_id: str,
    own_designation: str,
    designated_on: str = DEFAULT_CLOCK,
    headers=None,
) -> dict:
    """Designate an organization, reading its current version immediately first."""
    current = read_organization(organization_id)
    return get_success_data(
        api_client.designate_organization(
            organization_id,
            {
                "own_designation": own_designation,
                "designated_on": designated_on,
                "expected_organization_version": current["version"],
            },
            headers or RSO,
        )
    )


def create_project(**overrides) -> dict:
    return get_success_data(
        api_client.create_project(create_project_payload(**overrides), ADMIN)
    )


def read_project(project_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_project(project_id, headers or RSO))


def add_personnel(
    project_id: str,
    investigator_id: str,
    role_on_project: str = "PI",
    committed_person_months: float = 1.00,
    activate: bool = True,
) -> dict:
    """Create a personnel row and, by default, walk it to ACTIVE."""
    personnel = get_success_data(
        api_client.create_personnel(
            project_id,
            create_personnel_payload(
                investigator_id,
                role_on_project=role_on_project,
                committed_person_months=committed_person_months,
            ),
            ADMIN,
        )
    )
    if activate:
        personnel = get_success_data(
            api_client.set_personnel_status(
                personnel["id"], {"to_status": "ACTIVE"}, ADMIN
            )
        )
    return personnel


def remove_personnel(personnel_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_personnel_status(
            personnel_id, {"to_status": "REMOVED"}, headers or ADMIN
        )
    )


def create_disclosure(investigator_id: str, headers=None, **overrides) -> dict:
    """Open a disclosure, reading the investigator's current version immediately first."""
    current = read_investigator(investigator_id)
    payload = create_disclosure_payload(
        investigator_id, current["version"], **overrides
    )
    return get_success_data(
        api_client.create_disclosure(
            payload, headers or make_investigator_headers(investigator_id)
        )
    )


def read_disclosure(disclosure_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_disclosure(disclosure_id, headers or RSO))


def add_disclosure_item(
    disclosure_id: str,
    foreign_organization_id: str,
    investigator_id: str = None,
    headers=None,
    **overrides,
) -> dict:
    """Add one item to a disclosure. Defaults to the owning investigator as caller."""
    if headers is None:
        assert investigator_id is not None, (
            "pass investigator_id or explicit headers for item creation"
        )
        headers = make_investigator_headers(investigator_id)
    return get_success_data(
        api_client.create_disclosure_item(
            disclosure_id,
            create_disclosure_item_payload(foreign_organization_id, **overrides),
            headers,
        )
    )


def read_disclosure_item(item_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_disclosure_item(item_id, headers or RSO))


def set_item_status(item_id: str, to_status: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_disclosure_item_status(
            item_id, {"to_status": to_status}, headers or RSO
        )
    )


def submit_disclosure(disclosure_id: str, investigator_id: str) -> dict:
    return get_success_data(
        api_client.submit_disclosure(
            disclosure_id, make_investigator_headers(investigator_id)
        )
    )


def begin_review(disclosure_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.review_disclosure(
            disclosure_id, {"action": "BEGIN_REVIEW"}, headers or RSO
        )
    )


def certify_disclosure(disclosure_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.review_disclosure(
            disclosure_id, {"action": "CERTIFY"}, headers or RSO
        )
    )


def return_for_revision(disclosure_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.review_disclosure(
            disclosure_id, {"action": "RETURN_FOR_REVISION"}, headers or RSO
        )
    )


def require_plan(disclosure_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.review_disclosure(
            disclosure_id, {"action": "REQUIRE_PLAN"}, headers or RSO
        )
    )


def issue_plan(disclosure_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.plan_disclosure(
            disclosure_id, issue_plan_payload(**overrides), headers or CRO
        )
    )


def acknowledge_plan(disclosure_id: str, investigator_id: str) -> dict:
    return get_success_data(
        api_client.plan_disclosure(
            disclosure_id,
            {"action": "ACKNOWLEDGE"},
            make_investigator_headers(investigator_id),
        )
    )


def assign_training(
    investigator_id: str,
    course_code: str = "RESEARCH_SECURITY_BASE",
    due_on: str = "2026-12-31T00:00:00Z",
    required_for_project_id: str = None,
    headers=None,
) -> dict:
    overrides = {"course_code": course_code, "due_on": due_on}
    if required_for_project_id is not None:
        overrides["required_for_project_id"] = required_for_project_id
    return get_success_data(
        api_client.create_training_assignment(
            create_training_assignment_payload(investigator_id, **overrides),
            headers or RSO,
        )
    )


def complete_training(assignment_id: str, investigator_id: str) -> dict:
    return get_success_data(
        api_client.complete_training_assignment(
            assignment_id, make_investigator_headers(investigator_id)
        )
    )


def assign_and_complete_training(
    investigator_id: str,
    course_code: str = "CONTROLLED_AREA_SAFETY",
    due_on: str = "2026-12-31T00:00:00Z",
    required_for_project_id: str = None,
) -> dict:
    """Assign a course and immediately record its completion."""
    assignment = assign_training(
        investigator_id,
        course_code=course_code,
        due_on=due_on,
        required_for_project_id=required_for_project_id,
    )
    return complete_training(assignment["id"], investigator_id)


def clear_project_security(project_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_security_status(
            project_id, {"to_status": "CLEARED"}, headers or RSO
        )
    )


def suspend_project_security(project_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_security_status(
            project_id, {"to_status": "SUSPENDED"}, headers or RSO
        )
    )


def set_award_status(project_id: str, to_status: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_award_status(
            project_id, {"to_status": to_status}, headers or ADMIN
        )
    )


def create_access_grant(
    project_id: str,
    investigator_id: str,
    valid_from: str = "2026-09-01T00:00:00Z",
    valid_until: str = "2026-12-01T00:00:00Z",
    headers=None,
    **overrides,
) -> dict:
    """Request an access grant, reading the project's current version immediately first."""
    current = read_project(project_id)
    payload = create_access_grant_payload(
        project_id,
        investigator_id,
        current["version"],
        valid_from=valid_from,
        valid_until=valid_until,
        **overrides,
    )
    return get_success_data(api_client.create_access_grant(payload, headers or RSO))


def read_access_grant(grant_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_access_grant(grant_id, headers or RSO))


def set_grant_status(grant_id: str, to_status: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_access_grant_status(
            grant_id, {"to_status": to_status}, headers or RSO
        )
    )


def create_subaward(project_id: str, organization_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_subaward(
            create_subaward_payload(project_id, organization_id, **overrides), RSO
        )
    )


def read_subaward(subaward_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_subaward(subaward_id, headers or RSO))


def screen_subaward(subaward_id: str, variant: str, headers=None) -> dict:
    return get_success_data(
        api_client.screen_subaward(subaward_id, {"variant": variant}, headers or RSO)
    )


def create_travel(investigator_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_travel_registration(
            create_travel_registration_payload(investigator_id, **overrides),
            headers or make_investigator_headers(investigator_id),
        )
    )


def read_travel(registration_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_travel_registration(registration_id, headers or RSO)
    )


def set_travel_status(registration_id: str, to_status: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_travel_status(
            registration_id, {"to_status": to_status}, headers or RSO
        )
    )


def submit_travel(registration_id: str, investigator_id: str) -> dict:
    return get_success_data(
        api_client.set_travel_status(
            registration_id,
            {"to_status": "SUBMITTED"},
            make_investigator_headers(investigator_id),
        )
    )


def create_incident(investigator_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_security_incident(
            create_security_incident_payload(investigator_id, **overrides), RSO
        )
    )


def read_incident(incident_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_security_incident(incident_id, headers or RSO)
    )


def investigate_incident(
    incident_id: str, lead_investigator_user_id: str = "rso-1", headers=None
) -> dict:
    return get_success_data(
        api_client.set_incident_status(
            incident_id,
            {
                "to_status": "INVESTIGATING",
                "lead_investigator_user_id": lead_investigator_user_id,
            },
            headers or RSO,
        )
    )


def substantiate_incident(incident_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_incident_status(
            incident_id, {"to_status": "SUBSTANTIATED"}, headers or RSO
        )
    )


def notify_incident(
    incident_id: str,
    agency_notified_on: str = DEFAULT_CLOCK,
    notification_reference: str = "AGENCY-OIG-2026-0001",
    headers=None,
) -> dict:
    return get_success_data(
        api_client.notify_incident(
            incident_id,
            {
                "agency_notified_on": agency_notified_on,
                "notification_reference": notification_reference,
            },
            headers or LIAISON,
        )
    )


def create_support_statement(
    investigator_id: str, project_id: str, headers=None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_support_statement(
            create_support_statement_payload(investigator_id, project_id, **overrides),
            headers or RSO,
        )
    )


def read_support_statement(statement_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_support_statement(statement_id, headers or RSO)
    )


def reconcile_support_statement(statement_id: str, variant: str, headers=None) -> dict:
    return get_success_data(
        api_client.reconcile_support_statement(
            statement_id, {"variant": variant}, headers or RSO
        )
    )


# --------------------------------------------------------------------------- #
# Tier 2 -- entity hierarchies
# --------------------------------------------------------------------------- #

def setup_owned_organization_pair(
    parent_designation: str = "SDN",
    child_designation: str = "NONE",
    ownership_pct: float = 60.00,
    parent_designated_on: str = "2025-06-15T00:00:00Z",
    parent_overrides: dict = None,
    child_overrides: dict = None,
) -> tuple:
    """A parent organization and a child held at ownership_pct by it.

    Returns (parent, child). The child is created after the parent so the ownership
    edge exists from the moment the child is stored.
    """
    parent_payload = {
        "legal_name": "Meridian Holdings Group",
        "country_code": "CN",
        "org_type": "COMPANY",
        "own_designation": parent_designation,
    }
    if parent_designation != "NONE":
        parent_payload["designated_on"] = parent_designated_on
    parent_payload.update(parent_overrides or {})
    parent = create_organization(**parent_payload)

    child_payload = {
        "legal_name": "Meridian Applied Optics",
        "country_code": "CN",
        "org_type": "INSTITUTE",
        "own_designation": child_designation,
        "parent_organization_id": parent["id"],
        "parent_ownership_pct": ownership_pct,
    }
    child_payload.update(child_overrides or {})
    child = create_organization(**child_payload)
    return parent, child


def setup_ownership_chain(
    hops: int,
    top_designation: str = "SDN",
    ownership_pct: float = 100.00,
) -> list:
    """A straight chain of organizations: index 0 is the top (designated) node and
    each later element is held at ownership_pct by its predecessor.

    Returns the list of organizations, top first.
    """
    top_payload = {
        "legal_name": "Chain Root Holdings",
        "country_code": "RU",
        "org_type": "GOVERNMENT_AGENCY",
        "own_designation": top_designation,
    }
    if top_designation != "NONE":
        top_payload["designated_on"] = "2025-01-01T00:00:00Z"
    chain = [create_organization(**top_payload)]
    for depth in range(1, hops + 1):
        chain.append(
            create_organization(
                legal_name=f"Chain Node {depth}",
                country_code="RU",
                org_type="COMPANY",
                own_designation="NONE",
                parent_organization_id=chain[-1]["id"],
                parent_ownership_pct=ownership_pct,
            )
        )
    return chain


def setup_project_with_active_pi(
    investigator_overrides: dict = None,
    committed_person_months: float = 1.00,
    **project_overrides,
) -> tuple:
    """Project plus one investigator holding an ACTIVE PI row.

    Returns (project, investigator, personnel).
    """
    investigator = create_investigator(**(investigator_overrides or {}))
    project = create_project(**project_overrides)
    personnel = add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=committed_person_months,
    )
    return project, investigator, personnel


# --------------------------------------------------------------------------- #
# Tier 3 -- full lifecycle shortcuts
# --------------------------------------------------------------------------- #

def create_certified_disclosure(investigator_id: str, **overrides) -> dict:
    """Open, submit, take under review and certify an item-free disclosure."""
    disclosure = create_disclosure(investigator_id, **overrides)
    submit_disclosure(disclosure["id"], investigator_id)
    begin_review(disclosure["id"])
    return certify_disclosure(disclosure["id"])


def setup_certified_investigator(
    institutional_base_effort_pct: int = 0, **investigator_overrides
) -> tuple:
    """An investigator whose item-free disclosure is already CERTIFIED.

    Returns (investigator, disclosure).
    """
    investigator = create_investigator(
        institutional_base_effort_pct=institutional_base_effort_pct,
        **investigator_overrides,
    )
    disclosure = create_certified_disclosure(investigator["id"])
    return investigator, disclosure


def setup_disclosure_under_review(
    investigator_id: str, items: list = None, organization_id: str = None
) -> tuple:
    """Open a disclosure, attach the given items, submit it and take it under review.

    ``items`` is a list of payload override dicts for POST of each item; each may
    carry its own ``foreign_organization_id``, otherwise ``organization_id`` is used.

    Returns (disclosure, created_items).
    """
    disclosure = create_disclosure(investigator_id)
    created = []
    for spec in items or []:
        spec = dict(spec)
        org_id = spec.pop("foreign_organization_id", organization_id)
        assert org_id is not None, "each item needs a foreign organization"
        created.append(
            add_disclosure_item(
                disclosure["id"], org_id, investigator_id=investigator_id, **spec
            )
        )
    submit_disclosure(disclosure["id"], investigator_id)
    begin_review(disclosure["id"])
    return read_disclosure(disclosure["id"]), created


def setup_investigator_with_verified_items(
    items: list,
    organization_overrides: dict = None,
    institutional_base_effort_pct: int = 0,
    certify: bool = False,
) -> tuple:
    """An investigator whose disclosure carries VERIFIED items.

    ``items`` is a list of payload override dicts. Each item is created, the
    disclosure is submitted, taken under review and every item is moved to
    VERIFIED so it counts toward risk score and outside effort.

    Returns (investigator, organization, disclosure, verified_items).
    """
    investigator = create_investigator(
        institutional_base_effort_pct=institutional_base_effort_pct
    )
    organization = create_organization(**(organization_overrides or {}))
    disclosure, created = setup_disclosure_under_review(
        investigator["id"], items=items, organization_id=organization["id"]
    )
    verified = [set_item_status(item["id"], "VERIFIED") for item in created]
    if certify:
        certify_disclosure(disclosure["id"])
    return (
        read_investigator(investigator["id"]),
        organization,
        read_disclosure(disclosure["id"]),
        verified,
    )


def setup_area_access_ready(
    controlled_area_capacity: int = 1,
    sensitivity_level: str = "CONTROLLED",
    investigator_count: int = 1,
    committed_person_months: float = 1.00,
    clear_security: bool = True,
    **project_overrides,
) -> tuple:
    """Everything an access grant needs before activation: a security-CLEARED
    project, ACTIVE personnel rows and a COMPLETED controlled-area course for
    each investigator.

    Returns (project, investigators, personnel_rows).
    """
    project = create_project(
        sensitivity_level=sensitivity_level,
        controlled_area_capacity=controlled_area_capacity,
        **project_overrides,
    )
    investigators, personnel_rows = [], []
    for index in range(investigator_count):
        investigator = create_investigator(institutional_base_effort_pct=0)
        investigators.append(investigator)
        personnel_rows.append(
            add_personnel(
                project["id"],
                investigator["id"],
                role_on_project="PI" if index == 0 else "KEY_PERSON",
                committed_person_months=committed_person_months,
            )
        )
        assign_and_complete_training(
            investigator["id"], course_code="CONTROLLED_AREA_SAFETY"
        )
    if clear_security:
        clear_project_security(project["id"])
    return read_project(project["id"]), investigators, personnel_rows


def setup_active_access_grant(
    controlled_area_capacity: int = 1,
    valid_from: str = "2026-09-01T00:00:00Z",
    valid_until: str = "2026-12-01T00:00:00Z",
    **project_overrides,
) -> tuple:
    """One ACTIVE controlled-access grant on a CLEARED project.

    Returns (project, investigator, grant).
    """
    project, investigators, _ = setup_area_access_ready(
        controlled_area_capacity=controlled_area_capacity, **project_overrides
    )
    investigator = investigators[0]
    grant = create_access_grant(
        project["id"],
        investigator["id"],
        valid_from=valid_from,
        valid_until=valid_until,
    )
    grant = set_grant_status(grant["id"], "ACTIVE")
    return read_project(project["id"]), investigator, grant


def setup_active_award(
    investigator_overrides: dict = None,
    training_course: str = "CONTROLLED_AREA_SAFETY",
    committed_person_months: float = 1.00,
    **project_overrides,
) -> tuple:
    """A project driven all the way to award_status ACTIVE: certified disclosure,
    completed course, ACTIVE PI and security CLEARED.

    Returns (project, investigator, disclosure).
    """
    investigator, disclosure = setup_certified_investigator(
        **(investigator_overrides or {})
    )
    project = create_project(**project_overrides)
    add_personnel(
        project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=committed_person_months,
    )
    assign_and_complete_training(investigator["id"], course_code=training_course)
    clear_project_security(project["id"])
    set_award_status(project["id"], "ACTIVATION_PENDING")
    set_award_status(project["id"], "ACTIVE")
    return read_project(project["id"]), investigator, disclosure


# --------------------------------------------------------------------------- #
# Tier 4 -- accumulation and threshold targeting
# --------------------------------------------------------------------------- #

def setup_committed_effort(
    project_count: int,
    committed_person_months: float = 1.00,
    institutional_base_effort_pct: int = 0,
) -> tuple:
    """One investigator holding ACTIVE personnel rows on ``project_count`` projects,
    each at the same committed_person_months. Used to target an exact
    committed_effort_pct, which is rounded per row before the rows are summed.

    Returns (investigator, projects, personnel_rows).
    """
    investigator = create_investigator(
        institutional_base_effort_pct=institutional_base_effort_pct
    )
    projects, rows = [], []
    for index in range(project_count):
        project = create_project(title=f"Commitment Project {index + 1}")
        projects.append(project)
        rows.append(
            add_personnel(
                project["id"],
                investigator["id"],
                role_on_project="PI" if index == 0 else "CO_PI",
                committed_person_months=committed_person_months,
            )
        )
    return read_investigator(investigator["id"]), projects, rows


def setup_outside_effort(
    item_count: int,
    annual_effort_hours: float = 100,
    item_type: str = "OUTSIDE_SUPPORT",
    institutional_base_effort_pct: int = 0,
) -> tuple:
    """One investigator with ``item_count`` VERIFIED items of equal effort hours.
    Used to target an exact outside_effort_pct, which is rounded per item before
    the items are summed.

    Returns (investigator, organization, disclosure, items).
    """
    items = [
        {"item_type": item_type, "annual_effort_hours": annual_effort_hours}
        for _ in range(item_count)
    ]
    return setup_investigator_with_verified_items(
        items,
        organization_overrides={"own_designation": "NONE"},
        institutional_base_effort_pct=institutional_base_effort_pct,
    )


def setup_disclosure_at_revision_round(
    investigator_id: str, rounds: int, items: list = None, organization_id: str = None
) -> dict:
    """Cycle a disclosure through ``rounds`` return-and-resubmit loops so its
    revision_round reaches exactly ``rounds``. Leaves the disclosure UNDER_REVIEW.
    """
    disclosure, _ = setup_disclosure_under_review(
        investigator_id, items=items, organization_id=organization_id
    )
    for _ in range(rounds):
        return_for_revision(disclosure["id"])
        submit_disclosure(disclosure["id"], investigator_id)
        begin_review(disclosure["id"])
    return read_disclosure(disclosure["id"])


def setup_restricted_investigator() -> tuple:
    """An investigator whose posture is RESTRICTED: one paid talent-program item on
    an SDN organization, verified so it scores.

    Returns (investigator, organization, disclosure, item).
    """
    investigator, organization, disclosure, verified = (
        setup_investigator_with_verified_items(
            [
                {
                    "item_type": "TALENT_PROGRAM",
                    "annual_effort_hours": 0,
                    "is_paid": True,
                }
            ],
            organization_overrides={
                "legal_name": "Crest Talent Institute",
                "org_type": "TALENT_PROGRAM",
                "own_designation": "SDN",
                "designated_on": "2025-02-01T00:00:00Z",
            },
        )
    )
    return investigator, organization, disclosure, verified[0]


def setup_substantiated_incident(
    incident_type: str = "UNDISCLOSED_APPOINTMENT",
    project_id: str = None,
    disclosure_id: str = None,
    investigator_id: str = None,
    discovered_on: str = "2026-07-20T00:00:00Z",
    lead_investigator_user_id: str = "rso-1",
) -> tuple:
    """An incident walked REPORTED -> INVESTIGATING -> SUBSTANTIATED so its severity
    and notification deadline are frozen.

    Returns (investigator_id, incident).
    """
    if investigator_id is None:
        investigator_id = create_investigator(institutional_base_effort_pct=0)["id"]
    overrides = {"incident_type": incident_type, "discovered_on": discovered_on}
    if project_id is not None:
        overrides["project_id"] = project_id
    if disclosure_id is not None:
        overrides["disclosure_id"] = disclosure_id
    incident = create_incident(investigator_id, **overrides)
    investigate_incident(
        incident["id"], lead_investigator_user_id=lead_investigator_user_id
    )
    incident = substantiate_incident(incident["id"])
    return investigator_id, incident


def setup_screened_subaward(
    variant: str = "DIRECT_MATCH",
    organization_designation: str = "SDN",
    project_overrides: dict = None,
    **subaward_overrides,
) -> tuple:
    """A project plus one subaward already screened under ``variant``.

    Returns (project, organization, subaward).
    """
    org_payload = {
        "legal_name": "Sanctioned Instruments Co",
        "country_code": "RU",
        "org_type": "COMPANY",
        "own_designation": organization_designation,
    }
    if organization_designation != "NONE":
        org_payload["designated_on"] = "2025-06-15T00:00:00Z"
    organization = create_organization(**org_payload)
    project = create_project(**(project_overrides or {}))
    subaward = create_subaward(project["id"], organization["id"], **subaward_overrides)
    subaward = screen_subaward(subaward["id"], variant)
    return read_project(project["id"]), organization, subaward


def setup_acknowledged_plan(
    investigator_id: str = None, disclosure_id: str = None, **plan_overrides
) -> tuple:
    """Drive a disclosure's plan dimension to PLAN_ACKNOWLEDGED. When no disclosure
    is supplied, a fresh investigator with a restricted-entity item is used so the
    plan requirement is warranted.

    Returns (investigator_id, disclosure).
    """
    if disclosure_id is None:
        investigator, _organization, disclosure, _item = setup_restricted_investigator()
        investigator_id = investigator["id"]
        disclosure_id = disclosure["id"]
    assert investigator_id is not None, "pass investigator_id with disclosure_id"
    require_plan(disclosure_id)
    issue_plan(disclosure_id, **plan_overrides)
    acknowledge_plan(disclosure_id, investigator_id)
    return investigator_id, read_disclosure(disclosure_id)


# --------------------------------------------------------------------------- #
# Tier 5 -- terminal states
# --------------------------------------------------------------------------- #

def setup_terminated_subaward(**overrides) -> tuple:
    """A subaward walked to the terminal TERMINATED status.

    Returns (project, organization, subaward).
    """
    project, organization, subaward = setup_screened_subaward(**overrides)
    subaward = get_success_data(
        api_client.set_subaward_status(
            subaward["id"], {"to_status": "TERMINATED"}, RSO
        )
    )
    return project, organization, subaward


def setup_closed_incident(**overrides) -> tuple:
    """An incident driven through agency notification to the terminal CLOSED status,
    including the remediation item its closure requires.

    Returns (investigator_id, incident).
    """
    investigator = create_investigator(institutional_base_effort_pct=0)
    disclosure = create_disclosure(investigator["id"])
    organization = create_organization(own_designation="NONE")
    investigator_id, incident = setup_substantiated_incident(
        investigator_id=investigator["id"], disclosure_id=disclosure["id"], **overrides
    )
    add_disclosure_item(
        disclosure["id"],
        organization["id"],
        headers=RSO,
        item_type="FOREIGN_APPOINTMENT",
        annual_effort_hours=0,
        is_paid=False,
        source="INCIDENT_REMEDIATION",
    )
    submit_disclosure(disclosure["id"], investigator_id)
    begin_review(disclosure["id"])
    certify_disclosure(disclosure["id"])
    notify_incident(incident["id"])
    incident = get_success_data(
        api_client.set_incident_status(incident["id"], {"to_status": "CLOSED"}, RSO)
    )
    return investigator_id, incident
