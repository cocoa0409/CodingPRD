"""Entity registry claims: creation defaults, required fields, enum
validation, not-found routing, officer email uniqueness, and nested-create
parent resolution."""
from test_helpers import (
    ABSENT_UUID,
    FC1,
    SEC1,
    ApiErrorId,
    assert_legal_entity,
    create_entity_payload,
    create_jurisdiction_j1,
    create_officer,
    create_officer_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)


def test_entity_create_applies_defaults(api):
    """PRD 3.2: "Optional fields include `fiscal_year_end_month` (default 12) and
    `authorized_shares` (default 0). The entity begins in `DRAFT` status with
    `compliance_posture` initialized to `GOOD_STANDING`, `fees_accrued_cents`
    set to 0, and `version` set to 1."
    PRD 2.4: "`id` — a server-minted UUID with no type prefix."

    Design: Corner/entities/entity_create_applies_defaults
    """
    j1 = create_jurisdiction_j1()

    response = api.create_entity(
        create_entity_payload(j1["id"], legal_name="Defaults LLC", entity_type="LLC"),
        SEC1,
    )
    entity = validate_success(response, 201)
    assert_legal_entity(entity)

    assert entity["fiscal_year_end_month"] == 12, "default fiscal_year_end_month is 12"
    assert entity["authorized_shares"] == 0, "default authorized_shares is 0"
    assert entity["status"] == "DRAFT"
    assert entity["compliance_posture"] == "GOOD_STANDING"
    assert entity["fees_accrued_cents"] == 0
    assert entity["version"] == 1
    assert is_valid_uuid(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])


def test_entity_create_missing_required_field(api):
    """PRD 3.2: "A `CorporateSecretary` creates a `LegalEntity` by supplying
    `legal_name`, `entity_type`, `formation_jurisdiction_id`, and
    `formation_date`."
    PRD 2.10: "Body-schema and range validation follow (priority 4)."
    PRD 5: ERR_INVALID_REQUEST maps to HTTP 400.

    Design: Corner/entities/entity_create_missing_required_field
    """
    j1 = create_jurisdiction_j1()

    response = api.create_entity(
        {
            "entity_type": "CORPORATION",
            "formation_jurisdiction_id": j1["id"],
            "formation_date": "2025-06-15",
        },
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_entity_create_invalid_enum_rejected(api):
    """PRD 3.2: "The `entity_type` must be one of `CORPORATION`, `LLC`,
    `LIMITED_PARTNERSHIP`, or `NONPROFIT_CORPORATION`."
    PRD 5: ERR_INVALID_REQUEST maps to HTTP 400.

    Design: Corner/entities/entity_create_invalid_enum_rejected
    """
    j1 = create_jurisdiction_j1()

    response = api.create_entity(
        create_entity_payload(j1["id"], legal_name="Trusty", entity_type="TRUST"),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_entity_get_not_found_returns_404(api):
    """PRD 2.5: "The request is rejected with a 404 error for the first
    identifier that does not resolve to an existing resource."
    PRD 5: ERR_ENTITY_NOT_FOUND maps to HTTP 404.

    Design: Corner/entities/entity_get_not_found_returns_404
    """
    response = api.get_entity(ABSENT_UUID, SEC1)
    validate_error(response, ApiErrorId.ERR_ENTITY_NOT_FOUND)


def test_officer_duplicate_email_rejected(api):
    """PRD 3.1: "The email must be unique; duplicates are rejected with
    `ERR_DUPLICATE_OFFICER`."

    Design: Corner/entities/officer_duplicate_email_rejected
    """
    create_officer(full_name="Olivia Ortiz", email="oo@example.com")

    response = api.create_officer(
        create_officer_payload(full_name="Other Olivia", email="oo@example.com"), SEC1
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_OFFICER)


def test_nested_create_parent_not_found(api):
    """PRD 2.5: "When an endpoint path contains multiple resource identifiers,
    the system validates each identifier from left to right. The request is
    rejected with a 404 error for the first identifier that does not resolve to
    an existing resource."
    PRD 5: ERR_ENTITY_NOT_FOUND maps to HTTP 404.

    Design: Corner/endpoints/nested_create_parent_not_found
    """
    response = api.create_resolution(
        ABSENT_UUID,
        {
            "resolution_type": "AUTHORIZE_FORMATION",
            "payload": {},
            "effective_date": "2025-06-15",
        },
        FC1,
    )
    validate_error(response, ApiErrorId.ERR_ENTITY_NOT_FOUND)
