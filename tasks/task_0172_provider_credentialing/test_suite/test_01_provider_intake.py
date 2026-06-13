"""Provider intake, organization defaults, and the application lifecycle.

Covers corner-design instances from the `entities` and `state_machines` sections
that concern creation, required/typed fields, defaults, not-found, and the
DRAFT -> SUBMITTED -> IN_VERIFICATION -> READY_FOR_REVIEW pipeline preconditions.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    make_system_admin_headers, make_specialist_headers,
    make_compliance_officer_headers, make_enrollment_coordinator_headers,
    ApiErrorId,
    create_org_payload, create_provider_payload, create_credential_item_payload,
    create_payer_payload, create_sanctions_source_payload,
    create_verification_request_payload, complete_verification_payload,
)
import test_helpers.fixtures as fx

ADMIN = make_system_admin_headers("admin-1")
SPEC = make_specialist_headers("spec-1")


def _new_org():
    return validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)


# =========================================================================
# Organization defaults
# =========================================================================
def test_org_create_applies_defaults():
    """PRD §3.1: "At creation the organization may also specify its
    re-credentialing cycle length as `recred_cycle_days` (defaulting to 1095
    days, i.e., three years) and the window at which credentials begin flagging
    as expiring via `expiring_soon_window_days` (defaulting to 90 days)."
    PRD §2.7: "exposed as `current_utc` on the organization and initialized to
    `2026-01-01T00:00:00.000Z` when the organization is created."

    Design: Corner/entities/org_create_defaults_applied
    """
    resp = api_client.create_org(create_org_payload(name="CVO"), ADMIN)
    data = validate_success(resp, 201)
    assert data["recred_cycle_days"] == 1095
    assert data["expiring_soon_window_days"] == 90
    assert data["current_utc"] == "2026-01-01T00:00:00.000Z"


# =========================================================================
# Provider creation
# =========================================================================
def test_create_provider_returns_201_with_system_fields():
    """PRD §3.2: "A freshly created provider begins with `application_status` of
    `DRAFT`, a derived `credentialing_status` of `PENDING`, and a `recred_state`
    of `NOT_CLEARED`."
    PRD §2.4: "`version` (integer): a server-managed integer that begins at its
    initial value and increments by one on every mutation to the resource."

    Design: Corner/entities/create_provider_returns_201_with_system_fields
    """
    org = _new_org()
    resp = api_client.create_provider(create_provider_payload(org["id"]), SPEC)
    data = validate_success(resp, 201)
    assert data["application_status"] == "DRAFT"
    assert data["credentialing_status"] == "PENDING"
    assert data["recred_state"] == "NOT_CLEARED"
    assert data["version"] == 1


def test_create_provider_missing_npi_returns_invalid_request():
    """PRD §2.6: "request-body well-formedness, including required fields,
    correct types, valid enum members, the ten-digit NPI rule ... (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_provider_missing_npi_returns_invalid_request
    """
    org = _new_org()
    payload = create_provider_payload(org["id"])
    payload.pop("npi")
    resp = api_client.create_provider(payload, SPEC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_provider_bad_npi_length_returns_invalid_request():
    """PRD §2.6: "request-body well-formedness, including required fields,
    correct types, valid enum members, the ten-digit NPI rule ... (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_provider_bad_npi_length_returns_invalid_request
    """
    org = _new_org()
    resp = api_client.create_provider(create_provider_payload(org["id"], npi="123"), SPEC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_provider_get_nonexistent_returns_not_found():
    """PRD §2.5: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    *first* identifier in the path that does not correspond to an existing
    resource".

    Design: Corner/entities/provider_get_nonexistent_returns_not_found
    """
    _new_org()
    resp = api_client.get_provider("00000000-0000-4000-8000-000000000000", SPEC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# =========================================================================
# Credential item creation
# =========================================================================
def test_credential_item_expirable_band_computed_valid_on_create():
    """PRD §3.3: "Each item begins in `verification_state` `UNVERIFIED`, and its
    `expirable_band` is computed immediately per §2.8."
    PRD §2.8: "Otherwise the band is `VALID`."

    Design: Corner/entities/credential_item_expirable_band_computed_valid_on_create
    """
    org = _new_org()
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    resp = api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(
            item_type="STATE_LICENSE", identifier="LIC-1",
            issued_date="2025-01-01T00:00:00.000Z",
            expiration_date="2030-01-01T00:00:00.000Z"),
        SPEC)
    data = validate_success(resp, 201)
    assert data["expirable_band"] == "VALID"
    assert data["verification_state"] == "UNVERIFIED"


def test_credential_item_bad_dates_returns_invalid_request():
    """PRD §3.3: "The expiration must fall strictly after the issue date, or the
    create is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/credential_item_bad_dates_returns_invalid_request
    """
    org = _new_org()
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    resp = api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(
            issued_date="2030-01-01T00:00:00.000Z",
            expiration_date="2029-01-01T00:00:00.000Z"),
        SPEC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_payer_bad_enum_payer_type_returns_invalid_request():
    """PRD §3.1: "a `payer_type` that must be one of `COMMERCIAL`, `MEDICARE`, or
    `MEDICAID`."
    PRD §2.6: "valid enum members ... (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/payer_bad_enum_payer_type_returns_invalid_request
    """
    org = _new_org()
    resp = api_client.create_payer(
        create_payer_payload(org["id"], name="X", payer_type="PRIVATE", panel_capacity=5),
        make_enrollment_coordinator_headers("enr-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# =========================================================================
# Application lifecycle preconditions
# =========================================================================
def test_submit_application_without_license_returns_no_license():
    """PRD §3.2: "when at least one credential item of type `STATE_LICENSE`
    already exists for the provider (otherwise `ERR_NO_LICENSE_ON_FILE`)."

    Design: Corner/state_machines/submit_application_without_license_returns_no_license
    """
    org = _new_org()
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(item_type="DEA_REGISTRATION", identifier="DEA-1"),
        SPEC), 201)
    resp = api_client.submit_application(provider["id"], SPEC)
    validate_error(resp, ApiErrorId.ERR_NO_LICENSE_ON_FILE.value)


def test_submit_application_without_caqh_returns_caqh_required():
    """PRD §3.2: "when the provider has a non-empty `caqh_id` on file (otherwise
    `ERR_CAQH_REQUIRED`)".

    Design: Corner/state_machines/submit_application_without_caqh_returns_caqh_required
    """
    org = _new_org()
    payload = create_provider_payload(org["id"])
    payload.pop("caqh_id")
    provider = validate_success(api_client.create_provider(payload, SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    resp = api_client.submit_application(provider["id"], SPEC)
    validate_error(resp, ApiErrorId.ERR_CAQH_REQUIRED.value)


def test_begin_verification_from_draft_returns_not_submitted():
    """PRD §3.2: "Beginning verification moves the application from `SUBMITTED` to
    `IN_VERIFICATION` and is permitted only when the application is currently
    `SUBMITTED` (otherwise `ERR_APPLICATION_NOT_SUBMITTED`)."

    Design: Corner/state_machines/begin_verification_from_draft_returns_invalid_state
    """
    org = _new_org()
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    resp = api_client.begin_verification(provider["id"], SPEC)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED.value)


def test_finalize_verification_with_pending_psv_returns_incomplete():
    """PRD §3.2: "Finalizing verification moves the application from
    `IN_VERIFICATION` to `READY_FOR_REVIEW` and is permitted only when the
    application is currently `IN_VERIFICATION` (otherwise
    `ERR_APPLICATION_NOT_IN_VERIFICATION`) and when no credential item remains in
    `PENDING_PSV` (otherwise `ERR_VERIFICATIONS_INCOMPLETE`)."

    Design: Corner/state_machines/finalize_verification_with_pending_psv_returns_incomplete
    """
    org_id, provider, item = fx.setup_provider_in_verification()
    resp = api_client.finalize_verification(provider["id"], SPEC)
    validate_error(resp, ApiErrorId.ERR_VERIFICATIONS_INCOMPLETE.value)


def test_start_recredentialing_not_due_returns_error():
    """PRD §3.7: "To renew, a `CredentialingSpecialist` starts re-credentialing,
    which is permitted only when the provider's `recred_state` is `RECRED_DUE`
    (otherwise `ERR_RECRED_NOT_DUE`)."

    Design: Corner/state_machines/start_recredentialing_not_due_returns_error
    """
    org = _new_org()
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    resp = api_client.start_recredentialing(provider["id"], SPEC)
    validate_error(resp, ApiErrorId.ERR_RECRED_NOT_DUE.value)
