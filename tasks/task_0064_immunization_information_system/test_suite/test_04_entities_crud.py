"""Entity creation, defaults, not-found, required-field, and uniqueness checks."""
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, assert_patient, set_clock, create_product, create_provider,
    api_client, make_registrar_headers, create_patient_payload,
    create_product_payload, create_lot_payload,
)

REG = make_registrar_headers()


def test_create_patient_returns_201_with_system_fields(api):
    """PRD §3.2: "A newly created patient has schedule_status of UP_TO_DATE and
    active_certificate_id of null."
    PRD §2.4: "The version field is an integer that starts at 1 and increments
    by exactly 1 on every mutation".

    Design: Corner/entities/create_patient_returns_201_with_system_fields
    """
    data = validate_success(
        api_client.create_patient(create_patient_payload(
            full_name="New Child", date_of_birth="2024-05-01",
            state_code="CA"), REG), expected_status=201)
    assert_patient(data)
    assert data["schedule_status"] == "UP_TO_DATE"
    assert data["version"] == 1
    assert data["active_certificate_id"] is None


def test_get_patient_not_found(api):
    """PRD §2.5: "rejects the request with ERR_NOT_FOUND (HTTP 404) at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_patient_not_found
    """
    validate_error(api_client.get_patient(NON_EXISTENT_UUID, REG),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_patient_missing_required_field(api):
    """PRD §3.2: "A date_of_birth after the clock date, like any missing required
    field, bad type, or invalid enum value, is rejected with ERR_INVALID_REQUEST
    (HTTP 400)."

    Design: Corner/entities/create_patient_missing_required_field
    """
    validate_error(api_client.create_patient(
        {"full_name": "No DOB", "state_code": "CA"}, REG),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_dob_after_clock_rejected(api):
    """PRD §3.2: "a date_of_birth as an ISO YYYY-MM-DD date that must be a
    calendar date on or before the current clock date ... A date_of_birth after
    the clock date ... is rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/dob_after_clock_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    validate_error(api_client.create_patient(create_patient_payload(
        full_name="Future Child", date_of_birth="2027-01-01",
        state_code="CA"), REG),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_lot_administered_count_default_zero_and_available(api):
    """PRD §3.1: "A lot is created with administered_count of 0 and status of
    AVAILABLE".

    Design: Corner/entities/lot_administered_count_default_zero_and_system
    """
    product = create_product(**create_product_payload())
    data = validate_success(api_client.create_lot(create_lot_payload(
        product_id=product["id"], lot_number="LX", doses_total=10), REG),
        expected_status=201)
    assert data["administered_count"] == 0
    assert data["status"] == "AVAILABLE"


def test_duplicate_product_code_rejected(api):
    """PRD §3.1: "a product_code such as DTAP ... which is a stable, non-empty
    code that must be unique across all products ... A duplicate lot_number
    within the same product, like a duplicate product_code or a duplicate
    provider vfc_pin, is rejected with ERR_DUPLICATE (HTTP 409)."

    Design: Corner/entities/duplicate_product_code_rejected
    """
    create_product(**create_product_payload(product_code="C1", antigen="C1"))
    validate_error(api_client.create_product(create_product_payload(
        product_code="C1", antigen="C1B"), REG),
        ApiErrorId.ERR_DUPLICATE.value)


def test_lot_expiration_not_after_received_rejected(api):
    """PRD §3.1: "The expiration_date must be strictly after the received_date;
    a violation is rejected with ERR_VALIDATION."

    Design: Corner/entities/product_cross_field_validation_expiration_before_received
    """
    product = create_product(**create_product_payload())
    validate_error(api_client.create_lot(create_lot_payload(
        product_id=product["id"], lot_number="BAD",
        received_date="2025-01-01", expiration_date="2025-01-01",
        doses_total=10), REG),
        ApiErrorId.ERR_VALIDATION.value)
