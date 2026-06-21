"""Corner coverage: entity creation, defaults, system fields, not-found, required
fields, type constraints, and listing (Queue B: entities)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_iso8601_timestamp,
    setup_application_line,
    create_borrower,
    create_property,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
)

OFFICER = TEST_USERS["loan_officer_headers"]


def test_create_heloc_returns_201_application(api):
    """PRD §3.3: "A line's status begins at APPLICATION ..."
    PRD §3.3: "At creation the computed monetary fields are all zero: current_balance_cents,
    available_credit_cents, current_apr_bps, accrued_interest_cents, delinquency_days,
    and anniversary_count all start at 0."
    PRD §2.4: "version — a system-managed integer that starts at 1 ..."

    Design: Corner/entities/create_heloc_with_all_required_fields_returns_201
    """
    bor = create_borrower()
    prop = create_property()
    heloc = validate_success(
        api.create_heloc(
            {
                "borrower_id": bor["id"],
                "property_id": prop["id"],
                "lien_position": "SECOND",
                "credit_limit_cents": 50000000,
                "margin_bps": 150,
                "rate_ceiling_bps": 1800,
                "origination_date": "2026-01-01T00:00:00Z",
            },
            OFFICER,
        ),
        201,
    )
    assert heloc["status"] == "APPLICATION"
    assert heloc["current_balance_cents"] == 0
    assert heloc["version"] == 1


def test_get_nonexistent_heloc_returns_not_found(api):
    """PRD §2.6: "the system validates the existence of each path-referenced resource in
    strict left-to-right order, rejecting the request with ERR_NOT_FOUND (HTTP 404) at
    the first path segment that does not resolve to an existing resource."

    Design: Corner/entities/get_heloc_nonexistent_returns_not_found
    """
    resp = api.get_heloc(NON_EXISTENT_UUID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_borrower_missing_credit_score_rejected(api):
    """PRD §3.1: "A borrower is created with a legal full_name, a verified gross
    annual_income_cents, an optional existing monthly_debt_obligation_cents ..., and a
    credit_score."
    PRD §3.12: "Body field constraints (positive amounts, enum membership, the
    credit-score range, and the credit-limit floor) that are violated on any create or
    update with a body are rejected with ERR_INVALID_REQUEST (HTTP 422)."

    credit_score is required (not optional); omitting it is rejected.

    Design: Corner/entities/create_borrower_missing_required_field_returns_invalid_request
    """
    resp = api.create_borrower(
        {"full_name": "No Score", "annual_income_cents": 50000000}, OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_borrower_credit_score_out_of_range_rejected(api):
    """PRD §3.1: "The credit score is a FICO figure constrained to the range 300 through
    850 inclusive."

    credit_score 900 (> 850) is rejected.

    Design: Corner/entities/borrower_credit_score_out_of_range_returns_invalid_request
    """
    resp = api.create_borrower(
        {
            "full_name": "Bad Score",
            "annual_income_cents": 50000000,
            "credit_score": 900,
            "kyc_status": "CLEARED",
        },
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_heloc_credit_limit_below_floor_rejected(api):
    """PRD §3.3: "the committed credit_limit_cents (which must be at least 100000) ..."

    credit_limit_cents 50000 (< 100000 floor) is rejected.

    Design: Corner/entities/heloc_credit_limit_below_floor_returns_invalid_request
    """
    bor = create_borrower()
    prop = create_property()
    resp = api.create_heloc(
        {
            "borrower_id": bor["id"],
            "property_id": prop["id"],
            "lien_position": "FIRST",
            "credit_limit_cents": 50000,
            "margin_bps": 150,
            "rate_ceiling_bps": 1800,
            "origination_date": "2026-01-01T00:00:00Z",
        },
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_borrower_defaults_kyc_pending_and_debt_zero(api):
    """PRD §3.1: "A borrower also carries a kyc_status recording the Know-Your-Customer
    outcome, one of PENDING, CLEARED, or REJECTED; when omitted at creation it defaults
    to PENDING."
    PRD §3.1: "an optional existing monthly_debt_obligation_cents (the borrower's monthly
    debt service excluding this HELOC, defaulting to 0 when omitted) ..."

    Design: Corner/entities/borrower_default_kyc_status_pending_applied
    """
    bor = validate_success(
        api.create_borrower(
            {"full_name": "Def KYC", "annual_income_cents": 50000000, "credit_score": 750},
            OFFICER,
        ),
        201,
    )
    assert bor["kyc_status"] == "PENDING"
    assert bor["monthly_debt_obligation_cents"] == 0


def test_heloc_apr_computed_zero_before_activation(api):
    """PRD §3.3: "At creation the computed monetary fields are all zero:
    current_balance_cents, available_credit_cents, current_apr_bps, accrued_interest_cents,
    delinquency_days, and anniversary_count all start at 0."
    PRD §2.4: "id — a unique, server-minted identifier formatted as a UUID ..."

    Design: Corner/entities/heloc_id_and_system_fields_server_minted
    """
    bor = create_borrower()
    prop = create_property()
    heloc = validate_success(
        api.create_heloc(
            {
                "borrower_id": bor["id"],
                "property_id": prop["id"],
                "lien_position": "FIRST",
                "credit_limit_cents": 50000000,
                "margin_bps": 150,
                "rate_ceiling_bps": 1800,
                "origination_date": "2026-01-01T00:00:00Z",
            },
            OFFICER,
        ),
        201,
    )
    assert heloc["current_apr_bps"] == 0, "current_apr_bps is 0 until activation"
    assert is_iso8601_timestamp(heloc["created_at"]), "created_at must be a server ISO8601 timestamp"


def test_list_helocs_paginated_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and has_more
    in the meta object of the envelope."

    Design: Corner/entities/list_helocs_pagination_envelope
    """
    setup_application_line(attach_covenants=False, publish_index_rate=False)
    data, meta = validate_paginated(api.list_helocs(OFFICER, params={"status": "APPLICATION"}))
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)
