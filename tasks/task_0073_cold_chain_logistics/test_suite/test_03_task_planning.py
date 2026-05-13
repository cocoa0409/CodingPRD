"""Transport task planning tests (PRD §3.2).

PRD coverage: §3.2 task creation, payload schema and constraints.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TaskParties,
    assert_transport_task,
    create_transport_task_payload,
    get_clock_now,
    iso_utc,
    make_dispatcher_headers,
    parse_iso,
    validate_error,
    validate_success,
)


def _future_start():
    return parse_iso(get_clock_now()) + timedelta(seconds=300)


# ===========================================================================
# Successful creation
# ===========================================================================
def test_create_task_planned_status(api):
    """PRD §3.2: 'A shipper, or a dispatcher operating on the shipper's
    behalf, creates a TransportTask in the PLANNED state.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
    )
    data = validate_success(
        api.create_transport_task(payload, parties.shipper_h()),
        expected_status=201,
    )
    assert_transport_task(data)
    assert data["status"] == "PLANNED"
    assert data["shipper_id"] == parties.shipper_id
    assert data["carrier_id"] == parties.carrier_id
    assert data["consignee_id"] == parties.consignee_id


def test_create_task_default_polling_interval_seconds(api):
    """PRD §3.2: 'polling_interval_seconds, an integer in the range ten
    to three thousand six hundred, defaulting to sixty when omitted.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
    )
    payload.pop("polling_interval_seconds", None)
    data = validate_success(
        api.create_transport_task(payload, parties.shipper_h()),
        expected_status=201,
    )
    assert data["polling_interval_seconds"] == 60


def test_create_task_default_stop_handover_required_true(api):
    """PRD §3.2: 'a boolean handover_required (default true).'"""
    parties = TaskParties()
    start = _future_start()
    stops = [
        {
            "sequence": 1, "location_label": "A",
            "planned_arrival_at": iso_utc(start + timedelta(seconds=600)),
        },
        {
            "sequence": 2, "location_label": "B",
            "planned_arrival_at": iso_utc(start + timedelta(seconds=1200)),
        },
    ]
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=start,
        stops=stops,
    )
    data = validate_success(
        api.create_transport_task(payload, parties.shipper_h()),
        expected_status=201,
    )
    for s in data["stops"]:
        assert s["handover_required"] is True


# ===========================================================================
# Validation failures
# ===========================================================================
def test_create_task_temp_min_not_less_than_temp_max_rejected(api):
    """PRD §3.2: 'temp_min_celsius must be strictly greater than minus
    eighty and strictly less than temp_max_celsius.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
        temp_min_celsius=10.00,
        temp_max_celsius=5.00,  # inverted
    )
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_task_temp_min_at_floor_rejected(api):
    """PRD §3.2: 'temp_min_celsius must be strictly greater than minus
    eighty.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
        temp_min_celsius=-80.00,
        temp_max_celsius=5.00,
    )
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_task_temp_max_at_ceiling_rejected(api):
    """PRD §3.2: 'temp_max_celsius must be strictly less than eighty.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
        temp_min_celsius=-5.00,
        temp_max_celsius=80.00,
    )
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_task_planned_end_before_start_rejected(api):
    """PRD §3.2: 'planned_end_at (ISO 8601 UTC, strictly later than
    planned_start_at).'"""
    parties = TaskParties()
    start = _future_start()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=start,
    )
    payload["planned_end_at"] = iso_utc(start - timedelta(seconds=60))
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_task_polling_interval_below_min_rejected(api):
    """PRD §3.2: 'polling_interval_seconds, an integer in the range ten
    to three thousand six hundred.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
        polling_interval_seconds=9,
    )
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_task_polling_interval_above_max_rejected(api):
    """PRD §3.2: 'polling_interval_seconds, an integer in the range ten
    to three thousand six hundred.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
        polling_interval_seconds=3601,
    )
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_task_invalid_cargo_type_rejected(api):
    """PRD §3.2: 'cargo_type — one of FOOD, PHARMACEUTICAL, or
    BIOLOGICAL.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
        cargo_type="HAZMAT",
    )
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Stop sequence rules
# ===========================================================================
def test_create_task_stop_arrival_not_strictly_increasing_rejected(api):
    """PRD §3.2: 'a planned_arrival_at ISO 8601 UTC timestamp strictly
    greater than the preceding stop's planned_arrival_at.'"""
    parties = TaskParties()
    start = _future_start()
    stops = [
        {
            "sequence": 1, "location_label": "A",
            "planned_arrival_at": iso_utc(start + timedelta(seconds=1200)),
            "handover_required": True,
        },
        {
            "sequence": 2, "location_label": "B",
            "planned_arrival_at": iso_utc(start + timedelta(seconds=600)),
            "handover_required": True,
        },
    ]
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=start,
        stops=stops,
    )
    resp = api.create_transport_task(payload, parties.shipper_h())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Patch — version + OCC
# ===========================================================================
def test_patch_task_version_conflict(api):
    """PRD §2.5: 'If supplied, the value is compared against the row's
    current version; a mismatch is rejected with ERR_VERSION_CONFLICT.'"""
    parties = TaskParties()
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=_future_start(),
    )
    task = validate_success(
        api.create_transport_task(payload, parties.shipper_h()),
        expected_status=201,
    )
    bad_version = task["version"] + 99
    resp = api.patch_transport_task(
        task["id"],
        {"version": bad_version, "polling_interval_seconds": 120},
        make_dispatcher_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)
