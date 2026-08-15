"""Story priority scoring: the desk-forward formula, its clamped time
pressure, and the analytics-blend variant fed by the author track record."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_greenlit_story,
    get_success_data,
    ingest_analytics,
    set_clock,
    setup_newsroom,
    setup_published_story,
    submit_pitch,
    greenlight,
)

ND = TEST_USERS["news_director_headers"]


class TestDeskForwardVsAnalyticsBlend:
    def _zero_track_record_story(self, api):
        """STANDARD FEATURES pitch with deadline exactly 72h out, greenlit.
        The author has no settled analytics, so the track record is 0."""
        ctx = setup_newsroom(reporter_desk="FEATURES")
        set_clock("2026-08-01T00:00:00Z")
        _pitch, story_id = create_greenlit_story(
            ctx, title="Garden gala", desk="FEATURES",
            deadline_at="2026-08-04T00:00:00Z", urgency="STANDARD")
        return ctx, story_id

    def test_stored_priority_and_desk_read(self, api):
        """PRD §3.2: "The urgency weight is 10 for a `STANDARD` pitch, 25 for
        an `URGENT` pitch, and 40 for a `BREAKING` pitch, and this weight is
        doubled."
        PRD §3.2: "The desk weight — 5 for `METRO`, 4 for `BUSINESS`, 3 for
        `SPORTS`, 2 for `FEATURES` — is added as-is."
        PRD §3.2: "This pure desk-forward value — it ignores the author's
        history entirely — is what is stored on `priority_score`, and it is
        the figure the breaking-news bump check later compares against the
        bump floor."
        PRD §3.2: "The `DESK` selection returns the stored desk-forward
        figure; the `ANALYTICS` selection recomputes the blended variant
        described in §3.7, so the same story can score differently once its
        author has settled analytics."

        Design: Difficulty/dual_variant_calc/story_priority_desk_vs_analytics
        """
        ctx, story_id = self._zero_track_record_story(api)
        story = get_success_data(api.get_story(story_id, ND))
        # 10 x 2 (doubled urgency) + 2 (FEATURES desk) + 0 (72h out, no
        # time pressure) = 22.00
        assert story["priority_score"] == pytest.approx(22.00, abs=0.01)

        desk_read = get_success_data(api.get_story_priority_score(
            story_id, ctx["desk_headers"], params={"variant": "DESK"}))
        assert desk_read["score"] == pytest.approx(22.00, abs=0.01)
        assert desk_read["variant"] == "DESK"

    def test_analytics_read_blends_zero_track_record(self, api):
        """PRD §3.7: "If no qualifying reports exist, the track record is 0;
        otherwise it is the arithmetic mean of their `performance_score`
        values, rounded half-up to two decimal places."
        PRD §3.7: "The analytics-blend variant of the story priority score —
        returned by the computed priority-score read of §3.2 when its
        `variant` parameter selects `ANALYTICS` — recomputes the desk base
        score and then mixes it with the author's track record: six-tenths of
        the base plus four-tenths of the track record, the sum rounded half-up
        to two decimal places."
        PRD §3.2: "The `DESK` selection returns the stored desk-forward
        figure; the `ANALYTICS` selection recomputes the blended variant
        described in §3.7, so the same story can score differently once its
        author has settled analytics."

        Design: Difficulty/dual_variant_calc/story_priority_desk_vs_analytics
        """
        ctx, story_id = self._zero_track_record_story(api)
        desk_read = get_success_data(api.get_story_priority_score(
            story_id, ctx["desk_headers"], params={"variant": "DESK"}))
        alt_read = get_success_data(api.get_story_priority_score(
            story_id, ctx["desk_headers"], params={"variant": "ANALYTICS"}))
        # round_half_up(0.6 x 22.00 + 0.4 x 0, 2) = 13.20
        assert alt_read["score"] == pytest.approx(13.20, abs=0.01)
        assert alt_read["variant"] == "ANALYTICS"
        assert desk_read["score"] != alt_read["score"], \
            "identical story data scores differently per variant"


class TestMultifactorNonlinear:
    def _scored_story(self, api, ctx, **pitch_kwargs):
        _pitch, story_id = create_greenlit_story(ctx, **pitch_kwargs)
        return get_success_data(api.get_story_priority_score(
            story_id, ctx["desk_headers"], params={"variant": "DESK"}))["score"]

    def test_past_deadline_clamps_time_pressure_at_max(self, api):
        """PRD §3.2: "Time pressure contributes up to 30 points: measure the
        hours from now until the pitch's `deadline_at`, subtract that figure
        from 72, divide the difference by 72, and clamp the fraction so it is
        never below 0 (a deadline more than 72 hours out contributes nothing)
        and never above 1 (a deadline at or past the present moment
        contributes the maximum); multiply the clamped fraction by 30."
        PRD §3.2: "The base score is the doubled urgency weight plus the desk
        weight plus the time-pressure points, rounded half-up to two decimal
        places."

        Design: Difficulty/combinatorial_formula/priority_score_multifactor_nonlinear
        """
        ctx = setup_newsroom()
        set_clock("2026-08-01T00:00:00Z")
        # Deadline 24h in the past: raw pressure (72+24)/72 = 1.333 clamps
        # to 1 -> 10 x 2 + 4 + 30 = 54.00
        score = self._scored_story(
            api, ctx, title="Late budget wrap", desk="BUSINESS",
            deadline_at="2026-07-31T00:00:00Z", urgency="STANDARD",
            story_type="DIGITAL")
        assert score == pytest.approx(54.00, abs=0.01)

    def test_breaking_pitch_lands_mid_clamp(self, api):
        """PRD §3.2: "Time pressure contributes up to 30 points: measure the
        hours from now until the pitch's `deadline_at`, subtract that figure
        from 72, divide the difference by 72, and clamp the fraction so it is
        never below 0 (a deadline more than 72 hours out contributes nothing)
        and never above 1 (a deadline at or past the present moment
        contributes the maximum); multiply the clamped fraction by 30."
        PRD §3.2: "The base score is the doubled urgency weight plus the desk
        weight plus the time-pressure points, rounded half-up to two decimal
        places."

        Design: Difficulty/combinatorial_formula/priority_score_multifactor_nonlinear
        """
        ctx = setup_newsroom()
        set_clock("2026-08-01T00:00:00Z")
        # 12h out: (72-12)/72 x 30 = 25.00 -> 40 x 2 + 3 + 25 = 108.00
        score = self._scored_story(
            api, ctx, title="Stadium fire", desk="SPORTS",
            deadline_at="2026-08-01T12:00:00Z", urgency="BREAKING",
            story_type="BROADCAST")
        assert score == pytest.approx(108.00, abs=0.01)


class TestAnalyticsBlendInputSet:
    def test_blend_uses_only_settled_active_reports(self, api):
        """PRD §3.7: "For a given author, consider only analytics reports that
        are `ACTIVE`, of the `SETTLED` variant, and attached to stories
        authored by that staff member whose status is `PUBLISHED` or
        `RETRACTED`; realtime and voided reports are excluded."
        PRD §3.7: "The analytics-blend variant of the story priority score —
        returned by the computed priority-score read of §3.2 when its
        `variant` parameter selects `ANALYTICS` — recomputes the desk base
        score and then mixes it with the author's track record: six-tenths of
        the base plus four-tenths of the track record, the sum rounded half-up
        to two decimal places."

        Design: Corner/calculations/analytics_blend_uses_only_settled_active
        """
        ctx, story1, _slot = setup_published_story(
            with_analyst=True, urgency="URGENT",
            deadline_at="2026-08-02T00:00:00Z")
        # SETTLED 390.00 and REALTIME 351.00 on identical inputs; both ACTIVE.
        settled = ingest_analytics(ctx, story1["id"], variant="SETTLED",
                                   views=5000, engagement_minutes=300)
        realtime = ingest_analytics(ctx, story1["id"], variant="REALTIME",
                                    views=5000, engagement_minutes=300)
        assert settled["performance_score"] == pytest.approx(390.00, abs=0.01)
        assert realtime["performance_score"] == pytest.approx(351.00, abs=0.01)
        assert settled["status"] == "ACTIVE" and realtime["status"] == "ACTIVE"

        # Same author's second story. The clock stands at 2026-08-01T06:30
        # after publication, so the deadline is set far enough out
        # (2026-08-05, >72h) for the time-pressure term to clamp to zero and
        # the desk base to be exactly 22.00.
        pitch2 = submit_pitch(ctx, title="BL two", desk="FEATURES",
                              deadline_at="2026-08-05T00:00:00Z",
                              urgency="STANDARD")
        pitch2 = greenlight(ctx, pitch2["id"], story_type="DIGITAL")
        story2_id = pitch2["greenlit_story_id"]

        blend = get_success_data(api.get_story_priority_score(
            story2_id, ctx["desk_headers"], params={"variant": "ANALYTICS"}))
        # round_half_up(0.6 x 22.00 + 0.4 x 390.00, 2) = 169.20; including the
        # REALTIME report in the track record would give 161.40 instead.
        assert blend["score"] == pytest.approx(169.20, abs=0.01)
