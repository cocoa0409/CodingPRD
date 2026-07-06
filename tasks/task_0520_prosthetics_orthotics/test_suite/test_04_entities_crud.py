"""Entity CRUD: creation, not-found, required fields, enum validation, defaults,
and the append-only audit record.

Covers Queue B (Corner) section: entities.
"""
from test_helpers import (
    validate_success, validate_error, is_valid_uuid,
    assert_patient, assert_compliance_check,
)
from test_helpers.test_users import TEST_USERS, make_practitioner_headers
from test_helpers.constants import NONEXISTENT_UUID
from test_helpers.factories import (
    create_patient_payload, create_physician_payload, create_prescription_payload,
)
from test_helpers.fixtures import setup_delivered_no_auth


def test_create_patient_returns_201_with_fields(api):
    """PRD §2.4: "`version`: an integer that starts at 1 and increments by exactly 1 on
    every mutation."
    PRD §2.4: "`id`: a unique, server-minted identifier formatted as a UUID. It carries
    no type prefix and is used for identity only."

    Design: Corner/entities/create_patient_returns_201_with_fields
    """
    res = api.create_patient(
        create_patient_payload(full_name="New Pat", date_of_birth="1970-02-02",
                               payer_type="COMMERCIAL"),
        TEST_USERS["billing_headers"])
    patient = validate_success(res, 201)
    assert patient["payer_type"] == "COMMERCIAL"
    assert patient["version"] == 1
    assert is_valid_uuid(patient["id"])
    assert_patient(patient)


def test_get_patient_not_found(api):
    """PRD §2.5: "the system validates each path identifier in strict left-to-right order
    and rejects the request with `ERR_RESOURCE_NOT_FOUND` at the *first* identifier that
    does not resolve to an existing resource."

    Design: Corner/entities/get_patient_not_found
    """
    res = api.get_patient(NONEXISTENT_UUID, TEST_USERS["billing_headers"])
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


def test_create_patient_missing_payer_type(api):
    """PRD §3.10: "A request body that is missing a required field, carries a value
    outside an enumeration, or carries an out-of-range integer is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_patient_missing_required_field
    """
    res = api.create_patient(
        {"full_name": "No Payer", "date_of_birth": "1970-02-02"},
        TEST_USERS["billing_headers"])
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_patient_bad_enum_payer_type(api):
    """PRD §3.10: "A request body that is missing a required field, carries a value
    outside an enumeration, or carries an out-of-range integer is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_patient_bad_enum_payer_type
    """
    res = api.create_patient(
        create_patient_payload(full_name="Bad Enum", payer_type="AETNA"),
        TEST_USERS["billing_headers"])
    validate_error(res, "ERR_INVALID_REQUEST")


def test_prescription_defaults_to_draft(api):
    """PRD §3.2: "A `Physician` authors a prescription, which begins life in `DRAFT`."

    Design: Corner/entities/prescription_default_status_draft
    """
    from test_helpers.test_users import make_physician_headers
    phys = validate_success(api.create_physician(
        create_physician_payload(full_name="Dr A", npi="1111111111", pecos_enrolled=True),
        TEST_USERS["compliance_headers"]), 201)
    patient = validate_success(api.create_patient(
        create_patient_payload(full_name="Pat D", payer_type="COMMERCIAL"),
        TEST_USERS["billing_headers"]), 201)
    rx = validate_success(api.create_prescription(
        create_prescription_payload(patient["id"], phys["id"],
                                    device_category="SPINAL_ORTHOSIS",
                                    primary_diagnosis_code="M54.5",
                                    face_to_face_date="2026-04-20"),
        make_physician_headers(phys["id"])), 201)
    assert rx["status"] == "DRAFT"


def test_compliance_check_is_append_only_without_version(api):
    """PRD §2.4: "Two entities are deliberate exceptions and carry only `id` and
    `created_at`; they have neither `updated_at` nor `version` because they are
    append-only and never mutated after creation."
    PRD §2.4: "The first is `ComplianceCheck`, the audit record written at delivery: in
    addition to `id` and `created_at` it records the `device_order_id` it audited, a
    boolean `passed` indicating the aggregate gate result, and an ordered
    `failure_reasons` array listing the reason codes that failed (empty when `passed` is
    true)."

    Design: Corner/entities/compliancecheck_is_immutable_no_version
    """
    cast = setup_delivered_no_auth()
    checks = validate_success(
        api.list_compliance_checks(cast["ord_id"], TEST_USERS["compliance_headers"]), 200)
    assert len(checks) == 1
    cc = checks[0]
    assert cc["passed"] is True
    assert cc["failure_reasons"] == []
    assert "version" not in cc
    assert_compliance_check(cc)
