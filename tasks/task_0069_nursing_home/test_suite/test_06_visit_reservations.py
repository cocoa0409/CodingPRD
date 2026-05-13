"""Visit reservations: slot duration, overlap, daily cap, health screening,
and lockdown handling.

Anchored in PRD §3.6.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    check_in_payload,
    create_visit_reservation,
    create_visit_reservation_payload,
    iso_z, future_iso,
    setup_admitted_elder_v2,
    set_epidemic_mode,
    ADMIN, FAMILY,
    validate_error, validate_success,
)


def _future_window(minutes_ahead: int,
                   duration_minutes: int) -> tuple[str, str]:
    start = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    end = start + timedelta(minutes=duration_minutes)
    return iso_z(start), iso_z(end)


# ===========================================================================
# Slot duration boundary (PRD §3.6 / §2.7 #17)
# ===========================================================================
class TestSlotDuration:

    def test_duration_below_15_min_rejected(self):
        """PRD §3.6: "the slot's duration must be at least 15 minutes and
        at most 120 minutes (rejection: `ERR_INVALID_SLOT_DURATION`)."

        Claim: 14-minute slot → ERR_INVALID_SLOT_DURATION / 422.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        # Always ensure we have a clean slate epidemic config.
        set_epidemic_mode("NORMAL")
        start, end = _future_window(60, 14)
        resp = api_client.create_visit_reservation(
            bundle["elder"]["id"],
            create_visit_reservation_payload(start, end),
            FAMILY,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_DURATION.value)

    def test_duration_15_min_succeeds(self):
        """PRD §3.6: "the slot's duration must be at least 15 minutes and
        at most 120 minutes (rejection: `ERR_INVALID_SLOT_DURATION`)."

        Claim: exact 15-minute slot succeeds (201).
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        set_epidemic_mode("NORMAL")
        start, end = _future_window(60, 15)
        resp = api_client.create_visit_reservation(
            bundle["elder"]["id"],
            create_visit_reservation_payload(start, end),
            FAMILY,
        )
        validate_success(resp, expected_status=201)

    def test_duration_120_min_succeeds(self):
        """PRD §3.6: "the slot's duration must be at least 15 minutes and
        at most 120 minutes (rejection: `ERR_INVALID_SLOT_DURATION`)."

        Claim: exact 120-minute slot succeeds (201).
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        set_epidemic_mode("NORMAL")
        start, end = _future_window(60, 120)
        resp = api_client.create_visit_reservation(
            bundle["elder"]["id"],
            create_visit_reservation_payload(start, end),
            FAMILY,
        )
        validate_success(resp, expected_status=201)

    def test_duration_above_120_min_rejected(self):
        """PRD §3.6: "the slot's duration must be at least 15 minutes and
        at most 120 minutes (rejection: `ERR_INVALID_SLOT_DURATION`)."

        Claim: 121-minute slot → ERR_INVALID_SLOT_DURATION / 422.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        set_epidemic_mode("NORMAL")
        start, end = _future_window(60, 121)
        resp = api_client.create_visit_reservation(
            bundle["elder"]["id"],
            create_visit_reservation_payload(start, end),
            FAMILY,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_DURATION.value)


# ===========================================================================
# Slot overlap (PRD §3.6 / §2.7 #15)
# ===========================================================================
class TestSlotOverlap:

    def test_overlapping_slot_rejected(self):
        """PRD §3.6: "the half-open interval from `slot_start_at`
        inclusive to `slot_end_at` exclusive must not intersect any
        existing `RESERVED` or `CHECKED_IN` reservation for the same
        elder (rejection: `ERR_VISIT_SLOT_CONFLICT`)."

        Claim: overlapping reservation → ERR_VISIT_SLOT_CONFLICT.
        # difficulty: resource_temporal_overlap/visit_reservation_half_open_interval_per_elder
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        set_epidemic_mode("NORMAL")
        start1, end1 = _future_window(60, 60)
        create_visit_reservation(bundle["elder"]["id"], start1, end1)
        # Overlapping window 30 min after start1.
        s1 = datetime.fromisoformat(start1.replace("Z", "+00:00"))
        start2 = iso_z(s1 + timedelta(minutes=30))
        end2 = iso_z(s1 + timedelta(minutes=90))
        resp = api_client.create_visit_reservation(
            bundle["elder"]["id"],
            create_visit_reservation_payload(start2, end2),
            FAMILY,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_SLOT_CONFLICT.value)

    def test_adjacent_slot_allowed_half_open(self):
        """PRD §3.6: "the half-open interval from `slot_start_at`
        inclusive to `slot_end_at` exclusive must not intersect any
        existing `RESERVED` or `CHECKED_IN` reservation for the same
        elder."

        Claim: adjacent reservation (next.start == prev.end) is allowed
        under half-open semantics.
        # difficulty: resource_temporal_overlap/visit_reservation_half_open_interval_per_elder
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        set_epidemic_mode("NORMAL")
        start1, end1 = _future_window(60, 60)
        create_visit_reservation(bundle["elder"]["id"], start1, end1)
        # Lift the daily cap so this test is not blocked by the per-day cap.
        set_epidemic_mode("NORMAL", max_visitors_per_day=10)
        # Adjacent — start2 == end1.
        e1 = datetime.fromisoformat(end1.replace("Z", "+00:00"))
        start2 = iso_z(e1)
        end2 = iso_z(e1 + timedelta(minutes=30))
        resp = api_client.create_visit_reservation(
            bundle["elder"]["id"],
            create_visit_reservation_payload(start2, end2),
            FAMILY,
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Daily cap (PRD §3.6 / §2.7 #16)
# ===========================================================================
class TestDailyVisitorCap:

    def test_third_reservation_for_day_rejected_at_default_cap_2(self):
        """PRD §3.6: "the elder's `RESERVED` plus `CHECKED_IN` count for
        the calendar day of `slot_start_at` must not exceed
        `max_visitors_per_day` (rejection: `ERR_VISIT_DAILY_LIMIT`)."

        Claim: under default cap of 2, a third non-overlapping reservation
        on the same day → ERR_VISIT_DAILY_LIMIT.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        set_epidemic_mode("NORMAL", max_visitors_per_day=2)
        # Three 30-minute slots, all in the future, no overlap.
        s1, e1 = _future_window(60, 30)
        s2, e2 = _future_window(120, 30)
        s3, e3 = _future_window(180, 30)
        create_visit_reservation(bundle["elder"]["id"], s1, e1)
        create_visit_reservation(bundle["elder"]["id"], s2, e2)
        resp = api_client.create_visit_reservation(
            bundle["elder"]["id"],
            create_visit_reservation_payload(s3, e3),
            FAMILY,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_DAILY_LIMIT.value)
