"""Going to press and measuring it: the publication scheduler, story kill
rules, the supersede link, and audience analytics scoring."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_staff_to,
    create_analytics_report_payload,
    create_greenlit_story,
    create_slot,
    drive_story_to_cleared,
    get_success_data,
    ingest_analytics,
    propose_and_accept,
    propose_assignment,
    schedule,
    set_clock,
    setup_newsroom,
    setup_published_story,
    validate_error,
    validate_paginated,
    validate_success,
)

ND = TEST_USERS["news_director_headers"]


class TestPublicationScheduler:
    def test_publishes_only_due_and_unembargoed(self, api):
        """PRD §3.5: "A `NewsDirector` triggers an operations checkpoint that
        publishes every `SCHEDULED` story whose slot's `window_start` has been
        reached by the logical clock and whose embargo is satisfied —
        `embargo_until` null or no later than now."
        PRD §3.5: "Each published story moves `SCHEDULED → PUBLISHED`,
        records `published_at` as now, and increments its `version`; the same
        checkpoint also sweeps staffing call-ins (§3.8), and its response
        lists the `published_story_ids` and `expired_call_in_ids` it
        processed."

        Design: Corner/endpoints/scheduler_publishes_only_due_and_unembargoed
        """
        ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                             legal_reviewer=True)
        set_clock("2026-08-01T00:00:00Z")
        _pa, sa = create_greenlit_story(
            ctx, title="SP A", deadline_at="2026-08-02T00:00:00Z",
            urgency="URGENT")
        drive_story_to_cleared(
            ctx, sa,
            assignment_window=("2026-08-01T01:00:00Z", "2026-08-01T02:00:00Z"))
        _pb, sb = create_greenlit_story(
            ctx, title="SP B", deadline_at="2026-08-02T00:00:00Z",
            urgency="URGENT")
        drive_story_to_cleared(
            ctx, sb, word_count=700, embargo_until="2026-08-01T06:45:00Z",
            assignment_window=("2026-08-01T02:00:00Z", "2026-08-01T03:00:00Z"))
        slot = create_slot(ctx["desk_headers"],
                           window_start="2026-08-01T06:00:00Z",
                           window_end="2026-08-01T07:00:00Z", capacity=2)
        schedule(ctx, sa, slot["id"])
        schedule(ctx, sb, slot["id"])

        # 06:30: A's window is open and it carries no embargo; B's embargo
        # (06:45) has not passed.
        set_clock("2026-08-01T06:30:00Z")
        run1 = get_success_data(api.run_publication_scheduler(ND))
        assert set(run1["published_story_ids"]) == {sa}, \
            "the embargoed story is withheld"
        story_a = get_success_data(api.get_story(sa, ND))
        assert story_a["status"] == "PUBLISHED"
        assert story_a["published_at"].startswith("2026-08-01T06:30:00")
        story_b = get_success_data(api.get_story(sb, ND))
        assert story_b["status"] == "SCHEDULED", "embargo not yet lifted"

        # 06:50: the embargo has passed; B publishes on the next checkpoint.
        set_clock("2026-08-01T06:50:00Z")
        run2 = get_success_data(api.run_publication_scheduler(ND))
        assert set(run2["published_story_ids"]) == {sb}
        story_b = get_success_data(api.get_story(sb, ND))
        assert story_b["status"] == "PUBLISHED"


class TestKillRules:
    def test_kill_published_story_rejected(self, api):
        """PRD §3.5: "A `ManagingEditor` may kill a story from any
        pre-publication state — `DRAFT`, `IN_EDIT`, `FACT_CHECK`,
        `LEGAL_REVIEW`, `CLEARED`, `SCHEDULED`, or `ON_HOLD` — moving it to
        `KILLED`; attempting to kill a `PUBLISHED` or `RETRACTED` story is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/story_kill_published_rejected
        """
        ctx, story, _slot = setup_published_story(with_managing_editor=True)
        assert story["status"] == "PUBLISHED"
        resp = api.kill_story(story["id"], ctx["managing_editor_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_story(story["id"], ND))
        assert after["status"] == "PUBLISHED", "no drift on the rejected kill"

    def test_kill_cancels_open_assignments(self, api):
        """PRD §3.5: "The kill cascades: every assignment on the story still
        in `PROPOSED` or `ACCEPTED` moves to `CANCELLED` with each affected
        staff member's `active_assignment_count` recomputed, and if the story
        was `SCHEDULED` its slot's `reserved_count` drops by one and `slot_id`
        clears."

        Design: Corner/state_machines/kill_cancels_open_assignments
        """
        ctx = setup_newsroom(managing_editor=True)
        rep_b = add_staff_to(ctx, "reporter_b", "REPORTER",
                             full_name="Rep B KC", home_desk="SPORTS")
        _pitch, story_id = create_greenlit_story(ctx, title="KC")
        propose_and_accept(ctx, story_id, "reporter")
        propose_assignment(ctx, story_id, rep_b["id"])

        get_success_data(
            api.kill_story(story_id, ctx["managing_editor_headers"]))

        assignments, meta = validate_paginated(
            api.get_story_assignments(story_id, ND))
        assert meta["total_count"] == 2
        assert {a["status"] for a in assignments} == {"CANCELLED"}, \
            "both open assignments were cancelled"
        for key in ("reporter", "reporter_b"):
            staff = get_success_data(api.get_staff(ctx[key]["id"], ND))
            assert staff["active_assignment_count"] == 0


class TestSupersede:
    def test_supersede_link_and_reverse_filter(self, api):
        """PRD §3.5: "Separately, an `AssignmentEditor` may link a `PUBLISHED`
        or `RETRACTED` story to a live follow-up by supplying
        `superseding_story_id`; the target of the link must exist
        (`ERR_STORY_NOT_FOUND`), must differ from the story being linked, and
        must reference a non-terminal story — violations of the latter two
        rules are rejected with `ERR_VALIDATION` (HTTP 400), while attempting
        the link on a story that is neither `PUBLISHED` nor `RETRACTED` yields
        `ERR_INVALID_STATE`."
        PRD §3.5: "The link is recorded in `superseded_by_story_id` and
        increments the story's `version`."
        PRD §3.4: "Stories support list filtering by `status`, `desk`,
        `author_staff_id`, and `superseded_by_story_id`; a story's
        assignments, its review records (filterable by `review_type`), its
        corrections (filterable by `status`), and its analytics reports
        (filterable by `variant`) are each readable as reverse collections,
        with the review and assignment collections restricted to the desk and
        review roles."

        Design: Corner/endpoints/supersede_link_and_reverse_filter
        """
        ctx, old_story, _slot = setup_published_story(urgency="URGENT")
        _pn, new_story_id = create_greenlit_story(
            ctx, title="SX new", deadline_at="2026-08-04T00:00:00Z",
            urgency="URGENT", story_type="DIGITAL")

        resp = api.supersede_story(old_story["id"],
                                   {"superseding_story_id": new_story_id},
                                   ctx["desk_headers"])
        linked = validate_success(resp)
        assert linked["superseded_by_story_id"] == new_story_id

        found, meta = validate_paginated(api.list_stories(
            ctx["desk_headers"],
            params={"superseded_by_story_id": new_story_id}))
        assert meta["total_count"] == 1
        assert found[0]["id"] == old_story["id"]

        # The follow-up is DRAFT: supersede targets only PUBLISHED/RETRACTED.
        resp2 = api.supersede_story(new_story_id,
                                    {"superseding_story_id": old_story["id"]},
                                    ctx["desk_headers"])
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestPerformanceScoring:
    def test_realtime_vs_settled_diverge_on_identical_inputs(self, api):
        """PRD §3.7: "Stage one computes `raw_score`: six points per view plus
        four points per engagement minute, the total divided by 100, rounded
        half-up to two decimal places."
        PRD §3.7: "Stage two derives the `tier` from the raw score alone: `A`
        when the raw score is at least 100, otherwise `B` when it is at least
        40, otherwise `C`."
        PRD §3.7: "For the `SETTLED` variant, the report's `performance_score`
        is the raw score times the tier multiplier, rounded half-up to two
        decimal places."
        PRD §3.7: "For the `REALTIME` variant, an additional dampening applies
        — the raw score times the tier multiplier times 0.9, rounded half-up
        to two decimal places — so identical in-flight measurements score
        lower than their settled counterparts."

        Design: Difficulty/dual_variant_calc/analytics_performance_realtime_vs_settled
        """
        ctx, story, _slot = setup_published_story(
            with_analyst=True, urgency="URGENT",
            deadline_at="2026-08-02T00:00:00Z")
        settled = ingest_analytics(ctx, story["id"], variant="SETTLED",
                                   views=5000, engagement_minutes=300)
        # raw = (5000 x 6 + 300 x 4) / 100 = 312.00 -> tier A -> x 1.25.
        assert settled["raw_score"] == pytest.approx(312.00, abs=0.01)
        assert settled["tier"] == "A"
        assert settled["performance_score"] == pytest.approx(390.00, abs=0.01)

        realtime = ingest_analytics(
            ctx, story["id"], variant="REALTIME",
            window_end="2026-08-02T08:00:00Z", views=5000,
            engagement_minutes=300)
        # round_half_up(312.00 x 1.25 x 0.9, 2) = 351.00
        assert realtime["performance_score"] == pytest.approx(351.00, abs=0.01)
        assert realtime["performance_score"] != settled["performance_score"]

    def test_settled_report_stages_are_pinned(self, api):
        """PRD §3.7: "Scoring follows a pinned three-stage order that breaks
        the apparent circularity between the raw score and the tier."
        PRD §3.7: "Stage three applies the tier multiplier — 1.25 for tier
        `A`, 1.0 for tier `B`, 0.8 for tier `C`."

        Design: Difficulty/dual_variant_calc/analytics_performance_realtime_vs_settled
        """
        ctx, story, _slot = setup_published_story(
            with_analyst=True, urgency="URGENT",
            deadline_at="2026-08-02T00:00:00Z")
        settled = ingest_analytics(ctx, story["id"], variant="SETTLED",
                                   views=5000, engagement_minutes=300)
        assert settled["raw_score"] == pytest.approx(312.00, abs=0.01)
        assert settled["tier"] == "A", "raw >= 100 is tier A"
        assert settled["performance_score"] == pytest.approx(390.00, abs=0.01)
        assert settled["status"] == "ACTIVE"

    def test_performance_tier_boundary(self, api):
        """PRD §3.7: "Stage two derives the `tier` from the raw score alone:
        `A` when the raw score is at least 100, otherwise `B` when it is at
        least 40, otherwise `C`."
        PRD §3.7: "Stage three applies the tier multiplier — 1.25 for tier
        `A`, 1.0 for tier `B`, 0.8 for tier `C`."

        Design: Corner/calculations/performance_tier_boundary
        """
        ctx, story, _slot = setup_published_story(
            with_analyst=True, urgency="URGENT",
            deadline_at="2026-08-02T00:00:00Z")
        # raw exactly 100.00 -> tier A (inclusive floor).
        r1 = ingest_analytics(ctx, story["id"], variant="SETTLED",
                              views=1000, engagement_minutes=1000)
        assert r1["raw_score"] == pytest.approx(100.00, abs=0.01)
        assert r1["tier"] == "A"
        assert r1["performance_score"] == pytest.approx(125.00, abs=0.01)

        # raw 39.94 -> below the B floor of 40 -> tier C.
        r2 = ingest_analytics(ctx, story["id"], variant="SETTLED",
                              window_start="2026-08-02T07:00:00Z",
                              window_end="2026-08-03T07:00:00Z",
                              views=499, engagement_minutes=250)
        assert r2["raw_score"] == pytest.approx(39.94, abs=0.01)
        assert r2["tier"] == "C"
        # round_half_up(39.94 x 0.8, 2) = round_half_up(31.952, 2) = 31.95
        assert r2["performance_score"] == pytest.approx(31.95, abs=0.01)


class TestAnalyticsIngestionRules:
    def test_duplicate_analytics_window(self, api):
        """PRD §3.7: "Measurement windows are unique per story and variant: a
        report already exists for the same story, the same `variant`, and the
        same `window_end`, the ingestion is rejected with
        `ERR_DUPLICATE_ANALYTICS_WINDOW` (HTTP 409)."

        Design: Corner/validations/duplicate_analytics_window
        """
        ctx, story, _slot = setup_published_story(
            with_analyst=True, urgency="URGENT",
            deadline_at="2026-08-02T00:00:00Z")
        ingest_analytics(ctx, story["id"], variant="SETTLED", views=100,
                         engagement_minutes=50)
        payload = create_analytics_report_payload(
            variant="SETTLED", views=200, engagement_minutes=60)
        resp = api.create_story_analytics_report(
            story["id"], payload, ctx["analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ANALYTICS_WINDOW)

    def test_analytics_create_requires_published(self, api):
        """PRD §3.7: "An `AnalyticsProducer` ingests an analytics report for a
        `PUBLISHED` story — ingestion against any other state is rejected with
        `ERR_STORY_NOT_PUBLISHED` — supplying a `variant` of `REALTIME` or
        `SETTLED`, the measurement window `window_start` to `window_end` (end
        strictly after start, else `ERR_INVALID_INTERVAL`), the measured
        `views`, and the measured `engagement_minutes`, both non-negative."

        Design: Corner/endpoints/analytics_create_requires_published
        """
        ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                             legal_reviewer=True, analyst=True)
        _pitch, story_id = create_greenlit_story(
            ctx, deadline_at="2026-08-03T00:00:00Z")
        story = drive_story_to_cleared(ctx, story_id)
        assert story["status"] == "CLEARED"
        resp = api.create_story_analytics_report(
            story_id, create_analytics_report_payload(),
            ctx["analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_STORY_NOT_PUBLISHED)
