"""Role-based access control and identity-header enforcement."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer_headers,
    setup_book, setup_settled_sale, setup_generated_form,
    make_firm, make_customer, make_account, make_security, make_lot, make_disposition,
    create_tax_lot_payload,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring their operational
    capacity. A request missing either header, or presenting a malformed one,
    is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    firm = make_firm("Firm V1")
    resp = api.get_firm(firm["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_customer_cannot_settle_disposition(api):
    """PRD §4: the settle endpoint (`POST
    /firms/{firmId}/dispositions/{dispositionId}/settle`) admits `TaxOps` only.
    PRD §2.1: "a well-identified caller whose role is not admitted to an
    endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_settle_disposition
    """
    s = setup_book(tin="TIN-R-1", cusip="616161616")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=15000)
    resp = api.settle_disposition(s["firm"]["id"], disp["id"], make_customer_headers(s["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_taxops_cannot_file_form(api):
    """PRD §2.1: "`FirmAdmin` is the firm superuser: it alone creates firms,
    suspends, reinstates, and closes customers, files and refiles 1099-B forms,
    and drives the logical clock."
    PRD §2.1: "a well-identified caller whose role is not admitted to an
    endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/taxops_cannot_file_form
    """
    s = setup_settled_sale(tin="TIN-R-2", cusip="626262626")
    form = setup_generated_form(s["firm"]["id"], s["customer"]["id"], 2025)
    resp = api.file_tax_form(s["firm"]["id"], s["customer"]["id"], form["id"], TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    form_after = validate_success(api.get_tax_form(s["firm"]["id"], s["customer"]["id"], form["id"], TAX_OPS))
    assert form_after["status"] == "GENERATED", "rejected file leaves the form unchanged"


def test_auditor_cannot_create_lot(api):
    """PRD §2.1: "`Auditor` is a read-only compliance role and cannot mutate
    anything."
    PRD §2.1: "a well-identified caller whose role is not admitted to an
    endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/auditor_cannot_create_lot
    """
    s = setup_book(tin="TIN-R-3", cusip="636363636")
    resp = api.create_tax_lot(
        s["firm"]["id"], s["account"]["id"],
        create_tax_lot_payload(security_id=s["security"]["id"], quantity=10,
                               original_cost_basis_cents=10000),
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
