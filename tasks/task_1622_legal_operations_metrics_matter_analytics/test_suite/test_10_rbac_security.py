"""Authentication and role-based access control (PRD §2.1, §4)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_invoice,
    create_department,
    create_invoice,
    create_matter_payload,
    setup_matter_graph,
    validate_success,
    validate_error,
)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying malformed header
    values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_matters(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_analyst_cannot_pay_invoice(api, analyst_headers):
    """PRD §2.1: "`LegalOpsAnalyst` — the day-to-day operator: matters,
    assignments, accruals, invoices (submission, approval, rejection), period
    soft-close, and dashboard drafting. An analyst cannot pay invoices or manage
    the taxonomy."
    PRD §2.1: "A well-authenticated request whose role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/analyst_cannot_pay_invoice
    """
    graph = setup_matter_graph()
    inv = create_invoice(
        graph["matter"]["id"], graph["firm"]["id"], graph["fiscal_period"]["id"], 1000
    )
    approve_invoice(inv["id"])
    res = api_client.pay_invoice(inv["id"], analyst_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_manager_cannot_create_matter(api, manager_headers):
    """PRD §2.1: "`LegalOpsAnalyst` — the day-to-day operator: matters,
    assignments, accruals, invoices (submission, approval, rejection), period
    soft-close, and dashboard drafting. An analyst cannot pay invoices or manage
    the taxonomy."
    PRD §2.1: "A well-authenticated request whose role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/manager_cannot_create_matter
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    payload = create_matter_payload(
        graph["practice_area"]["id"],
        graph["matter_type"]["id"],
        graph["fiscal_period"]["id"],
        graph["counsel"]["id"],
        primary_firm_id=graph["firm"]["id"],
    )
    res = api_client.create_matter(payload, manager_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_executive_can_read_but_not_write(api, executive_headers):
    """PRD §2.1: "`LegalOpsExecutive` — a read-only consumer of dashboards,
    reports, and drill-downs, with no write operations of its own."
    PRD §2.1: "A well-authenticated request whose role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/executive_can_read_but_not_write
    """
    dept = create_department()
    read = api.get_department(dept["id"], executive_headers)
    data = validate_success(read, 200)
    assert data["id"] == dept["id"]

    res = api.create_fiscal_period(
        {"label": "FY2027", "start_date": "2027-01-01", "end_date": "2027-12-31"},
        executive_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
