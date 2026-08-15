"""Entity defaults, request shape, existence, and append-only record shape
(PRD §2.2, §2.4, §2.5, §2.7, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_customer,
    assert_payment,
    complete_milestones_seq,
    create_customer,
    create_tool_design_payload,
    get_job_version,
    get_success_data,
    invoice_milestones_seq,
    is_valid_uuid,
    make_customer_headers,
    record_payment_payload,
    setup_booked_job,
    start_build,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["shop_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
FIN_PAYER = TEST_USERS["finance_payer_headers"]


def test_customer_creation_defaults_and_system_fields(api):
    """PRD §3.1: "The credit limit defaults to 0 — meaning unlimited — and may
    not be negative. New customers start in `ACTIVE` status with an
    `outstanding_balance_cents` of zero."
    PRD §2.5: "Every persisted resource carries an `id` — a server-minted UUID
    with no type prefix — plus `created_at` and `updated_at` timestamps in ISO
    8601 UTC with three fractional digits, and a `version` integer that
    increments on every mutation of the resource."
    PRD §2.4: "Before any operator sets it, the logical clock starts at
    exactly 2026-08-01T00:00:00Z."

    Design: Corner/entities/customer_creation_defaults_and_system_fields
    """
    res = api_client.create_customer(
        {"company_name": "Default Co", "contact_email": "df@x.com"}, ADMIN
    )
    customer = validate_success(res, 201)

    assert_customer(customer)
    assert customer["credit_limit_cents"] == 0
    assert customer["status"] == "ACTIVE"
    assert customer["outstanding_balance_cents"] == 0
    assert is_valid_uuid(customer["id"]), "id must be a bare UUID with no type prefix"
    assert isinstance(customer["version"], int)
    # Datetime comparisons resolve to the second (PRD §2.4).
    assert customer["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at must stamp the logical-clock default, got {customer['created_at']}"
    )


def test_customer_missing_required_field_rejected(api):
    """PRD §3.1: "A `ShopAdmin` onboards each customer with a `company_name`,
    a `contact_email`, and an optional `credit_limit_cents`."
    PRD §2.7: "Required fields are present, unknown payload keys are rejected,
    enum values are in-domain (`die_class`, `tool_type`, `quote_kind`,
    `decision`, `target_state`, `press_id`, `machine_id`, `warranty_terms`),
    and declared ranges hold: `cavity_count` between 1 and 64 inclusive,
    `design_complexity_score` between 1 and 20 inclusive,
    `requested_lead_weeks` at least 1, `affects_from_milestone_seq` between 1
    and 6 inclusive, monetary and quantity amounts at their declared minimums
    of 0 or 1. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400), with
    out-of-domain enum values surfaced as `ERR_INVALID_ENUM_VALUE` (HTTP
    400)."

    Design: Corner/entities/customer_missing_required_field_rejected
    """
    res = api_client.create_customer({"contact_email": "nofields@x.com"}, ADMIN)
    error = validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    assert error["error_id"] == "ERR_INVALID_REQUEST"
    assert res.status_code == 400

    _, meta = validate_paginated(api_client.list_customers(ADMIN))
    assert meta["total_count"] == 0, "a rejected create must persist nothing"


def test_design_invalid_die_class_enum_rejected(api):
    """PRD §3.2: "`tool_type` is one of `PROGRESSIVE_DIE`, `TRANSFER_DIE`,
    `INJECTION_MOLD`, `BLOW_MOLD`, or `COMPRESSION_MOLD`; `die_class` is one
    of `CLASS_101` through `CLASS_105`."
    PRD §2.7: "Violations surface as `ERR_INVALID_REQUEST` (HTTP 400), with
    out-of-domain enum values surfaced as `ERR_INVALID_ENUM_VALUE` (HTTP
    400)."

    Design: Corner/entities/design_invalid_die_class_enum_rejected
    """
    customer = create_customer(company_name="Enum Co")
    payload = create_tool_design_payload(customer["id"], part_number="PN-E1",
                                         die_class="CLASS_999")
    res = api_client.create_tool_design(payload, make_customer_headers(customer["id"]))
    error = validate_error(res, ApiErrorId.ERR_INVALID_ENUM_VALUE)
    assert error["error_id"] == "ERR_INVALID_ENUM_VALUE"
    assert res.status_code == 400


def test_nonexistent_quote_returns_not_found(api):
    """PRD §2.7: "Path identifiers are validated left to right, then body
    foreign keys; each missing resource surfaces its own 404 —
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_TOOL_DESIGN_NOT_FOUND`,
    `ERR_QUOTE_NOT_FOUND`, `ERR_BUILD_JOB_NOT_FOUND`,
    `ERR_BUILD_MILESTONE_NOT_FOUND`, `ERR_PROGRESS_INVOICE_NOT_FOUND`,
    `ERR_PAYMENT_NOT_FOUND`, `ERR_TRYOUT_SAMPLE_NOT_FOUND`,
    `ERR_ENGINEERING_CHANGE_NOT_FOUND`, `ERR_REWORK_AUTHORIZATION_NOT_FOUND`,
    `ERR_TOOL_ASSET_NOT_FOUND`, `ERR_SHOT_REPORT_NOT_FOUND`,
    `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_SPARE_INSERT_NOT_FOUND`,
    `ERR_PRESS_RESERVATION_NOT_FOUND`, or `ERR_MACHINE_RESERVATION_NOT_FOUND`."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/nonexistent_quote_returns_not_found
    """
    res = api_client.get_quote(NON_EXISTENT_UUID, ESTIMATOR)
    error = validate_error(res, ApiErrorId.ERR_QUOTE_NOT_FOUND)
    assert error["error_id"] == "ERR_QUOTE_NOT_FOUND"
    assert res.status_code == 404
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_payment_is_append_only_without_version(api):
    """PRD §2.5: "Two resources are exceptions: payments and shot reports
    carry only `id` and `created_at`; both `updated_at` and `version` are
    absent from them."
    PRD §3.5: "Walking that order, each invoice receives the smaller of its
    `balance_due_cents` and the remaining unallocated cash; each allocation is
    recorded as an `invoice_id` and `applied_cents` pair in the payment's
    `allocations` array in allocation order, skipping any invoice that would
    receive zero. An invoice whose balance is fully covered moves to `PAID` —
    with `paid_cents` equal to `amount_cents` and `balance_due_cents` zeroed —
    and an invoice partially covered moves from `ISSUED` to `PARTIALLY_PAID`;
    both recompute `paid_cents` and `balance_due_cents`."

    Design: Corner/entities/payment_entity_immutable_no_version
    """
    ctx = setup_booked_job(company_name="Imm Co", part_number="PN-IM1")
    start_build(ctx["job"]["id"])
    complete_milestones_seq(ctx["milestones"], ctx["customer"]["id"], seqs=(1,))
    invoices = invoice_milestones_seq(ctx["milestones"], seqs=(1,))
    invoice_id = invoices[1]["id"]
    assert invoices[1]["amount_cents"] == 2_100_000

    version = get_job_version(ctx["job"]["id"])
    payment = validate_success(
        api_client.record_payment(
            ctx["job"]["id"], record_payment_payload(1, version), FIN_PAYER
        ),
        201,
    )
    assert_payment(payment)
    assert "version" not in payment, "payment must not carry a version key"
    assert "updated_at" not in payment, "payment must not carry an updated_at key"
    assert payment["allocations"] == [{"invoice_id": invoice_id, "applied_cents": 1}]

    fetched = validate_success(api_client.get_payment(payment["id"], ADMIN), 200)
    assert "version" not in fetched
    assert "updated_at" not in fetched

    invoice = get_success_data(api_client.get_progress_invoice(invoice_id, ADMIN))
    assert invoice["status"] == "PARTIALLY_PAID"
    assert invoice["balance_due_cents"] == 2_099_999
    assert invoice["paid_cents"] == 1
