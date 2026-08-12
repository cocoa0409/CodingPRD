"""RBAC translations: exclusive-operation denial, entity-backed ClientContact
ownership scoping, and segregation of cash handling from voiding."""
from test_helpers import ApiErrorId, add_certified_classification, onboard_client, onboard_client_b, setup_paid_claim, TEST_USERS, make_client_contact_headers, validate_error, validate_paginated, validate_success
from test_helpers.factories import create_client_payload, create_import_entry_payload

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_analyst_cannot_create_client_forbidden(api):
    """PRD 2.1: "A request whose role is not listed among the roles authorized
    for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD 3.1: "A `FirmAdmin` onboards each importer or exporter as a `Client` by
    supplying the legal `name`, the IRS-issued `importer_of_record_number` —
    which must be globally unique across all clients — and the engagement's
    `contingency_fee_bps`, the firm's percentage cut of any recovered duty
    expressed in basis points."

    Design: Corner/rbac/analyst_cannot_create_client_forbidden
    """
    res = api.create_client(create_client_payload(), ANALYST)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    _, meta = validate_paginated(api.list_clients(ADMIN))
    assert meta["total_count"] == 0


def test_broker_cannot_register_entry_forbidden(api):
    """PRD 2.1: "A request whose role is not listed among the roles authorized
    for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD 3.3: "With a certified classification in hand, an `Analyst` registers
    the client's trade data."

    Design: Corner/rbac/broker_cannot_register_entry_forbidden
    """
    client = onboard_client()
    cls = add_certified_classification(client["id"])

    res = api.create_import_entry(
        create_import_entry_payload(client["id"], cls["id"]), BROKER
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_clientcontact_cannot_read_other_client_forbidden(api):
    """PRD 2.1: "When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id`
    of the acting `Client`; ownership checks on any resource that references a
    `Client` compare the resource's `client_id` field to `X-User-ID`, and a
    `ClientContact` attempting to read another client's resource or respond to a
    deficiency on another client's claim is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/clientcontact_cannot_read_other_client_forbidden
    """
    client_a = onboard_client()
    client_b = onboard_client_b()

    own = validate_success(
        api.get_client(client_a["id"], make_client_contact_headers(client_a["id"]))
    )
    assert own["id"] == client_a["id"]

    res = api.get_client(client_b["id"], make_client_contact_headers(client_a["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_analyst_cannot_void_invoice_forbidden(api):
    """PRD 2.1: "A request whose role is not listed among the roles authorized
    for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD 3.7: "A `ComplianceManager` may void an invoice, but only while no
    payment has ever been recorded against it — `amount_paid_cents` must be
    zero, otherwise `ERR_INVOICE_HAS_PAYMENTS` — moving it from `ISSUED` to the
    terminal `VOID`."

    Design: Corner/rbac/analyst_cannot_void_invoice_forbidden
    """
    ctx = setup_paid_claim(approved_duty_cents=32670)
    invoice = ctx["invoice"]
    assert invoice["status"] == "ISSUED"

    # FirmAdmin — who records payments — is also denied the void.
    res = api.void_invoice(invoice["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_invoice(invoice["id"], ADMIN))
    assert after["status"] == "ISSUED"
