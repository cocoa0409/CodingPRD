"""Role authorization, separation of duties and header authentication.

The eight roles of PRD 2.1 are peers: each write endpoint belongs to exactly one
of them, every GET is shared by all eight, and three decision points compare the
acting `X-User-ID` against a previously recorded operator identifier.
"""

import pytest

from test_helpers import (
    ALL_ROLES,
    NON_EXISTENT_UUID,
    ROLE_CIVIL_SUPERINTENDENT,
    ROLE_COMMISSIONING_ENGINEER,
    ROLE_EPC_PROJECT_MANAGER,
    ROLE_INSTALLATION_FOREMAN,
    ROLE_LABOR_COMPLIANCE_OFFICER,
    ROLE_OWNER_ENGINEER,
    ROLE_PROCUREMENT_COORDINATOR,
    ROLE_UTILITY_COORDINATOR,
    assert_contains_id,
    factories as f,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.fixtures import (
    create_block,
    create_grading_area,
    create_project,
    create_punch_item,
    graded_area,
    project_version,
    read_payroll_week,
    read_project,
    read_punch_item,
)
from test_helpers.test_users import (
    HEADERS_BY_ROLE,
    headers_without_auth,
    headers_without_role,
    headers_without_user_id,
    make_foreman_headers,
    make_labor_headers,
    make_owner_headers,
    role_headers,
)


# ---------------------------------------------------------------------------
# One exclusive write per role
# ---------------------------------------------------------------------------
def _own_exclusive_write(api, role):
    """Issue, under `role`'s own headers, the one write only that role may make.

    Returns the response, the status code the PRD pairs with that operation and
    the field values the operation's own narrative pins on its result.
    """
    headers = HEADERS_BY_ROLE[role]

    if role == ROLE_EPC_PROJECT_MANAGER:
        response = api.create_project(f.project_payload(), headers)
        return response, 201, {"milestone_state": "PRECONSTRUCTION"}

    project = create_project(api)

    if role == ROLE_CIVIL_SUPERINTENDENT:
        response = api.create_grading_area(
            project["id"], f.grading_area_payload(), headers
        )
        return response, 201, {"status": "PLANNED"}

    if role == ROLE_PROCUREMENT_COORDINATOR:
        response = api.create_yard_zone(project["id"], f.yard_zone_payload(), headers)
        return response, 201, {"available_pallets": 100}

    if role == ROLE_UTILITY_COORDINATOR:
        response = api.create_substation(
            project["id"], f.substation_payload(), headers
        )
        return response, 201, {"status": "SITE_CIVIL"}

    if role == ROLE_LABOR_COMPLIANCE_OFFICER:
        response = api.create_payroll_week(
            project["id"], f.payroll_week_payload(), headers
        )
        return response, 201, {"status": "OPEN"}

    if role == ROLE_COMMISSIONING_ENGINEER:
        payload = f.commissioning_test_payload(
            project["id"], project_version(api, project["id"])
        )
        response = api.create_commissioning_test(payload, headers)
        return response, 201, {"status": "SCHEDULED"}

    if role == ROLE_OWNER_ENGINEER:
        area = graded_area(api, project["id"])
        response = api.accept_grading_area(
            area["id"], f.acceptance_payload(), headers
        )
        return response, 200, {"status": "ACCEPTED"}

    area = create_grading_area(api, project["id"])
    block = create_block(api, project["id"], area["id"])
    response = api.create_pile(block["id"], f.pile_payload(), headers)
    return response, 201, {"status": "PLANNED"}


@pytest.mark.parametrize("role", ALL_ROLES)
def test_each_role_performs_the_write_it_exclusively_owns(api, role):
    """Every one of the eight roles is admitted on the write reserved to it.

    PRD 2.1: "Every write endpoint is exclusive to the single role named in its §4 row, with no overlap between roles."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_write
    """
    response, expected_status, expectations = _own_exclusive_write(api, role)
    data = validate_success(response, expected_status=expected_status)
    for field, value in expectations.items():
        assert data[field] == value, (
            f"{role} performed its own write but {field} came back {data[field]!r} "
            f"instead of {value!r}"
        )


# ---------------------------------------------------------------------------
# The same writes attempted by a role that does not own them
# ---------------------------------------------------------------------------
def _cross_role_write(api, operation, project):
    """Issue one exclusive write under a plausible but unauthorized role."""
    if operation == "create_project":
        return api.create_project(
            f.project_payload(name="Shadow Project"),
            HEADERS_BY_ROLE[ROLE_CIVIL_SUPERINTENDENT],
        )
    if operation == "create_grading_area":
        return api.create_grading_area(
            project["id"],
            f.grading_area_payload(area_code="A9"),
            HEADERS_BY_ROLE[ROLE_PROCUREMENT_COORDINATOR],
        )
    if operation == "accept_grading_area":
        return api.accept_grading_area(
            NON_EXISTENT_UUID,
            f.acceptance_payload(),
            HEADERS_BY_ROLE[ROLE_CIVIL_SUPERINTENDENT],
        )
    if operation == "create_yard_zone":
        return api.create_yard_zone(
            project["id"],
            f.yard_zone_payload(zone_code="Y9"),
            HEADERS_BY_ROLE[ROLE_INSTALLATION_FOREMAN],
        )
    if operation == "register_pile":
        return api.create_pile(
            NON_EXISTENT_UUID,
            f.pile_payload(row_index=9, position_index=9),
            HEADERS_BY_ROLE[ROLE_CIVIL_SUPERINTENDENT],
        )
    if operation == "create_substation":
        return api.create_substation(
            project["id"],
            f.substation_payload(substation_code="S9"),
            HEADERS_BY_ROLE[ROLE_COMMISSIONING_ENGINEER],
        )
    if operation == "schedule_commissioning_test":
        return api.create_commissioning_test(
            f.commissioning_test_payload(project["id"], project["version"]),
            HEADERS_BY_ROLE[ROLE_UTILITY_COORDINATOR],
        )
    return api.create_payroll_week(
        project["id"],
        f.payroll_week_payload(week_start_date="2026-08-10"),
        HEADERS_BY_ROLE[ROLE_OWNER_ENGINEER],
    )


CROSS_ROLE_OPERATIONS = (
    "create_project",
    "create_grading_area",
    "accept_grading_area",
    "create_yard_zone",
    "register_pile",
    "create_substation",
    "schedule_commissioning_test",
    "open_payroll_week",
)


@pytest.mark.parametrize("operation", CROSS_ROLE_OPERATIONS)
def test_cross_role_write_is_refused_on_every_exclusive_operation(
    api, project, operation
):
    """A write attempted by any role other than its owner is refused, and writes nothing.

    PRD 2.1: "If both headers are well-formed but the declared role is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

    Design: Corner/rbac/cross_role_writes_are_forbidden_on_every_exclusive_operation
    """
    response = _cross_role_write(api, operation, project)
    validate_error(response, ERR_FORBIDDEN_ROLE)

    after = read_project(api, project["id"])
    assert after["version"] == project["version"], (
        "a refused write must not advance the project's version"
    )
    rows, meta = validate_paginated(
        api.list_projects(HEADERS_BY_ROLE[ROLE_EPC_PROJECT_MANAGER])
    )
    assert meta["total_count"] == 1, "the refused write must not have created a project"
    assert_contains_id(rows, project["id"])


# ---------------------------------------------------------------------------
# Reads are shared by every role
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ALL_ROLES)
def test_project_read_is_open_to_every_role(api, project, role):
    """All eight roles retrieve the same project row, and reading changes nothing.

    PRD 2.1: "Read access is uniform: every GET endpoint in §4 is available to all eight roles."

    Design: Corner/rbac/shared_read_operations_are_open_to_all_eight_roles
    """
    headers = HEADERS_BY_ROLE[role]

    data = validate_success(api.get_project(project["id"], headers))
    assert data["id"] == project["id"]
    assert data["version"] == project["version"], "a read must not advance the version"

    rows, meta = validate_paginated(api.list_projects(headers))
    assert meta["total_count"] == 1
    assert_contains_id(rows, project["id"])


