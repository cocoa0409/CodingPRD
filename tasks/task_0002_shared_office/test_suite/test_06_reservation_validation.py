"""Reservation input validation tests — time window, granularity, capacity,
conflict detection.

Covers PRD §2.6 (time intervals are half-open; start < end; integer-minute boundaries;
±1h/+180d horizon) and §3.3 (granularity per kind; capacity; overlap guard).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    create_member,
    create_reservation_payload,
    create_resource,
    create_tenant,
    make_tenant_member_headers,
    setup_tenant_member_badge,
    validate_error,
    validate_success,
)


def _headers_for(member):
    return make_tenant_member_headers(member["id"])


def test_start_at_not_before_end_at_rejected(api, admin_headers):
    """PRD §2.6: "`start_at` must be strictly earlier than `end_at`, and both
    endpoints must lie within the window that begins one hour before the
    current clock and ends 180 days after it; any violation is rejected with
    `ERR_INVALID_TIME_WINDOW`."

    Claim: start_at == end_at → ERR_INVALID_TIME_WINDOW (422).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    resource = create_resource(kind="WORKSTATION")
    advance_clock_to("2026-07-02T08:00:00.000Z")
    payload = create_reservation_payload(
        tenant["id"], member["id"], resource["id"],
        "2026-07-02T10:00:00.000Z", "2026-07-02T10:00:00.000Z",
    )
    res = api.create_reservation(payload, _headers_for(member))
    validate_error(res, "ERR_INVALID_TIME_WINDOW", expected_status=422)


def test_sub_minute_precision_rejected(api, admin_headers):
    """PRD §3.3: "Reservation `start_at` and `end_at` must land on integer-minute
    boundaries (no sub-minute precision is accepted), `start_at` must be
    strictly earlier than `end_at`."

    Claim: start_at with non-zero seconds → ERR_INVALID_TIME_WINDOW (422).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    resource = create_resource(kind="WORKSTATION")
    advance_clock_to("2026-07-03T08:00:00.000Z")
    payload = create_reservation_payload(
        tenant["id"], member["id"], resource["id"],
        "2026-07-03T09:00:15.000Z", "2026-07-03T10:00:00.000Z",
    )
    res = api.create_reservation(payload, _headers_for(member))
    validate_error(res, "ERR_INVALID_TIME_WINDOW", expected_status=422)


def test_event_area_requires_4_hour_multiple(api, admin_headers):
    """PRD §3.3: "event-area reservation duration must be an exact multiple of
    four hours, meeting-room duration must be a multiple of half an hour, and
    workstation duration must be a multiple of one full hour; a mismatch
    surfaces `ERR_RESERVATION_GRANULARITY`."

    Claim: event-area 2-hour booking → ERR_RESERVATION_GRANULARITY (422).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    event_area = create_resource(kind="EVENT_AREA", code="EVT-GRAN-1")
    advance_clock_to("2026-07-06T07:00:00.000Z")  # Monday
    payload = create_reservation_payload(
        tenant["id"], member["id"], event_area["id"],
        "2026-07-06T09:00:00.000Z", "2026-07-06T11:00:00.000Z",  # 2h, not multiple of 4
    )
    res = api.create_reservation(payload, _headers_for(member))
    validate_error(res, "ERR_RESERVATION_GRANULARITY", expected_status=422)


def test_meeting_room_requires_half_hour_multiple(api, admin_headers):
    """PRD §3.3: "meeting-room duration must be a multiple of half an hour."

    Claim: meeting-room 40-minute booking → ERR_RESERVATION_GRANULARITY (422).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    mr = create_resource(kind="MEETING_ROOM", code="MR-GRAN-1")
    advance_clock_to("2026-07-06T07:00:00.000Z")
    payload = create_reservation_payload(
        tenant["id"], member["id"], mr["id"],
        "2026-07-06T09:00:00.000Z", "2026-07-06T09:40:00.000Z",  # 40min
    )
    res = api.create_reservation(payload, _headers_for(member))
    validate_error(res, "ERR_RESERVATION_GRANULARITY", expected_status=422)


def test_workstation_requires_full_hour_multiple(api, admin_headers):
    """PRD §3.3: "workstation duration must be a multiple of one full hour."

    Claim: workstation 90-minute booking → ERR_RESERVATION_GRANULARITY (422).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    ws = create_resource(kind="WORKSTATION", code="WS-GRAN-1")
    advance_clock_to("2026-07-06T07:00:00.000Z")
    payload = create_reservation_payload(
        tenant["id"], member["id"], ws["id"],
        "2026-07-06T09:00:00.000Z", "2026-07-06T10:30:00.000Z",  # 90 min
    )
    res = api.create_reservation(payload, _headers_for(member))
    validate_error(res, "ERR_RESERVATION_GRANULARITY", expected_status=422)


