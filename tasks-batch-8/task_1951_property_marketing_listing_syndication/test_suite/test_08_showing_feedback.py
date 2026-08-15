"""Showing windows and feedback: half-open overlap semantics, feedback timing and
uniqueness, rating ranges, exclusion, and the raw-vs-weighted score pair
(PRD §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_showing_window_payload, create_feedback_payload,
    create_active_listing, owner_headers, create_window, submit_feedback,
    create_ended_window, get_summary, get_listing, set_clock,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]


class TestFeedbackScoreVariants:
    def _setup_two_aged_feedback(self, api):
        """Ratings 5 (created 2026-08-01T12:00:00Z) and 3 (created
        2026-08-15T12:00:00Z); the clock is left at 2026-08-29T12:00:00Z so the
        feedback ages are exactly 28 and 14 days."""
        agent, active = create_active_listing()
        w1 = create_window(active, agent, "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        w2 = create_window(active, agent, "2026-08-15T10:00:00Z", "2026-08-15T11:00:00Z")
        set_clock("2026-08-01T12:00:00Z")
        submit_feedback(w1, agent, 5)
        set_clock("2026-08-15T12:00:00Z")
        submit_feedback(w2, agent, 3)
        set_clock("2026-08-29T12:00:00Z")
        return agent, active

    def test_raw_mean_and_decay_weighted_mean_diverge_on_summary(self, api):
        """PRD §3.8: "Otherwise, `feedback_score_raw` is the simple mean of the
        included ratings, rounded half up to three decimal places, ignoring age
        entirely. The `feedback_score_weighted` score applies an age decay: each
        feedback's age in days is the exact number of seconds between its
        `created_at` and now, divided by 86400; its weight is two raised to the
        power of negative that age divided by a half-life of fourteen days; and the
        score is the sum of each rating multiplied by its weight, divided by the sum
        of the weights, rounded half up to three decimal places."
        Ages 28 and 14 days give weights 0.25 and 0.5: raw 4.0, weighted 3.667.

        Design: Difficulty/dual_variant_calc/feedback_score_raw_vs_decay_weighted
        """
        agent, active = self._setup_two_aged_feedback(api)
        summary = get_summary(active["id"])
        assert summary["feedback_score_raw"] == pytest.approx(4.0, abs=1e-9)
        assert summary["feedback_score_weighted"] == pytest.approx(3.667, abs=1e-9)
        assert summary["feedback_score_raw"] != summary["feedback_score_weighted"]

    def test_same_scores_surface_on_listing_read(self, api):
        """PRD §3.8: "Two scores summarize a listing's included feedback, and both
        are recomputed on feedback creation, on exclusion, and on every read of the
        listing or its summary."
        PRD §3.8: "Because older feedback contributes less, the weighted score
        differs from the raw score whenever the included records differ in age."

        Design: Difficulty/dual_variant_calc/feedback_score_raw_vs_decay_weighted
        """
        agent, active = self._setup_two_aged_feedback(api)
        listing = get_listing(active["id"])
        assert listing["feedback_score_raw"] == pytest.approx(4.0, abs=1e-9)
        assert listing["feedback_score_weighted"] == pytest.approx(3.667, abs=1e-9)


class TestShowingWindowOverlap:
    def test_touching_endpoints_do_not_overlap(self, api):
        """PRD §3.8: "two windows that merely touch, where one window's `ends_at`
        equals the other's `starts_at`, do not overlap and are both allowed."
        PRD §3.8: "Windows occupy a half-open interval — a visitor at exactly
        `starts_at` is inside the window, one at exactly `ends_at` is not"

        Design: Difficulty/resource_temporal_overlap/showing_window_half_open_adjacency
        """
        agent, active = create_active_listing()
        create_window(active, agent, "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        adjacent = validate_success(api.create_showing_window(
            active["id"],
            create_showing_window_payload("2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z"),
            owner_headers(agent)), 201)
        assert adjacent["status"] == "SCHEDULED"

        windows = get_success_data(api.list_showing_windows(active["id"], MC), 200)
        assert len(windows) == 2

    def test_interior_intersection_rejected(self, api):
        """PRD §3.8: "Windows occupy a half-open interval — a visitor at exactly
        `starts_at` is inside the window, one at exactly `ends_at` is not — and a new
        window must not intersect any other `SCHEDULED` window of the same listing;
        two windows that merely touch, where one window's `ends_at` equals the
        other's `starts_at`, do not overlap and are both allowed."
        PRD §3.8: "An intersecting request is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/showing_window_half_open_adjacency
        """
        agent, active = create_active_listing()
        create_window(active, agent, "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        res = api.create_showing_window(
            active["id"],
            create_showing_window_payload("2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z"),
            owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP, expected_status=409)

        windows = get_success_data(api.list_showing_windows(active["id"], MC), 200)
        assert len(windows) == 1


def test_excluded_feedback_removed_from_scores(api):
    """PRD §3.8: "The input set is exactly the listing's feedback records in
    `INCLUDED` status; `EXCLUDED` records are ignored entirely."
    PRD §3.8: "Exclusion recomputes both scores over the remaining included
    feedback."

    Design: Corner/calculations/excluded_feedback_removed_from_scores
    """
    agent, active = create_active_listing()
    w1 = create_window(active, agent, "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    w2 = create_window(active, agent, "2026-08-15T10:00:00Z", "2026-08-15T11:00:00Z")
    set_clock("2026-08-01T12:00:00Z")
    fb1 = submit_feedback(w1, agent, 5)
    set_clock("2026-08-15T12:00:00Z")
    submit_feedback(w2, agent, 3)

    excluded = validate_success(
        api.exclude_feedback(fb1["id"], TEST_USERS["marketing_coordinator_headers"]), 200)
    assert excluded["status"] == "EXCLUDED"

    summary = get_summary(active["id"])
    assert summary["feedback_score_raw"] == pytest.approx(3.0, abs=1e-9)
    assert summary["feedback_score_weighted"] == pytest.approx(3.0, abs=1e-9), (
        "a single remaining INCLUDED rating dominates both variants identically"
    )


def test_feedback_exclude_twice_rejected(api):
    """PRD §3.8: "A `MarketingCoordinator` may moderate a feedback record out of the
    aggregate by excluding it, moving it from `INCLUDED` to `EXCLUDED`; excluding a
    record that is not currently `INCLUDED` is rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "When the set is empty, both scores are null."

    Design: Corner/state_machines/feedback_exclude_twice_rejected
    """
    agent, active = create_active_listing()
    window = create_ended_window(active, agent)
    feedback = submit_feedback(window, agent, 4)
    validate_success(
        api.exclude_feedback(feedback["id"], TEST_USERS["marketing_coordinator_headers"]), 200)

    res = api.exclude_feedback(feedback["id"], TEST_USERS["marketing_coordinator_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    listed = get_success_data(api.get_window_feedback(window["id"], MC), 200)
    assert listed[0]["status"] == "EXCLUDED"
    summary = get_summary(active["id"])
    assert summary["feedback_score_raw"] is None
    assert summary["feedback_score_weighted"] is None


def test_feedback_rating_out_of_range_returns_invalid_request(api):
    """PRD §3.8: "After a window ends, attendees' impressions are collected as
    showing feedback: a `rating` from 1 to 5 inclusive and an optional free-text
    `comment`."
    PRD §2.9: "Field validity — required fields present, types correct, enum
    membership, and ranges, else `ERR_INVALID_REQUEST`."

    Design: Corner/validations/feedback_rating_out_of_range_returns_invalid_request
    """
    agent, active = create_active_listing()
    window = create_ended_window(active, agent)
    res = api.create_feedback(window["id"], create_feedback_payload(6), owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    assert get_success_data(api.get_window_feedback(window["id"], MC), 200) == []


def test_feedback_before_window_end_returns_window_not_ended(api):
    """PRD §3.8: "Submitting feedback is allowed only once the current instant has
    reached the window's `ends_at` — earlier submissions fail with
    `ERR_WINDOW_NOT_ENDED`"

    Design: Corner/validations/feedback_before_window_end_returns_window_not_ended
    """
    agent, active = create_active_listing()
    window = create_window(active, agent, "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    set_clock("2026-08-01T10:30:00Z")  # window still running

    res = api.create_feedback(window["id"], create_feedback_payload(4), owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_WINDOW_NOT_ENDED, expected_status=422)

    assert get_success_data(api.get_window_feedback(window["id"], MC), 200) == []


def test_second_feedback_same_window_returns_feedback_already_exists(api):
    """PRD §3.8: "a window accepts at most one feedback record, a second attempt
    failing with `ERR_FEEDBACK_ALREADY_EXISTS`"

    Design: Corner/validations/second_feedback_same_window_returns_feedback_already_exists
    """
    agent, active = create_active_listing()
    window = create_ended_window(active, agent)
    submit_feedback(window, agent, 4)

    res = api.create_feedback(window["id"], create_feedback_payload(2), owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_FEEDBACK_ALREADY_EXISTS, expected_status=409)

    listed = get_success_data(api.get_window_feedback(window["id"], MC), 200)
    assert len(listed) == 1 and listed[0]["rating"] == 4
