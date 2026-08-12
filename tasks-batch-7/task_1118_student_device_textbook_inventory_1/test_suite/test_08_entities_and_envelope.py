"""Entity creation defaults, common fields, and the pagination envelope
(PRD §2.2, §2.3, §2.5, §3.1, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_program,
    create_fleet,
    create_program,
    enroll_student,
    intake_asset,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


def test_program_create_applies_defaults(api, admin_headers):
    """PRD §3.1: "The program may also declare `loaner_pool_threshold_pct`, the fraction of the deployable fleet held in reserve as the loaner floor; when omitted, the reserve defaults to 0.10 — ten percent. New programs start in `DRAFT`."

    Design: Corner/entities/district_program_create_returns_defaults
    """
    program = create_program()
    fetched = validate_success(api.get_program(program["id"], admin_headers), 200)
    assert fetched["loaner_pool_threshold_pct"] == pytest.approx(0.10)
    assert fetched["status"] == "DRAFT"


def test_student_enrollment_defaults(api):
    """PRD §3.2: "The registrar supplies the `student_external_id` (the student information system identifier, unique within the program), the student's `full_name`, a `grade_level` from 0 through 12, and optionally the `free_lunch_eligible` flag that drives fee-waiver eligibility (defaulting to false). The account is born `ENROLLED` with `financial_posture` set to `CLEAR` and `family_agreement_status` set to `PENDING`, and a FamilyAgreement row is auto-created alongside it in `PENDING` signature state."

    free_lunch_eligible omitted -> false; all derived fields at their birth values.

    Design: Corner/entities/student_account_free_lunch_default_false
    """
    program = create_program()
    create_fleet(program["id"])
    activate_program(program["id"])
    student = enroll_student(program["id"], "SIS-DFT-1", "Defaults")
    assert student["free_lunch_eligible"] is False
    assert student["family_agreement_status"] == "PENDING"
    assert student["financial_posture"] == "CLEAR"
    assert student["insurance_enrolled"] is False
    assert student["lifetime_damage_count"] == 0
    assert student["status"] == "ENROLLED"


def test_asset_unit_intake_defaults_and_initial_depreciation(api, admin_headers):
    """PRD §3.1: "Each unit is registered with an `asset_tag_barcode` that is unique within the program and a manufacturer `serial_number` that is unique within its fleet; an intake `condition_grade` may be supplied and defaults to `A`."
    PRD §3.1: "A freshly intaken unit begins life in `READY` status and an `INTAKE` event lands on its lifecycle trail."

    Fleet in_service_date equals the boot clock, so months_in_service is 0 and
    no depreciation has accrued: depreciated_value_cents == replacement cost.

    Design: Corner/entities/asset_unit_initial_lifecycle_ready_and_depreciated_value_computed
    """
    program = create_program()
    fleet = create_fleet(program["id"], in_service_date="2026-05-01T00:00:00Z")
    activate_program(program["id"])
    unit = intake_asset(program["id"], fleet["id"], "BC-CMP-1", "SN-CMP-1")
    assert unit["lifecycle_status"] == "READY"
    assert unit["condition_grade"] == "A"
    assert unit["months_in_service"] == 0
    assert unit["depreciated_value_cents"] == 100000


def test_asset_unit_missing_barcode_rejected(api):
    """PRD §2.10: "A malformed request body — a missing required field, a value of the wrong type, or an enum value outside its declared set — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/asset_unit_required_field_missing_rejected
    """
    program = create_program()
    fleet = create_fleet(program["id"])
    activate_program(program["id"])
    res = api.create_asset_unit(
        program["id"], fleet["id"], {"serial_number": "SN-NOBC"}, TECH
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_family_agreement_auto_created_on_enrollment(api, registrar_headers):
    """PRD §3.2: "The account is born `ENROLLED` with `financial_posture` set to `CLEAR` and `family_agreement_status` set to `PENDING`, and a FamilyAgreement row is auto-created alongside it in `PENDING` signature state."
    PRD §3.2: "The agreement is one-per-student, so reading it returns an array containing zero or one element."

    Design: Corner/entities/family_agreement_auto_created_on_student_enroll
    """
    program = create_program()
    create_fleet(program["id"])
    activate_program(program["id"])
    student = enroll_student(program["id"], "SIS-FA-1", "Fa")
    agreements = validate_success(
        api.get_family_agreement(program["id"], student["id"], registrar_headers),
        200,
    )
    assert len(agreements) == 1, f"Expected exactly one agreement, got {agreements}"
    assert agreements[0]["signature_state"] == "PENDING"


def test_common_fields_id_uuid_and_timestamps(api):
    """PRD §2.5: "The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time, and `updated_at` records the last modification; both are ISO 8601 UTC timestamps with three fractional digits. The `version` is an integer that increments on every mutation of the resource — including system-driven recomputations such as a student's financial posture being re-derived after a fee changes, or an asset's depreciated value being refreshed."

    Design: Corner/entities/common_fields_present_and_id_is_uuid
    """
    program = create_program()
    assert is_valid_uuid(program["id"]), f"id is not a UUID: {program['id']}"
    assert is_iso8601_timestamp(program["created_at"])
    assert is_iso8601_timestamp(program["updated_at"])
    assert isinstance(program["version"], int)


def test_program_list_pagination_envelope(api, admin_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_pagination_envelope
    """
    for name in ("P1", "P2", "P3"):
        create_program(program_name=name)
    data, meta = validate_paginated(
        api.list_programs(admin_headers, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
