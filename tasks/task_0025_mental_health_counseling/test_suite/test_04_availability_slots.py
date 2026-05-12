"""Availability slot creation and the four scheduling invariants
(PRD §2.11, §3.4)."""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    assert_availability_slot,
    bring_counselor_to_active,
    create_availability_slot_payload,
    create_counselor,
    create_slot,
    DEFAULT_T0,
    make_admin_headers,
    make_counselor_headers,
    setup_counselor_with_seven_60min_slots_same_local_day,
    shift,
    validate_error,
    validate_success,
)


class TestSlotCreation:
    def test_create_slot_succeeds(self):
        """PRD §3.4: "On success the slot is persisted with `status` of
        `OPEN` and both `held_until` and `held_appointment_id` null."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        assert_availability_slot(slot)
        assert slot["status"] == "OPEN"
        assert slot["held_until"] is None
        assert slot["held_appointment_id"] is None

    def test_pending_cert_counselor_cannot_create_slot(self, api):
        """PRD §3.4: "The creation request is gated by the counselor being
        `ACTIVE` (otherwise `ERR_COUNSELOR_NOT_ACTIVE`)..."
        """
        counselor = create_counselor()  # PENDING_CERT
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=shift(DEFAULT_T0, hours=200),
            end_at=shift(DEFAULT_T0, hours=201),
        )
        res = api.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_COUNSELOR_NOT_ACTIVE", expected_status=409)

    def test_unsupported_channel_rejected(self, api):
        """PRD §3.4: "and by the chosen `channel` being one of the values
        listed in that counselor's `supported_channels` (otherwise
        `ERR_CHANNEL_NOT_SUPPORTED`)."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active(
            supported_channels=["VIDEO", "AUDIO"],
        )
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=shift(DEFAULT_T0, hours=200),
            end_at=shift(DEFAULT_T0, hours=201),
            channel="TEXT",   # not in supported_channels
        )
        res = api.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_CHANNEL_NOT_SUPPORTED", expected_status=422)

    def test_invalid_slot_duration_rejected_too_short(self, api):
        """PRD §3.4: "The slot's duration is then checked: `end_at` must
        equal `start_at` plus exactly sixty minutes, with anything else
        rejected as `ERR_INVALID_SLOT_DURATION`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        start = shift(DEFAULT_T0, hours=200)
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=start,
            end_at=shift(start, minutes=59),    # only 59 minutes
            channel="VIDEO",
        )
        res = api.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_SLOT_DURATION", expected_status=422)

    def test_invalid_slot_duration_rejected_too_long(self, api):
        """PRD §3.4: "The slot's duration is then checked: `end_at` must
        equal `start_at` plus exactly sixty minutes, with anything else
        rejected as `ERR_INVALID_SLOT_DURATION`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        start = shift(DEFAULT_T0, hours=200)
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=start,
            end_at=shift(start, minutes=61),    # 61 minutes
            channel="VIDEO",
        )
        res = api.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_SLOT_DURATION", expected_status=422)


class TestSlotOverlap:
    def test_overlap_rejected(self):
        """PRD §2.11: "the proposed slot must not overlap any other slot of
        the same counselor in `OPEN`, `HELD`, or `BOOKED` status when
        overlap is evaluated as a half-open interval intersection (so two
        slots that touch end-to-start at exactly the same instant are
        adjacent, not overlapping)."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        # Existing slot: 10:00-11:00 UTC.
        s1_start = shift(DEFAULT_T0, hours=200)
        create_slot(counselor=counselor, start_at=s1_start)
        # Overlap candidate: 10:30-11:30 — must be rejected.
        from test_helpers import create_availability_slot_payload
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=shift(s1_start, minutes=30),
            end_at=shift(s1_start, minutes=90),
        )
        res = api_client.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_SLOT_OVERLAP", expected_status=422)

    def test_adjacent_slot_at_boundary_allowed(self):
        """PRD §2.11: "two slots that touch end-to-start at exactly the same
        instant are adjacent, not overlapping."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        s1_start = shift(DEFAULT_T0, hours=200)
        create_slot(counselor=counselor, start_at=s1_start)        # 10:00-11:00
        # Adjacent slot 11:00-12:00 — gap == 0 (allowed per PRD §2.11).
        s2 = create_slot(counselor=counselor, start_at=shift(s1_start, minutes=60))
        assert s2["status"] == "OPEN"


