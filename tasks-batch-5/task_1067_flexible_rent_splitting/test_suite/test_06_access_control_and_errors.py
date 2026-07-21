"""Authentication, authorization, ownership, and resource not-found errors."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_property, create_renter, make_renter_headers,
    create_property_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
RENTER = TEST_USERS["renter_headers"]


# ---------------------------------------------------------------------------
# Corner: rbac
# ---------------------------------------------------------------------------

def test_renter_cannot_create_property_returns_403(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/renter_cannot_create_property_returns_403
    """
    resp = api.create_property(create_property_payload(
        landlord_name="X", unit_label="Y", full_rent_cents=100000,
        rent_due_day=1, remittance_account_ref="z"), make_renter_headers("some-renter"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_underwriter_cannot_remit_returns_403(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/underwriter_cannot_remit_returns_403
    """
    # Authorization precedes existence, so the cycle need not exist.
    resp = api.remit_cycle(NON_EXISTENT_UUID, UNDERWRITER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_renter_reads_other_renter_ownership_violation(api):
    """PRD §2.1: "When an entity-backed `Renter` or `PropertyManager` acts on a resource they
    do not own, the request is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/renter_reads_other_renter_ownership_violation
    """
    prop = create_property(api, unit_label="Oak #14")
    renter_a = create_renter(prop["id"], api, email="a@x.com", full_name="A")
    renter_b = create_renter(prop["id"], api, email="b@x.com", full_name="B")
    resp = api.get_renter(renter_a["id"], make_renter_headers(renter_b["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, 403)


def test_unauthenticated_missing_auth_headers_returns_401(api):
    """PRD §2.1: "When either header is missing or blank, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/rbac/unauthenticated_missing_auth_headers_returns_401
    """
    resp = api.list_properties({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ---------------------------------------------------------------------------
# Corner: errors (not-found)
# ---------------------------------------------------------------------------

def test_property_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource —
    `ERR_PROPERTY_NOT_FOUND`, ... — each HTTP 404."

    Design: Corner/errors/property_not_found_returns_404
    """
    resp = api.get_property(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value, 404)


def test_renter_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource — ...
    `ERR_RENTER_NOT_FOUND`, ... — each HTTP 404."

    Design: Corner/entities/renter_not_found_returns_404
    """
    resp = api.get_renter(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RENTER_NOT_FOUND.value, 404)


def test_application_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource — ...
    `ERR_APPLICATION_NOT_FOUND`, ... — each HTTP 404."

    Design: Corner/errors/application_not_found_returns_404
    """
    resp = api.get_application(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, 404)


def test_billing_cycle_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource — ...
    `ERR_BILLING_CYCLE_NOT_FOUND`, ... — each HTTP 404."

    Design: Corner/errors/billing_cycle_not_found_returns_404
    """
    resp = api.get_billing_cycle(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BILLING_CYCLE_NOT_FOUND.value, 404)


def test_installment_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource — ...
    `ERR_INSTALLMENT_NOT_FOUND`, ... — each HTTP 404."

    Design: Corner/errors/installment_not_found_returns_404
    """
    resp = api.get_installment(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSTALLMENT_NOT_FOUND.value, 404)


def test_remittance_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource — ...
    `ERR_REMITTANCE_NOT_FOUND`, ... — each HTTP 404."

    Design: Corner/errors/remittance_not_found_returns_404
    """
    resp = api.get_remittance(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REMITTANCE_NOT_FOUND.value, 404)


def test_mandate_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource — ...
    `ERR_MANDATE_NOT_FOUND`, ... — each HTTP 404."

    Design: Corner/errors/mandate_not_found_returns_404
    """
    resp = api.get_mandate(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MANDATE_NOT_FOUND.value, 404)


def test_delinquency_case_not_found_returns_404(api):
    """PRD §2.9: "A missing resource yields a not-found error naming that resource — ...
    `ERR_DELINQUENCY_CASE_NOT_FOUND` — each HTTP 404."

    Design: Corner/errors/delinquency_case_not_found_returns_404
    """
    resp = api.get_delinquency_case(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DELINQUENCY_CASE_NOT_FOUND.value, 404)
