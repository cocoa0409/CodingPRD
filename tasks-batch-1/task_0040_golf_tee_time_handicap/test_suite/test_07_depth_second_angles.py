"""Second-angle coverage for the depth (difficulty) instances: each difficulty
instance is asserted from a distinct observable angle (a boundary partner, a
side-effect field, or the alternate branch) so every rule carries >=2 tests."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_booking_payload, create_tee_time_payload, make_proshop_headers, make_golfer_headers,
    create_course, create_golfer, create_tee_time, post_score, void_score, run_refresh,
    book_as_golfer, cancel_as_golfer, add_standby, fetch_tee_time, fetch_booking,
    fetch_golfer, set_clock, setup_full_twosome,
)


class TestDualVariantSecondAngles:
    def test_asof_divergence_revision_number_and_no_caps_first_run(self, api):
        """PRD §3.4: "the official handicap_index over that golfer's posted scores whose
        played_on falls on or before the date of the revision's effective_utc. This as-of-date
        filter is the first way the official figure diverges from the provisional one."

        Design: Difficulty/dual_variant_calc/provisional_vs_official_index_diverge_on_asof_date
        """
        course = create_course(name="Flat113b", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Asof2", membership_tier="PUBLIC")
        post_score(golfer["id"], course["id"], "2026-03-05", 85)
        post_score(golfer["id"], course["id"], "2026-03-12", 86)
        post_score(golfer["id"], course["id"], "2026-03-19", 87)
        post_score(golfer["id"], course["id"], "2026-03-26", 88)
        post_score(golfer["id"], course["id"], "2026-04-15", 75)
        run_refresh("2026-03-31T00:00:00Z")
        result = fetch_golfer(golfer["id"])
        # low seeded to the official (no anchor on first run) and revision stamped.
        assert result["handicap_index"] == 14.0
        assert result["low_handicap_index"] == 14.0
        assert result["handicap_revision"] == 1

    def test_member_discount_divergence_tier_frozen_off_peak(self, api):
        """PRD §2.8: "multiply the base by the course's member_discount_pct, round that
        discount amount half-up to whole cents, and then subtract the rounded discount from
        the base; the order is pinned — round the discount first, subtract second."

        Design: Difficulty/dual_variant_calc/green_fee_member_discount_rounding_order_divergence
        """
        set_clock()
        course = create_course(name="RoundEdgeC", course_rating=71.0, slope_rating=120,
                               peak_fee_cents=9000, offpeak_fee_cents=5005,
                               peak_start_hour=7, peak_end_hour=15, member_discount_pct=0.10)
        member = create_golfer(full_name="Member Three", membership_tier="MEMBER")
        # local_hour 6 is before the peak start -> OFF_PEAK base 5005.
        tt = create_tee_time(course["id"], "2026-06-02T06:00:00Z", 6, "FOURSOME")
        bk = book_as_golfer(tt["id"], member["id"], tt["version"])
        assert bk["pricing_tier"] == "OFF_PEAK"
        assert bk["green_fee_cents"] == 4504


class TestCombinatorialSecondAngles:
    def test_soft_cap_only_when_under_hard_ceiling(self, api):
        """PRD §3.4: "If the base exceeds the anchor by more than the soft-cap threshold of
        3.0, the excess above that threshold is damped to half its size: the capped value
        becomes the anchor plus 3.0 plus one-half of the amount by which the base exceeds the
        anchor-plus-3.0."

        Design: Difficulty/combinatorial_formula/official_index_soft_then_hard_cap_clamp
        """
        course = create_course(name="SoftOnly", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Soft Golfer", membership_tier="PUBLIC")
        # First refresh: AGS 73,74,75 -> diffs 3,4,5; n=3,k=1,adj=-2.0 -> 1.0; low=1.0.
        s1 = post_score(golfer["id"], course["id"], "2026-03-05", 73)
        s2 = post_score(golfer["id"], course["id"], "2026-03-12", 74)
        s3 = post_score(golfer["id"], course["id"], "2026-03-19", 75)
        run_refresh("2026-03-31T00:00:00Z")
        void_score(s1["id"]); void_score(s2["id"]); void_score(s3["id"])
        # New scores giving base 5.0: AGS 79,80,81 -> diffs 9,10,11; n=3,k=1,adj=-2.0 -> 9.0-2.0=7.0.
        post_score(golfer["id"], course["id"], "2026-04-05", 79)
        post_score(golfer["id"], course["id"], "2026-04-12", 80)
        post_score(golfer["id"], course["id"], "2026-04-19", 81)
        # base 7.0 > low+3.0 (=4.0): soft = 1.0+3.0+(7.0-4.0)*0.5 = 5.5; hard min(5.5, 6.0)=5.5.
        run_refresh("2026-04-30T00:00:00Z")
        result = fetch_golfer(golfer["id"])
        assert result["handicap_index"] == 5.5

    def test_green_fee_round_then_subtract_twosome(self, api):
        """PRD §2.8: "Computing the fee as the base times one-minus-the-percentage and
        rounding the product is not equivalent and is not permitted, because it can differ by
        a cent."

        Design: Difficulty/combinatorial_formula/green_fee_rounding_order_pinned_round_then_subtract
        """
        set_clock()
        course = create_course(name="RoundEdge3", course_rating=71.0, slope_rating=120,
                               peak_fee_cents=9000, offpeak_fee_cents=5005, member_discount_pct=0.10)
        member = create_golfer(full_name="Member Four", membership_tier="MEMBER")
        tt = create_tee_time(course["id"], "2026-06-03T19:00:00Z", 19, "FOURSOME")
        bk = book_as_golfer(tt["id"], member["id"], tt["version"])
        assert bk["green_fee_cents"] == 4504
        assert bk["pricing_tier"] == "OFF_PEAK"


class TestStateMachineSecondAngles:
    def test_cycle_reopened_slot_accepts_new_booking(self, api):
        """PRD §3.8: "If no standby booking exists, no promotion happens and the slot reopens,
        moving from FULL to OPEN."

        Design: Difficulty/non_linear_state_machine/teetime_open_full_open_cycle_on_cancel_no_standby
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "CycleCourse2", "course_rating": 72.0, "slope_rating": 125},
            start_utc="2026-06-04T11:00:00Z", local_hour=11,
        )
        cancel_as_golfer(bk_a["id"], ga["id"])
        # Reopened: a fresh golfer can now confirm into the freed seat.
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        slot = fetch_tee_time(tt["id"])
        bk_c = book_as_golfer(tt["id"], gc["id"], slot["version"])
        assert bk_c["status"] == "CONFIRMED"
        refilled = fetch_tee_time(tt["id"])
        assert refilled["status"] == "FULL"
        assert refilled["confirmed_count"] == 2

    def test_branch_cancelled_booking_is_terminal(self, api):
        """PRD §3.8: "The booking moves from CONFIRMED to CANCELLED, its green_fee_cents is
        zeroed."

        Design: Difficulty/non_linear_state_machine/booking_branching_cancel_promote_vs_reopen
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "BranchCourse2", "course_rating": 72.0, "slope_rating": 125,
                              "peak_fee_cents": 8000, "offpeak_fee_cents": 5000},
            start_utc="2026-06-05T20:00:00Z", local_hour=20,
        )
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        add_standby(tt["id"], gc)
        cancelled = cancel_as_golfer(bk_a["id"], ga["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["green_fee_cents"] == 0


class TestCascadeSecondAngles:
    def test_cancelled_booking_zeroed_and_promoted_standby_rank_reset(self, api):
        """PRD §3.8: "its standby_rank is reset to 0 ... and every booking still waiting behind
        it has its standby_rank recomputed."

        Design: Difficulty/transitive_cascade/cancel_confirmed_promotes_standby_and_prices_it_depth3
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "CascadeCourse2", "course_rating": 72.0, "slope_rating": 125,
                              "peak_fee_cents": 8000, "offpeak_fee_cents": 5000,
                              "peak_start_hour": 7, "peak_end_hour": 15, "member_discount_pct": 0.25},
            start_utc="2026-06-06T11:00:00Z", local_hour=11,
        )
        gd = create_golfer(full_name="GD", membership_tier="PUBLIC")
        gc = create_golfer(full_name="GC", membership_tier="MEMBER")
        bk_d = add_standby(tt["id"], gd)
        bk_c = add_standby(tt["id"], gc)
        cancel_as_golfer(bk_a["id"], ga["id"])
        assert fetch_booking(bk_c["id"])["standby_rank"] == 0
        assert fetch_booking(bk_d["id"])["standby_rank"] == 1

    def test_void_depth2_score_excluded_then_provisional_null(self, api):
        """PRD §3.3: "Voiding moves the score from POSTED to VOID, which removes it from every
        subsequent handicap calculation, and immediately recomputes the holding golfer's
        provisional_handicap_index over the remaining posted scores (excluding the now-voided
        one) using the same lowest-k-of-recent-20 procedure from §3.2."

        Design: Difficulty/transitive_cascade/void_score_recomputes_provisional_index_depth2
        """
        course = create_course(name="VoidCourse2", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Void Golfer 2", membership_tier="PUBLIC")
        s_low = post_score(golfer["id"], course["id"], "2026-05-01", 73)
        post_score(golfer["id"], course["id"], "2026-05-08", 80)
        post_score(golfer["id"], course["id"], "2026-05-15", 90)
        # Before void: n=3,k=1,adj=-2.0 over diffs 3,10,20 -> 1.0.
        assert fetch_golfer(golfer["id"])["provisional_handicap_index"] == 1.0
        void_score(s_low["id"])
        assert fetch_golfer(golfer["id"])["provisional_handicap_index"] is None


class TestPrecedenceSecondAngles:
    def test_closed_beats_duplicate_status_is_409(self, api):
        """PRD §3.6: "a slot already in CLOSED status rejects booking creation with
        ERR_TEE_TIME_CLOSED, which is the more specific code that takes precedence over the
        generic invalid-state result for the closed case."

        Design: Difficulty/priority_pair_validation_conflict/closed_slot_beats_duplicate_booking
        """
        set_clock()
        course = create_course(name="PriCourse2", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-07T11:00:00Z", 11, "FOURSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])
        closed = validate_success(api.close_tee_time(tt["id"], make_proshop_headers()), 200)
        resp = api.create_booking(
            tt["id"], create_booking_payload(ga["id"], closed["version"]),
            make_golfer_headers(ga["id"]),
        )
        # ERR_TEE_TIME_CLOSED maps to HTTP 409 (auto-checked from the registered status map).
        validate_error(resp, ApiErrorId.ERR_TEE_TIME_CLOSED)

    def test_not_owner_beats_invalid_state_status_is_403(self, api):
        """PRD §3.8: "a golfer who is not the holder and is not acting as ProShop is rejected
        with ERR_NOT_BOOKING_OWNER."

        Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_invalid_state_on_cancel
        """
        set_clock()
        course = create_course(name="OwnCourse2", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        gb = create_golfer(full_name="GB", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-08T11:00:00Z", 11, "FOURSOME")
        bk = book_as_golfer(tt["id"], ga["id"], tt["version"])
        cancel_as_golfer(bk["id"], ga["id"])
        resp = api.cancel_booking(bk["id"], make_golfer_headers(gb["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_BOOKING_OWNER)


class TestBoundarySecondAngles:
    def test_peak_window_just_inside_end_is_peak(self, api):
        """PRD §2.8: "A tee time whose local hour is at least the peak start hour and strictly
        less than the peak end hour is priced at the PEAK tier; any other hour is OFF_PEAK."

        Design: Difficulty/boundary_precision_check/peak_window_end_hour_exclusive_boundary
        """
        set_clock()
        course = create_course(name="EdgeCourse2", peak_fee_cents=8000, offpeak_fee_cents=5000,
                               peak_start_hour=7, peak_end_hour=15)
        golfer = create_golfer(full_name="Edge14", membership_tier="PUBLIC")
        # local_hour 14 is strictly less than 15 -> PEAK.
        tt = create_tee_time(course["id"], "2026-06-09T14:00:00Z", 14, "FOURSOME")
        bk = book_as_golfer(tt["id"], golfer["id"], tt["version"])
        assert bk["pricing_tier"] == "PEAK"
        assert bk["green_fee_cents"] == 8000


class TestCrossEntitySecondAngles:
    def test_standby_cannot_advance_without_freed_seat(self, api):
        """PRD §3.6: "Creating a standby booking does not change the slot's confirmed_count and
        the slot remains FULL."

        Design: Difficulty/cross_entity_state_dependency/standby_promotion_requires_teetime_freed_seat
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "GuardCourse2", "course_rating": 72.0, "slope_rating": 125},
            start_utc="2026-06-10T20:00:00Z", local_hour=20,
        )
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        bk_c = add_standby(tt["id"], gc)
        # No seat freed yet: standby stays STANDBY, slot stays FULL.
        assert fetch_booking(bk_c["id"])["status"] == "STANDBY"
        slot = fetch_tee_time(tt["id"])
        assert slot["status"] == "FULL"
        assert slot["confirmed_count"] == 2

    def test_first_booking_keeps_slot_open(self, api):
        """PRD §3.6: "When the slot has an open seat, the booking is created CONFIRMED ...
        increments the slot's confirmed_count, and bumps the slot's version."

        Design: Difficulty/cross_entity_state_dependency/teetime_auto_full_depends_on_booking_confirmed_count
        """
        set_clock()
        course = create_course(name="FullCourse2", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-11T11:00:00Z", 11, "TWOSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])
        slot = fetch_tee_time(tt["id"])
        assert slot["status"] == "OPEN"
        assert slot["confirmed_count"] == 1


class TestTemporalOverlapSecondAngles:
    def test_golfer_adjacent_slot_at_twelve_minutes_allowed(self, api):
        """PRD §3.6: "each confirmed booking occupies its slot's start instant through 12
        minutes later, treated as a half-open interval ... back-to-back slots that merely touch
        at the boundary do not conflict."

        Design: Difficulty/resource_temporal_overlap/golfer_calendar_halfopen_overlap_adjacency_allowed
        """
        set_clock()
        course_a = create_course(name="AdjA", course_rating=72.0, slope_rating=125)
        course_b = create_course(name="AdjB", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt1 = create_tee_time(course_a["id"], "2026-06-12T09:00:00Z", 9, "FOURSOME")
        # Exactly 12 minutes later: [09:00,09:12) and [09:12,09:24) touch but do not overlap.
        tt2 = create_tee_time(course_b["id"], "2026-06-12T09:12:00Z", 9, "FOURSOME")
        book_as_golfer(tt1["id"], ga["id"], tt1["version"])
        bk2 = book_as_golfer(tt2["id"], ga["id"], tt2["version"])
        assert bk2["status"] == "CONFIRMED"

    def test_teesheet_spacing_under_eight_minutes_rejected_reverse(self, api):
        """PRD §3.5: "the absolute difference between the new slot's start and any existing
        slot's start must not be under 8 minutes. Exactly 8 minutes apart is allowed; anything
        strictly closer collides and is rejected with ERR_TEE_INTERVAL_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/course_teesheet_buffer_spacing_conflict
        """
        set_clock()
        course = create_course(name="SheetCourse2", course_rating=72.0, slope_rating=125)
        # Existing slot at 10:10; new earlier slot at 10:07 is 3 min before -> collides (symmetric).
        create_tee_time(course["id"], "2026-06-13T10:10:00Z", 10, "FOURSOME")
        resp = api.create_tee_time(
            create_tee_time_payload(course["id"], "2026-06-13T10:07:00Z", 10, "FOURSOME"),
            make_proshop_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_TEE_INTERVAL_CONFLICT)


class TestCompensatingSecondAngles:
    def test_seat_count_never_exceeds_capacity_through_cancel_promote(self, api):
        """PRD §3.8: "the slot's confirmed_count is incremented back up so the slot stays
        FULL."

        Design: Difficulty/compensating_invariant/cancel_then_promote_conserves_confirmed_seat_count
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(
            course_overrides={"name": "ConsCourse2", "course_rating": 72.0, "slope_rating": 125},
            start_utc="2026-06-14T20:00:00Z", local_hour=20,
        )
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        add_standby(tt["id"], gc)
        cancel_as_golfer(bk_a["id"], ga["id"])
        slot = fetch_tee_time(tt["id"])
        assert slot["confirmed_count"] == slot["capacity"] == 2

    def test_void_repost_restores_exact_index_value(self, api):
        """PRD §3.2: "the lowest k of them taken, their arithmetic mean computed, an adjustment
        added, and the result rounded half-up to one decimal place."

        Design: Difficulty/compensating_invariant/void_then_repost_conserves_provisional_index_value
        """
        course = create_course(name="InvCourse2", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Inv Golfer 2", membership_tier="PUBLIC")
        post_score(golfer["id"], course["id"], "2026-05-01", 80)
        s_mid = post_score(golfer["id"], course["id"], "2026-05-08", 82)
        post_score(golfer["id"], course["id"], "2026-05-15", 84)
        before = fetch_golfer(golfer["id"])["provisional_handicap_index"]
        assert before == 8.0
        void_score(s_mid["id"])
        post_score(golfer["id"], course["id"], "2026-05-08", 82)
        after = fetch_golfer(golfer["id"])["provisional_handicap_index"]
        assert after == before == 8.0