class TestRestInterval:
    def test_rest_interval_violation_rejected(self):
        """PRD §2.11: "the gap from the proposed slot to its nearest
        neighbouring slot of the same counselor must be either zero (fully
        adjacent) or at least fifteen minutes; any gap strictly greater
        than zero and strictly less than fifteen minutes violates the rest
        interval."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        s1_start = shift(DEFAULT_T0, hours=200)
        create_slot(counselor=counselor, start_at=s1_start)        # 10:00-11:00
        # Candidate at 11:10-12:10 — gap is 10 minutes. Must be rejected.
        from test_helpers import create_availability_slot_payload
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=shift(s1_start, minutes=70),
            end_at=shift(s1_start, minutes=130),
        )
        res = api_client.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_REST_INTERVAL", expected_status=422)

    def test_15min_gap_allowed(self):
        """PRD §2.11: "the gap from the proposed slot to its nearest
        neighbouring slot of the same counselor must be either zero (fully
        adjacent) or at least fifteen minutes."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        s1_start = shift(DEFAULT_T0, hours=200)
        create_slot(counselor=counselor, start_at=s1_start)        # 10:00-11:00
        s2 = create_slot(counselor=counselor, start_at=shift(s1_start, minutes=75))   # 11:15-12:15
        assert s2["status"] == "OPEN"


class TestDailyAndWeeklyCap:
    def test_daily_cap_at_480_allowed(self):
        """PRD §2.11: "the cumulative minutes of slots overlapping the same
        local calendar day plus the proposed sixty must not exceed eight
        hours ... The thresholds are applied with strict greater-than-cap
        rejection: a day total landing exactly on eight hours is permitted,
        eight hours and one minute is not."
        """
        counselor, slots = setup_counselor_with_seven_60min_slots_same_local_day()
        assert len(slots) == 7
        # 7 * 60 = 420 minutes; 8th slot brings total to 480 (== cap, allowed).
        # Continue cadence: 75-min spacing.
        eighth_start = shift("2026-06-01T17:00:00.000Z", minutes=75 * 7)
        eighth = create_slot(counselor=counselor, start_at=eighth_start)
        assert eighth["status"] == "OPEN"

    def test_daily_cap_exceeded_rejected(self):
        """PRD §2.11: "a day total landing exactly on eight hours is
        permitted, eight hours and one minute is not." — the 9th slot
        attempt brings the day to 540 (> 480) and must be rejected with
        `ERR_DAILY_CAP_EXCEEDED` per PRD §3.4 / §1.4 (priority 15)."""
        counselor, slots = setup_counselor_with_seven_60min_slots_same_local_day()
        # Build the 8th — should succeed.
        eighth_start = shift("2026-06-01T17:00:00.000Z", minutes=75 * 7)
        create_slot(counselor=counselor, start_at=eighth_start)
        # 9th slot — same local day, but daily total would be 540 > 480.
        from test_helpers import create_availability_slot_payload
        ninth_start = shift("2026-06-01T17:00:00.000Z", minutes=75 * 8)
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=ninth_start,
            end_at=shift(ninth_start, minutes=60),
        )
        res = api_client.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_DAILY_CAP_EXCEEDED", expected_status=422)


class TestSlotDeletion:
    def test_delete_open_slot_returns_204(self, api):
        """PRD §3.4: "A counselor may delete a slot they own as long as it
        is still `OPEN`; the delete returns 204 No Content and transitions
        `status` to `RELEASED`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        res = api.delete_availability_slot(
            slot["id"], make_counselor_headers(counselor["id"]),
        )
        assert res.status_code == 204

    def test_delete_slot_in_held_rejected(self, api):
        """PRD §3.4: "A delete on a slot in `HELD`, `BOOKED`, `BLOCKED`, or
        `RELEASED` is rejected with `ERR_INVALID_STATE`."
        """
        from test_helpers import (
            create_appointment_in_hold,
            create_client,
        )
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        # Hold the slot via an INTAKE booking (PENDING client allowed).
        create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        res = api.delete_availability_slot(
            slot["id"], make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