# ---------------------------------------------------------------------------
# Segregation of duties compares operator identities, not roles
# ---------------------------------------------------------------------------
def test_owner_engineer_cannot_decide_the_closure_it_submitted(api, project):
    """A closure decision is refused when the decider's user id submitted the evidence.

    PRD 2.10: "A punch-list closure decision is refused when the deciding `X-User-ID` equals the item's `submitted_by_user_id`."

    Design: Corner/rbac/same_user_cannot_both_submit_and_decide_the_same_step
    """
    item = create_punch_item(
        api,
        project["id"],
        title="Tracker bearing loose at row 2",
        category="MECHANICAL",
        severity="MAJOR",
        estimated_cost_cents=80000,
    )
    submitted = get_success_data(
        api.create_closure_submission(
            item["id"],
            f.closure_submission_payload(closure_evidence_ref="TORQ-5501"),
            make_foreman_headers("u-dual-1"),
        )
    )
    assert submitted["status"] == "CLOSURE_SUBMITTED"
    assert submitted["submitted_by_user_id"] == "u-dual-1"

    refused = api.create_closure_decision(
        item["id"],
        f.closure_decision_payload("APPROVE"),
        make_owner_headers("u-dual-1"),
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES)
    assert read_punch_item(api, item["id"])["status"] == "CLOSURE_SUBMITTED"

    decided = validate_success(
        api.create_closure_decision(
            item["id"],
            f.closure_decision_payload("APPROVE"),
            make_owner_headers("u-oe-9"),
        )
    )
    assert decided["status"] == "CLOSED"
    assert decided["decided_by_user_id"] == "u-oe-9"


