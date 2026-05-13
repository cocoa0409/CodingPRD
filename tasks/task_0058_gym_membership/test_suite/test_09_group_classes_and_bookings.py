"""Group classes, capacity, waitlist promotion, and class cancellation.

PRD §3.9.
"""
from __future__ import annotations
import pytest
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    PA, SO,
    create_funded_member,
    create_group_class,
    create_group_booking,
    create_trainer,
    iso_z, parse_iso,
    make_member_headers,
    reset_clock_to,
    setup_group_class_with_waitlist,
    validate_error,
    validate_success,
)


# ===========================================================================
# Group-class 30-min buffer (PRD §3.9)
# ===========================================================================
class TestGroupClassInstructorBuffer:

    def test_adjacent_endpoints_rejected(self, api):
        """PRD §3.9: 'group classes require a 30-minute buffer between
        any two classes for the same instructor_trainer_id whose
        status is SCHEDULED; specifically, for any two such classes a
        and b ordered in time, b's starts_at minus a's ends_at must
        be at least 30 minutes. Adjacent-endpoint classes are
        therefore rejected at this step, with ERR_CLASS_OVERLAP.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
            capacity=5,
        )
        res = api.create_group_class(
            {"class_code": "GC_ADJ", "instructor_trainer_id": trainer["id"],
             "starts_at": "2026-01-02T11:00:00.000Z",
             "ends_at": "2026-01-02T12:00:00.000Z",
             "capacity": 5},
            SO,
        )
        validate_error(res, ApiErrorId.ERR_CLASS_OVERLAP.value)

    def test_30_min_buffer_accepted(self, api):
        """PRD §3.9: 'b's starts_at minus a's ends_at must be at least
        30 minutes.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
            capacity=5,
        )
        # 30 minutes after first ends_at.
        res = api.create_group_class(
            {"class_code": "GC_BUFFER", "instructor_trainer_id": trainer["id"],
             "starts_at": "2026-01-02T11:30:00.000Z",
             "ends_at": "2026-01-02T12:30:00.000Z",
             "capacity": 5},
            SO,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Waitlist when at capacity (PRD §3.9)
# ===========================================================================
class TestWaitlistBehavior:

    def test_booking_when_at_capacity_with_accept_waitlist_false(self, api):
        """PRD §3.9: 'When accept_waitlist is false and the class is at
        capacity, the booking is rejected with
        ERR_CAPACITY_REACHED.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
            capacity=1,
        )
        m1 = create_funded_member(wallet_balance_cents=50_000)
        m2 = create_funded_member(wallet_balance_cents=50_000)
        # m1 fills capacity.
        create_group_booking(class_id=klass["id"], member=m1)
        # m2 refuses waitlist.
        res = api.create_group_booking(
            {"class_id": klass["id"], "member_id": m2["id"],
             "accept_waitlist": False},
            make_member_headers(m2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CAPACITY_REACHED.value)

    def test_booking_at_capacity_with_accept_waitlist_lands_waitlisted(self, api):
        """PRD §3.9: 'When accept_waitlist is true or omitted and the
        class is at capacity, the booking is created in WAITLISTED
        status.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
            capacity=1,
        )
        m1 = create_funded_member(wallet_balance_cents=50_000)
        m2 = create_funded_member(wallet_balance_cents=50_000)
        create_group_booking(class_id=klass["id"], member=m1)
        b2 = create_group_booking(
            class_id=klass["id"], member=m2, accept_waitlist=True,
        )
        assert b2["status"] == "WAITLISTED"
        assert b2.get("waitlist_position") == 1, (
            "PRD §3.9: WAITLISTED booking carries 1-based waitlist_position."
        )


# ===========================================================================
# Group-booking cancel window (PRD §3.9)
# ===========================================================================
class TestGroupBookingCancelWindow:

    def test_cancel_within_2h_window_rejected(self, api):
        """PRD §3.9: 'Cancelling a CONFIRMED booking requires the
        cancellation to land at least 2 hours before starts_at;
        otherwise it is rejected with ERR_CANCEL_WINDOW_EXPIRED.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        starts = parse_iso("2026-01-02T10:00:00.000Z")
        ends = starts + timedelta(hours=1)
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at=iso_z(starts), ends_at=iso_z(ends),
            capacity=5,
        )
        m = create_funded_member(wallet_balance_cents=50_000)
        b = create_group_booking(class_id=klass["id"], member=m)
        # Advance to 1 hour before starts_at — inside the 2h window.
        from test_helpers import advance_clock
        advance_clock(iso_z(starts - timedelta(hours=1)))
        res = api.cancel_group_booking(
            b["id"], make_member_headers(m["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CANCEL_WINDOW_EXPIRED.value)

    def test_cancel_more_than_2h_before_succeeds(self, api):
        """PRD §3.9: 'requires the cancellation to land at least 2
        hours before starts_at.'

        At exactly 3 hours before (well outside the 2h window) the
        cancel must succeed.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        starts = parse_iso("2026-01-02T10:00:00.000Z")
        ends = starts + timedelta(hours=1)
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at=iso_z(starts), ends_at=iso_z(ends),
            capacity=5,
        )
        m = create_funded_member(wallet_balance_cents=50_000)
        b = create_group_booking(class_id=klass["id"], member=m)
        # Clock is at 2026-01-01T00:00:00Z → ~34 hours before starts_at.
        res = api.cancel_group_booking(
            b["id"], make_member_headers(m["id"]),
        )
        validate_success(res, expected_status=200)
