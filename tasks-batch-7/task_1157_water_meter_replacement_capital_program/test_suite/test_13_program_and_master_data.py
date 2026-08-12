"""Corner coverage — entities: creation defaults, computed-field handling,
uniqueness, not-found envelope, pagination, append-only readings."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_ID, TEST_USERS, api_client, assert_meter_reading,
    create_meter, create_program_payload, create_account_payload,
    create_program, create_wave, create_installed_account,
    get_success_data, is_valid_uuid, is_iso8601_timestamp,
    setup_work_order_created, validate_error, validate_paginated,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def test_program_create_defaults_and_system_fields(api):
    """PRD §3.1: "A new program starts in `PLANNING` status with
    `budget_committed_cents` and `budget_spent_cents` at zero,
    `completed_meter_count` at zero, and `budget_posture` of `FUNDED`." And:
    "optionally `notice_days`, the regulatory minimum days between
    notification delivery and appointment slot, which defaults to 3 when
    omitted."

    Design: Corner/entities/program_create_defaults_and_system_fields
    """
    # Omit notice_days entirely to exercise the server-side default of 3.
    payload = create_program_payload(budget_total_cents=1000000,
                                     target_meter_count=100)
    payload.pop("notice_days")
    resp = api.create_program(payload, PM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PLANNING"
    assert data["budget_committed_cents"] == 0
    assert data["budget_spent_cents"] == 0
    assert data["budget_available_cents"] == 1000000
    assert data["budget_posture"] == "FUNDED"
    assert data["completed_meter_count"] == 0
    assert data["notice_days"] == 3
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_account_priority_tier_default(api):
    """PRD §3.2: "an optional `priority_tier` of `STANDARD`, `SENSITIVE`, or
    `CRITICAL` defaulting to `STANDARD`" and "A new account starts
    `ELIGIBLE`."

    Design: Corner/entities/account_priority_tier_default
    """
    payload = create_account_payload(account_number="A-0001",
                                     service_address="1 Test Way",
                                     meter_location="INSIDE",
                                     customer_name="Te",
                                     customer_phone="555-0001",
                                     avg_daily_usage_ccf=1.5,
                                     last_billed_read_value=500,
                                     last_billed_read_at="2026-04-01T00:00:00Z")
    payload.pop("priority_tier", None)  # factory omits it; be explicit anyway
    resp = api.create_account(payload, SCHED)
    data = validate_success(resp, expected_status=201)
    assert data["priority_tier"] == "STANDARD"
    assert data["status"] == "ELIGIBLE"


def test_program_create_computed_input_ignored(api):
    """PRD §3.1: "A new program starts in `PLANNING` status with
    `budget_committed_cents` and `budget_spent_cents` at zero,
    `completed_meter_count` at zero, and `budget_posture` of `FUNDED`."

    Design: Corner/entities/program_create_computed_input_ignored
    """
    payload = create_program_payload(budget_total_cents=1000000,
                                     target_meter_count=100)
    payload["budget_committed_cents"] = 999999  # computed field as input
    resp = api.create_program(payload, PM)
    data = validate_success(resp, expected_status=201)
    assert data["budget_committed_cents"] == 0
    assert data["budget_available_cents"] == 1000000


def test_work_order_get_not_found_returns_error_envelope(api):
    """PRD §2.7: "Existence — every path identifier and every body foreign-key
    reference resolves to an existing resource, validated left to right along
    the URL path (path variables are named `programId`, `contractorId`,
    `accountId`, `meterId`, `waveId`, `workOrderId`, `notificationId`,
    `appointmentId`, `caseId`, `readingId`, `registrationId`, `benchTestId`,
    `complaintId`, `auditId`, and `invoiceId`); otherwise `ERR_NOT_FOUND`."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/work_order_get_not_found_returns_error_envelope
    """
    resp = api.get_work_order(NON_EXISTENT_ID, SCHED)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)
    assert isinstance(err.get("message"), str) and err["message"]
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_work_order_create_bogus_wave_rejected(api):
    """PRD §2.7: "Existence — every path identifier and every body foreign-key
    reference resolves to an existing resource, validated left to right along
    the URL path (path variables are named `programId`, `contractorId`,
    `accountId`, `meterId`, `waveId`, `workOrderId`, `notificationId`,
    `appointmentId`, `caseId`, `readingId`, `registrationId`, `benchTestId`,
    `complaintId`, `auditId`, and `invoiceId`); otherwise `ERR_NOT_FOUND`."

    Design: Corner/entities/work_order_create_bogus_wave_rejected
    """
    resp = api.create_work_order(
        {"wave_id": NON_EXISTENT_ID, "service_account_id": NON_EXISTENT_ID},
        SCHED)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_duplicate_meter_serial_rejected(api):
    """PRD §3.2: "Meters enter the inventory through the `Scheduler` with a
    unique `serial_number` (a duplicate is refused with
    `ERR_METER_SERIAL_CONFLICT`)"

    Design: Corner/entities/duplicate_meter_serial_rejected
    """
    create_meter(serial_number="L-DUP", size_code="S_1", technology="LEGACY")
    resp = api.create_meter(
        {"serial_number": "L-DUP", "size_code": "S_2", "technology": "AMI"},
        SCHED)
    validate_error(resp, ApiErrorId.ERR_METER_SERIAL_CONFLICT.value,
                   expected_status=409)


def test_wave_list_pagination_limit_offset(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. List responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object."

    Design: Corner/entities/wave_list_pagination_limit_offset
    """
    prog = get_success_data(api_client.create_program(
        create_program_payload(budget_total_cents=1000000,
                               target_meter_count=100), PM))
    for i, (ws, we) in enumerate((
            ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"),
            ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"),
            ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")), start=1):
        create_wave(prog["id"], open_it=False, wave_number=i,
                    window_start=ws, window_end=we, capacity=5)
    page1, meta1 = validate_paginated(api.list_waves(
        PM, params={"program_id": prog["id"], "limit": 2}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_waves(
        PM, params={"program_id": prog["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_meter_reading_immutable_and_filtered_by_meter(api):
    """PRD §2.4: "The one exception is the meter reading: a reading is an
    append-only event carrying only `id` and `created_at`; it has no
    `updated_at` and no `version`, and no endpoint modifies or deletes a
    recorded reading."
    PRD §2.3: "readings by `work_order_id`, `meter_id`, and `read_type`"

    Design: Corner/entities/meter_reading_immutable_and_filtered_by_meter
    """
    ctx = setup_work_order_created()
    resp = api.create_reading({
        "work_order_id": ctx["work_order"]["id"],
        "meter_id": ctx["old_meter"]["id"],
        "read_type": "VERIFICATION",
        "value": 505,
        "source": "CUSTOMER",
        "read_at": "2026-05-03T08:00:00Z",
    }, SCHED)
    rdg = validate_success(resp, expected_status=201)
    assert_meter_reading(rdg)
    data, meta = validate_paginated(api.list_readings(
        SCHED, params={"meter_id": ctx["old_meter"]["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == rdg["id"]
    assert data[0]["read_type"] == "VERIFICATION"
    assert data[0]["value"] == 505
    assert data[0]["source"] == "CUSTOMER"