def test_officer_cannot_certify_a_week_holding_its_own_posted_entry(api, project):
    """Certification is refused for the officer who posted a still-posted line of the week.

    PRD 2.10: "A payroll-week certification is refused when the certifying `X-User-ID` matches the `posted_by_user_id` of any labor entry of that week that is still posted."

    Design: Corner/rbac/same_user_cannot_both_submit_and_decide_the_same_step
    """
    week = get_success_data(
        api.create_payroll_week(
            project["id"],
            f.payroll_week_payload(week_start_date="2026-08-03"),
            make_labor_headers("u-dual-2"),
        )
    )
    entry = get_success_data(
        api.create_labor_entry(
            week["id"],
            f.labor_entry_payload(
                worker_ref="W-1101", classification="LABORER", hours=12.00
            ),
            make_labor_headers("u-dual-2"),
        )
    )
    assert entry["status"] == "POSTED"
    assert entry["posted_by_user_id"] == "u-dual-2"

    refused = api.certify_payroll_week(
        week["id"], f.certification_payload(), make_labor_headers("u-dual-2")
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES)
    assert read_payroll_week(api, week["id"])["status"] == "OPEN"

    certified = validate_success(
        api.certify_payroll_week(
            week["id"], f.certification_payload(), make_labor_headers("u-lc-9")
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "u-lc-9"


# ---------------------------------------------------------------------------
# Header authentication precedes every other check
# ---------------------------------------------------------------------------
UNIDENTIFIED_CALLERS = (
    ("no_headers_at_all", headers_without_auth()),
    ("undeclared_role", role_headers("SiteSafetyOfficer", "u-sso-1")),
    ("role_without_user_id", headers_without_user_id(ROLE_EPC_PROJECT_MANAGER)),
    ("user_id_without_role", headers_without_role("u-pm-8")),
)


@pytest.mark.parametrize(
    "label,headers", UNIDENTIFIED_CALLERS, ids=[case[0] for case in UNIDENTIFIED_CALLERS]
)
def test_shared_read_without_a_recognised_identity_is_unauthenticated(
    api, project, epc_headers, label, headers
):
    """A missing header or an undeclared role is 401, even on a read every role shares.

    PRD 2.1: "If either header is absent, or if `X-User-Role` carries a value that is not one of the eight roles below, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/requests_without_a_recognised_identity_are_unauthenticated
    """
    validate_error(api.get_project(project["id"], headers), ERR_UNAUTHENTICATED)

    control = validate_success(api.get_project(project["id"], epc_headers))
    assert control["id"] == project["id"]


def test_unidentified_write_is_unauthenticated_and_changes_no_ledger(api, project):
    """An unidentified write is refused before any scope arithmetic runs.

    PRD 2.1: "Every request to this API — including every read — must carry two headers."

    Design: Corner/rbac/requests_without_a_recognised_identity_are_unauthenticated
    """
    response = api.create_change_order(
        project["id"],
        f.change_order_payload(100, reason="unauthenticated attempt"),
        headers_without_auth(),
    )
    validate_error(response, ERR_UNAUTHENTICATED)

    after = read_project(api, project["id"])
    assert after["approved_change_order_cents"] == 0
    assert after["version"] == project["version"]
