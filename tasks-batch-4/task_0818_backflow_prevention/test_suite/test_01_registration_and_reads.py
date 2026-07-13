"""Registration basics, computed-field reads, listing, and not-found/validation errors.

Covers Corner/entities, Corner/state_machines (initial state), and
Corner/consistency_model instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    factories, fixtures,
    assert_connection, assert_device,
)

ADMIN = TEST_USERS["admin_headers"]


def test_connection_create_returns_all_fields(api):
    """PRD §3.1: "A newly registered connection opens in the `COMPLIANT` posture with
    `risk_tier` at `LOW`, `water_service_active` true, and every derived count —
    `protected_device_count`, `overdue_device_count`, `open_notice_count`, and
    `total_penalty_cents` — at zero."
    PRD §2.4: "a `version` integer that starts at 1 on creation and increments by one on
    every mutation of that resource."

    Design: Corner/entities/connection_create_returns_all_fields
    """
    payload = factories.connection_payload(account_number="AC-C01", address="9 Elm St",
                                           owner_user_id="owner-9", hazard_class="LOW_HAZARD")
    data = validate_success(api.create_connection(payload, ADMIN), expected_status=201)
    assert_connection(data)
    assert data["version"] == 1, f"expected version 1 on creation, got {data['version']}"
    assert data["compliance_posture"] == "COMPLIANT"
    assert data["risk_tier"] == "LOW"
    assert data["water_service_active"] is True
    assert data["protected_device_count"] == 0
    assert data["overdue_device_count"] == 0
    assert data["open_notice_count"] == 0
    assert data["total_penalty_cents"] == 0


def test_device_get_nonexistent_id_returns_not_found(api):
    """PRD §2.7: "the system validates their existence left to right in the order they
    appear, and returns the not-found error specific to the first missing entity:
    `ERR_CONNECTION_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_TESTER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`,
    `ERR_NOTICE_NOT_FOUND`, or `ERR_REPAIR_ORDER_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/device_get_nonexistent_id_returns_not_found
    """
    resp = api.get_device(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_FOUND)


def test_device_create_missing_required_serial_returns_validation(api):
    """PRD §2.10: "(14) body field presence, types, enum membership, and score ranges,
    else `ERR_VALIDATION`".
    PRD §3.1: "a `serial_number` that must be non-empty and unique across all devices."

    Design: Corner/entities/device_create_missing_required_serial_returns_validation
    """
    conn = fixtures.create_connection(api, ADMIN)
    payload = factories.device_payload(conn["id"])
    payload.pop("serial_number")
    resp = api.create_device(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_device_create_invalid_enum_type_returns_validation(api):
    """PRD §2.10: "(14) body field presence, types, enum membership, and score ranges,
    else `ERR_VALIDATION`".

    Design: Corner/entities/device_create_invalid_enum_type_returns_validation
    """
    conn = fixtures.create_connection(api, ADMIN)
    payload = factories.device_payload(conn["id"], serial_number="SN-C03", device_type="XYZ")
    resp = api.create_device(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_device_next_due_date_computed_from_install(api):
    """PRD §3.1: "The device's `next_test_due_date` is computed at creation by advancing a
    baseline date by `test_interval_months` whole calendar months."
    PRD §3.1: "Before the device has any accepted passing test — while `last_pass_date` is
    null — the baseline is the `install_date`."

    Design: Corner/entities/device_next_due_date_computed_from_install
    """
    conn = fixtures.create_connection(api, ADMIN)
    payload = factories.device_payload(conn["id"], serial_number="SN-C04",
                                       test_interval_months=12,
                                       install_date="2025-03-01T00:00:00Z")
    data = validate_success(api.create_device(payload, ADMIN), expected_status=201)
    assert data["next_test_due_date"][:10] == "2026-03-01", \
        f"expected due 2026-03-01 (install + 12 months), got {data['next_test_due_date']}"


def test_connection_list_returns_pagination_envelope(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/entities/connection_list_returns_pagination_envelope
    """
    fixtures.create_connection(api, ADMIN, address="1 Main St")
    fixtures.create_connection(api, ADMIN, address="1 Main St")
    data, meta = validate_paginated(api.list_connections(ADMIN))
    assert isinstance(data, list)
    assert meta["total_count"] >= 2, f"expected total_count >= 2, got {meta['total_count']}"
    assert "has_more" in meta and "limit" in meta and "offset" in meta


def test_device_initial_state_is_active(api):
    """PRD §3.1: "A new device starts with its `status` field set to `ACTIVE` and its
    `last_pass_date` unset (it has no accepted passing test yet)."

    Design: Corner/state_machines/device_initial_state_is_active
    """
    conn = fixtures.create_connection(api, ADMIN)
    payload = factories.device_payload(conn["id"], serial_number="SN-C08",
                                       device_type="DC", hazard_rating="LOW")
    data = validate_success(api.create_device(payload, ADMIN), expected_status=201)
    assert data["status"] == "ACTIVE"


def test_device_create_computed_fields_visible_immediately(api):
    """PRD §3.1: "The device's `next_test_due_date` is computed at creation by advancing a
    baseline date by `test_interval_months` whole calendar months."
    PRD §2.2: "operations that create or modify a resource will return the created or
    updated resource object in the data field."

    Design: Corner/consistency_model/device_create_computed_fields_visible_immediately
    """
    conn = fixtures.create_connection(api, ADMIN)
    payload = factories.device_payload(conn["id"], serial_number="SN-C26",
                                       test_interval_months=12,
                                       install_date="2026-01-01T00:00:00Z")
    data = validate_success(api.create_device(payload, ADMIN), expected_status=201)
    assert_device(data)
    assert data["next_test_due_date"][:10] == "2027-01-01", \
        f"expected computed due 2027-01-01 in the creation response, got {data['next_test_due_date']}"
