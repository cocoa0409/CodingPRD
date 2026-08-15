"""Access control: authentication, role gates, manager subtree confidentiality."""
import pytest

from test_helpers import (
    ApiErrorId,
    close_cycle,
    configure_cycle,
    get_direct_snapshot,
    get_success_data,
    make_active_bank,
    make_cycle,
    make_employee,
    make_unit,
    make_employee_headers,
    make_unit_manager_headers,
    open_cycle,
    pin_items,
    publish_cycle,
    score_cycle,
    api_client,
    set_clock,
    submit_full,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

HR_ADMIN = TEST_USERS["hr_admin_headers"]
PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. ... A request missing either header, or presenting a role
    the platform does not declare, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    resp = api.list_survey_cycles(None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    resp_partial = api.list_survey_cycles({"X-User-Role": "HRAdmin"})
    validate_error(resp_partial, ApiErrorId.ERR_UNAUTHENTICATED)


def test_employee_role_cannot_list_invites(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| GET | `/engagement/survey-invites` | List invitations, filterable
    by cycle, employee, status, unit-at-invite | HRAdmin, PeopleAnalyst |"

    Design: Corner/rbac/employee_cannot_list_invites
    """
    resp = api.list_survey_invites(
        make_employee_headers("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_manager_cannot_read_other_subtree_snapshot(api):
    """PRD §2.6: "A `UnitManager` may read report snapshots only for units
    inside their own subtree — the units whose `manager_user_id` matches their
    `X-User-ID`, plus every descendant unit — and only after the cycle's
    results have been published. ... Violations of these boundaries — reaching
    for a snapshot outside the manager's subtree, requesting suppressed scores,
    or attempting response-level access — are rejected with
    `ERR_CONFIDENTIALITY` (HTTP 403)."
    PRD §3.5: "Publication is the moment managers gain access: from `REPORTED`
    onward a `UnitManager` may read snapshots within their own subtree."

    Design: Corner/rbac/manager_cannot_read_other_subtree_snapshot
    """
    bank, items = make_active_bank("RBAC Bank")
    unit_x = make_unit("Unit X", "mgr-x", min_n_threshold=3, verbatim_n_threshold=5)
    unit_y = make_unit("Unit Y", "mgr-y", min_n_threshold=3, verbatim_n_threshold=5)
    employees = []
    for prefix, unit in (("X", unit_x), ("Y", unit_y)):
        for i in range(1, 4):
            employees.append(make_employee(unit["id"], f"{prefix}{i:03d}"))

    set_clock("2026-09-01T00:00:00Z")
    cycle = make_cycle(bank["id"], label="RBAC Census")
    cycle_items = pin_items(cycle["id"], items)
    configure_cycle(cycle["id"])
    open_cycle(cycle["id"])

    invites, _meta = validate_paginated(
        api.list_survey_invites(PEOPLE_ANALYST, params={"cycle_id": cycle["id"], "limit": 100})
    )
    assert len(invites) == 6
    for invite in invites:
        resp = submit_full(invite, cycle_items, [4, 4, 4])
        assert resp.status_code == 201, f"setup submit failed: {resp.text}"

    close_cycle(cycle["id"])
    score_cycle(cycle["id"])
    publish_cycle(cycle["id"])

    snap_y = get_direct_snapshot(cycle["id"], unit_y["id"])

    denied = api.get_report_snapshot(snap_y["id"], make_unit_manager_headers("mgr-x"))
    validate_error(denied, ApiErrorId.ERR_CONFIDENTIALITY)

    allowed = api.get_report_snapshot(snap_y["id"], make_unit_manager_headers("mgr-y"))
    snap = validate_success(allowed, 200)
    assert snap["overall_score"] == pytest.approx(75.00, abs=0.005), (
        "mgr-y reads own unit's snapshot after publish"
    )
