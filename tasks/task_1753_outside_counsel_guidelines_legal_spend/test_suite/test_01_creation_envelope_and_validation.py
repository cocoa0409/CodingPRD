"""Creation defaults, response envelope, pagination, and base validation rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_legal_department,
    assert_matter,
    create_legal_department_payload,
    create_matter,
    create_department,
    create_firm,
    firm_headers,
    is_iso8601_timestamp,
    is_valid_uuid,
    ops_headers,
    setup_department_with_firm,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_legal_department_creation_returns_defaults(api, legal_ops_headers):
    """PRD §2.4: "`id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments by one on every mutation, including mutations caused by cascades and derived-field recomputation."
    PRD §2.4: "Newly created resources return `201 Created`; operations that modify an existing resource return `200 OK`."

    Design: Corner/entities/legal_department_creation_returns_defaults
    """
    resp = api.create_legal_department(create_legal_department_payload(name="D"), legal_ops_headers)
    data = validate_success(resp, 201)
    assert_legal_department(data)
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data["updated_at"]), "updated_at must be ISO 8601"


def test_matter_spend_counters_start_at_zero(api, legal_ops_headers):
    """PRD §3.3: "The matter begins with `engagement_status` `PENDING`, and its two spend counters start at zero: `billed_to_date_cents`, the running sum of approved line amounts across all non-voided invoices, and `accrual_outstanding_cents`, the sum of accrual amounts not yet matched by a submitted invoice."

    Design: Corner/entities/matter_computed_fields_ignore_input
    """
    dept, firm = setup_department_with_firm()
    resp = api.create_matter(
        dept["id"],
        {"panel_firm_id": firm["id"], "title": "M", "budget_cents": 1000},
        legal_ops_headers,
    )
    data = validate_success(resp, 201)
    assert_matter(data)
    assert data["billed_to_date_cents"] == 0, (
        f"billed_to_date_cents must start at 0, got {data['billed_to_date_cents']}"
    )
    assert data["accrual_outstanding_cents"] == 0, (
        f"accrual_outstanding_cents must start at 0, got {data['accrual_outstanding_cents']}"
    )
    assert data["engagement_status"] == "PENDING"


def test_timekeeper_invalid_tk_class_rejected(api):
    """PRD §3.4: "A `PanelFirmUser` registers a timekeeper with a `full_name` and a `tk_class` of `PARTNER`, `ASSOCIATE`, or `PARALEGAL`; the classification matters because it drives the rate-increase sub-cap below."

    Design: Corner/entities/timekeeper_invalid_tk_class_rejected
    """
    dept, firm = setup_department_with_firm()
    resp = api.create_timekeeper(
        dept["id"], firm["id"],
        {"full_name": "X", "tk_class": "PARTNER_SHIP"},
        firm_headers(firm["id"]),
    )
    assert 400 <= resp.status_code < 500, (
        f"out-of-set tk_class must be rejected with a 4xx error, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("response_type") == "error", f"expected error envelope, got {body!r}"
    assert isinstance(body["data"].get("error_id"), str) and body["data"]["error_id"]


def test_get_nonexistent_matter_returns_404(api, legal_ops_headers):
    """PRD §2.6: "The server validates path identifiers strictly left to right: it confirms the legal department exists before it looks for the panel firm or matter within it, confirms that scope before descending further, and rejects the request immediately with `ERR_NOT_FOUND` at the first identifier that does not resolve within its expected parent scope."

    Design: Corner/entities/get_nonexistent_matter_returns_404
    """
    dept = create_department()
    resp = api.get_matter(dept["id"], NON_EXISTENT_UUID, legal_ops_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_matter_creation_missing_budget_rejected(api, legal_ops_headers):
    """PRD §3.3: "A `LegalOpsReviewer` creates a matter under a department by naming the engaged `panel_firm_id`, a `title`, and a `budget_cents` cap in cents."

    Design: Corner/entities/matter_creation_missing_required_field
    """
    dept, firm = setup_department_with_firm()
    resp = api.create_matter(
        dept["id"],
        {"panel_firm_id": firm["id"], "title": "NoBudget"},
        legal_ops_headers,
    )
    assert 400 <= resp.status_code < 500, (
        f"missing required budget_cents must be rejected with a 4xx error, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("response_type") == "error", f"expected error envelope, got {body!r}"


def test_matter_listing_pagination_envelope(api, legal_ops_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/matter_listing_pagination_envelope
    """
    dept, firm = setup_department_with_firm()
    create_matter(dept["id"], firm["id"], title="M1", budget_cents=1000)
    create_matter(dept["id"], firm["id"], title="M2", budget_cents=1000)

    resp = api.list_matters(dept["id"], legal_ops_headers, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    body = resp.json()
    assert body["response_type"] == "array", f"list responses use response_type 'array', got {body['response_type']!r}"
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_")
    assert isinstance(data, list) and len(data) == 1, f"limit=1 must return exactly 1 item, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when a second item remains"
    assert meta["limit"] == 1 and meta["offset"] == 0


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.create_legal_department(create_legal_department_payload(name="D"), headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_role_not_permitted_returns_403(api, panel_firm_headers):
    """PRD §2.1: "Write operations are restricted per endpoint, and a caller whose role is not permitted on an endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "`PanelFirmUser` — staff at an outside panel firm. This role acknowledges guidelines, accepts matter engagements, drafts and submits rate cards and rate rows, registers timekeepers, submits invoices, voids rejected invoices, files appeals, and submits monthly accruals."

    Design: Corner/validations/role_not_permitted_returns_403
    """
    resp = api.create_legal_department(create_legal_department_payload(name="D"), panel_firm_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
