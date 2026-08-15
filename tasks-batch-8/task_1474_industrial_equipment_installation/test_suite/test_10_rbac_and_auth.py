"""Authentication and role-based authorization (PRD sections 2.1 and 4)."""
import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    create_labor_entry_payload,
    create_project,
    create_project_payload,
    find_labor_entry,
    make_site_supervisor_headers,
    validate_error,
    validate_success,
)


@pytest.mark.parametrize(
    "headers",
    [
        ANONYMOUS_HEADERS,  # no X-User-Role header at all
        {  # an unrecognized role string
            "X-User-ID": "anon-1",
            "X-User-Role": "Administrator",
            "Content-Type": "application/json",
        },
    ],
    ids=["missing-role-header", "unrecognized-role"],
)
def test_missing_role_header_unauthenticated(api, headers):
    """PRD section 2.1: "A request whose `X-User-Role` header is missing or
    does not match one of these five declared roles is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_role_header_unauthenticated
    """
    resp = api.create_project(
        create_project_payload(name="No Role", site_address="37 Plant Rd"),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_safety_officer_cannot_create_project(api, so_headers):
    """PRD section 2.1: "When the role is recognized but not permitted to
    invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD section 2.1: "The division of labor across roles follows a strict
    segregation-of-duties model: the `SiteSupervisor` records field data
    (surveys, rigging plans, lift bookings, alignment measurements, labor
    entries, checklist items), the `ProjectManager` owns the project
    lifecycle, reviews, invoicing, and the test clock, the `SafetyOfficer`
    alone manages the safety plan and lockout-tagout windows, the
    `PayrollClerk` approves or rejects submitted labor and is deliberately
    distinct from the submitting supervisor, and the `CustomerRep` holds sole
    authority for commissioning sign-off."

    Design: Corner/rbac/safety_officer_cannot_create_project
    """
    resp = api.create_project(
        create_project_payload(name="RBAC Job", site_address="59 Plant Rd"),
        so_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_payroll_clerk_cannot_create_labor_entry(api, pay_headers):
    """PRD section 2.1: "When the role is recognized but not permitted to
    invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD section 3.8: "Labor is reported by the `SiteSupervisor` one entry per
    worker per date, with the worker identified by `worker_ref` (their union
    card reference), a prevailing-wage `classification` of `MW_JOURNEYMAN`,
    `MW_APPRENTICE`, `MW_FOREMAN`, or `OPERATOR`, the `work_date`, the
    `hours_worked` that date (greater than zero and at most twenty-four), and
    a `shift` of `DAY` or `NIGHT`."

    Design: Corner/rbac/payroll_clerk_cannot_create_labor_entry
    """
    project = create_project(name="RBAC2 Job", site_address="60 Plant Rd")
    resp = api.create_labor_entry(
        create_labor_entry_payload(project_id=project["id"], worker_ref="U-9601"),
        pay_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_site_supervisor_cannot_approve_labor(api):
    """PRD section 2.1: "When the role is recognized but not permitted to
    invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD section 3.8: "Payroll review belongs to the `PayrollClerk`, with one
    hard segregation rule: the approver's `X-User-ID` must differ from the
    entry's `submitted_by_user_id`, and a self-approval attempt is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/site_supervisor_cannot_approve_labor
    """
    project = create_project(name="RBAC3 Job", site_address="61 Plant Rd")
    entry = validate_success(
        api.create_labor_entry(
            create_labor_entry_payload(project_id=project["id"], worker_ref="U-9602"),
            make_site_supervisor_headers("sup-1"),
        ),
        201,
    )
    validate_success(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1"))
    )

    # A second supervisor (not the submitter) is still the wrong role.
    resp = api.approve_labor_entry(entry["id"], make_site_supervisor_headers("sup-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    assert find_labor_entry(project["id"], entry["id"])["status"] == "SUBMITTED"
