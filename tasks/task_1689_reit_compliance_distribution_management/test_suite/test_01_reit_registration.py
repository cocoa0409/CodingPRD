"""REIT registration, identity envelope, pagination and error envelope claims."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_iso8601_millis,
    assert_reit,
    create_reit,
    create_reit_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_reit_applies_computed_defaults(api, tax_director_headers):
    """PRD §3.1: "On creation the REIT's `status` is set to `ACTIVE`, its
    `current_ep_balance_cents` and `dividend_distribution_deficit_cents` are
    both initialized to 0, and `five_fifty_blocked` is initialized to false."
    PRD §2.4: "Each resource has an `id`, a server-minted UUID with no type
    prefix. Each carries `created_at`, an ISO 8601 UTC timestamp with three
    fractional digits, and `updated_at` in the same format. Each carries
    `version`, an integer that starts at its initial value on creation and
    increments by one on every mutation that touches the row".

    Design: Corner/entities/create_reit_applies_computed_defaults
    """
    resp = api.create_reit(
        create_reit_payload(legal_name="Corner REIT", ticker="CRNR"),
        tax_director_headers,
    )
    data = validate_success(resp, 201)
    assert_reit(data)
    assert data["status"] == "ACTIVE"
    assert data["current_ep_balance_cents"] == 0
    assert data["dividend_distribution_deficit_cents"] == 0
    assert data["five_fifty_blocked"] is False
    assert is_valid_uuid(data["id"])
    assert_iso8601_millis(data["created_at"])
    assert_iso8601_millis(data["updated_at"])


def test_create_reit_missing_ticker_returns_validation(api, tax_director_headers):
    """PRD §3.1: "A `TaxDirector` onboards a new trust by registering it with
    a `legal_name`, an exchange `ticker`, a `charter_ownership_limit_pct`, and
    a `taxable_year_start`."
    PRD §2.9: "then payload shape and enum/range checks (`ERR_VALIDATION`)".

    Design: Corner/entities/create_reit_missing_ticker_returns_validation
    """
    payload = create_reit_payload(legal_name="No Ticker")
    del payload["ticker"]
    resp = api.create_reit(payload, tax_director_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_reit_charter_limit_at_50_rejected(api, tax_director_headers):
    """PRD §3.1: "The ownership limit is the charter-imposed per-person
    concentration cap — a value such as 9.8 — and must lie strictly between 0
    and 50.0; a value outside that open interval is rejected with
    `ERR_VALIDATION`."

    Design: Corner/entities/create_reit_charter_limit_out_of_range_returns_validation
    """
    payload = create_reit_payload(legal_name="BadCap", ticker="BADC",
                                  charter_ownership_limit_pct=50.0)
    resp = api.create_reit(payload, tax_director_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_missing_reit_returns_not_found(api, compliance_officer_headers):
    """PRD §2.8: "A path id that does not resolve to an existing entity yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_missing_reit_returns_not_found
    """
    resp = api.get_reit(NON_EXISTENT_UUID, compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_duplicate_ticker_rejected(api, tax_director_headers):
    """PRD §2.10: "A REIT's `ticker` must be unique across all registered
    REITs." and "Violating any of these yields `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_ticker_rejected
    """
    first = api.create_reit(
        create_reit_payload(legal_name="First", ticker="DUPT"),
        tax_director_headers,
    )
    validate_success(first, 201)
    resp = api.create_reit(
        create_reit_payload(legal_name="Second", ticker="DUPT",
                            charter_ownership_limit_pct=9.5),
        tax_director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_list_reits_pagination_envelope(api, compliance_officer_headers,
                                        tax_director_headers):
    """PRD §2.3: "List endpoints accept two optional query parameters: `limit`
    and `offset`. When omitted, `limit` defaults to 10 and `offset` defaults
    to 0." and "The `meta` block of a list response carries four pagination
    fields — `limit`, `offset`, `total_count`, and `has_more` — so callers
    can page deterministically through the full set."

    Design: Corner/endpoints/list_reits_pagination_envelope
    """
    create_reit(legal_name="P1")
    create_reit(legal_name="P2")

    resp = api.list_reits(compliance_officer_headers,
                          params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return one row, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    body = resp.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "array"

    resp2 = api.list_reits(compliance_officer_headers,
                           params={"limit": 1, "offset": 1})
    data2, meta2 = validate_paginated(resp2)
    assert len(data2) == 1
    assert meta2["has_more"] is False


def test_error_envelope_shape_on_failure(api, board_director_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with "`response_type`: "error"" and a data
    block where "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    resp = api.get_quarter(NON_EXISTENT_UUID, board_director_headers)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert error["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"].strip()
