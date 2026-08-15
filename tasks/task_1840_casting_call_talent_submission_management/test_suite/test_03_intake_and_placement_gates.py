"""Submission-intake and hold-placement validation gates (PRD sections 2.7,
3.3, 3.4, 3.6)."""
from test_helpers import (
    ApiErrorId,
    create_hold_payload,
    create_self_tape_payload,
    create_submission_payload,
    create_talent,
    set_clock,
    setup_released_breakdown,
    setup_submission,
    submit_talent,
    upload_self_tape,
    validate_error,
    validate_paginated,
    validate_success,
)


def _fresh_version(api, breakdown_id, headers):
    return validate_success(api.get_breakdown(breakdown_id, headers))["version"]


class TestSubmissionIntakeGates:
    def test_submission_after_deadline_returns_deadline_passed(self, api, director_headers, associate_headers):
        """PRD section 3.3: "Then the deadline gate: submissions are accepted only
        while the logical clock is strictly before the breakdown's
        `submission_deadline`, and an attempt at or after that instant is rejected
        with `ERR_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/submission_after_deadline_returns_deadline_passed
        """
        ctx = setup_released_breakdown(
            breakdown_overrides={"submission_deadline": "2026-08-05T00:00:00Z"},
            clock="2026-08-01T00:00:00Z",
        )
        talent = create_talent()
        set_clock("2026-08-06T00:00:00Z")
        version = _fresh_version(api, ctx["breakdown"]["id"], director_headers)
        payload = create_submission_payload(talent["id"], version)
        resp = api.create_submission(ctx["breakdown"]["id"], payload, associate_headers)
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED)

    def test_agent_only_breakdown_rejects_self_submission(self, api, director_headers, associate_headers):
        """PRD section 3.3: "Then the distribution gate: an `AGENT_ONLY` breakdown
        accepts only submissions whose `agent_id` references a `FRANCHISED`,
        active agent profile, while an `OPEN_CALL` breakdown accepts agent and
        self submissions alike; a channel violation is rejected with
        `ERR_CHANNEL_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/agent_only_breakdown_rejects_self_submission
        """
        ctx = setup_released_breakdown(distribution="AGENT_ONLY", clock="2026-08-01T00:00:00Z")
        talent = create_talent()
        version = _fresh_version(api, ctx["breakdown"]["id"], director_headers)
        payload = create_submission_payload(talent["id"], version)  # no agent_id -> self-submission
        resp = api.create_submission(ctx["breakdown"]["id"], payload, associate_headers)
        validate_error(resp, ApiErrorId.ERR_CHANNEL_FORBIDDEN)

    def test_duplicate_submission_auto_rejected_201(self, api, director_headers, associate_headers):
        """PRD section 3.3: "When an earlier submission exists for the same
        `breakdown_id` and `talent_id` in any status other than `REJECTED`,
        `WITHDRAWN`, or `NOT_BOOKED`, the new submission is not turned away with
        an error response: the server persists it with a `201 Created` outcome,
        its status already `REJECTED` without ever having entered `SUBMITTED`,
        and its `duplicate_of_id` pointing at the earlier active submission."

        Design: Corner/endpoints/duplicate_submission_auto_rejected_201
        """
        ctx = setup_submission()
        first_id = ctx["submission"]["id"]
        talent_id = ctx["talent"]["id"]
        version = _fresh_version(api, ctx["breakdown"]["id"], director_headers)
        payload = create_submission_payload(talent_id, version)
        resp = api.create_submission(ctx["breakdown"]["id"], payload, associate_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "REJECTED", "duplicate is persisted already REJECTED"
        assert data.get("duplicate_of_id") == first_id, "duplicate_of_id points at the earlier active submission"

    def test_submissions_reverse_reachable_from_breakdown(self, api, director_headers):
        """PRD section 4: "| GET | `/casting/breakdowns/{id}/submissions` | List
        submissions of a breakdown | CastingDirector, CastingAssociate,
        ProductionCoordinator, Agent |".
        PRD section 2.3: "List-based responses include the following pagination
        fields in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/fk_reverse_reachability_submissions_by_breakdown
        """
        ctx = setup_submission()
        first = ctx["submission"]
        other_talent = create_talent()
        second = submit_talent(ctx["breakdown"]["id"], other_talent["id"])
        resp = api.list_breakdown_submissions(ctx["breakdown"]["id"], director_headers)
        data, meta = validate_paginated(resp)
        ids = {row["id"] for row in data}
        assert first["id"] in ids and second["id"] in ids, "both submissions reverse-reachable from the breakdown"
        assert len(data) == 2 and meta["total_count"] == 2

    def test_stale_breakdown_version_rejected_on_submit(self, api, director_headers, associate_headers):
        """PRD section 2.7: "If the breakdown's current version differs — because
        the breakdown was widened from agent-only to open call, was closed, or
        simply absorbed further submissions since the client rendered its
        submission form — the submission request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and nothing is persisted."

        Design: Corner/cross_cutting_layers/stale_breakdown_version_rejected_on_submit
        """
        ctx = setup_released_breakdown(distribution="AGENT_ONLY", clock="2026-08-01T00:00:00Z")
        stale_version = ctx["breakdown"]["version"]
        # Widening flips RELEASED_AGENT_ONLY -> RELEASED_OPEN and bumps the version.
        validate_success(api.widen_breakdown(ctx["breakdown"]["id"], director_headers))
        talent = create_talent()
        payload = create_submission_payload(talent["id"], stale_version)
        resp = api.create_submission(ctx["breakdown"]["id"], payload, associate_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSelfTapeBounds:
    def test_tape_too_long_error_triggerable(self, api, associate_headers):
        """PRD section 3.4: "a `duration_seconds` giving its length, which must
        exceed zero and must not exceed 600 seconds — a tape outside that bound is
        rejected with `ERR_TAPE_TOO_LONG` (HTTP 422)."

        Design: Corner/errors/tape_too_long_error_triggerable
        """
        ctx = setup_submission()
        resp = api.create_self_tape(
            ctx["submission"]["id"],
            create_self_tape_payload(duration_seconds=601),
            associate_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TAPE_TOO_LONG)


class TestHoldPlacementGates:
    def test_talent_mismatch_beats_inverted_window(self, api, director_headers):
        """PRD section 3.6: "Placement runs two checks in order after reference
        resolution. First, the hold's `talent_id` must equal the referenced
        submission's own `talent_id`; a mismatch is rejected with
        `ERR_HOLD_TALENT_MISMATCH` (HTTP 422). Second, the window must be
        well-formed — `window_start` strictly before `window_end`, and
        `expires_at` strictly after `window_start` — else `ERR_INVALID_WINDOW`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_on_hold_create
        """
        ctx = setup_submission()
        other_talent = create_talent()
        payload = create_hold_payload(
            other_talent["id"],  # mismatches the submission's talent
            window_start="2026-08-23T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",  # inverted window (temporal violation)
            expires_at="2026-08-19T00:00:00Z",
        )
        resp = api.create_hold(ctx["submission"]["id"], payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_HOLD_TALENT_MISMATCH)

    def test_talent_mismatch_beats_bad_expiry(self, api, director_headers):
        """PRD section 3.6: "Placement runs two checks in order after reference
        resolution. First, the hold's `talent_id` must equal the referenced
        submission's own `talent_id`; a mismatch is rejected with
        `ERR_HOLD_TALENT_MISMATCH` (HTTP 422). Second, the window must be
        well-formed — `window_start` strictly before `window_end`, and
        `expires_at` strictly after `window_start` — else `ERR_INVALID_WINDOW`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_on_hold_create
        """
        ctx = setup_submission()
        other_talent = create_talent()
        payload = create_hold_payload(
            other_talent["id"],  # mismatches the submission's talent
            window_start="2026-08-20T00:00:00Z",
            window_end="2026-08-23T00:00:00Z",
            expires_at="2026-08-20T00:00:00Z",  # not strictly after window_start (temporal violation)
        )
        resp = api.create_hold(ctx["submission"]["id"], payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_HOLD_TALENT_MISMATCH)

    def test_inverted_window_alone_returns_invalid_window(self, api, director_headers):
        """PRD section 3.6: "Second, the window must be well-formed —
        `window_start` strictly before `window_end`, and `expires_at` strictly
        after `window_start` — else `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/hold_invalid_window_returns_invalid_window
        """
        ctx = setup_submission()
        payload = create_hold_payload(
            ctx["talent"]["id"],  # matches, so the referential check passes
            window_start="2026-08-23T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            expires_at="2026-08-19T00:00:00Z",
        )
        resp = api.create_hold(ctx["submission"]["id"], payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
