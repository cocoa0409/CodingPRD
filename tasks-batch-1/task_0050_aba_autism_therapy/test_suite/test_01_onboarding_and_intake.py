"""Onboarding and intake: creating clients and providers, required-field and
not-found enforcement, optional-field defaults, and the list envelope."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_payer,
    create_bcba,
    factories,
)


def test_create_client_starts_in_intake_with_system_fields(api):
    """PRD §3.1: "A newly created client enters `INTAKE` status."
    PRD §2.4: "a `version` (an integer that begins at creation and increments by
    one on every mutation, used for optimistic concurrency control)."

    Design: Corner/entities/create_client_returns_201_with_intake_status_and_system_fields
    """
    payer = create_payer(api, name="Corner Payer")
    resp = api.create_client(
        factories.create_client_payload(
            payer["id"], full_name="Corner Child",
            date_of_birth="2019-01-01", caregiver_user_id="cg-corner",
        ),
        TEST_USERS["intake_headers"],
    )
    data = validate_success(resp, 201)
    assert data["status"] == "INTAKE", f"expected INTAKE, got {data['status']}"
    assert data["version"] == 1, f"expected version 1 at create, got {data['version']}"
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_create_client_missing_insurance_payer_id_rejected(api):
    """PRD §2.4: "Body well-formedness is checked next on every mutating endpoint
    — the body must be valid JSON, every required input field must be present, and
    every enumerated or numeric value must fall within its declared range (for
    instance `assessment_score` between 0 and 180 inclusive, `coinsurance_pct`
    between 0 and 1 inclusive, and `scheduled_units` at least 1); any violation
    yields `ERR_VALIDATION`."

    Design: Corner/entities/create_client_missing_required_field_returns_validation
    """
    resp = api.create_client(
        {
            "full_name": "No Payer Child",
            "date_of_birth": "2019-01-01",
            "caregiver_user_id": "cg-x",
        },
        TEST_USERS["intake_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_get_nonexistent_client_returns_not_found(api):
    """PRD §2.4: "every path and body foreign-key resource must exist, validated
    left-to-right in the order they appear, with the first missing one yielding
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_client_nonexistent_returns_not_found
    """
    resp = api.get_client(
        "00000000-0000-4000-8000-000000000000", TEST_USERS["intake_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_bcba_without_supervisor_is_active_and_null_supervisor(api):
    """PRD §3.1: "Each `Provider` is created with a `full_name`, a `credential`
    that is either `BCBA` or `RBT`, an `npi` (National Provider Identifier), and
    — for a technician — an optional `supervising_bcba_id` naming the BCBA who
    supervises them (a BCBA leaves this null). A provider begins in `ACTIVE`
    status and may later be moved to `INACTIVE` through the deactivate capability."

    Design: Corner/entities/provider_supervising_bcba_id_default_null_for_bcba
    """
    resp = api.create_provider(
        factories.create_provider_payload(credential="BCBA", full_name="Solo BCBA"),
        TEST_USERS["intake_headers"],
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["supervising_bcba_id"] is None, (
        f"expected null supervising_bcba_id, got {data['supervising_bcba_id']!r}"
    )


def test_list_providers_returns_array_envelope_with_pagination(api):
    """PRD §2.3: "Every list response includes the following fields inside the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_providers_pagination_envelope_fields
    """
    create_bcba(api, full_name="P1")
    create_bcba(api, full_name="P2")
    resp = api.list_providers(TEST_USERS["intake_headers"])
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] >= 2
    assert "has_more" in meta
