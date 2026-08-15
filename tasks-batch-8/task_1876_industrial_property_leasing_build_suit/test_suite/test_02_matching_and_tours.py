"""Market-survey match scoring and tour coordination (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_tour,
    create_requirement,
    create_site,
    create_tour_payload,
    request_tour,
    set_logical_clock,
    setup_toured_pair,
    validate_error,
    validate_success,
)

LM = TEST_USERS["leasing_manager_headers"]
REP_1 = TEST_USERS["tenant_rep_1_headers"]
REP_2 = TEST_USERS["tenant_rep_2_headers"]


class TestMatchEvaluation:
    def test_match_score_weighted_literal(self, api):
        """PRD §3.2: "The score weights four physical attributes: clear height
        at 30%, dock doors at 30%, power at 20%, and yard depth at 20%." and
        "A site that exactly meets every minimum therefore scores 80, and the
        cap means a site at or beyond 125% of every minimum scores the full
        100." and "`hard_minimums_met` is true only when all five conditions
        hold".

        Design: Corner/calculations/match_score_weighted_literal
        """
        req = create_requirement(REP_1)
        over = create_site()  # 36 ch / 20 dock / 4000 pw / 200 yd vs 32/16/3000/150
        exact = create_site(
            site_name="Exact Fit Center", total_sf=100000, clear_height_ft=32,
            dock_doors=16, power_amps=3000, yard_depth_ft=150,
        )
        low = create_site(
            site_name="Low Clear Center", total_sf=100000, clear_height_ft=30,
            dock_doors=16, power_amps=3000, yard_depth_ft=150,
            asking_rate_psf=5.00,
        )

        s1 = validate_success(
            api.create_match_evaluation(
                {"requirement_id": req["id"], "site_id": over["id"]}, LM
            )
        )
        assert s1["match_score"] == pytest.approx(97.00, abs=0.005), (
            f"Over-specced site must score 97.00, got {s1['match_score']}"
        )
        assert s1["hard_minimums_met"] is True

        s2 = validate_success(
            api.create_match_evaluation(
                {"requirement_id": req["id"], "site_id": exact["id"]}, LM
            )
        )
        assert s2["match_score"] == pytest.approx(80.00, abs=0.005), (
            f"Exactly-at-minimum site must score 80.00, got {s2['match_score']}"
        )
        assert s2["hard_minimums_met"] is True

        s3 = validate_success(
            api.create_match_evaluation(
                {"requirement_id": req["id"], "site_id": low["id"]}, LM
            )
        )
        assert s3["match_score"] == pytest.approx(78.50, abs=0.005), (
            f"Site 2ft short on clear height must score 78.50, "
            f"got {s3['match_score']}"
        )
        assert s3["hard_minimums_met"] is False, (
            "clear height 30 < 32 fails the hard minimum even though the "
            "weighted score stays high"
        )

    def test_match_eval_persists_nothing(self, api):
        """PRD §3.2: "The evaluation persists nothing — it is a screening read
        — and returns `requirement_id`, `site_id`, the computed `match_score`,
        and the boolean `hard_minimums_met`." PRD §2.4: "`version` is an
        integer that increments by one on every mutation of the resource".

        Design: Corner/endpoints/match_eval_persists_nothing
        """
        req = create_requirement(REP_1)
        site = create_site()
        req_v0 = req["version"]
        site_v0 = site["version"]

        for headers in (REP_1, LM):
            data = validate_success(
                api.create_match_evaluation(
                    {"requirement_id": req["id"], "site_id": site["id"]}, headers
                )
            )
            assert data["requirement_id"] == req["id"]
            assert data["site_id"] == site["id"]

        site_after = validate_success(api.get_site(site["id"], LM))
        req_after = validate_success(api.get_tenant_requirement(req["id"], REP_1))
        assert site_after["version"] == site_v0, (
            f"Two match evaluations must not mutate the site: version "
            f"{site_v0} -> {site_after['version']}"
        )
        assert req_after["version"] == req_v0, (
            f"Two match evaluations must not mutate the requirement: version "
            f"{req_v0} -> {req_after['version']}"
        )


class TestTourSchedulingGuards:
    def test_tour_create_invalid_time_range_returns_422(self, api):
        """PRD §3.2: "the representative requests a tour by naming `site_id`
        and `requirement_id` with a window from `start_at` to `end_at`; the
        end must be strictly after the start, otherwise
        `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/tour_create_invalid_time_range_returns_422
        """
        req = create_requirement(REP_1)
        site = create_site()
        resp = api.create_tour(
            create_tour_payload(
                site["id"], req["id"],
                start_at="2026-08-10T10:00:00Z",
                end_at="2026-08-10T10:00:00Z",
            ),
            REP_1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_tour_confirm_cancelled_returns_invalid_state(self, api):
        """PRD §3.2: "Cancellation moves a `REQUESTED` or `CONFIRMED` tour to
        `CANCELLED`" and "`COMPLETED` and `CANCELLED` are terminal."
        PRD §2.8: "terminal states accept no further transitions — otherwise
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/tour_confirm_cancelled_returns_invalid_state
        """
        req = create_requirement(REP_1)
        site = create_site()
        tour = request_tour(site["id"], req["id"], REP_1)
        cancelled = validate_success(api.cancel_tour(tour["id"], REP_1))
        assert cancelled["status"] == "CANCELLED"
        resp = api.confirm_tour(tour["id"], LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_tour_complete_before_end_returns_409(self, api):
        """PRD §3.2: "The owning representative then marks the confirmed tour
        `CONFIRMED` → `COMPLETED`, but only once the logical clock has reached
        the tour's `end_at`; an earlier attempt fails with
        `ERR_TOUR_NOT_CONCLUDED` (409)".

        Design: Corner/validations/tour_complete_before_end_returns_409
        """
        req = create_requirement(REP_1)
        site = create_site()
        tour = request_tour(site["id"], req["id"], REP_1)
        confirmed = validate_success(api.confirm_tour(tour["id"], LM))
        assert confirmed["status"] == "CONFIRMED"
        set_logical_clock("2026-08-10T10:30:00Z")  # 30 minutes before end_at
        resp = api.complete_tour(tour["id"], REP_1)
        validate_error(resp, ApiErrorId.ERR_TOUR_NOT_CONCLUDED)
        after = validate_success(api.get_tour(tour["id"], LM))
        assert after["status"] == "CONFIRMED", (
            f"Tour must remain CONFIRMED after a premature completion, "
            f"got {after['status']}"
        )


class TestSiteTourBuffer:
    """30-minute buffered site-schedule semantics (PRD §3.2)."""

    def _setup_first_tour(self):
        req = create_requirement(REP_1)
        site = create_site()
        request_tour(
            site["id"], req["id"], REP_1,
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        )
        return req, site

    def test_site_tour_buffer_conflict_inside_buffer_rejected(self, api):
        """PRD §3.2: "The site guard rejects the request with
        `ERR_TOUR_SITE_CONFLICT` (409) when any non-`CANCELLED` tour at the
        same site has a buffered window — thirty minutes of padding on each
        side, running from thirty minutes before its `start_at` to thirty
        minutes after its `end_at` — that intersects the new tour's half-open
        window from `start_at` up to but not including `end_at`."

        Design: Difficulty/resource_temporal_overlap/site_tour_buffer_conflict
        """
        req, site = self._setup_first_tour()
        # 11:20 is inside the buffered window [09:30, 11:30) of the 10:00-11:00 tour.
        resp = api.create_tour(
            create_tour_payload(
                site["id"], req["id"],
                start_at="2026-08-10T11:20:00Z", end_at="2026-08-10T12:00:00Z",
            ),
            REP_2,
        )
        validate_error(resp, ApiErrorId.ERR_TOUR_SITE_CONFLICT)

    def test_site_tour_buffer_boundary_exclusive_succeeds(self, api):
        """PRD §3.2: "The site guard rejects the request with
        `ERR_TOUR_SITE_CONFLICT` (409) when any non-`CANCELLED` tour at the
        same site has a buffered window — thirty minutes of padding on each
        side ... that intersects the new tour's half-open window from
        `start_at` up to but not including `end_at`."

        11:30 is exactly the end of the buffered window [09:30, 11:30), which
        is half-open, so an 11:30 start does not intersect it.

        Design: Difficulty/resource_temporal_overlap/site_tour_buffer_conflict
        """
        req, site = self._setup_first_tour()
        resp = api.create_tour(
            create_tour_payload(
                site["id"], req["id"],
                start_at="2026-08-10T11:30:00Z", end_at="2026-08-10T12:00:00Z",
            ),
            REP_2,
        )
        data = validate_success(resp, 201)
        assert_tour(data)
        assert data["status"] == "REQUESTED", (
            "A tour starting exactly at the buffer boundary (11:30) must be "
            "accepted — the buffered window is half-open"
        )


class TestRepCalendarOverlap:
    """Plain half-open overlap on the representative's calendar (PRD §3.2)."""

    def _setup_rep_calendar(self):
        req = create_requirement(REP_1)
        site_a = create_site()
        site_b = create_site(site_name="Summit Logistics Center",
                             asking_rate_psf=6.50)
        site_c = create_site(site_name="Valley Commerce Center",
                             asking_rate_psf=5.50)
        request_tour(
            site_a["id"], req["id"], REP_1,
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        )
        return req, site_a, site_b, site_c

    def test_rep_calendar_adjacency_allowed(self, api):
        """PRD §3.2: "The calendar guard then rejects with
        `ERR_REP_CALENDAR_CONFLICT` (409) when any non-`CANCELLED` tour
        belonging to the same `tenant_rep_id` has a plain, unpadded half-open
        window intersecting the new one; back-to-back tours that merely touch
        at an endpoint do not intersect and are allowed."

        Design: Difficulty/resource_temporal_overlap/rep_calendar_adjacency_allowed
        """
        req, _site_a, site_b, _site_c = self._setup_rep_calendar()
        resp = api.create_tour(
            create_tour_payload(
                site_b["id"], req["id"],
                start_at="2026-08-10T11:00:00Z", end_at="2026-08-10T12:00:00Z",
            ),
            REP_1,
        )
        data = validate_success(resp, 201)
        assert_tour(data)
        assert data["status"] == "REQUESTED", (
            "A back-to-back tour touching at 11:00 must be allowed under "
            "plain half-open calendar semantics"
        )

    def test_rep_calendar_overlap_rejected(self, api):
        """PRD §3.2: "The calendar guard then rejects with
        `ERR_REP_CALENDAR_CONFLICT` (409) when any non-`CANCELLED` tour
        belonging to the same `tenant_rep_id` has a plain, unpadded half-open
        window intersecting the new one".

        Design: Difficulty/resource_temporal_overlap/rep_calendar_adjacency_allowed
        """
        req, _site_a, _site_b, site_c = self._setup_rep_calendar()
        resp = api.create_tour(
            create_tour_payload(
                site_c["id"], req["id"],
                start_at="2026-08-10T10:30:00Z", end_at="2026-08-10T11:30:00Z",
            ),
            REP_1,
        )
        validate_error(resp, ApiErrorId.ERR_REP_CALENDAR_CONFLICT)
