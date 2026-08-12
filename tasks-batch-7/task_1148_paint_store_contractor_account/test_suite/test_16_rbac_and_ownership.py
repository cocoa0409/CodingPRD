"""Role denial (PRD §2.1, §4) and the fixed error envelope (PRD §2.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_product,
    create_product_payload,
    create_spec_sheet_with_line,
    make_contractor_headers,
    setup_paid_order_with_delivery,
    submit_spec_sheet,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
WRITER = TEST_USERS["spec_writer_headers"]


def test_specwriter_cannot_approve_own_spec(api):
    """PRD §2.1: "`SpecWriter` — specification services: writes, submits, and
    revises spec sheets for architects; cannot approve them." PRD §2.1: "A
    request whose role is authenticated but not permitted for the addressed
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/specwriter_cannot_approve_own_spec
    """
    product = create_product(sku="P-RB1", name="Can", list_price_cents=5000)
    sheet = create_spec_sheet_with_line(product["id"], project_code="PRJ-RB",
                                        specified_qty=5)
    submit_spec_sheet(sheet["id"])
    resp = api.approve_spec_sheet(sheet["id"], WRITER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = validate_success(api.get_spec_sheet(sheet["id"], WRITER))
    assert after["status"] == "SUBMITTED", (
        f"the refused approval must not move the sheet, got {after['status']}")


def test_associate_cannot_dispatch_delivery(api):
    """PRD §2.1: "`StoreManager` — store operator: owns delivery scheduling,
    dispatch, completion, and failure, mistint write-off, and shares
    job-account lifecycle actions with the owning contractor." PRD §2.1: "A
    request whose role is authenticated but not permitted for the addressed
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." The §4 routing
    table lists dispatch under StoreManager only.

    Design: Corner/rbac/associate_cannot_dispatch_delivery
    """
    account, job, product, order, delivery = setup_paid_order_with_delivery(
        window_start="2026-06-25T09:00:00Z", window_end="2026-06-25T10:00:00Z",
        jurisdiction_code="SC-OPEN")
    resp = api.dispatch_delivery(delivery["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = validate_success(api.get_delivery(delivery["id"], ASSOCIATE))
    assert after["status"] == "SCHEDULED", (
        f"the refused dispatch must not move the delivery, got {after['status']}")


def test_contractor_cannot_manage_catalog(api):
    """PRD §2.1: "`CorporateAdmin` — head-office operator: owns the catalog
    (jurisdictions, VOC rules, products, bulletins), contractor account
    administration, tier evaluation, rebate settlement, spec-sheet approval,
    formula retirement, and the logical clock." PRD §2.1: "`Contractor` — a
    contractor account holder acting on its own account, jobs, orders,
    color-match requests, and rebate statements." PRD §2.1: "A request whose
    role is authenticated but not permitted for the addressed endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." The §4 routing table lists
    POST /products under CorporateAdmin only.

    Design: Corner/rbac/contractor_cannot_manage_catalog
    """
    account = validate_success(
        api.create_contractor_account(
            {"company_name": "RB3 Co", "credit_limit_cents": 1_000_000}, ADMIN),
        expected_status=201)
    payload = create_product_payload(sku="P-RB3", name="Hack", list_price_cents=1)
    resp = api.create_product(payload, make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format: ... The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`. The `error_id`
    is a unique, machine-readable string that identifies the specific error.
    The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api.get_product(NON_EXISTENT_UUID, ADMIN)
    body = resp.json()
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}"
    assert body["response_type"] == "error", (
        f"error responses are response_type error, got {body['response_type']}")
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], \
        "message must be a non-empty human-readable string"
    assert "meta" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
