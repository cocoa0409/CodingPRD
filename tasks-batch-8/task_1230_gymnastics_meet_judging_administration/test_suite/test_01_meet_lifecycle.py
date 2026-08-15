"""Meet lifecycle: creation defaults, retrieval, pagination, session window,
posture/state gating on session close, terminal lockdown, session-close OCC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_meet,
    assert_session,
    create_credentialed_coach,
    create_meet,
    create_meet_payload,
    create_session_payload,
    get_success_data,
    make_coach_headers,
    set_clock,
    setup_archived_meet,
    setup_closed_session,
    setup_meet_with_session,
    setup_competition_ready,
    run_rotations_with_scores,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestMeetCreationAndRetrieval:
    def test_meet_creation_with_declared_defaults(self, api, meet_director_headers):
        """PRD §3.1: "Four policy knobs may be set at creation: `tiebreak_policy`, either
        `USAG_CLASSIC` or `NCAA_MODIFIED`, defaulting to `USAG_CLASSIC`; `qualifying_score_rule`,
        one of `ALL_AROUND_ONLY`, `PER_EVENT`, or `BOTH`, defaulting to `BOTH`;
        `inquiry_window_minutes`, the minutes after a score's publication during which a coach
        may file an inquiry, defaulting to 5; and `max_athletes_per_squad`, the squad size cap,
        defaulting to 12. A new meet rests in `DRAFT` posture."

        Design: Corner/entities/meet_creation_with_defaults
        """
        set_clock()
        meet = validate_success(api.create_meet(create_meet_payload(), meet_director_headers), 201)
        assert_meet(meet)
        assert meet["tiebreak_policy"] == "USAG_CLASSIC"
        assert meet["qualifying_score_rule"] == "BOTH"
        assert meet["inquiry_window_minutes"] == 5
        assert meet["max_athletes_per_squad"] == 12
        assert meet["posture"] == "DRAFT"

    def test_meet_not_found_returns_404(self, api, meet_director_headers):
        """PRD §2.9: "then the existence of every path-templated resource identifier validated
        left to right (`ERR_RESOURCE_NOT_FOUND`, HTTP 404)".

        Design: Corner/entities/meet_not_found_404
        """
        set_clock()
        res = api.get_meet(NON_EXISTENT_UUID, meet_director_headers)
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_meet_list_pagination_envelope(self, api, meet_director_headers):
        """PRD §2.3: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/meet_list_pagination
        """
        set_clock()
        for _ in range(3):
            validate_success(api.create_meet(create_meet_payload(), meet_director_headers), 201)
        res = api.list_meets(meet_director_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        assert len(data) == 2, f"expected 2 items with limit=2, got {len(data)}"
        assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestSessionWindow:
    def test_session_outside_meet_window_rejected(self, api, meet_director_headers):
        """PRD §3.1: "The session's window must sit inside the meet's: `scheduled_start` no
        earlier than the meet's `start_date`, and `scheduled_end` later than `scheduled_start`
        but no later than the meet's `end_date` plus a two-hour overflow buffer — a session
        declared outside that window, whether at creation or by a later update, is rejected
        with `ERR_SESSION_OUTSIDE_MEET_WINDOW`."

        Design: Corner/validations/session_outside_meet_window
        """
        ctx = setup_meet_with_session()
        meet_id = ctx["meet"]["id"]
        assert ctx["session"]["state"] == "SCHEDULED"
        # Boundary satisfaction: end_date + 2h exactly is permitted.
        ok = api.create_session(meet_id, create_session_payload(
            session_label="Edge OK", scheduled_start="2026-05-02T20:00:00Z",
            scheduled_end="2026-05-03T00:00:00Z"), meet_director_headers)
        validate_success(ok, 201)
        # One hour past the overflow buffer is rejected.
        late = api.create_session(meet_id, create_session_payload(
            session_label="Too Late", scheduled_start="2026-05-02T14:00:00Z",
            scheduled_end="2026-05-03T02:00:00Z"), meet_director_headers)
        validate_error(late, ApiErrorId.ERR_SESSION_OUTSIDE_MEET_WINDOW)


class TestSessionCloseStateGate:
    def test_close_session_from_scheduled_rejected(self, api, meet_director_headers):
        """PRD §3.7: "When a session has reached `SCORING` — all four rotations closed or
        finalized — the meet director closes it, an OCC-guarded write carrying
        `expected_session_version` per §2.8."
        PRD §2.9: "Only then do state gates apply: first the parent meet's posture
        (`ERR_MEET_POSTURE_FORBIDS`), then the entity-specific state precondition of the
        requested transition (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/meet_posture_vs_invalid_state_conflict
        """
        ctx = setup_meet_with_session()
        session = ctx["session"]
        assert session["state"] == "SCHEDULED"
        res = api.close_session(session["id"],
                                {"expected_session_version": session["version"]},
                                meet_director_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_session(session["id"], meet_director_headers))
        assert after["state"] == "SCHEDULED", "failed close must not transition the session"
        assert after["version"] == session["version"], "failed close must not bump version"

    def test_close_session_from_scoring_succeeds(self, api, meet_director_headers):
        """PRD §3.7: "Closure requires that every score linked to entries in the session is
        `FINAL` or `VOID` and that no inquiry on any such score remains `FILED` or
        `UNDER_REVIEW`. The close stamps the session's `closed_at`, runs the award-ordering
        computation for the session, runs the qualification evaluation for each of its
        entries, and bubbles up to re-evaluate the parent meet's posture."

        Design: Difficulty/priority_pair_validation_conflict/meet_posture_vs_invalid_state_conflict
        """
        ctx = setup_closed_session(num_athletes=1)
        closed = ctx["session"]
        assert_session(closed)
        assert closed["state"] == "CLOSED"
        assert closed.get("closed_at"), "closed_at must be stamped at close"


class TestTerminalMeetLockdown:
    def test_archived_meet_rejects_further_transitions(self, api, meet_director_headers):
        """PRD §2.6: "A mutation attempted against an entity that has already reached a
        terminal state of its lifecycle is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)."
        PRD §3.1: "A `FINALIZED` meet can finally be archived, reaching the terminal posture
        `ARCHIVED`."

        Design: Corner/state_machines/terminal_archived_meet_no_transitions
        """
        ctx = setup_archived_meet()
        meet = ctx["meet"]
        assert meet["posture"] == "ARCHIVED"
        for trigger in (api.publish_meet, api.close_meet_scoring,
                        api.finalize_meet, api.archive_meet):
            res = trigger(meet["id"], meet_director_headers)
            assert res.status_code == 409, (
                f"expected 409 on archived meet, got {res.status_code}: {res.text}")
            validate_error_is_one_of(
                res, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE])
        after = get_success_data(api.get_meet(meet["id"], meet_director_headers))
        assert after["posture"] == "ARCHIVED"


class TestSessionCloseOcc:
    def test_close_session_with_stale_version_rejected(self, api, meet_director_headers):
        """PRD §2.8: "Closing a session requires `expected_session_version`, the session's
        `version` as last observed by the meet director. A late score finalization or rotation
        close advances the session's version, so a close request carrying the older version is
        rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_session_version_occ
        """
        # Session reaches SCORING (all rotations finalized) but is not yet closed.
        ctx = setup_competition_ready(num_athletes=1)
        run_rotations_with_scores(ctx, lambda i, a: (5.0, 8.0, 0.0))
        fresh = get_success_data(api.get_session(ctx["session"]["id"], meet_director_headers))
        assert fresh["state"] == "SCORING", (
            f"setup should leave the session in SCORING, got {fresh['state']}")
        res = api.close_session(fresh["id"],
                                {"expected_session_version": fresh["version"] - 1},
                                meet_director_headers)
        validate_error(res, ApiErrorId.ERR_STALE_SESSION_VERSION)
        after = get_success_data(api.get_session(fresh["id"], meet_director_headers))
        assert after["state"] == "SCORING", "stale close must not transition the session"


class TestMeetPublishRbac:
    def test_coach_cannot_publish_meet(self, api, meet_director_headers):
        """PRD §2.1: "Once authenticated, the acting role must be permitted to invoke the
        target endpoint; otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403).""
        PRD §4: `POST /api/v1/meets/{id}/publish` is authorized for MeetDirector only.

        Design: Corner/rbac/coach_cannot_publish_meet
        """
        set_clock()
        meet = create_meet()
        coach = create_credentialed_coach()
        res = api.publish_meet(meet["id"], make_coach_headers(coach["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_meet(meet["id"], meet_director_headers))
        assert after["posture"] == "DRAFT", "denied publish must not transition the meet"
