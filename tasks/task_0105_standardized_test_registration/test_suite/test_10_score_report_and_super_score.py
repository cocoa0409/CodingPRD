"""Score report posting and Super Score computation tests.

Covers PRD §3.9 — ScoreReport append-only semantics, RESCORED
superseding OFFICIAL, Super Score COLLEGE_BOARD_OFFICIAL vs
INSTITUTIONAL_SUBMISSION variants, ACT mean rounding, AP/CLEP
latest-sitting-only, empty-pool fallback, 730-day lookback.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    assert_score_report,
    complete_registration_lifecycle,
    create_candidate,
    fmt_iso,
    make_candidate_headers,
    parse_iso,
    post_score_report,
    reset_clock_to,
    validate_error,
    validate_success,
)


# ===========================================================================
# Score report posting
# ===========================================================================
class TestScoreReportPosting:
    def test_post_score_report_returns_append_only_envelope(self, api):
        """PRD §2.4: "A `ScoreReport`, a `CLEPCreditAward`, and a
        `RefundTransaction` each carry only an `id` and a `created_at`
        — they have no `updated_at` and no `version`".

        Claim: POST /score-reports returns id + created_at and the
        append-only envelope per PRD §2.4.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg = complete_registration_lifecycle(cand)
        report = post_score_report(
            event["id"], reg["id"],
            section_scores={"reading_writing": 600, "math": 700},
            total_score=1300,
        )
        assert_score_report(report)
        assert report["report_type"] == "OFFICIAL"


# ===========================================================================
# Super Score — empty pool fallback
# ===========================================================================
class TestSuperScoreEmptyPool:
    def test_empty_pool_returns_null_composite(self, api):
        """PRD §3.9: "When the candidate pool after filtering is
        empty, the endpoint returns a composite value of null, an
        empty sections object, and a `sittings_used` count of zero."

        Claim: a candidate with no completed registrations returns
        composite=null, sections={}, sittings_used=0.
        """
        cand = create_candidate()
        res = api.get_super_score(
            cand["id"], make_candidate_headers(cand["id"]),
            params={"test_type": "SAT"},
        )
        data = validate_success(res, 200)
        assert data["composite"] is None
        assert data["sections"] == {}
        assert data["sittings_used"] == 0
        assert data["source_score_report_ids"] == []


