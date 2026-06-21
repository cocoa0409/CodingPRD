"""Booking lifecycle and the cancellation cascade: OPEN/FULL/OPEN cycling, standby
promotion vs reopen branching, depth-3 cancel cascade, cross-entity seat dependence,
the waitlist ordering, and the seat-conservation invariant."""
import pytest
from test_helpers import (
    create_course, create_golfer, create_tee_time, book_as_golfer,
    cancel_as_golfer, add_standby, fetch_tee_time, fetch_booking, set_clock,
    setup_full_twosome,
)


class TestTeeTimeStateCycle:
    def test_open_full_open_cycle_on_cancel_no_standby(self, api):
        """PRD §3.8: "If no standby booking exists, no promotion happens and the slot reopens,
        moving from FULL to OPEN."

        Design: Difficulty/non_linear_state_machine/teetime_open_full_open_cycle_on_cancel_no_standby
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "CycleCourse", "course_rating": 72.0, "slope_rating": 125},
            start_utc="2026-06-04T09:00:00Z", local_hour=9,
        )
        # Slot is FULL with no standby; cancel GA reopens.
        cancel_as_golfer(bk_a["id"], ga["id"])
        slot = fetch_tee_time(tt["id"])
        assert slot["status"] == "OPEN"
        assert slot["confirmed_count"] == 1

    def test_teetime_auto_full_depends_on_confirmed_count(self, api):
        """PRD §3.6: "If that confirmation takes the last seat — the confirmed count reaches
        capacity — the slot transitions from OPEN to FULL."

        Design: Difficulty/cross_entity_state_dependency/teetime_auto_full_depends_on_booking_confirmed_count
        """
        set_clock()
        course = create_course(name="FullCourse", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        gb = create_golfer(full_name="GB", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-11T09:00:00Z", 9, "TWOSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])
        slot_after_one = fetch_tee_time(tt["id"])
        assert slot_after_one["status"] == "OPEN", "one short of capacity stays OPEN"
        book_as_golfer(tt["id"], gb["id"], slot_after_one["version"])
        slot = fetch_tee_time(tt["id"])
        assert slot["status"] == "FULL"
        assert slot["confirmed_count"] == 2


class TestBookingBranchingCancel:
    def test_cancel_confirmed_promotes_standby_branch(self, api):
        """PRD §3.8: "If at least one standby booking exists, the highest-priority one
        selected by the ordering in §3.7 is promoted from STANDBY to CONFIRMED: its
        standby_rank is reset to 0, its green_fee_cents is computed by the green-fee procedure
        of §2.8 using the pricing_tier that was frozen when it first joined the waitlist, the
        slot's confirmed_count is incremented back up so the slot stays FULL."

        Design: Difficulty/non_linear_state_machine/booking_branching_cancel_promote_vs_reopen
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "BranchCourse", "course_rating": 72.0, "slope_rating": 125,
                              "peak_fee_cents": 8000, "offpeak_fee_cents": 5000},
            start_utc="2026-06-05T18:00:00Z", local_hour=18,
        )
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        bk_c = add_standby(tt["id"], gc)
        cancel_as_golfer(bk_a["id"], ga["id"])
        promoted = fetch_booking(bk_c["id"])
        assert promoted["status"] == "CONFIRMED"
        assert promoted["green_fee_cents"] == 5000  # OFF_PEAK base, PUBLIC
        assert promoted["standby_rank"] == 0
        slot = fetch_tee_time(tt["id"])
        assert slot["status"] == "FULL"
        assert slot["confirmed_count"] == 2

    def test_standby_promotion_requires_freed_seat(self, api):
        """PRD §3.8: "Cancelling a confirmed booking is the deepest cascade in the system. The
        booking moves from CONFIRMED to CANCELLED, its green_fee_cents is zeroed, and the
        slot's confirmed_count is decremented. The system then looks for a waitlisted booking
        to promote."

        Design: Difficulty/cross_entity_state_dependency/standby_promotion_requires_teetime_freed_seat
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "GuardCourse", "course_rating": 72.0, "slope_rating": 125},
            start_utc="2026-06-10T18:00:00Z", local_hour=18,
        )
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        bk_c = add_standby(tt["id"], gc)
        cancel_as_golfer(bk_a["id"], ga["id"])
        promoted = fetch_booking(bk_c["id"])
        assert promoted["status"] == "CONFIRMED"
        slot = fetch_tee_time(tt["id"])
        assert slot["confirmed_count"] == 2


class TestDepth3Cascade:
    def test_cancel_promotes_prices_and_reranks(self, api):
        """PRD §3.8: "the highest-priority one selected by the ordering in §3.7 is promoted
        from STANDBY to CONFIRMED: its standby_rank is reset to 0, its green_fee_cents is
        computed by the green-fee procedure of §2.8 using the pricing_tier that was frozen
        when it first joined the waitlist, the slot's confirmed_count is incremented back up so
        the slot stays FULL, and every booking still waiting behind it has its standby_rank
        recomputed."
        PRD §3.7: "those held by a MEMBER rank ahead of those held by a PUBLIC golfer."

        Design: Difficulty/transitive_cascade/cancel_confirmed_promotes_standby_and_prices_it_depth3
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "CascadeCourse", "course_rating": 72.0, "slope_rating": 125,
                              "peak_fee_cents": 8000, "offpeak_fee_cents": 5000,
                              "peak_start_hour": 7, "peak_end_hour": 15, "member_discount_pct": 0.25},
            start_utc="2026-06-06T09:00:00Z", local_hour=9,
        )
        gd = create_golfer(full_name="GD", membership_tier="PUBLIC")
        gc = create_golfer(full_name="GC", membership_tier="MEMBER")
        bk_d = add_standby(tt["id"], gd)  # PUBLIC joins first
        bk_c = add_standby(tt["id"], gc)  # MEMBER joins second
        cancel_as_golfer(bk_a["id"], ga["id"])
        # MEMBER GC outranks PUBLIC GD -> promoted at PEAK member fee: 8000-round(2000)=6000.
        promoted = fetch_booking(bk_c["id"])
        assert promoted["status"] == "CONFIRMED"
        assert promoted["green_fee_cents"] == 6000
        remaining = fetch_booking(bk_d["id"])
        assert remaining["status"] == "STANDBY"
        assert remaining["standby_rank"] == 1
        slot = fetch_tee_time(tt["id"])
        assert slot["confirmed_count"] == 2