def test_capacity_exceeded_rejected(api, admin_headers):
    """PRD §3.3: "`Resource.capacity` must be at least the requested headcount,
    which defaults to 1 when the caller omits it, otherwise `ERR_CAPACITY_EXCEEDED`."

    Claim: requesting headcount > resource.capacity → ERR_CAPACITY_EXCEEDED.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    mr = create_resource(kind="MEETING_ROOM", code="MR-CAP-1", capacity=2)
    advance_clock_to("2026-07-07T08:00:00.000Z")
    payload = create_reservation_payload(
        tenant["id"], member["id"], mr["id"],
        "2026-07-07T09:00:00.000Z", "2026-07-07T10:00:00.000Z",
        headcount=5,
    )
    res = api.create_reservation(payload, _headers_for(member))
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=422)


def test_back_to_back_reservations_do_not_conflict(api, admin_headers):
    """PRD §2.6: "Reservation intervals are **half-open on the right**: a
    reservation with `start_at` 09:00 and `end_at` 11:00 occupies the time range
    that includes 09:00 and excludes 11:00, so back-to-back reservations of
    09:00-11:00 and 11:00-13:00 on the same resource do not conflict."

    Claim: R2 starting at R1.end_at is accepted without ERR_RESERVATION_CONFLICT.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    mr = create_resource(kind="MEETING_ROOM", code="MR-BTB-1")
    advance_clock_to("2026-07-08T07:00:00.000Z")
    payload1 = create_reservation_payload(
        tenant["id"], member["id"], mr["id"],
        "2026-07-08T09:00:00.000Z", "2026-07-08T11:00:00.000Z",
    )
    res1 = api.create_reservation(payload1, _headers_for(member))
    validate_success(res1, expected_status=201)
    payload2 = create_reservation_payload(
        tenant["id"], member["id"], mr["id"],
        "2026-07-08T11:00:00.000Z", "2026-07-08T13:00:00.000Z",
    )
    res2 = api.create_reservation(payload2, _headers_for(member))
    validate_success(res2, expected_status=201)


def test_overlapping_reservations_conflict(api, admin_headers):
    """PRD §3.3: "the proposed half-open interval from `start_at` inclusive to
    `end_at` exclusive must not overlap any existing reservation on the same
    `resource_id` whose `status` is one of `PENDING`, `CONFIRMED`, or `IN_USE`; a
    collision surfaces `ERR_RESERVATION_CONFLICT`."

    Claim: overlapping by one minute against a PENDING reservation → ERR_RESERVATION_CONFLICT.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    mr = create_resource(kind="MEETING_ROOM", code="MR-OVLP-1")
    advance_clock_to("2026-07-09T07:00:00.000Z")
    payload1 = create_reservation_payload(
        tenant["id"], member["id"], mr["id"],
        "2026-07-09T09:00:00.000Z", "2026-07-09T11:00:00.000Z",
    )
    validate_success(api.create_reservation(payload1, _headers_for(member)), expected_status=201)
    # R2 starts 10:30, so it overlaps R1 by 30 minutes (granularity-compliant for MEETING_ROOM).
    payload2 = create_reservation_payload(
        tenant["id"], member["id"], mr["id"],
        "2026-07-09T10:30:00.000Z", "2026-07-09T13:00:00.000Z",
    )
    res2 = api.create_reservation(payload2, _headers_for(member))
    validate_error(res2, "ERR_RESERVATION_CONFLICT", expected_status=409)


def test_far_future_reservation_beyond_180_days_rejected(api, admin_headers):
    """PRD §2.6: "both endpoints must lie within the window that begins one hour
    before the current clock and ends 180 days after it; any violation is
    rejected with `ERR_INVALID_TIME_WINDOW`."

    Claim: start_at more than 180 days past now → ERR_INVALID_TIME_WINDOW.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    mr = create_resource(kind="WORKSTATION", code="WS-FAR-1")
    advance_clock_to("2026-07-10T08:00:00.000Z")
    payload = create_reservation_payload(
        tenant["id"], member["id"], mr["id"],
        "2027-03-01T09:00:00.000Z", "2027-03-01T10:00:00.000Z",
    )
    res = api.create_reservation(payload, _headers_for(member))
    validate_error(res, "ERR_INVALID_TIME_WINDOW", expected_status=422)
