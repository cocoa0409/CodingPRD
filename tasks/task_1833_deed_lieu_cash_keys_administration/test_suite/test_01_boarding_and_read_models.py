"""Boarding reference data and read-model basics: loans, borrowers, properties,
case listing pagination, and FK/not-found resolution (PRD §2.3, §2.9, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_borrower,
    assert_loan,
    assert_property,
    assert_workout_case,
    board_loan,
    create_case_payload,
    create_property_payload,
    is_valid_uuid,
    open_workout_case,
    register_borrower,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_loan_boarding_computes_per_diem(api, servicing_admin_headers):
    """Boarding a loan derives per-diem interest server-side and births the loan
    ACTIVE_DELINQUENT with the referral default.

    PRD §3.1: "From these inputs the system derives `per_diem_interest_cents` — the unpaid principal balance multiplied by the note annual rate and divided by 365, rounded half-up to whole cents — computed at creation and again on any balance or rate change; any client-supplied value for it is ignored."
    PRD §3.1: "A freshly boarded loan has `status` `ACTIVE_DELINQUENT`, a `deficiency_balance_cents` of zero, and `servicing_system_synced` false."
    PRD §3.1: "The `foreclosure_referral_status` is one of `NONE`, `REFERRED`, `ACTIVE`, or `WITHDRAWN`, defaulting to `NONE` when omitted."

    Design: Corner/entities/loan_creation_computes_per_diem
    """
    payload = {
        "loan_number": "LN-E1",
        "unpaid_principal_balance_cents": 20000000,
        "accrued_interest_cents": 300000,
        "escrow_advances_cents": 120000,
        "foreclosure_fees_cents": 80000,
        "note_annual_rate": 0.06,
        "fair_market_value_cents": 18000000,
        "delinquency_days": 90,
        "per_diem_interest_cents": 999999,  # client-supplied: must be ignored
    }
    loan = validate_success(api.create_loan(payload, servicing_admin_headers), 201)
    assert_loan(loan)
    assert loan["per_diem_interest_cents"] == 3288, (
        f"per-diem must be round_half_up(20000000*0.06/365)=3288, got {loan['per_diem_interest_cents']}"
    )
    assert loan["status"] == "ACTIVE_DELINQUENT"
    assert loan["foreclosure_referral_status"] == "NONE"
    assert loan["deficiency_balance_cents"] == 0
    assert loan["servicing_system_synced"] is False


def test_property_default_condition_standard(api, servicing_admin_headers):
    """Omitting required_condition_standard yields the BROOM_CLEAN default.

    PRD §3.1: "Registering the subject property ties it to its loan through the `loan_id` in the payload and records the `address_line`, the `county` of record (which later determines where the deed is recorded), a two-letter `state_code`, an `occupancy_type` of `OWNER_OCCUPIED`, `TENANT_OCCUPIED`, or `SECOND_HOME`, and the `required_condition_standard` demanded at handover — currently only `BROOM_CLEAN` is supported, and it is the default."

    Design: Corner/entities/property_creation_applies_default_condition_standard
    """
    loan = board_loan("LN-E2", accrued_interest_cents=0, escrow_advances_cents=0, foreclosure_fees_cents=0)
    prop = validate_success(
        api.create_property(create_property_payload(loan["id"], address_line="7 Main St"), servicing_admin_headers),
        201,
    )
    assert_property(prop)
    assert prop["required_condition_standard"] == "BROOM_CLEAN"


def test_case_create_missing_borrower_id_rejected(api, specialist_headers):
    """A case payload lacking the required borrower_id is malformed.

    PRD §3.2: "A `PropertySolutionsSpecialist` opens a workout case with a payload carrying the `loan_id`, the `borrower_id`, and the `program_type` — `DEED_IN_LIEU` or `CASH_FOR_KEYS`."
    PRD §2.10: "Fourth, well-formedness: required fields are present, types are valid, enum values fall within their declared domains (an out-of-domain enum value is rejected with `ERR_INVALID_ENUM`, HTTP 400), integer cent fields respect their declared sign constraints, and datetimes are well formed; other malformations are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/case_creation_missing_borrower_id_returns_invalid_request
    """
    loan = board_loan("LN-E3", accrued_interest_cents=0, escrow_advances_cents=0, foreclosure_fees_cents=0)
    resp = api.create_case({"loan_id": loan["id"], "program_type": "DEED_IN_LIEU"}, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    # No case was created for the loan.
    data, meta = validate_paginated(api.list_cases(specialist_headers, params={"loan_id": loan["id"]}))
    assert meta["total_count"] == 0 and data == []


def test_property_invalid_occupancy_enum_rejected(api, servicing_admin_headers):
    """An occupancy_type outside its declared domain is rejected as an enum error.

    PRD §3.1: "an `occupancy_type` of `OWNER_OCCUPIED`, `TENANT_OCCUPIED`, or `SECOND_HOME`"
    PRD §2.10: "Fourth, well-formedness: required fields are present, types are valid, enum values fall within their declared domains (an out-of-domain enum value is rejected with `ERR_INVALID_ENUM`, HTTP 400), integer cent fields respect their declared sign constraints, and datetimes are well formed; other malformations are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/invalid_occupancy_enum_rejected
    """
    loan = board_loan("LN-E4", accrued_interest_cents=0, escrow_advances_cents=0, foreclosure_fees_cents=0)
    resp = api.create_property(
        create_property_payload(loan["id"], address_line="8 Main St", occupancy_type="IGLOO"),
        servicing_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_get_case_not_found_returns_404(api, specialist_headers):
    """GET on a well-formed but nonexistent case id returns the case 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    resp = api.get_case(NON_EXISTENT_UUID, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND.value)