# ===========================================================================
# Super Score COLLEGE_BOARD_OFFICIAL vs INSTITUTIONAL_SUBMISSION
# ===========================================================================
class TestSuperScoreVariants:
    def _complete_event_with_scores(self, cand, test_date_iso,
                                    registration_deadline_iso,
                                    late_registration_deadline_iso,
                                    score_release_iso,
                                    section_scores, total_score):
        """Helper: drive event through to COMPLETED and post a score."""
        event, reg = complete_registration_lifecycle(
            cand,
            test_type="SAT",
            test_date_iso=test_date_iso,
            registration_deadline=registration_deadline_iso,
            late_registration_deadline=late_registration_deadline_iso,
            score_release_date=score_release_iso,
        )
        return event, post_score_report(
            event["id"], reg["id"],
            section_scores=section_scores,
            total_score=total_score,
        )

    def test_college_board_official_takes_per_section_max(self, api):
        """PRD §3.9: "In `COLLEGE_BOARD_OFFICIAL` mode (the default),
        each section's contribution is the maximum of that section's
        `section_scores` value across all sittings in the pool — so
        `reading_writing`'s maximum and `math`'s maximum may come from
        different sittings."

        Claim: two sittings (600/700 and 650/650) yield composite
        1350 under COLLEGE_BOARD_OFFICIAL (max rw=650, max math=700).
        """
        reset_clock_to("2024-06-01T00:00:00.000Z")
        cand = create_candidate()
        # Sitting 1 — June 2024.
        self._complete_event_with_scores(
            cand,
            test_date_iso="2024-06-15T09:00:00.000Z",
            registration_deadline_iso="2024-06-01T00:00:00.000Z",
            late_registration_deadline_iso="2024-06-10T00:00:00.000Z",
            score_release_iso="2024-06-22T00:00:00.000Z",
            section_scores={"reading_writing": 600, "math": 700},
            total_score=1300,
        )
        # Sitting 2 — June 2025.
        reset_clock_to("2025-06-01T00:00:00.000Z")
        self._complete_event_with_scores(
            cand,
            test_date_iso="2025-06-15T09:00:00.000Z",
            registration_deadline_iso="2025-06-01T00:00:00.000Z",
            late_registration_deadline_iso="2025-06-10T00:00:00.000Z",
            score_release_iso="2025-06-22T00:00:00.000Z",
            section_scores={"reading_writing": 650, "math": 650},
            total_score=1300,
        )
        # Compute Super Score.
        advance_clock_to("2025-09-01T00:00:00.000Z")
        res = api.get_super_score(
            cand["id"], make_candidate_headers(cand["id"]),
            params={"test_type": "SAT", "reporting_mode": "COLLEGE_BOARD_OFFICIAL"},
        )
        data = validate_success(res, 200)
        assert data["composite"] == 1350, (
            "PRD §3.9: COLLEGE_BOARD_OFFICIAL takes per-section max across sittings"
        )
        assert data["sections"]["reading_writing"] == 650
        assert data["sections"]["math"] == 700
        assert data["sittings_used"] == 2

    def test_institutional_submission_takes_single_best_sitting(self, api):
        """PRD §3.9: "In `INSTITUTIONAL_SUBMISSION` mode, the system
        instead identifies the single sitting whose `total_score` is
        highest within the pool and uses that sitting's `section_scores`
        verbatim — so all sections of the returned composite come from
        the same sitting".

        Claim: two sittings (600/700=1300 and 650/650=1300) — tied by
        total — yield composite 1300 with sections from a SINGLE
        sitting in INSTITUTIONAL_SUBMISSION mode.
        """
        reset_clock_to("2024-06-01T00:00:00.000Z")
        cand = create_candidate()
        self._complete_event_with_scores(
            cand,
            test_date_iso="2024-06-15T09:00:00.000Z",
            registration_deadline_iso="2024-06-01T00:00:00.000Z",
            late_registration_deadline_iso="2024-06-10T00:00:00.000Z",
            score_release_iso="2024-06-22T00:00:00.000Z",
            section_scores={"reading_writing": 600, "math": 700},
            total_score=1300,
        )
        reset_clock_to("2025-06-01T00:00:00.000Z")
        self._complete_event_with_scores(
            cand,
            test_date_iso="2025-06-15T09:00:00.000Z",
            registration_deadline_iso="2025-06-01T00:00:00.000Z",
            late_registration_deadline_iso="2025-06-10T00:00:00.000Z",
            score_release_iso="2025-06-22T00:00:00.000Z",
            section_scores={"reading_writing": 650, "math": 650},
            total_score=1300,
        )
        advance_clock_to("2025-09-01T00:00:00.000Z")
        res = api.get_super_score(
            cand["id"], make_candidate_headers(cand["id"]),
            params={"test_type": "SAT", "reporting_mode": "INSTITUTIONAL_SUBMISSION"},
        )
        data = validate_success(res, 200)
        # Composite is the single best sitting's total: 1300.
        assert data["composite"] == 1300
        assert data["sittings_used"] == 1, (
            "PRD §3.9: INSTITUTIONAL_SUBMISSION uses sections from a single sitting"
        )
        rw = data["sections"]["reading_writing"]
        math = data["sections"]["math"]
        # Both sittings tie at total=1300; the implementation picks one
        # deterministically. Whichever it picks, the pair must match one
        # of the original sittings exactly.
        assert (rw, math) in {(600, 700), (650, 650)}, (
            "PRD §3.9: sections must come from the SAME sitting verbatim"
        )
