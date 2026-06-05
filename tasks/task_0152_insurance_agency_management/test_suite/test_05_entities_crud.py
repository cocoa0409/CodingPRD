"""Breadth tests for entity creation, computed fields, required-field validation,
not-found, and uniqueness.

Queue B (Corner) translations for the `entities` section.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_producer_headers,
    assert_carrier,
    assert_account,
    create_producer,
    create_license,
    create_active_carrier,
    create_product,
    create_account,
    create_trust_account,
    set_clock,
    factories,
)

ADMIN = lambda: TEST_USERS["agency_admin_headers"]
MANAGER = lambda: TEST_USERS["account_manager_headers"]
TRUST = lambda: TEST_USERS["trust_accountant_headers"]


def test_carrier_create_returns_201_with_defaults(api):
    """PRD §3.1: "an optional `download_supported` flag indicating whether the carrier offers
    an ACORD policy-download feed (defaulting to false when omitted)".
    PRD §3.1: "A newly created carrier begins in the `PROSPECTIVE` state."
    PRD §2.4: "a `version`, an integer that begins at 1 on creation and increments by exactly
    one on every mutation."

    Design: Corner/entities/carrier_create_returns_201_with_defaults
    """
    # Omit download_supported so the server applies its declared default of false.
    payload = factories.create_carrier_payload(name="Acme Ins")
    payload.pop("download_supported", None)
    resp = api.create_carrier(payload, ADMIN())
    data = validate_success(resp, 201)
    assert_carrier(data)
    assert data["status"] == "PROSPECTIVE", data
    assert data["version"] == 1, data
    assert data["download_supported"] is False, data


def test_carrier_get_not_found(api):
    """PRD §2.5: "the first identifier that names no existing resource causes the whole request
    to fail with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated."

    Design: Corner/entities/carrier_get_not_found
    """
    resp = api.get_carrier(NON_EXISTENT_UUID, ADMIN())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_carrier_missing_required_field_returns_invalid_request(api):
    """PRD §2.5: "the body must parse, every required field must be present, every field must
    be of the correct type, every enumerated field must carry a permitted value, and every
    numeric field must fall within its declared range; any violation yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/carrier_missing_required_field_returns_invalid_request
    """
    payload = factories.create_carrier_payload()
    payload.pop("naic_code")
    resp = api.create_carrier(payload, ADMIN())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_producer_npn_duplicate_rejected(api):
    """PRD §2.8: "a `Producer` must have an `npn` distinct from every other producer's ...
    Any creation that would duplicate one of these values is rejected with `ERR_DUPLICATE`
    (HTTP 409)."

    Design: Corner/entities/producer_npn_duplicate_rejected
    """
    api.create_producer(factories.create_producer_payload(full_name="First", npn="NPN-DUP"), ADMIN())
    resp = api.create_producer(
        factories.create_producer_payload(full_name="Second", npn="NPN-DUP"), ADMIN()
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_trust_account_state_code_duplicate_rejected(api):
    """PRD §2.8: "a `TrustAccount` must have a `state_code` distinct from every other trust
    account's. Any creation that would duplicate one of these values is rejected with
    `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/entities/trust_account_state_code_duplicate_rejected
    """
    api.create_trust_account(factories.create_trust_account_payload(name="CA Trust", state_code="CA"), TRUST())
    resp = api.create_trust_account(
        factories.create_trust_account_payload(name="CA Trust 2", state_code="CA"), TRUST()
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_license_status_computed_active_at_now(api):
    """PRD §3.2: "A license carries no stored status; instead its validity is computed against
    the authoritative clock at read time: it is `ACTIVE` when the current moment is at or after
    its `effective_date` and strictly before its `expiration_date`".

    Design: Corner/entities/license_status_computed_active_at_now
    """
    set_clock("2026-06-01T00:00:00Z")
    producer = create_producer()
    lic = create_license(
        producer["id"], state_code="CA", line_of_business="AUTO",
        effective_date="2025-01-01T00:00:00Z", expiration_date="2030-01-01T00:00:00Z",
    )
    data = get_success_data(api.get_license(lic["id"], ADMIN()))
    assert data["status"] == "ACTIVE", data


def test_license_status_computed_pending_before_effective(api):
    """PRD §3.2: "it is ... `PENDING` while the current moment is still before its
    `effective_date`."

    Design: Corner/entities/license_status_computed_pending_before_effective
    """
    set_clock("2024-06-01T00:00:00Z")
    producer = create_producer()
    lic = create_license(
        producer["id"], state_code="CA", line_of_business="AUTO",
        effective_date="2025-01-01T00:00:00Z", expiration_date="2030-01-01T00:00:00Z",
    )
    data = get_success_data(api.get_license(lic["id"], ADMIN()))
    assert data["status"] == "PENDING", data


def test_policy_system_fields_ignored_on_input(api):
    """PRD §3.3: "its absence sets `term_kind` to `NEW_BUSINESS`. ... the policy is created in
    `QUOTED` status, the policy lifecycle's initial state."
    PRD §2.4: "a `version`, an integer that begins at 1 on creation".

    Design: Corner/entities/policy_system_fields_ignored_on_input
    """
    carrier = create_active_carrier()
    product = create_product(carrier["id"])
    producer = create_producer()
    account = create_account(producer["id"])
    resp = api.create_policy(
        factories.create_policy_payload(
            account["id"], product["id"], producer["id"],
            annual_premium_cents=100000,
            effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
        ),
        make_producer_headers(producer["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "QUOTED", data
    assert data["term_kind"] == "NEW_BUSINESS", data
    assert data["version"] == 1, data


def test_account_active_policy_count_starts_zero(api):
    """PRD §3.3: "An account tracks a derived `active_policy_count` ... which starts at 0 and
    is recomputed on every policy state change that could affect it."

    Design: Corner/entities/account_active_policy_count_starts_zero
    """
    producer = create_producer()
    resp = api.create_account(
        factories.create_account_payload(producer["id"], name="Fresh Acct", account_type="COMMERCIAL"),
        MANAGER(),
    )
    data = validate_success(resp, 201)
    assert_account(data)
    assert data["active_policy_count"] == 0, data


def test_policy_create_unknown_account_not_found(api):
    """PRD §2.5: "The server resolves these identifiers left to right; the first identifier
    that names no existing resource causes the whole request to fail with `ERR_NOT_FOUND`
    (HTTP 404) before any business rule is evaluated."

    Design: Corner/entities/policy_create_unknown_account_not_found
    """
    carrier = create_active_carrier()
    product = create_product(carrier["id"])
    producer = create_producer()
    resp = api.create_policy(
        factories.create_policy_payload(
            NON_EXISTENT_UUID, product["id"], producer["id"],
            annual_premium_cents=100000,
            effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
        ),
        make_producer_headers(producer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_license_invalid_date_range_rejected(api):
    """PRD §3.2: "A license's `effective_date` must be strictly before its `expiration_date`,
    or the creation is rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/entities/license_invalid_date_range_rejected
    """
    producer = create_producer()
    resp = api.create_license(
        factories.create_license_payload(
            producer["id"], state_code="CA", line_of_business="AUTO",
            effective_date="2027-01-01T00:00:00Z", expiration_date="2026-01-01T00:00:00Z",
        ),
        ADMIN(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)