class TestWaitlistOrdering:
    def test_member_promoted_over_earlier_public(self, api):
        """PRD §3.7: "Among a slot's standby bookings, those held by a MEMBER rank ahead of
        those held by a PUBLIC golfer; within the same membership priority, the earlier
        created_at ranks ahead."

        Design: Corner/state_machines/standby_promotion_picks_member_over_earlier_public
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "PriSb"},
            start_utc="2026-06-25T09:00:00Z", local_hour=9,
        )
        gd = create_golfer(full_name="GD", membership_tier="PUBLIC")
        gc = create_golfer(full_name="GC", membership_tier="MEMBER")
        bk_d = add_standby(tt["id"], gd)  # PUBLIC first
        bk_c = add_standby(tt["id"], gc)  # MEMBER second
        cancel_as_golfer(bk_a["id"], ga["id"])
        promoted = fetch_booking(bk_c["id"])
        assert promoted["status"] == "CONFIRMED"
        remaining = fetch_booking(bk_d["id"])
        assert remaining["status"] == "STANDBY"
        assert remaining["standby_rank"] == 1

    def test_cancel_standby_reranks_no_promotion(self, api):
        """PRD §3.8: "Cancelling a standby booking is simpler because it never frees a
        confirmed seat. The booking moves from STANDBY to CANCELLED and the remaining standby
        bookings on the slot have their standby_rank recomputed; no promotion fires."

        Design: Corner/state_machines/cancel_standby_rerank_no_promotion
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "SbCourse"},
            start_utc="2026-06-24T09:00:00Z", local_hour=9,
        )
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        gd = create_golfer(full_name="GD", membership_tier="PUBLIC")
        bk_c = add_standby(tt["id"], gc)  # rank 1
        bk_d = add_standby(tt["id"], gd)  # rank 2
        cancel_as_golfer(bk_c["id"], gc["id"])
        remaining = fetch_booking(bk_d["id"])
        assert remaining["status"] == "STANDBY"
        assert remaining["standby_rank"] == 1
        slot = fetch_tee_time(tt["id"])
        assert slot["confirmed_count"] == 2


class TestSeatConservation:
    def test_cancel_then_promote_conserves_confirmed_count(self, api):
        """PRD §3.8: "the slot's confirmed_count is incremented back up so the slot stays
        FULL."

        Design: Difficulty/compensating_invariant/cancel_then_promote_conserves_confirmed_seat_count
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "ConsCourse", "course_rating": 72.0, "slope_rating": 125},
            start_utc="2026-06-14T18:00:00Z", local_hour=18,
        )
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        bk_c = add_standby(tt["id"], gc)
        cancel_as_golfer(bk_a["id"], ga["id"])
        slot = fetch_tee_time(tt["id"])
        assert slot["confirmed_count"] == 2
        assert fetch_booking(bk_a["id"])["status"] == "CANCELLED"
        assert fetch_booking(bk_c["id"])["status"] == "CONFIRMED"


class TestInitialBookingState:
    def test_first_booking_on_open_slot_confirmed(self, api):
        """PRD §3.6: "When the slot has an open seat, the booking is created CONFIRMED ...
        sets its standby_rank to 0."

        Design: Corner/state_machines/booking_initial_state_confirmed_on_open_slot
        """
        set_clock()
        course = create_course(name="InitCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-26T09:00:00Z", 9, "FOURSOME")
        bk = book_as_golfer(tt["id"], ga["id"], tt["version"])
        assert bk["status"] == "CONFIRMED"
        assert bk["standby_rank"] == 0
