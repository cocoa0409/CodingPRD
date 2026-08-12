"""Screening score: dual-variant divergence, threshold boundary, cap."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_recruiter_headers, make_candidate_headers,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


def _setup_divergent_screening_scenario(api, admin_headers):
    """Season (threshold 50) with school initially TARGET; one COMPLETED event
    before submission; application submitted; two more events completed and the
    tier edited TARGET->CORE afterwards; season advanced to SELECTION."""
    season = fx.create_season(shortlist_score_threshold=50)
    school = fx.create_school(season["id"], tier="TARGET")
    fx.advance_season(season["id"])  # OPEN
    fx.set_clock("2026-05-13T00:00:00Z")
    fx.create_completed_event(
        season["id"], school["id"],
        "2026-05-12T10:00:00Z", "2026-05-12T12:00:00Z",
        event_type="RESUME_DROP", resume_count=30,
    )
    candidate = fx.create_candidate()
    fx.set_clock("2026-05-15T00:00:00Z")
    application = fx.submit_application(
        season["id"], candidate["id"], school["id"],
    )
    fx.create_completed_event(
        season["id"], school["id"],
        "2026-05-16T10:00:00Z", "2026-05-16T12:00:00Z",
        event_type="INFO_SESSION", resume_count=10,
    )
    fx.create_completed_event(
        season["id"], school["id"],
        "2026-05-17T10:00:00Z", "2026-05-17T12:00:00Z",
        event_type="CAREER_FAIR", resume_count=5,
    )
    school_fresh = validate_success(api.get_school_target(school["id"], RECRUITER))
    resp = api.patch_school_target(
        school["id"],
        {"tier": "CORE",
         "expected_school_target_version": school_fresh["version"]},
        admin_headers,
    )
    assert resp.status_code == 200, f"Setup failed: tier patch -> {resp.text}"
    fx.set_clock("2026-05-21T00:00:00Z")
    fx.advance_season(season["id"])  # SELECTION
    return season, school, candidate, application


class TestScreeningDualVariant:
    def test_provisional_snapshot_frozen_at_submission(
        self, api, admin_headers
    ):
        """PRD §3.3: "The provisional variant, computed at submission and
        stored in `screening_score_provisional`, takes the application's own
        creation timestamp as its as-of instant and the school's tier as it
        then stood; it is a snapshot and is never recomputed afterwards."

        Design: Difficulty/dual_variant_calc/screening_score_provisional_vs_final
        """
        _, _, _, application = _setup_divergent_screening_scenario(
            api, admin_headers
        )
        # TARGET 25 + 1 completed event x 5 = 30, pinned at submission.
        assert application["screening_score_provisional"] == 30
        # After tier edit and later event completions the snapshot is frozen.
        resp = api.screen_application(application["id"], "SHORTLIST", RECRUITER)
        assert resp.status_code == 200
        after = validate_success(api.get_application(application["id"], RECRUITER))
        assert after["screening_score_provisional"] == 30

    def test_final_variant_uses_current_tier_and_clock(
        self, api, admin_headers
    ):
        """PRD §3.3: "The final variant, computed at screening time, takes the
        current logical clock as its as-of instant and the school's *current*
        tier — so it diverges from the provisional snapshot whenever events
        completed, or the tier was edited, between submission and screening."
        PRD §3.4: "A `SHORTLIST` decision succeeds only when the freshly
        computed final score is at least the season's
        `shortlist_score_threshold`".

        Design: Difficulty/dual_variant_calc/screening_score_provisional_vs_final
        """
        _, _, _, application = _setup_divergent_screening_scenario(
            api, admin_headers
        )
        resp = api.screen_application(application["id"], "SHORTLIST", RECRUITER)
        data = validate_success(resp)
        # CORE 40 + 3 completed events x 5 = 55, evaluated at screen time.
        assert data["screening_score_final"] == 55
        assert data["screening_score_final"] != data[
            "screening_score_provisional"
        ]
        assert data["status"] == "SHORTLISTED"  # 55 >= threshold 50


class TestScreeningThreshold:
    def test_screening_threshold_exact_boundary(self, api):
        """PRD §3.4: "A `SHORTLIST` decision succeeds only when the freshly
        computed final score is at least the season's
        `shortlist_score_threshold`, failing with
        `ERR_SCREENING_THRESHOLD_NOT_MET` (HTTP 422) below the bar".

        Design: Corner/calculations/screening_threshold_exact_boundary
        """
        season = fx.create_season(shortlist_score_threshold=30)
        school = fx.create_school(season["id"], tier="TARGET")
        fx.advance_season(season["id"])  # OPEN
        fx.set_clock("2026-05-13T00:00:00Z")
        fx.create_completed_event(
            season["id"], school["id"],
            "2026-05-12T10:00:00Z", "2026-05-12T12:00:00Z",
            resume_count=30,
        )
        candidate = fx.create_candidate()
        fx.set_clock("2026-05-15T00:00:00Z")
        application = fx.submit_application(
            season["id"], candidate["id"], school["id"],
        )
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        resp = api.screen_application(application["id"], "SHORTLIST", RECRUITER)
        data = validate_success(resp)
        assert data["screening_score_final"] == 30  # 25 + 1 x 5
        assert data["status"] == "SHORTLISTED"  # 30 >= 30 inclusive

    def test_screening_below_threshold_then_reject(self, api):
        """PRD §3.4: "A `SHORTLIST` decision succeeds only when the freshly
        computed final score is at least the season's
        `shortlist_score_threshold`, failing with
        `ERR_SCREENING_THRESHOLD_NOT_MET` (HTTP 422) below the bar, and moves
        the application `SUBMITTED → SHORTLISTED`. A `REJECT` decision carries
        no threshold requirement and moves the application `SUBMITTED →
        SCREENED_OUT`, with the final score still computed and stored."

        Design: Corner/calculations/screening_below_threshold_then_reject
        """
        season = fx.create_season(shortlist_score_threshold=30)
        school = fx.create_school(season["id"], tier="TARGET")
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        candidate = fx.create_candidate()
        application = fx.submit_application(
            season["id"], candidate["id"], school["id"],
        )
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        resp = api.screen_application(application["id"], "SHORTLIST", RECRUITER)
        validate_error(resp, ApiErrorId.ERR_SCREENING_THRESHOLD_NOT_MET)
        resp = api.screen_application(application["id"], "REJECT", RECRUITER)
        data = validate_success(resp)
        assert data["status"] == "SCREENED_OUT"
        assert data["screening_score_final"] == 25  # TARGET 25, no events


class TestScreeningScoreCap:
    def test_screening_score_capped_at_100(self, api):
        """PRD §3.3: "The **screening score** is a weighted sum capped at 100
        points: a tier weight of 40 for a `CORE` school, 25 for `TARGET`, or
        10 for `EXPLORATORY`; plus 5 points for each qualifying completed
        campus event; plus 15 points when the application's `referral_flag` is
        set; plus 10 points per prior internship recorded in
        `prior_internship_count`."

        Design: Corner/calculations/screening_score_capped_at_100
        """
        season = fx.create_season(shortlist_score_threshold=10)
        school = fx.create_school(
            season["id"], tier="CORE", stipend_region="METRO",
        )
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-13T00:00:00Z")
        # Ten completed events before submission (non-overlapping).
        windows = [
            ("2026-05-12T08:00:00Z", "2026-05-12T09:00:00Z"),
            ("2026-05-12T10:00:00Z", "2026-05-12T11:00:00Z"),
            ("2026-05-12T12:00:00Z", "2026-05-12T13:00:00Z"),
            ("2026-05-12T14:00:00Z", "2026-05-12T15:00:00Z"),
            ("2026-05-12T16:00:00Z", "2026-05-12T17:00:00Z"),
            ("2026-05-13T08:00:00Z", "2026-05-13T09:00:00Z"),
            ("2026-05-13T10:00:00Z", "2026-05-13T11:00:00Z"),
            ("2026-05-13T12:00:00Z", "2026-05-13T13:00:00Z"),
            ("2026-05-13T14:00:00Z", "2026-05-13T15:00:00Z"),
            ("2026-05-13T16:00:00Z", "2026-05-13T17:00:00Z"),
        ]
        for start, end in windows:
            fx.create_completed_event(season["id"], school["id"], start, end)
        candidate = fx.create_candidate()
        fx.set_clock("2026-05-15T00:00:00Z")
        application = fx.submit_application(
            season["id"], candidate["id"], school["id"],
            referral_flag=True, prior_internship_count=2,
        )
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        resp = api.screen_application(application["id"], "SHORTLIST", RECRUITER)
        data = validate_success(resp)
        # Raw 40 + 10*5 + 15 + 2*10 = 125 -> clamped to 100.
        assert data["screening_score_final"] == 100
        assert data["status"] == "SHORTLISTED"
