"""Customer / Invoice / Payment creation, retrieval, and computed-field claims.

Each test cites the verbatim PRD sentence that fixes the asserted behavior.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    create_customer_payload,
    create_invoice_payload,
    create_payment_payload,
    assert_customer,
    assert_invoice,
    set_clock,
    create_customer,
    create_invoice,
)


def test_create_customer_returns_201_with_defaults(api, ar_manager_headers):
    """PRD §3.1: "A new customer is born with `credit_status` of `GOOD` and
    `collection_stage` of `CURRENT`, with `exposure_cents`,
    `total_open_balance_cents`, and `bad_debt_total_cents` all at zero and
    `manual_hold` false."
    PRD §3.1: "The `currency` is one of `USD`, `EUR`, or `GBP` and defaults to
    `USD` when omitted".
    PRD §2.4: "`version` — an integer that starts at its initial value and
    increments by one on every mutation of the resource."

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    res = api.create_customer(
        create_customer_payload(name="Acme", credit_limit_cents=500_000), ar_manager_headers
    )
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["currency"] == "USD"
    assert customer["credit_status"] == "GOOD"
    assert customer["collection_stage"] == "CURRENT"
    assert customer["exposure_cents"] == 0
    assert customer["version"] == 1


def test_get_customer_by_id_returns_stored_entity(api, ar_manager_headers, auditor_headers):
    """PRD §3.1: "Reading a single customer recomputes `exposure_cents`,
    `total_open_balance_cents`, and `credit_status` before responding, so the
    returned posture is always live."

    Design: Corner/entities/get_customer_by_id_returns_stored_entity
    """
    created = validate_success(
        api.create_customer(
            create_customer_payload(name="Beta", credit_limit_cents=300_000),
            ar_manager_headers,
        ),
        201,
    )
    fetched = validate_success(api.get_customer(created["id"], auditor_headers), 200)
    assert fetched["name"] == "Beta"
    assert fetched["id"] == created["id"]


def test_customer_currency_default_applied_when_omitted(api, ar_manager_headers):
    """PRD §3.1: "The `currency` is one of `USD`, `EUR`, or `GBP` and defaults to
    `USD` when omitted".

    Design: Corner/entities/customer_currency_default_applied_when_omitted
    """
    payload = create_customer_payload(name="DefCo", credit_limit_cents=100_000)
    payload.pop("currency", None)
    res = api.create_customer(payload, ar_manager_headers)
    customer = validate_success(res, 201)
    assert customer["currency"] == "USD"


def test_invoice_balance_computed_equals_face_at_creation(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.1: "On success the invoice starts in `OPEN` status with
    `balance_cents` equal to `face_amount_cents`, `disputed_amount_cents` zero,
    and `dunning_stage_index` zero".

    Design: Corner/entities/invoice_balance_computed_equals_face_at_creation
    """
    customer = create_customer(name="CompCo")
    payload = create_invoice_payload(
        customer["id"],
        invoice_date="2026-01-01T00:00:00Z",
        due_date="2026-02-01T00:00:00Z",
        face_amount_cents=7777,
    )
    payload["balance_cents"] = 1  # client attempt to set computed field — must be ignored
    res = api.create_invoice(payload, ar_clerk_headers)
    invoice = validate_success(res, 201)
    assert invoice["balance_cents"] == 7777


def test_payment_system_fields_generated_on_create(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID,
    with no type prefix."
    PRD §2.4: "`version` — an integer that starts at its initial value and
    increments by one on every mutation of the resource."

    Design: Corner/entities/system_fields_generated_on_create
    """
    customer = create_customer(name="SysCo")
    res = api.create_payment(
        create_payment_payload(customer["id"], amount_cents=5000, received_at="2026-03-01T00:00:00Z"),
        ar_clerk_headers,
    )
    payment = validate_success(res, 201)
    assert isinstance(payment["id"], str) and len(payment["id"]) > 0
    assert payment["version"] == 1


def test_invoice_initial_state_is_open(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.1: "On success the invoice starts in `OPEN` status with
    `balance_cents` equal to `face_amount_cents`, `disputed_amount_cents` zero,
    and `dunning_stage_index` zero".

    Design: Corner/state_machines/invoice_initial_state_is_open
    """
    customer = create_customer(name="InitCo")
    res = api.create_invoice(
        create_invoice_payload(
            customer["id"], face_amount_cents=1000,
            invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
        ),
        ar_clerk_headers,
    )
    invoice = validate_success(res, 201)
    assert_invoice(invoice)
    assert invoice["status"] == "OPEN"
    assert invoice["dunning_stage_index"] == 0


def test_list_invoices_paginated_envelope(api, ar_manager_headers, ar_clerk_headers, auditor_headers):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_invoices_paginated_envelope
    """
    customer = create_customer(name="ListCo")
    create_invoice(customer["id"], face_amount_cents=1000)
    create_invoice(customer["id"], face_amount_cents=2000)
    res = api.list_invoices(
        auditor_headers, params={"customer_id": customer["id"], "limit": 1, "offset": 0}
    )
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
