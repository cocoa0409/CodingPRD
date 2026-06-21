"""Handicap Index calculations: provisional (live), official (capped, as-of-date),
score differential, and the void/refresh cascades."""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    make_proshop_headers,
    create_course, create_golfer, post_score, void_score, run_refresh,
    fetch_golfer, fetch_score,
)


class TestScoreDifferential:
    def test_score_differential_computed_and_frozen(self, api):
        """PRD §2.7: "take the standard slope constant of 113, divide it by the course's
        slope_rating, multiply that ratio by the result of subtracting the course's
        course_rating from the round's adjusted_gross_score, and round the product half-up
        to one decimal place."

        Design: Corner/entities/score_differential_computed_and_immutable
        """
        course = create_course(name="DiffCourse", course_rating=72.0, slope_rating=130)
        golfer = create_golfer(full_name="DG", membership_tier="PUBLIC")
        score = post_score(golfer["id"], course["id"], "2026-05-01", 95)
        # (113/130)*(95-72.0) = 0.86923*23 = 19.99... -> 20.0
        assert score["score_differential"] == 20.0
        assert score["status"] == "POSTED"


class TestProvisionalIndex:
    def test_provisional_null_below_three_scores(self, api):
        """PRD §3.2: "If fewer than three posted scores exist, there is insufficient data
        and the provisional index is null."

        Design: Difficulty/boundary_precision_check/provisional_index_null_below_three_scores_boundary
        """
        course = create_course(name="TwoScoreCourse", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Two Golfer", membership_tier="PUBLIC")
        post_score(golfer["id"], course["id"], "2026-05-01", 80)
        post_score(golfer["id"], course["id"], "2026-05-08", 90)
        result = fetch_golfer(golfer["id"])
        assert result["provisional_handicap_index"] is None

    def test_provisional_number_at_three_scores(self, api):
        """PRD §3.2: "the lowest k of them taken, their arithmetic mean computed, an
        adjustment added, and the result rounded half-up to one decimal place."

        Design: Difficulty/boundary_precision_check/provisional_index_null_below_three_scores_boundary
        """
        # slope 113 rating 70 -> diff == AGS - 70. AGS 73,80,90 -> diffs 3,10,20.
        # n=3,k=1,adj=-2.0 -> lowest 1 (=3.0) mean 3.0 + (-2.0) = 1.0.
        course = create_course(name="ThreeScoreCourse", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Three Golfer", membership_tier="PUBLIC")
        post_score(golfer["id"], course["id"], "2026-05-01", 73)
        post_score(golfer["id"], course["id"], "2026-05-08", 80)
        post_score(golfer["id"], course["id"], "2026-05-15", 90)
        result = fetch_golfer(golfer["id"])
        assert result["provisional_handicap_index"] == 1.0

    def test_provisional_trims_to_recent_twenty_before_lowest_k(self, api):
        """PRD §3.2: "The order is pinned: trim to the recent 20 by date first, then sort
        and take the lowest k — taking the lowest k across all rounds before trimming would
        let an old low round survive a recency window that should have excluded it."

        Design: Corner/calculations/provisional_index_uses_lowest_of_recent_twenty_trim_first
        """
        course = create_course(name="Trim20", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Trim G", membership_tier="PUBLIC")
        # Oldest score is the all-time lowest (diff 0.0) but falls outside recent-20.
        post_score(golfer["id"], course["id"], "2026-01-01", 70)
        for day in range(1, 21):
            post_score(golfer["id"], course["id"], f"2026-02-{day:02d}", 90)
        result = fetch_golfer(golfer["id"])
        # Recent-20 all diff 20.0; lowest-8 mean = 20.0 (NOT 0.0).
        assert result["provisional_handicap_index"] == 20.0


class TestVoidCascade:
    def test_void_score_recomputes_provisional_to_null(self, api):
        """PRD §3.3: "Voiding moves the score from POSTED to VOID, which removes it from
        every subsequent handicap calculation, and immediately recomputes the holding
        golfer's provisional_handicap_index over the remaining posted scores (excluding the
        now-voided one) using the same lowest-k-of-recent-20 procedure from §3.2."

        Design: Difficulty/transitive_cascade/void_score_recomputes_provisional_index_depth2
        """
        course = create_course(name="VoidCourse", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Void Golfer", membership_tier="PUBLIC")
        s_low = post_score(golfer["id"], course["id"], "2026-05-01", 73)  # diff 3
        post_score(golfer["id"], course["id"], "2026-05-08", 80)          # diff 10
        post_score(golfer["id"], course["id"], "2026-05-15", 90)          # diff 20
        voided = void_score(s_low["id"])
        assert voided["status"] == "VOID"
        result = fetch_golfer(golfer["id"])
        # Remaining n=2 -> insufficient -> NULL.
        assert result["provisional_handicap_index"] is None

    def test_void_then_repost_restores_provisional_value(self, api):
        """PRD §3.2: "the lowest k of them taken, their arithmetic mean computed, an
        adjustment added, and the result rounded half-up to one decimal place."
        PRD §3.3: "removes it from every subsequent handicap calculation, and immediately
        recomputes the holding golfer's provisional_handicap_index over the remaining posted
        scores (excluding the now-voided one) using the same lowest-k-of-recent-20 procedure."

        Design: Difficulty/compensating_invariant/void_then_repost_conserves_provisional_index_value
        """
        # slope 113 rating 70. AGS 80,82,84 -> diffs 10,12,14; n=3,k=1,adj=-2.0 -> 10.0-2.0 = 8.0.
        course = create_course(name="InvCourse", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Inv Golfer", membership_tier="PUBLIC")
        post_score(golfer["id"], course["id"], "2026-05-01", 80)
        s_mid = post_score(golfer["id"], course["id"], "2026-05-08", 82)
        post_score(golfer["id"], course["id"], "2026-05-15", 84)
        void_score(s_mid["id"])  # n=2 -> NULL
        # Re-post an identical score -> back to n=3.
        post_score(golfer["id"], course["id"], "2026-05-08", 82)
        result = fetch_golfer(golfer["id"])
        assert result["provisional_handicap_index"] == 8.0


class TestOfficialIndexAndDualVariant:
    def test_first_refresh_seeds_low_handicap_index_no_caps(self, api):
        """PRD §3.4: "When a golfer has no anchor yet because no prior refresh has set a
        low_handicap_index (it is null), both caps are skipped entirely, the official index
        equals the uncapped base, and this same refresh seeds the golfer's low_handicap_index
        to that official index."

        Design: Corner/calculations/first_refresh_seeds_low_handicap_index
        """
        course = create_course(name="SeedCrs", course_rating=70.0, slope_rating=113)
        golfer = create_golfer(full_name="Seed G", membership_tier="PUBLIC")
        # AGS 80,82,84,86,88 -> diffs 10..18; n=5,k=1 -> base/official = 10.0.
        for day, ags in zip(("01", "05", "09", "13", "17"), (80, 82, 84, 86, 88)):
            post_score(golfer["id"], course["id"], f"2026-03-{day}", ags)
        run_refresh("2026-03-31T00:00:00Z")
        result = fetch_golfer(golfer["id"])
        assert result["handicap_index"] == 10.0
        assert result["low_handicap_index"] == 10.0
        assert result["handicap_revision"] == 1

    def test_provisional_and_official_diverge_on_asof_date(self, api):
        """PRD §3.4: "the refresh computes the official handicap_index over that golfer's
        posted scores whose played_on falls on or before the date of the revision's
        effective_utc."
        PRD §3.2: "This recomputation considers only the golfer's scores still in POSTED
        status; voided rounds are excluded."

        Design: Difficulty/dual_variant_calc/provisional_vs_official_index_diverge_on_asof_date
        """
        course = create_course(name="Flat113", course_rating=70.0, slope_rating=113,
                               peak_fee_cents=10000, offpeak_fee_cents=6000)
        golfer = create_golfer(full_name="Asof Golfer", membership_tier="PUBLIC")
        post_score(golfer["id"], course["id"], "2026-03-05", 85)  # diff 15
        post_score(golfer["id"], course["id"], "2026-03-12", 86)  # diff 16
        post_score(golfer["id"], course["id"], "2026-03-19", 87)  # diff 17
        post_score(golfer["id"], course["id"], "2026-03-26", 88)  # diff 18
        post_score(golfer["id"], course["id"], "2026-04-15", 75)  # diff 5 (future-dated)
        # Provisional uses ALL 5 (n=5,k=1) -> lowest diff 5.0.
        before = fetch_golfer(golfer["id"])
        assert before["provisional_handicap_index"] == 5.0
        # Official as-of 2026-03-31 excludes the 04-15 score: 4 March scores (n=4,k=1,adj=-1.0)
        # -> lowest 15.0 + (-1.0) = 14.0.
        run_refresh("2026-03-31T00:00:00Z")
        result = fetch_golfer(golfer["id"])
        assert result["provisional_handicap_index"] == 5.0
        assert result["handicap_index"] == 14.0
        assert result["handicap_revision"] == 1

    def test_official_index_soft_then_hard_cap_clamp(self, api):
        """PRD §3.4: "If the base exceeds the anchor by more than the soft-cap threshold of
        3.0, the excess above that threshold is damped to half its size: the capped value
        becomes the anchor plus 3.0 plus one-half of the amount by which the base exceeds the
        anchor-plus-3.0. The hard cap then clamps the result so it is never more than 5.0
        above the anchor — that is, the value is the smaller of the soft-capped figure and the
        anchor plus 5.0."

        Design: Difficulty/combinatorial_formula/official_index_soft_then_hard_cap_clamp
        """
        course = create_course(name="CapCourse", course_rating=70.0, slope_rating=113,
                               peak_fee_cents=10000, offpeak_fee_cents=6000)
        golfer = create_golfer(full_name="Cap Golfer", membership_tier="PUBLIC")
        # First refresh: three great scores AGS 73,74,75 -> diffs 3,4,5; n=3,k=1,adj=-2.0 -> 3.0-2.0=1.0.
        s1 = post_score(golfer["id"], course["id"], "2026-03-05", 73)
        s2 = post_score(golfer["id"], course["id"], "2026-03-12", 74)
        s3 = post_score(golfer["id"], course["id"], "2026-03-19", 75)
        run_refresh("2026-03-31T00:00:00Z")  # official=1.0, low seeded to 1.0
        # Void all three, post three bad April scores AGS 90,91,92 -> diffs 20,21,22.
        void_score(s1["id"])
        void_score(s2["id"])
        void_score(s3["id"])
        post_score(golfer["id"], course["id"], "2026-04-05", 90)
        post_score(golfer["id"], course["id"], "2026-04-12", 91)
        post_score(golfer["id"], course["id"], "2026-04-19", 92)
        # Second refresh: base = n=3,k=1,adj=-2.0 over diffs 20,21,22 -> 20.0-2.0 = 18.0.
        # soft cap: 1.0+3.0+(18.0-4.0)*0.5 = 11.0; hard cap: min(11.0, 1.0+5.0) = 6.0.
        run_refresh("2026-04-30T00:00:00Z")
        result = fetch_golfer(golfer["id"])
        assert result["low_handicap_index"] == 1.0
        assert result["handicap_index"] == 6.0
        assert result["handicap_revision"] == 2


class TestRevisionRecord:
    def test_handicap_revision_is_immutable_audit_entry(self, api):
        """PRD §2.4: "A revision record is an immutable audit entry: it carries only an id
        (server-minted UUID, no prefix) and a created_at timestamp. It has no updated_at field
        and no version field, because it is never mutated after the refresh that created it."

        Design: Corner/entities/handicaprevision_immutable_no_version_field
        """
        rev = run_refresh("2026-03-31T00:00:00Z")
        resp = api.list_handicap_revisions(make_proshop_headers())
        data, meta = validate_paginated(resp)
        assert rev["revision_number"] == 1
        assert "version" not in rev
        assert "updated_at" not in rev
