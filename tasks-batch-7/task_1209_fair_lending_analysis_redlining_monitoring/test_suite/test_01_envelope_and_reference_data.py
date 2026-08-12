"""Envelope, market/branch/application creation, and listing rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_application,
    assert_market,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_market_created_with_required_fields_and_defaults(api, bank_admin_headers):
    """PRD §3.1: "A `BankAdmin` registers each assessment area as a market
    carrying a display `name`, a unique `msa_code`, the
    `protected_group_population_share` of the market's population expressed
    as a fraction between 0 and 1 (this share later becomes the denominator
    of the branch-weighted penetration index), and a `peer_group_code`
    identifying the comparison cohort."
    PRD §4: "Creating a new resource returns HTTP 201".
    PRD §2.4: "an integer `version` that starts at 1 and increments by one
    on every mutation."

    Design: Corner/entities/market_created_with_required_fields_and_defaults
    """
    payload = {
        "name": "Metro One",
        "msa_code": "M001",
        "protected_group_population_share": 0.40,
        "peer_group_code": "PG7",
    }
    resp = api.create_market(payload, bank_admin_headers)
    data = validate_success(resp, expected_status=201)
    assert_market(data)
    assert data["name"] == "Metro One"
    assert data["msa_code"] == "M001"
    assert data["protected_group_population_share"] == pytest.approx(0.40)
    assert data["peer_group_code"] == "PG7"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_market_missing_required_field_returns_invalid_request(api, bank_admin_headers):
    """PRD §3.1: "A `BankAdmin` registers each assessment area as a market
    carrying a display `name`, a unique `msa_code`, the
    `protected_group_population_share` of the market's population expressed
    as a fraction between 0 and 1 (this share later becomes the denominator
    of the branch-weighted penetration index), and a `peer_group_code`
    identifying the comparison cohort."
    PRD §5: "ERR_INVALID_REQUEST | 400".

    Design: Corner/entities/market_missing_required_field_returns_invalid_request
    """
    payload = {
        "name": "Metro One",
        "protected_group_population_share": 0.40,
        "peer_group_code": "PG7",
    }
    resp = api.create_market(payload, bank_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    # No market persisted: the list stays empty.
    rows, meta = validate_paginated(api.list_markets(bank_admin_headers))
    assert meta["total_count"] == 0, f"no Market row may persist, got {meta['total_count']}"


def test_branch_create_with_unknown_market_returns_not_found(api, bank_admin_headers):
    """PRD §2.4: "Nested resource URLs are validated left to right: each path
    identifier must resolve to an existing resource before any body-level
    foreign key is examined, and the first unresolved identifier
    short-circuits the request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/branch_create_with_unknown_market_returns_not_found
    """
    payload = {
        "market_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
        "name": "Main",
        "tract_minority_pct": 55.0,
        "opened_on": "2020-01-15",
    }
    resp = api.create_branch(payload, bank_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_application_invalid_enum_returns_invalid_request(
    api, bank_admin_headers, data_ops_headers
):
    """PRD §3.2: "`outcome` drawn from `ORIGINATED`, `DENIED`, `WITHDRAWN`,
    or `APPROVED_NOT_ACCEPTED`".
    PRD §5: "ERR_INVALID_REQUEST | 400".

    Design: Corner/entities/application_invalid_enum_returns_invalid_request
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    branch = validate_success(
        api.create_branch(
            {"market_id": market["id"], "name": "Main", "tract_minority_pct": 55.0,
             "opened_on": "2020-01-15"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    officer = validate_success(
        api.create_loan_officer(
            {"branch_id": branch["id"], "full_name": "Officer One"}, bank_admin_headers
        ),
        expected_status=201,
    )
    payload = {
        "market_id": market["id"],
        "branch_id": branch["id"],
        "loan_officer_id": officer["id"],
        "product_type": "CONVENTIONAL",
        "applicant_group": "CONTROL",
        "outcome": "PENDING_REVIEW",
        "note_rate_bps": 700,
        "loan_amount_cents": 30_000_000,
        "credit_score": 720,
        "dti_pct": 36.0,
        "application_date": "2026-01-05",
        "decision_date": "2026-01-20",
    }
    resp = api.create_application(payload, data_ops_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_application_not_found_returns_404(api, data_ops_headers):
    """PRD §2.4: "the first unresolved identifier short-circuits the request
    with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/application_not_found_returns_404
    """
    resp = api.get_application(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", data_ops_headers
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_error_envelope_shape(api, bank_admin_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api.get_market(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", bank_admin_headers
    )
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}"
    body = resp.json()
    assert body.get("response_type") == "error", (
        f"response_type must be 'error', got {body.get('response_type')!r}"
    )
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    meta = body.get("meta", {})
    assert meta.get("api_request_id"), "meta.api_request_id must be present"
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "meta.api_request_timestamp must be an ISO 8601 timestamp"
    )


def test_computed_field_input_ignored(api, bank_admin_headers, data_ops_headers):
    """PRD §3.2: "New records land in `RECEIVED` status with `has_exception`
    set to `NONE`."

    Design: Corner/entities/computed_field_input_ignored
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    branch = validate_success(
        api.create_branch(
            {"market_id": market["id"], "name": "Main", "tract_minority_pct": 55.0,
             "opened_on": "2020-01-15"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    officer = validate_success(
        api.create_loan_officer(
            {"branch_id": branch["id"], "full_name": "Officer One"}, bank_admin_headers
        ),
        expected_status=201,
    )
    payload = {
        "market_id": market["id"],
        "branch_id": branch["id"],
        "loan_officer_id": officer["id"],
        "product_type": "CONVENTIONAL",
        "applicant_group": "CONTROL",
        "outcome": "ORIGINATED",
        "note_rate_bps": 700,
        "loan_amount_cents": 30_000_000,
        "credit_score": 720,
        "dti_pct": 36.0,
        "application_date": "2026-01-05",
        "decision_date": "2026-01-20",
        "status": "VALIDATED",
        "has_exception": "APPROVED",
    }
    data = validate_success(api.create_application(payload, data_ops_headers),
                            expected_status=201)
    assert_application(data)
    assert data["status"] == "RECEIVED", (
        f"client-supplied status must be ignored; got {data['status']}"
    )
    assert data["has_exception"] == "NONE", (
        f"client-supplied has_exception must be ignored; got {data['has_exception']}"
    )


def test_list_pagination_defaults_and_envelope(api, bank_admin_headers, data_ops_headers):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
    of 100; `offset` defaults to 0. List results are sorted by `created_at`
    ascending. The `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."

    Design: Corner/entities/list_pagination_defaults_and_envelope
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    branch = validate_success(
        api.create_branch(
            {"market_id": market["id"], "name": "Main", "tract_minority_pct": 55.0,
             "opened_on": "2020-01-15"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    officer = validate_success(
        api.create_loan_officer(
            {"branch_id": branch["id"], "full_name": "Officer One"}, bank_admin_headers
        ),
        expected_status=201,
    )
    for i in range(12):
        validate_success(
            api.create_application(
                {
                    "market_id": market["id"],
                    "branch_id": branch["id"],
                    "loan_officer_id": officer["id"],
                    "product_type": "CONVENTIONAL",
                    "applicant_group": "CONTROL",
                    "outcome": "ORIGINATED",
                    "note_rate_bps": 700,
                    "loan_amount_cents": 30_000_000,
                    "credit_score": 720 + i,
                    "dti_pct": 36.0,
                    "application_date": f"2026-01-{(i % 27) + 1:02d}",
                    "decision_date": f"2026-01-{(i % 27) + 1:02d}",
                },
                data_ops_headers,
            ),
            expected_status=201,
        )
    resp = api.list_applications(data_ops_headers)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    body = resp.json()
    assert body.get("response_type") == "array", (
        f"list response_type must be 'array', got {body.get('response_type')!r}"
    )
    assert body.get("meta", {}).get("api_request_id"), "meta.api_request_id present"
    data, meta = validate_paginated(resp)
    assert len(data) == 10, f"default limit returns 10 rows, got {len(data)}"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(
        api.list_applications(data_ops_headers, params={"limit": 5, "offset": 10})
    )
    assert len(data2) == 2, f"limit 5 offset 10 over 12 rows returns 2, got {len(data2)}"
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 12
