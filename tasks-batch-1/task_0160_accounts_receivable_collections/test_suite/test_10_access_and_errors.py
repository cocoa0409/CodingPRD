"""Access control and request-validation corner cases.

Queue B (Corner): unauthenticated request, read-only auditor refused a write,
peer-role boundary on cash application, not-found, missing required field,
invalid enum, field constraint (due before invoice date), missing parent FK,
pagination bound.
"""
from test_helpers import (
    validate_error,
    create_customer,
    create_invoice,
    create_payment,
    create_invoice_payload,
    create_customer_payload,
    create_payment_application_payload,
    NON_EXISTENT_UUID,
)


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing or malforming either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    res = api.create_customer(
        create_customer_payload(name="NoAuth", credit_limit_cents=1000), {}
    )
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_auditor_cannot_create_customer(api, auditor_headers):
    """PRD §2.1: "The `AUDITOR` has read-only oversight across the entire ledger
    and may perform any GET read but no mutation."
    PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/auditor_readonly_cannot_create_customer
    """
    res = api.create_customer(
        create_customer_payload(name="AudCo", credit_limit_cents=1000), auditor_headers
    )
    validate_error(res, "ERR_UNAUTHORIZED")


def test_collections_agent_cannot_apply_cash(api, ar_manager_headers, ar_clerk_headers, collections_agent_headers):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.3: "Manually applying cash to one invoice is exclusive to the
    `AR_CLERK`."

    Design: Corner/rbac/collections_agent_cannot_apply_cash
    """
    customer = create_customer(name="PR")
    invoice = create_invoice(customer["id"], face_amount_cents=10_000)
    payment = create_payment(customer["id"], amount_cents=5000)
    res = api.create_payment_application(
        payment["id"],
        create_payment_application_payload(invoice["id"], 5000),
        collections_agent_headers,
    )
    validate_error(res, "ERR_UNAUTHORIZED")


def test_get_invoice_not_found(api, auditor_headers):
    """PRD §2.5: "if the parent named in the path does not exist, the request is
    rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_invoice_not_found_returns_404
    """
    res = api.get_invoice(NON_EXISTENT_UUID, auditor_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_invoice_missing_face_amount_rejected(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.10: "a missing required field or malformed JSON yields
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_invoice_missing_required_field_returns_invalid_request
    """
    customer = create_customer(name="MissCo", credit_limit_cents=100_000)
    payload = create_invoice_payload(
        customer["id"], invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z"
    )
    del payload["face_amount_cents"]
    res = api.create_invoice(payload, ar_clerk_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_customer_invalid_currency_enum_rejected(api, ar_manager_headers):
    """PRD §3.10: "an enum field carrying a value outside its declared members
    yields `ERR_INVALID_ENUM`."
    PRD §3.1: "The `currency` is one of `USD`, `EUR`, or `GBP`".

    Design: Corner/entities/invoice_invalid_currency_enum_rejected
    """
    res = api.create_customer(
        create_customer_payload(name="Yen", currency="JPY", credit_limit_cents=100_000),
        ar_manager_headers,
    )
    validate_error(res, "ERR_INVALID_ENUM")


def test_invoice_due_before_invoice_date_rejected(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.1: "The `due_date` must be the same as or later than the
    `invoice_date`; a `due_date` earlier than `invoice_date` is rejected with
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/invoice_due_before_invoice_date_rejected
    """
    customer = create_customer(name="DateCo")
    res = api.create_invoice(
        create_invoice_payload(
            customer["id"], invoice_date="2026-03-01T00:00:00Z",
            due_date="2026-02-01T00:00:00Z", face_amount_cents=1000,
        ),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_VALIDATION")


def test_create_invoice_unknown_customer_returns_not_found(api, ar_clerk_headers):
    """PRD §3.10: "Existence is then checked — every path and body id (customer,
    invoice, payment, dispute, sequence, promise) must resolve, left to right,
    else `ERR_NOT_FOUND`".

    Design: Corner/entities/invoice_requires_existing_customer_parent
    """
    res = api.create_invoice(
        create_invoice_payload(
            NON_EXISTENT_UUID, invoice_date="2026-01-01T00:00:00Z",
            due_date="2026-02-01T00:00:00Z", face_amount_cents=1000,
        ),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_NOT_FOUND")


def test_pagination_limit_over_max_rejected(api, auditor_headers):
    """PRD §2.3: "it defaults to 10, with a minimum of 1 and a maximum of 100... A
    `limit` or `offset` outside these bounds is rejected with
    `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/pagination_limit_over_max_rejected
    """
    res = api.list_invoices(auditor_headers, params={"limit": 101})
    validate_error(res, "ERR_PAGINATION_INVALID")
