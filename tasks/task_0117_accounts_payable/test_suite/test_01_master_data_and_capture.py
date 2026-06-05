"""Master data, vendor rules, and invoice capture (PRD §3.1, §3.3).

Every test below translates exactly one corner-design instance.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_vendor_payload, create_invoice_payload, create_invoice_line_payload,
    create_gl_account_payload,
    setup_master_data, create_vendor, capture_invoice, create_lined_invoice,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_vendor_returns_201_with_defaults(api):
    """PRD §3.1: "A new vendor begins life with a `status` of `ACTIVE` and a
    `ytd_1099_paid_cents` of 0, both system-managed."
    PRD §2.4: "a `version` integer that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/create_vendor_returns_201_with_defaults
    """
    resp = api.create_vendor(create_vendor_payload(legal_name="Acme", payment_method="ACH"), MGR)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["ytd_1099_paid_cents"] == 0
    assert data["version"] == 1


def test_get_vendor_returns_stored_entity(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/entities/get_vendor_returns_stored_entity
    """
    created = create_vendor(legal_name="Echo", payment_method="CHECK")
    resp = api.get_vendor(created["id"], AUDITOR)
    data = validate_success(resp, 200)
    assert data["legal_name"] == "Echo"


def test_get_vendor_nonexistent_returns_not_found(api):
    """PRD §2.4: "then existence of every resource referenced in the path or body
    (`ERR_NOT_FOUND`)".

    Design: Corner/entities/get_vendor_nonexistent_returns_not_found
    """
    resp = api.get_vendor(NON_EXISTENT, AUDITOR)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_create_vendor_missing_payment_method_invalid_request(api):
    """PRD §2.4: "then well-formedness of the request body — required fields present,
    correct types, valid enum values (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_vendor_missing_payment_method_invalid_request
    """
    resp = api.create_vendor({"legal_name": "NoMethod"}, MGR)
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_vendor_default_net_terms_applied_to_due_date(api):
    """PRD §3.1: "The vendor's `net_terms_days` (defaulting to 30) governs how far
    after the invoice date payment is due."
    PRD §3.3: "the system computes the invoice's `due_date` as the invoice date
    advanced by the vendor's net terms".

    Design: Corner/entities/vendor_default_net_terms_applied_to_due_date
    """
    vendor = create_vendor(legal_name="Def", payment_method="ACH")
    resp = api.create_invoice(
        create_invoice_payload(vendor["id"], invoice_number="DUE-1", invoice_date="2026-05-01"),
        CLERK)
    data = validate_success(resp, 201)
    assert data["due_date"][:10] == "2026-05-31", f"expected 2026-05-31, got {data['due_date']}"


def test_invoice_total_amount_computed_from_lines(api):
    """PRD §3.3: "Every time a line is added, the invoice's `total_amount_cents` is
    recomputed as the sum of its lines' amounts."

    Design: Corner/entities/invoice_total_amount_computed_from_lines
    """
    setup_master_data()
    vendor = create_vendor(legal_name="Sum", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="SUM-1")
    api.add_invoice_line(inv["id"], create_invoice_line_payload(amount_cents=30000, description="a"), CLERK)
    resp = api.add_invoice_line(inv["id"], create_invoice_line_payload(amount_cents=20000, description="b"), CLERK)
    validate_success(resp, 201)
    data = validate_success(api.get_invoice(inv["id"], CLERK), 200)
    assert data["total_amount_cents"] == 50000


def test_create_vendor_invalid_payment_method_enum_rejected(api):
    """PRD §3.1: "a default disbursement rail in `payment_method`, which must be one of
    `ACH`, `CHECK`, or `CARD`."

    Design: Corner/entities/create_vendor_invalid_payment_method_enum_rejected
    """
    resp = api.create_vendor(create_vendor_payload(legal_name="BadEnum", payment_method="WIRE"), MGR)
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_invoice_wrong_vendor_parent_not_found(api):
    """PRD §2.4: "then existence of every resource referenced in the path or body
    (`ERR_NOT_FOUND`)".

    Design: Corner/entities/invoice_wrong_vendor_parent_not_found
    """
    resp = api.create_invoice(
        create_invoice_payload(NON_EXISTENT, invoice_number="ORPH", invoice_date="2026-05-01"),
        CLERK)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_vendor_1099_without_tax_id_rejected(api):
    """PRD §3.1: "when `is_1099` is true, a non-empty `tax_id` must be supplied at
    creation, and a creation that sets the flag without a tax identifier is rejected
    with `ERR_TAX_ID_REQUIRED`."

    Design: Corner/entities/vendor_1099_without_tax_id_rejected
    """
    resp = api.create_vendor(
        create_vendor_payload(legal_name="NoTIN", payment_method="ACH", is_1099=True), MGR)
    validate_error(resp, "ERR_TAX_ID_REQUIRED", 422)
