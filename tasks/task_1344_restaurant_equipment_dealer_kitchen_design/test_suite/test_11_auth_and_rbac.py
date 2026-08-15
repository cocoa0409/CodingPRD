"""Authentication headers, role authorization, and shared read access."""
from test_helpers import (
    TEST_USERS,
    create_customer,
    create_customer_payload,
    create_layout,
    create_project,
    create_project_payload,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
SR = TEST_USERS["sales_rep_headers"]
KD = TEST_USERS["kitchen_designer_headers"]


def test_error_missing_user_context_header(api):
    """PRD §2.1: "Every request carries two identity headers: `X-User-ID` and
    `X-User-Role`. When either header is missing or malformed the request
    fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/errors/error_missing_user_context_header
    """
    res = api.list_customers(headers={})
    validate_error(
        res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400
    )


def test_error_missing_user_role_header(api):
    """PRD §2.1: "When either header is missing or malformed the request fails
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/errors/error_missing_user_context_header
    """
    res = api.list_customers(headers={"X-User-ID": "someone-1"})
    validate_error(
        res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400
    )


def test_error_insufficient_permissions_role_cannot_create_customer(api):
    """PRD §2.1: "`PlatformAdmin` is the back-office operator: it alone creates
    and suspends customers and drives the test-only logical clock" and "When
    the supplied role is not authorized for the attempted operation the
    request fails with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/errors/error_insufficient_permissions_role_cannot_create_customer
    """
    res = api.create_customer(
        create_customer_payload(
            legal_name="NoPerm", contact_email="np@x.test", credit_limit_cents=100_000
        ),
        SR,
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_project_manager_can_read_all_resources(api):
    """PRD §2.1: "`ProjectManager` is the dealer-side PM and owns project
    creation, project cancellation, punch-list close, project completion,
    layout approval and return-for-revision, shop-drawing approval, and
    punch-item verification and voiding; it shares punch-item creation with
    `Customer` and reads broadly."

    Design: Corner/roles/project_manager_can_read_all_resources
    """
    customer = create_customer(legal_name="PMRead")
    project = create_project(customer["id"], project_name="PMRead")

    proj = validate_success(api.get_project(project["id"], PM), 200)
    assert proj["id"] == project["id"]
    cust = validate_success(api.get_customer(customer["id"], PM), 200)
    assert cust["id"] == customer["id"]


def test_project_manager_reads_layouts_and_quotes(api):
    """PRD §2.1: "`ProjectManager` is the dealer-side PM and owns project
    creation, project cancellation, punch-list close, project completion,
    layout approval and return-for-revision, shop-drawing approval, and
    punch-item verification and voiding; it shares punch-item creation with
    `Customer` and reads broadly."

    Design: Corner/roles/project_manager_can_read_all_resources
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"])

    got_layout = validate_success(
        api.get_layout(project["id"], layout["id"], PM), 200
    )
    assert got_layout["id"] == layout["id"]
    layouts = validate_success(api.list_layouts(project["id"], PM), 200)
    assert isinstance(layouts, list)
