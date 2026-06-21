"""Entity creation, required fields, enum validity, not-found, defaults, and
system-minted fields at origination."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    is_valid_uuid,
    TEST_USERS,
    setup_originated_loan,
    ensure_profile,
    create_borrower,
    create_vehicle,
    set_clock,
    CLOCK_ORIGIN,
    create_borrower_payload,
    create_appraisal_payload,
)

_UW = TEST_USERS["underwriter_headers"]
_APPR = TEST_USERS["appraiser_headers"]
_SERVICER = TEST_USERS["loan_servicer_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Corner: create borrower -> status defaults ACTIVE, server-minted UUID id
# ─────────────────────────────────────────────────────────────────────────
def test_create_borrower_success_returns_active_status(api):
    """PRD §3.1: "A borrower's lifecycle status begins at ACTIVE and may become BARRED".
    PRD §2.4: "Every primary resource carries a server-minted id formatted as a UUID
    with no type prefix."

    Design: Corner/entities/create_borrower_success_returns_active_status
    """
    res = api.create_borrower(
        create_borrower_payload(email="newb@example.com", full_name="New B",
                                state_code="CA", monthly_income_cents=400000), _UW)
    borrower = validate_success(res, 201)
    assert borrower["status"] == "ACTIVE"
    assert is_valid_uuid(borrower["id"])
    assert "_" not in borrower["id"]


# ─────────────────────────────────────────────────────────────────────────
# Corner: missing required field -> ERR_INVALID_REQUEST
# ─────────────────────────────────────────────────────────────────────────
def test_create_borrower_missing_state_code_returns_invalid_request(api):
    """PRD §3.1: "a two-letter state_code of residence that must be one of CA, TX, FL,
    VA, or AZ".
    PRD §2.6: "request-body field presence, type, and enum-member validity
    (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_borrower_missing_state_code_returns_invalid_request
    """
    res = api.create_borrower(
        {"email": "nob@example.com", "full_name": "No State", "monthly_income_cents": 400000}, _UW)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────
# Corner: invalid enum member -> ERR_INVALID_REQUEST
# ─────────────────────────────────────────────────────────────────────────
def test_create_borrower_invalid_state_enum_returns_invalid_request(api):
    """PRD §3.1: "a two-letter state_code of residence that must be one of CA, TX, FL,
    VA, or AZ".
    PRD §2.6: "request-body field presence, type, and enum-member validity
    (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_borrower_invalid_state_enum_returns_invalid_request
    """
    res = api.create_borrower(
        create_borrower_payload(email="ny@example.com", full_name="NY Person",
                                state_code="NY", monthly_income_cents=400000), _UW)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────
# Corner: GET non-existent loan -> ERR_NOT_FOUND
# ─────────────────────────────────────────────────────────────────────────
def test_get_loan_nonexistent_id_returns_not_found(api):
    """PRD §2.5: "the system resolves each one to an existing entity, evaluated
    left-to-right, and rejects the request with ERR_NOT_FOUND at the first identifier
    that does not resolve."

    Design: Corner/entities/get_loan_nonexistent_id_returns_not_found
    """
    res = api.get_loan("00000000-0000-4000-8000-000000000000", _SERVICER)
    validate_error(res, "ERR_NOT_FOUND")


# ─────────────────────────────────────────────────────────────────────────
# Corner: appraisal status defaults to DRAFT on create
# ─────────────────────────────────────────────────────────────────────────
def test_appraisal_status_defaults_to_draft_on_create(api):
    """PRD §3.2: "An Appraiser creates an appraisal in DRAFT status against a
    vehicle_id".

    Design: Corner/entities/appraisal_status_defaults_to_draft_on_create
    """
    set_clock(CLOCK_ORIGIN)
    ensure_profile()
    borrower = create_borrower()
    vehicle = create_vehicle(borrower["id"])
    res = api.create_appraisal(create_appraisal_payload(vehicle["id"]), _APPR)
    appraisal = validate_success(res, 201)
    assert appraisal["status"] == "DRAFT"


# ─────────────────────────────────────────────────────────────────────────
# Corner: loan system fields minted at origination
# ─────────────────────────────────────────────────────────────────────────
def test_loan_system_fields_minted_at_origination(api):
    """PRD §3.3: "A new loan is created with payoff_status of OUTSTANDING and
    delinquency_status of CURRENT, whose original_principal_cents equals the
    application's requested_principal_cents."
    PRD §3.4: "the outstanding principal_balance_cents".

    Design: Corner/entities/loan_system_fields_minted_at_origination
    """
    ctx = setup_originated_loan()
    loan = get_success_data(api.get_loan(ctx["loan"]["id"], _SERVICER))
    assert loan["original_principal_cents"] == 600000
    assert loan["principal_balance_cents"] == 600000


# ─────────────────────────────────────────────────────────────────────────
# Corner: filtered loans by borrower_id
# ─────────────────────────────────────────────────────────────────────────
def test_filtered_loans_by_borrower_id(api):
    """PRD §3.4: "Loans can be fetched individually and listed with filters by
    application_id, borrower_id, or vehicle_id."

    Design: Corner/endpoints/filtered_loans_by_borrower_id
    """
    ctx = setup_originated_loan()
    borrower_id = ctx["borrower"]["id"]
    data = get_success_data(api.list_loans(_SERVICER, params={"borrower_id": borrower_id}))
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["borrower_id"] == borrower_id
