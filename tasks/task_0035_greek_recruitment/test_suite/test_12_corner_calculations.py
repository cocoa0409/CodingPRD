"""Corner — calculations section.

Two non-stub instances:
  - corner_mutual_select_waterfall_pnm_already_matched_excluded_from_other_chapter
  - corner_risk_status_at_suspend_threshold_exact_boundary

(corner_dvc_dues_snapshot_already_covered is a stub deferred to
 Difficulty/dual_variant_calc/dvc_dues_snapshot_vs_live_at_read — no test emitted.)
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    create_chapter,
    create_round,
    register_and_activate_pnm,
    create_and_open_party,
    create_invitation,
    accept_invitation,
    complete_party,
    advance_round,
    file_pnm_preference,
    file_chapter_preference,
    file_risk_incident,
    list_pnm_bid_matches,
    TEST_USERS,
)


class TestMutualSelectionWaterfallPnmAlreadyMatchedExcludedFromOtherChapter:
    """A legacy PNM L matched to C1 in the legacy_pass is removed from C2's
    candidate set for the remainder of the run — waterfall, not bipartite."""

    def test_legacy_pnm_matched_only_to_legacy_chapter_not_other_chapter(self, api):
        """PRD §3.5: "A PNM matched in the legacy pass is removed from all other chapters' candidate lists immediately."
        PRD §3.5: "as before, a PNM matched in either pass is removed from every chapter's candidate list for the remainder of the run, so no PNM emerges from the allocator with more than one `BidMatch`."

        Design: Corner/calculations/corner_mutual_select_waterfall_pnm_already_matched_excluded_from_other_chapter
        """
        set_clock("2026-09-01T00:00:00Z")
        c1 = create_chapter(
            name="C1",
            greek_type="SORORITY",
            quota_total=2,
            dues_per_member_cents=10000,
            legacy_priority_slots=1,
        )
        c2 = create_chapter(
            name="C2",
            greek_type="SORORITY",
            quota_total=2,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 mw")
        lx = register_and_activate_pnm(
            full_name="LX", gpa=3.50, legacy_chapter_id=c1["id"]
        )
        # PNM attends parties at both chapters.
        p1 = create_and_open_party(
            rnd["id"], c1["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        p2 = create_and_open_party(
            rnd["id"], c2["id"], scheduled_start_utc="2026-09-06T18:00:00Z"
        )
        i1 = create_invitation(p1["id"], lx["id"], c1["id"])
        i2 = create_invitation(p2["id"], lx["id"], c2["id"])
        accept_invitation(i1["id"], lx["id"])
        accept_invitation(i2["id"], lx["id"])
        complete_party(p1["id"], c1["id"])
        complete_party(p2["id"], c2["id"])
        advance_round(rnd["id"])  # PARTY -> MUTUAL_SELECTION
        # PNM ranks C1 first, C2 second.
        file_pnm_preference(rnd["id"], lx["id"], c1["id"], rank=1)
        file_pnm_preference(rnd["id"], lx["id"], c2["id"], rank=2)
        # Both chapters rank LX rank=1.
        file_chapter_preference(rnd["id"], c1["id"], lx["id"], rank=1)
        file_chapter_preference(rnd["id"], c2["id"], lx["id"], rank=1)
        advance_round(rnd["id"])  # MUTUAL_SELECTION -> BID_DAY (allocator runs)
        bids = list_pnm_bid_matches(lx["id"])
        assert len(bids) == 1, (
            f"LX should be matched exactly once; got {len(bids)}: {bids}"
        )
        assert bids[0]["chapter_id"] == c1["id"]
        assert bids[0]["priority_kind"] == "LEGACY"


class TestRiskStatusAtSuspendThresholdExactBoundary:
    """risk_points == 15 (== SUSPEND_THRESHOLD) yields SUSPENDED;
    risk_points == 14 yields PROBATION."""

    def test_chapter_at_14_points_is_probation(self, api):
        """PRD §2.8: "if `risk_points` is at least 15, the chapter is `SUSPENDED`; otherwise, if `risk_points` is at least 6, the chapter is on `PROBATION`; otherwise it is in `GOOD_STANDING`. The boundary is inclusive on the lower bound — 6 points is `PROBATION` (not `GOOD_STANDING`), 5 points is `GOOD_STANDING`, 15 points is `SUSPENDED`, 14 points is `PROBATION`."

        Design: Corner/calculations/corner_risk_status_at_suspend_threshold_exact_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        ch = create_chapter(
            name="SuspBoundaryA",
            greek_type="FRATERNITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        file_risk_incident(chapter_id=ch["id"], severity_points=10, reason="x")
        file_risk_incident(chapter_id=ch["id"], severity_points=4, reason="y")
        ch_after = validate_success(
            api.get_chapter(ch["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_after["risk_points"] == 14
        assert ch_after["risk_status"] == "PROBATION"

    def test_chapter_at_15_points_is_suspended(self, api):
        """PRD §2.8: "15 points is `SUSPENDED`, 14 points is `PROBATION`."

        Design: Corner/calculations/corner_risk_status_at_suspend_threshold_exact_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        ch = create_chapter(
            name="SuspBoundaryB",
            greek_type="FRATERNITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        file_risk_incident(chapter_id=ch["id"], severity_points=10, reason="x")
        file_risk_incident(chapter_id=ch["id"], severity_points=4, reason="y")
        file_risk_incident(chapter_id=ch["id"], severity_points=1, reason="z")
        ch_after = validate_success(
            api.get_chapter(ch["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_after["risk_points"] == 15
        assert ch_after["risk_status"] == "SUSPENDED"
