"""CRUD, creation echoes, defaults, computed fields, listing, reference
integrity, and error catalogue corners.

These breadth probes exercise the entity surface and the body-level error
catalogue (validation, reference-not-found, not-found, duplicate permit number).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    create_plan,
    create_account,
    create_system,
    create_sensor,
    issue_permit,
    create_monitoring_plan_payload,
    create_account_payload,
    create_system_payload,
    create_permit_payload,
    create_alarm_event_payload,
    assert_monitoring_plan,
    NON_EXISTENT_UUID,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
           max_sensors=32, cellular_backup_included=True)


# ─── entities ────────────────────────────────────────────────────────────────

def test_create_monitoring_plan_returns_201_echoes_fields(api):
    """PRD §3.1: "An `Administrator` creates a plan by supplying its `tier` — one
    of `BASIC`, `PLUS`, or `PRO`... together with the `monthly_fee_cents` charged
    each cycle (which may not be negative), a `police_dispatch_included` flag, a
    `max_sensors` ceiling (at least 1), and a `cellular_backup_included` flag."

    Design: Corner/entities/create_monitoring_plan_returns_201_all_fields
    """
    res = api.create_monitoring_plan(
        create_monitoring_plan_payload(tier="BASIC", monthly_fee_cents=1500,
                                       police_dispatch_included=False, max_sensors=8,
                                       cellular_backup_included=False), ADMIN)
    plan = validate_success(res, 201)
    assert_monitoring_plan(plan)
    assert plan["tier"] == "BASIC"
    assert plan["monthly_fee_cents"] == 1500


def test_get_account_returns_pending_and_suspended(api):
    """PRD §3.1: "A freshly created account begins with `contract_status` of
    `PENDING`; its derived `monitoring_status` reads `SUSPENDED` because no
    service runs before activation; and every balance and counter starts at
    zero."

    Design: Corner/entities/get_account_returns_stored_data
    """
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    acct = create_account(plan["id"])
    fetched = validate_success(api.get_account(acct["id"], ADMIN), 200)
    assert fetched["contract_status"] == "PENDING"
    assert fetched["monitoring_status"] == "SUSPENDED"


def test_list_monitoring_plans_array_envelope_pagination(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping in the
    `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_monitoring_plans_paginated_envelope
    """
    create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                max_sensors=8, cellular_backup_included=False)
    data, meta = validate_paginated(api.list_monitoring_plans(ADMIN))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_get_account_nonexistent_returns_not_found(api):
    """PRD §2.5: "when a request addresses a resource by its identifier in the
    path and no such resource exists, the request is rejected with `ERR_NOT_FOUND`
    before further processing."

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    res = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_account_missing_contract_term_returns_validation(api):
    """PRD §2.10: "Request-body well-formedness — all required input fields
    present, every enum member valid, every numeric input within range — is
    logically enforced immediately after authentication... a malformed body is
    rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_account_missing_required_field_returns_validation
    """
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    payload = create_account_payload(plan["id"])
    del payload["contract_term_months"]
    res = api.create_account(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_create_account_invalid_premises_enum_returns_validation(api):
    """PRD §2.10: "Request-body well-formedness — all required input fields
    present, every enum member valid, every numeric input within range — is
    logically enforced immediately after authentication... a malformed body is
    rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_account_invalid_premises_enum_returns_validation
    """
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    res = api.create_account(
        create_account_payload(plan["id"], premises_type="OFFICE"), ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_new_system_test_mode_false_and_disarmed(api):
    """PRD §3.3: "A newly registered system starts `DISARMED`, with `test_mode`
    false, `sensor_count` zero, and `communicator_health` derived from the
    telemetry."

    Design: Corner/entities/system_field_default_test_mode_false
    """
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    assert system["test_mode"] is False
    assert system["arming_state"] == "DISARMED"


def test_communicator_health_offline_on_stale_checkin(api):
    """PRD §3.3: "if `last_checkin_minutes_ago` is greater than 360 minutes (that
    is, more than six hours), the system is `OFFLINE` outright and no further
    checks are made."

    Design: Corner/entities/system_computed_communicator_health_offline_on_stale_checkin
    """
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR", last_checkin_minutes_ago=361)
    assert system["communicator_health"] == "OFFLINE"


def test_monitoring_plan_has_no_version_field(api):
    """PRD §2.4: "The `MonitoringPlan` entity is the sole exception. A plan is an
    immutable price-book row, so it carries only `id` and `created_at`; it has
    neither `updated_at` nor `version`."

    Design: Corner/entities/monitoring_plan_immutable_no_version_field
    """
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    fetched = validate_success(api.get_monitoring_plan(plan["id"], ADMIN), 200)
    assert "version" not in fetched, "an immutable plan carries no version field"
    assert "updated_at" not in fetched, "an immutable plan carries no updated_at field"


def test_create_system_unknown_account_reference_not_found(api):
    """PRD §2.5: "when a creation request names another resource by a body-level
    foreign key — a `plan_id` on an account, an `account_id` on a system or
    permit... that reference must resolve to an existing row. A dangling reference
    is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_system_unknown_account_id_returns_reference_not_found
    """
    res = api.create_system(create_system_payload(NON_EXISTENT_UUID, primary_path="BROADBAND"), ADMIN)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


def test_list_systems_filtered_by_account_id(api):
    """PRD §3.9: "related resources are discovered through filter parameters on
    the list endpoints rather than through nested paths... systems by
    `account_id`."

    Design: Corner/entities/flat_fk_filter_systems_by_account_id
    """
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    a1 = create_account(plan["id"])
    a2 = create_account(plan["id"])
    create_system(a1["id"], primary_path="BROADBAND")
    data, meta = validate_paginated(api.list_systems(ADMIN, params={"account_id": a2["id"]}))
    assert meta["total_count"] == 0, "account a2 has no systems"


# ─── errors ──────────────────────────────────────────────────────────────────

def test_duplicate_permit_number_rejected(api):
    """PRD §3.8: "A duplicate `permit_number` across any account is rejected with
    `ERR_DUPLICATE_PERMIT_NUMBER`."

    Design: Corner/errors/duplicate_permit_number_rejected
    """
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=8, cellular_backup_included=False)
    a1 = create_account(plan["id"])
    a2 = create_account(plan["id"])
    issue_permit(a1["id"], "P-DUP", filed_days_late=0)
    res = api.create_permit(create_permit_payload(a2["id"], "P-DUP", filed_days_late=0), ADMIN)
    validate_error(res, "ERR_DUPLICATE_PERMIT_NUMBER")


def test_alarm_event_unknown_sensor_reference_not_found(api):
    """PRD §2.5: "a `system_id` on a sensor or alarm event, or a `sensor_id` on an
    alarm event — that reference must resolve to an existing row. A dangling
    reference is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/errors/reference_not_found_alarm_event_bad_sensor
    """
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR")
    res = api.create_alarm_event(
        create_alarm_event_payload(system["id"], NON_EXISTENT_UUID, signal_type="FIRE"), OPERATOR)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")
