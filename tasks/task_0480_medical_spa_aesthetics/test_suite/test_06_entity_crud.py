"""Entity creation / validation tests (§2.7, §3.1, §3.5).

Creation defaults, not-found and invalid-request handling, computed fields on
intake, and the immutable `ConsentPhoto` envelope.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_clinic_admin_headers,
    make_provider_headers,
    assert_provider,
    assert_injectable_lot,
    assert_consent_photo,
    create_provider_payload,
    create_membership_package_payload,
    create_patient_payload,
    create_injectable_lot_payload,
    create_consent_photo_payload,
    make_injector,
    make_patient,
)

ADMIN = make_clinic_admin_headers()


def test_create_provider_returns_201_with_system_defaults(api):
    """PRD §3.1: "Every provider begins with `status` of `ACTIVE`, and the computed
    counters `open_complication_count`, `resolved_complication_count`, and
    `committed_session_count` all start at 0." PRD §2.4: "a version integer that
    begins at its initial value and increments by one on every mutation."

    Design: Corner/entities/create_provider_returns_201_with_system_defaults
    """
    resp = api.create_provider(
        create_provider_payload(full_name="Co Inj", license_number="L-CO-1",
                                role_kind="INJECTOR"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_provider(data)
    assert data["status"] == "ACTIVE"
    assert data["open_complication_count"] == 0
    assert data["resolved_complication_count"] == 0
    assert data["committed_session_count"] == 0
    assert data["version"] == 1, f"version should start at 1, got {data['version']}"


def test_get_patient_not_found_returns_404(api):
    """PRD §2.7: "Path identifiers are validated first and left to right: the
    addressed resource must exist or the request is rejected with the not-found
    error specific to that resource type — `ERR_PROVIDER_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND` ..."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_create_membership_missing_required_field_returns_invalid_request(api):
    """PRD §2.7: "A malformed body — a missing required field, a type mismatch,
    an unrecognized enum value, or a non-positive amount or unit count where a
    positive value is required — is rejected with `ERR_INVALID_REQUEST`."

    Omitting `member_discount_pct` (a required input) is rejected.

    Design: Corner/entities/create_membership_missing_required_field_returns_invalid_request
    """
    payload = create_membership_package_payload(tier="PLUS", loyalty_program="ALLE",
                                                monthly_fee_cents=9900)
    del payload["member_discount_pct"]
    resp = api.create_membership_package(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_patient_membership_id_default_null_no_discount(api):
    """PRD §3.1: "A `Patient` is registered by a `ClinicAdmin` with a full_name, a
    date_of_birth as an ISO 8601 UTC instant, and an optional `membership_id`
    referencing a `MembershipPackage`; a patient with no membership receives no
    discount and is priced at list." PRD §3.1: "Each patient carries the computed
    flag `photo_consent_on_file`, which begins `false` ..."

    A patient created without `membership_id` has `photo_consent_on_file`==`false`.

    Design: Corner/entities/patient_membership_id_default_null_no_discount
    """
    resp = api.create_patient(
        create_patient_payload(full_name="Def Pat"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["photo_consent_on_file"] is False, (
        f"photo_consent_on_file should default false, got {data['photo_consent_on_file']}")


def test_lot_remaining_units_computed_equals_total_on_intake(api):
    """PRD §3.1: "At intake `reserved_units` and `consumed_units` are both 0,
    `remaining_units` equals `total_units`, and `status` is `AVAILABLE`."

    Design: Corner/entities/lot_remaining_units_computed_equals_total_on_intake
    """
    resp = api.create_injectable_lot(
        create_injectable_lot_payload(product="BOTOX", lot_number="LOT-C1",
                                      total_units=150), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_injectable_lot(data)
    assert data["remaining_units"] == 150, (
        f"remaining_units should equal total 150 on intake, got {data['remaining_units']}")
    assert data["reserved_units"] == 0
    assert data["consumed_units"] == 0
    assert data["status"] == "AVAILABLE"


def test_create_provider_invalid_enum_role_kind_returns_invalid_request(api):
    """PRD §2.7: "A malformed body — a missing required field, a type mismatch, an
    unrecognized enum value, or a non-positive amount or unit count where a
    positive value is required — is rejected with `ERR_INVALID_REQUEST`." PRD §3.1:
    "supplying the `full_name`, the state `license_number`, and the `role_kind`,
    which is either `INJECTOR` or `MEDICAL_DIRECTOR`."

    `role_kind`=NURSE is not in the enum.

    Design: Corner/entities/create_provider_invalid_enum_role_kind_returns_invalid_request
    """
    resp = api.create_provider(
        create_provider_payload(full_name="Bad Role", license_number="L-BAD",
                                role_kind="NURSE"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_consent_photo_immutable_no_version_field(api):
    """PRD §2.4: "The single exception is the `ConsentPhoto`, which is an immutable
    event record: it carries only id and created_at, and has neither an
    updated_at field nor a version field." PRD §3.5: "Photo records are immutable
    once written."

    Design: Corner/entities/consent_photo_immutable_no_version_field
    """
    patient = make_patient(full_name="Imm Pat")
    inj = make_injector(license_number="L-IM-I")
    resp = api.create_consent_photo(
        create_consent_photo_payload(patient["id"], kind="CONSENT",
                                     storage_uri="s3://im", signed=True),
        make_provider_headers(inj["id"]))
    data = validate_success(resp, expected_status=201)
    assert_consent_photo(data)
    assert "version" not in data, "ConsentPhoto must not carry a version field"
    assert "updated_at" not in data, "ConsentPhoto must not carry an updated_at field"


def test_foreign_key_patient_membership_invalid_returns_membership_not_found(api):
    """PRD §2.7: "Once path identifiers resolve, every foreign key supplied in a
    creation body must resolve to an existing record — `membership_id`, patient_id,
    ... failing with the corresponding `ERR_MEMBERSHIP_NOT_FOUND`, ..."

    A patient created with a non-existent `membership_id` is rejected.

    Design: Corner/entities/foreign_key_patient_membership_invalid_returns_membership_not_found
    """
    resp = api.create_patient(
        create_patient_payload(full_name="Fk Pat", membership_id=NON_EXISTENT_UUID),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND.value)
