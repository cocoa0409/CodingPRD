"""Entity creation / required-field / defaults / system-field / duplicate corners, listing
and reverse-reachability endpoints, and RBAC denials.

Covers the corner entities, endpoints, and rbac sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_subscriber_headers, make_agent_headers, TEST_USERS, NON_EXISTENT_UUID,
    create_plan_payload, create_subscriber_payload, create_device_payload,
    setup_plan_subscriber_contract, setup_active_contract_with_device, setup_assigned_alarm,
    create_subscriber, create_plan, create_contract, set_clock, raise_alarm,
    create_shift,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Corner — entities
# ===========================================================================
def test_create_plan_returns_201_with_fields(api):
    """PRD 3.1: "Each plan also carries an `archived` flag that begins `false`".
    PRD 3.1: "A plan is created with a `tier` — one of `BASIC`, `PLUS`, or `PREMIUM`".

    Design: Corner/entities/create_monitoring_plan_returns_201_with_fields
    """
    res = api.create_plan(create_plan_payload(tier="BASIC", monthly_fee_cents=3000), ADMIN)
    data = validate_success(res, 201)
    assert data["tier"] == "BASIC"
    assert data["archived"] is False


def test_create_subscriber_missing_email_returns_invalid_request(api):
    """PRD 3.1: "A subscriber account is created by a `PlatformAdmin` with a `full_name`, an
    `email`, a `residence_address`, and a `phone`."
    PRD 2.9: "Field-level input validity — required fields present, enum values in range,
    integers within their bounds, amounts non-negative, and interval ordering — is the
    lowest-priority family and surfaces as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_subscriber_missing_email_returns_invalid_request
    """
    payload = create_subscriber_payload()
    del payload["email"]
    res = api.create_subscriber(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_device_fall_detection_defaults_false(api):
    """PRD 3.5: "A **Device** is registered — by either a `PlatformAdmin` or the owning
    `Subscriber` — under a contract by supplying the `contract_id`, a `serial_number`, a
    `device_type`, and optionally a `fall_detection_enabled` flag (default `false`)."
    PRD 3.5: "A new device begins in `REGISTERED` status".
    PRD 3.5: "The device also tracks `battery_pct` (last reported battery percentage, an integer
    from 0 to 100, default 100)".
    PRD 3.5: "A percentage of 40 or more is `GOOD`".

    Design: Corner/entities/device_fall_detection_default_false
    """
    plan, sub, contract = setup_plan_subscriber_contract()
    res = api.create_device(create_device_payload(contract["id"], device_type="PENDANT"),
                            make_subscriber_headers(sub["id"]))
    data = validate_success(res, 201)
    assert data["fall_detection_enabled"] is False
    assert data["status"] == "REGISTERED"
    assert data["battery_health"] == "GOOD"


def test_get_nonexistent_subscriber_returns_not_found(api):
    """PRD 2.9: "returns `ERR_NOT_FOUND` for the first identifier that does not resolve to an
    existing resource."

    Design: Corner/entities/get_subscriber_nonexistent_returns_not_found
    """
    res = api.get_subscriber(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_subscriber_system_fields_server_minted(api):
    """PRD 3.1: "Each subscriber carries a system-managed `status` that is set to `ACTIVE` on
    creation and is the only value that field takes in this system."
    PRD 2.4: "`version`, an integer that starts at 1 on creation".

    Design: Corner/entities/system_fields_server_minted_on_create
    """
    res = api.create_subscriber(create_subscriber_payload(), ADMIN)
    data = validate_success(res, 201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_device_invalid_device_type_returns_invalid_request(api):
    """PRD 3.5: "The `device_type` is one of `PENDANT`, `WRISTBAND`, `MOBILE_GPS`, or
    `HOME_BASE`."
    PRD 2.9: "Field-level input validity — required fields present, enum values in range,
    integers within their bounds, amounts non-negative, and interval ordering — is the
    lowest-priority family and surfaces as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/device_invalid_device_type_enum_returns_invalid_request
    """
    plan, sub, contract = setup_plan_subscriber_contract()
    res = api.create_device(
        {"contract_id": contract["id"], "serial_number": "SN-BAD", "device_type": "SMARTWATCH"},
        make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_device_test_battery_out_of_range_returns_invalid_request(api):
    """PRD 3.5: "A `Subscriber` submits a **DeviceTest** against their device, supplying the
    `reported_battery_pct` (an integer from 0 to 100) and a boolean `signal_ok`."
    PRD 2.9: "Field-level input validity — required fields present, enum values in range,
    integers within their bounds, amounts non-negative, and interval ordering — is the
    lowest-priority family and surfaces as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/device_test_battery_out_of_range_returns_invalid_request
    """
    plan, sub, contract = setup_plan_subscriber_contract()
    device = get_success_data(api.create_device(
        create_device_payload(contract["id"]), make_subscriber_headers(sub["id"])))
    res = api.submit_test(device["id"], {"reported_battery_pct": 150, "signal_ok": True},
                          make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_contract_pins_monthly_fee_on_activation(api):
    """PRD 3.2: "it copies `monthly_fee_cents` into `pinned_monthly_fee_cents`".

    Design: Corner/entities/contract_pins_plan_fees_on_activation_computed_field
    """
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=create_plan_payload(monthly_fee_cents=4500), clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    assert contract["pinned_monthly_fee_cents"] == 4500, (
        f"pinned_monthly_fee_cents must equal plan fee 4500, got {contract['pinned_monthly_fee_cents']}"
    )


def test_duplicate_device_serial_returns_duplicate(api):
    """PRD 3.5: "The `serial_number` is unique across all devices; a duplicate is rejected with
    `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_device_serial_returns_duplicate
    """
    plan, sub, contract = setup_plan_subscriber_contract()
    hdrs = make_subscriber_headers(sub["id"])
    get_success_data(api.create_device(
        create_device_payload(contract["id"], serial_number="SN-DUP"), hdrs))
    res = api.create_device(
        {"contract_id": contract["id"], "serial_number": "SN-DUP", "device_type": "WRISTBAND"}, hdrs)
    validate_error(res, "ERR_DUPLICATE")


# ===========================================================================
# Corner — endpoints
# ===========================================================================
def test_list_contracts_pagination_and_filter(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."
    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/endpoints/list_contracts_pagination_envelope
    """
    plan = create_plan()
    sub = create_subscriber()
    create_contract(sub["id"], plan["id"])
    res = api.list_contracts(ADMIN, params={"subscriber_id": sub["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_device_alarms_subresource_lists_raised_alarms(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."
    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    The device-alarms list subresource (Section 4) returns the device's raised alarms; here the
    one alarm raised on the device is present, so total_count is 1.

    Design: Corner/endpoints/reverse_reachability_device_alarms_subresource
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    res = api.list_device_alarms(device["id"], TEST_USERS["agent_headers"])
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1


# ===========================================================================
# Corner — RBAC
# ===========================================================================
def test_subscriber_cannot_create_plan_forbidden(api):
    """PRD 2.1: "the system checks whether their role is permitted to perform the requested
    operation; a role acting outside its remit is rejected with `ERR_FORBIDDEN`."
    PRD Section 4: creating a monitoring plan is a PlatformAdmin operation.

    Design: Corner/rbac/subscriber_cannot_create_plan_returns_forbidden
    """
    sub = create_subscriber()
    res = api.create_plan(create_plan_payload(tier="BASIC"), make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_subscriber_cannot_act_on_other_subscribers_device(api):
    """PRD 2.1: "A subscriber who attempts to act on a contract, device, or contact they do not
    own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/subscriber_cannot_act_on_other_subscribers_device_returns_not_owner
    """
    plan = create_plan()
    sub_a = create_subscriber()
    sub_b = create_subscriber()
    contract_a = create_contract(sub_a["id"], plan["id"])
    device_a = get_success_data(api.create_device(
        create_device_payload(contract_a["id"]), make_subscriber_headers(sub_a["id"])))
    # B submits a test on A's device.
    res = api.submit_test(device_a["id"], {"reported_battery_pct": 90, "signal_ok": True},
                          make_subscriber_headers(sub_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_unassigned_agent_cannot_dispatch(api):
    """PRD 3.10: "Every dispatch step requires that the acting agent is the alarm's assigned
    agent — `assigned_agent_id` must equal `X-User-ID` — or the step is rejected with
    `ERR_NOT_ASSIGNED_AGENT`."

    Design: Corner/rbac/agent_not_assigned_cannot_dispatch_returns_not_assigned_agent
    """
    sub, contract, device, alarm = setup_assigned_alarm(agent_user_id="agent-A")
    # agent-B (not the assigned agent) attempts a dispatch action.
    res = api.create_dispatch_action(
        alarm["id"], {"action_type": "CALL_SUBSCRIBER", "outcome": "ANSWERED"},
        make_agent_headers("agent-B"))
    validate_error(res, "ERR_NOT_ASSIGNED_AGENT")


def test_missing_headers_returns_unauthenticated(api):
    """PRD 2.1: "Every request must be authenticated through two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. If either header is missing or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.list_plans(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
