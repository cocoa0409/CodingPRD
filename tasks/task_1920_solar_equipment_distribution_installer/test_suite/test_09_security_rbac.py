"""Authentication headers and per-operation role authorization."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_active_installer,
    create_installer_payload,
    create_inverter_product,
    create_module_product,
    create_product_payload,
    create_project_payload,
    make_installer_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD section 2.1: "Every request must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their
    operational capacity. A request in which either header is missing or
    invalid is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    resp = api.list_products(headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_insufficient_permissions_for_role(api):
    """PRD section 2.1: "Authorization is per-operation, and a request whose
    role is not permitted for the operation is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." Product creation is a
    `DistributionAdmin` operation (PRD section 4), so an `InstallerRep` is
    denied.

    Design: Corner/validations/insufficient_permissions_for_role
    """
    installer = validate_success(
        api_client.create_installer(create_installer_payload(), MANAGER), 201
    )
    resp = api.create_product(
        create_product_payload(), make_installer_rep_headers(installer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_installerrep_cannot_suspend_installer(api):
    """PRD section 3.2: "Suspension and termination are `CreditOfficer`
    actions." An `InstallerRep` calling suspend is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403) per PRD section 2.1.

    Design: Corner/rbac/installerrep_cannot_suspend_installer
    """
    installer = create_active_installer()
    resp = api.suspend_installer(
        installer["id"], make_installer_rep_headers(installer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_creditofficer_cannot_create_project_for_installer(api):
    """PRD section 4: POST /solar-dist/installers/{installerId}/projects is
    authorized for "InstallerRep, ChannelManager" only. PRD section 2.1:
    "Authorization is per-operation, and a request whose role is not
    permitted for the operation is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/creditofficer_cannot_create_project_for_installer
    """
    module = create_module_product()
    inverter = create_inverter_product()
    installer = create_active_installer()
    resp = api.create_project(
        installer["id"],
        create_project_payload(module["id"], inverter["id"]),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
