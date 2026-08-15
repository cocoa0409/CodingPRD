"""Member/staff creation rules and read-envelope behavior (PRD §2.2, §2.5,
§2.6, §3.1, §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    assert_member,
    create_member_payload,
    validate_error,
    validate_success,
)


def test_member_creation_defaults_and_system_fields():
    """PRD §3.1: "A new member starts with `status` `ACTIVE`,
    `waiver_signed_date` null, `outstanding_fines_cents` zero, and
    `no_show_count` zero."
    PRD §2.5: "Every resource carries an `id` that is a server-minted UUID
    with no type prefix, a `created_at` timestamp, and an `updated_at`
    timestamp, both ISO 8601 UTC with three fractional digits, plus a
    `version` integer that starts at 1 and increments by 1 on every mutation
    of that resource."

    Design: Corner/entities/member_creation_defaults_and_system_fields
    """
    resp = api_client.create_member(
        create_member_payload(
            email="d1@x.edu", full_name="Def One", affiliation="COMMUNITY"),
        REC_ADMIN,
    )
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["status"] == "ACTIVE"
    assert data["waiver_signed_date"] is None
    assert data["outstanding_fines_cents"] == 0
    assert data["no_show_count"] == 0
    assert data["version"] == 1


def test_member_missing_affiliation_returns_invalid_request():
    """PRD §2.8: "**Request shape** (`ERR_VALIDATION`): required fields
    present; enum values valid; numeric ranges; interval well-formedness;
    conditional staff fields; fine-payment amounts; and the other field-level
    rules detailed in §3."

    Design: Corner/entities/member_missing_affiliation_returns_invalid_request
    """
    resp = api_client.create_member(
        {"email": "d2@x.edu", "full_name": "Def Two"}, REC_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_member_invalid_enum_returns_invalid_request():
    """PRD §3.1: "The `affiliation` is one of `STUDENT`, `FACULTY`, or
    `COMMUNITY` and drives fee tables throughout the system."
    PRD §2.8: "**Request shape** (`ERR_VALIDATION`): required fields
    present; enum values valid; numeric ranges; interval well-formedness;
    conditional staff fields; fine-payment amounts; and the other field-level
    rules detailed in §3."

    Design: Corner/entities/member_invalid_enum_returns_invalid_request
    """
    resp = api_client.create_member(
        create_member_payload(email="d3@x.edu", full_name="Def Three",
                              affiliation="ALUMNI"),
        REC_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_staff_conditional_fields_rejected():
    """PRD §3.6: "The conditional fields differ by role: `certification_level`
    is required exactly when the role is `OFFICIAL` — an integer from 1 to 3 —
    and forbidden when the role is `INSTRUCTOR`; `certified_class_types` is
    required non-empty exactly when the role is `INSTRUCTOR` — a subset of the
    class-type enum — and forbidden when the role is `OFFICIAL`. Raw
    conditional-field violations are `ERR_VALIDATION`; the contextual errors
    `ERR_STAFF_NOT_OFFICIAL` and `ERR_STAFF_NOT_INSTRUCTOR` apply only in
    assignment and class contexts."

    Design: Corner/entities/staff_conditional_fields_rejected
    """
    # OFFICIAL without certification_level.
    resp1 = api_client.create_staff(
        {"full_name": "No Cert", "staff_role": "OFFICIAL",
         "base_hourly_rate_cents": 2000},
        REC_ADMIN,
    )
    validate_error(resp1, ApiErrorId.ERR_VALIDATION)

    # INSTRUCTOR carrying the forbidden certification_level.
    resp2 = api_client.create_staff(
        {
            "full_name": "Wrong Field", "staff_role": "INSTRUCTOR",
            "base_hourly_rate_cents": 3000, "certification_level": 2,
            "certified_class_types": ["YOGA"],
        },
        REC_ADMIN,
    )
    validate_error(resp2, ApiErrorId.ERR_VALIDATION)


def test_entity_not_found_returns_404():
    """PRD §2.6: "Path resource identifiers are validated for existence left
    to right; a missing path resource yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api_client.get_member(NON_EXISTENT_UUID, REC_ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error["message"].strip(), "error message must be non-empty"
