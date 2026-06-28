"""Entity creation, defaults, not-found, required-field, type-constraint, and
immutability claims (queue-B entities section)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_studio_payload,
    create_client_payload,
    create_color_formula_payload,
    create_consent_payload,
    assert_studio,
    assert_consent_record,
)

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


def test_create_studio_returns_201_frozen_posture_kit_ledger(api):
    """PRD §3.1: "At creation the studio's `sterile_kit_consumed` is zero and
    its compliance posture is computed — it begins `FROZEN` because no licensed
    technician yet exists."
    PRD §2.4: "a `version`, an integer that begins at 1".

    Design: Corner/entities/entity_create_studio_returns_201_all_fields
    """
    res = api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN)
    studio = validate_success(res, 201)
    assert_studio(studio)
    assert studio["compliance_posture"] == "FROZEN"
    assert studio["sterile_kit_consumed"] == 0
    assert studio["sterile_kit_available"] == 5
    assert studio["version"] == 1


def test_min_client_age_defaults_to_18(api):
    """PRD §3.1: "`min_client_age` defaults to 18 and may never be set below 18."

    Design: Corner/entities/entity_min_client_age_default_18
    """
    studio = validate_success(
        api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN), 201
    )
    assert studio["min_client_age"] == 18


def test_get_nonexistent_client_returns_not_found(api):
    """PRD §2.7: "rejects the request with `ERR_NOT_FOUND` at the first
    identifier that does not correspond to an existing resource".

    Design: Corner/entities/entity_client_not_found_404
    """
    res = api.get_client(NON_EXISTENT, FRONT)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_client_missing_date_of_birth_rejected(api):
    """PRD §2.9: "then request well-formedness — required fields present, enums
    valid, numerics within their declared ranges ... (`ERR_INVALID_REQUEST`)."
    PRD §3.2: "registers a `Client` against a studio by supplying `studio_id`,
    the client's `full_name`, the `date_of_birth` ...".

    Design: Corner/entities/entity_client_missing_required_dob
    """
    studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN))
    payload = {"studio_id": studio["id"], "full_name": "No DOB"}
    res = api.create_client(payload, FRONT)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_color_formula_invalid_procedure_type_enum_rejected(api):
    """PRD §2.9: "then request well-formedness — required fields present, enums
    valid ... (`ERR_INVALID_REQUEST`)."
    PRD §3.4: "the `procedure_type` it is intended for (`BROWS`, `EYELINER`, or
    `LIP_BLUSH`)".

    Design: Corner/entities/entity_color_formula_invalid_enum_procedure_type
    """
    studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN))
    payload = create_color_formula_payload(studio["id"], name="Bad", procedure_type="NOSE", pigment_count=1)
    res = api.create_color_formula(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_consent_record_is_append_only_without_version(api):
    """PRD §3.3: "Consent records are immutable audit entries; they carry only
    `id` and `created_at`."

    Design: Corner/entities/entity_consent_record_immutable_no_version
    """
    studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN))
    client = get_success_data(
        api.create_client(create_client_payload(studio["id"], full_name="C"), FRONT)
    )
    res = api.create_consent_record(
        create_consent_payload(client["id"], consent_type="PHOTO_RELEASE", signed_by_name="C"),
        FRONT,
    )
    consent = validate_success(res, 201)
    assert_consent_record(consent)
    assert "version" not in consent, "ConsentRecord must not carry a version field"


def test_studio_negative_kit_total_rejected_range(api):
    """PRD §2.9: "a `sterile_kit_total` below 0 are the range violations this
    code covers." and "rejected with `ERR_VALIDATION_RANGE`".

    Design: Corner/entities/entity_studio_kit_total_negative_rejected
    """
    res = api.create_studio(create_studio_payload(sterile_kit_total=-1), ADMIN)
    validate_error(res, "ERR_VALIDATION_RANGE")
