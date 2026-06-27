"""Corner coverage — entities: creation, defaults, not-found, required-field and
type validation, system-field protection, and list-envelope shape.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_office, create_client, setup_office_with_preparer,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
)

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


def test_create_office_returns_201_with_defaults(api):
    """PRD §3.1: "On creation the office's efin_status is ACTIVE and its
    open_return_count is zero."
    PRD §3.1: "may optionally pass bank_product_enabled to declare whether the
    office is licensed to offer refund-transfers and advances; when omitted,
    bank products are disabled."

    Design: Corner/entities/create_office_returns_201_with_defaults
    """
    res = api.create_office({"name": "Fresh Office", "efin": "100001", "state_code": "CA"}, OM)
    office = validate_success(res, 201)
    assert office["efin_status"] == "ACTIVE"
    assert office["open_return_count"] == 0
    assert office["version"] == 1
    assert office["bank_product_enabled"] is False


def test_get_return_nonexistent_returns_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing
    resource causes the request to be rejected with ERR_NOT_FOUND (HTTP 404)"

    Design: Corner/entities/get_return_nonexistent_returns_not_found
    """
    res = api.get_return(NON_EXISTENT_UUID, OM)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_return_missing_office_id_invalid_request(api):
    """PRD §2.5: "then request-body well-formedness (ERR_INVALID_REQUEST, 422)
    on create and transition endpoints, covering required fields present"
    PRD §3.3: "The opener supplies office_id, client_id, and tax_year"

    Design: Corner/entities/create_return_missing_required_office_id_returns_invalid_request
    """
    office = create_office()
    client = create_client(office["id"], full_name="Req Cli", ssn_last4="3030")
    res = api.create_return({"client_id": client["id"], "tax_year": 2025}, FD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_return_default_kind_band_status(api):
    """PRD §3.3: "The return_kind is one of ORIGINAL, PRIOR_YEAR, or
    AMENDED_1040X, defaulting to ORIGINAL. The complexity_band is one of SIMPLE,
    STANDARD, or COMPLEX, defaulting to SIMPLE"
    PRD §3.3: "A new return opens in INTAKE status"

    Design: Corner/entities/create_return_default_kind_and_band_applied
    """
    office = create_office()
    client = create_client(office["id"], full_name="Def Cli", ssn_last4="3131")
    res = api.create_return({"office_id": office["id"], "client_id": client["id"], "tax_year": 2025}, FD)
    ret = validate_success(res, 201)
    assert ret["return_kind"] == "ORIGINAL"
    assert ret["complexity_band"] == "SIMPLE"
    assert ret["status"] == "INTAKE"


def test_create_client_invalid_risk_band_rejected(api):
    """PRD §3.2: "The risk_band defaults to MEDIUM and is one of LOW, MEDIUM, or
    HIGH"
    PRD §2.5: "then request-body well-formedness (ERR_INVALID_REQUEST, 422) ...
    covering required fields present, enum values in range"

    Design: Corner/entities/create_client_invalid_risk_band_enum_rejected
    """
    office = create_office()
    res = api.create_client(
        office["id"], {"full_name": "Enum Cli", "ssn_last4": "3232", "risk_band": "EXTREME"}, FD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_appointment_end_not_after_start_rejected(api):
    """PRD §2.5: "an appointment's end_utc strictly after its start_utc"
    PRD §3.2: "end_utc (the exclusive end, which must be strictly after
    start_utc)"

    Design: Corner/entities/appointment_end_not_after_start_rejected
    """
    office, _, prep, _ = setup_office_with_preparer(credential_overrides={"ptin": "P50505050"})
    client = create_client(office["id"], full_name="Bw Cli", ssn_last4="3434")
    res = api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T10:00:00Z"}, FD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_system_fields_ignored_on_return_create(api):
    """PRD §3.3: "A new return opens in INTAKE status, its preparer_id is null
    until assignment, its computed prep_fee_cents is unset until preparation"

    Design: Corner/entities/system_fields_ignored_on_return_create
    """
    office = create_office()
    client = create_client(office["id"], full_name="Sys Cli", ssn_last4="3535")
    res = api.create_return(
        {"office_id": office["id"], "client_id": client["id"], "tax_year": 2025,
         "complexity_band": "SIMPLE", "status": "EFILED_ACCEPTED", "prep_fee_cents": 99999}, FD)
    ret = validate_success(res, 201)
    assert ret["status"] == "INTAKE", "status is system-set to INTAKE regardless of input"


def test_list_office_clients_pagination_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    Design: Corner/entities/list_offices_clients_pagination_envelope
    """
    office = create_office()
    create_client(office["id"], full_name="L One", ssn_last4="3636")
    create_client(office["id"], full_name="L Two", ssn_last4="3737")
    res = api.list_office_clients(office["id"], FD, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