def test_cases_list_pagination_and_loan_filter(api, specialist_headers):
    """List responses carry the pagination meta; the cases list filters by loan.

    PRD §2.3: "List endpoints paginate through two query parameters: `limit` — the maximum number of items to return, defaulting to 10, with a minimum of 1 and a maximum of 100 — and `offset` — the number of items to skip, defaulting to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."
    PRD §2.3: "Several lists additionally accept filters: the loans list and the junior-liens list accept `status`, the properties list accepts `loan_id`, and the cases list accepts `loan_id`, `borrower_id`, and `status`."

    Design: Corner/entities/cases_list_pagination_envelope
    """
    loan = board_loan("LN-E6", accrued_interest_cents=0, escrow_advances_cents=0, foreclosure_fees_cents=0)
    borrower = register_borrower(full_name="E. Six", email="e6@x.com", hardship_type="NONE",
                               self_reported_condition_grade="A")
    case = open_workout_case(loan["id"], borrower["id"], "CASH_FOR_KEYS")

    resp = api.list_cases(specialist_headers)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert_workout_case(data[0])

    filtered, meta2 = validate_paginated(api.list_cases(specialist_headers, params={"loan_id": loan["id"]}))
    assert meta2["total_count"] == 1
    assert [c["id"] for c in filtered] == [case["id"]]

    other, meta3 = validate_paginated(api.list_cases(specialist_headers, params={"loan_id": NON_EXISTENT_UUID}))
    assert meta3["total_count"] == 0 and other == []


def test_property_with_unknown_loan_returns_not_found(api, servicing_admin_headers):
    """A property payload whose loan_id does not resolve fails FK resolution.

    PRD §2.9: "The same resolution duty applies to foreign-key references inside request payloads — `loan_id`, `borrower_id`, `case_id`, `agreement_id`, and `lien_id` must each resolve, and a `lien_id` in a lien-release payload must resolve on the addressed title commitment."
    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/property_with_unknown_loan_returns_not_found
    """
    resp = api.create_property(
        create_property_payload(NON_EXISTENT_UUID, address_line="9 Main St"), servicing_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_FOUND.value)
