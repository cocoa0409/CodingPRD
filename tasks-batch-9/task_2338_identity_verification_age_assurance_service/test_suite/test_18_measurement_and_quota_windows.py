"""Interval semantics: half-open audit windows and the closed rolling quota window."""
from test_helpers import (
    OFFICER,
    create_bias_audit_payload,
    create_verification_session_payload,
    list_profile_audits,
    make_client_integrator_headers,
    open_bias_audit,
    open_session,
    register_method_profile,
    set_clock,
    setup_client_with_published_policy,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_WINDOW = ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
ADJACENT_WINDOW = ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
CONTAINED_WINDOW = ("2026-07-15T00:00:00Z", "2026-07-20T00:00:00Z")


def _profile_with_two_adjacent_live_audit_windows(api):
    """A profile carrying two touching measurement windows, both still live."""
    profile = register_method_profile("KNOWLEDGE_BASED")
    first = open_bias_audit(profile["id"], *FIRST_WINDOW)
    second = validate_success(
        api.create_bias_audit(create_bias_audit_payload(profile["id"], *ADJACENT_WINDOW), OFFICER),
        201,
    )
    return profile, first, second


class TestAuditWindowsAreHalfOpenIntervals:
    def test_a_window_starting_where_the_previous_one_ends_is_admitted(self, api):
        """PRD §3.9: "A **BiasAudit** is opened against a `method_profile_id` with a measurement
        window bounded by an inclusive `window_start` and an exclusive `window_end` that must be
        strictly later than the start." "Because windows are half-open, an audit that begins exactly
        at another's `window_end` is admissible."

        Design: Difficulty/resource_temporal_overlap/bias_audit_windows_half_open_adjacency_admitted_containment_rejected
        """
        _, first, second = _profile_with_two_adjacent_live_audit_windows(api)

        assert first["state"] == "COLLECTING"
        assert second["state"] == "COLLECTING"
        assert second["window_start"].startswith("2026-07-01T00:00:00")

    def test_a_window_strictly_inside_a_live_window_is_refused_as_an_overlap(self, api):
        """PRD §3.9: "Windows on the same profile may not overlap while another audit on that
        profile is still live — that is, while it sits in `COLLECTING`, `EVALUATED` or
        `REMEDIATION_REQUIRED` — and an overlap is rejected with `ERR_AUDIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/bias_audit_windows_half_open_adjacency_admitted_containment_rejected
        """
        profile, _, _ = _profile_with_two_adjacent_live_audit_windows(api)
        validate_error(
            api.create_bias_audit(
                create_bias_audit_payload(profile["id"], *CONTAINED_WINDOW), OFFICER
            ),
            "ERR_AUDIT_WINDOW_OVERLAP",
            409,
        )

    def test_the_refused_window_leaves_exactly_the_two_admitted_audits_on_file(self, api):
        """PRD §3.9: "an overlap is rejected with `ERR_AUDIT_WINDOW_OVERLAP`." PRD §2.9: "reverse
        navigation is offered through filtered list endpoints and through read-only sub-resource
        collections such as the captures of one attempt or the audit trail of one session."

        Design: Difficulty/resource_temporal_overlap/bias_audit_windows_half_open_adjacency_admitted_containment_rejected
        """
        profile, first, second = _profile_with_two_adjacent_live_audit_windows(api)
        validate_error(
            api.create_bias_audit(
                create_bias_audit_payload(profile["id"], *CONTAINED_WINDOW), OFFICER
            ),
            "ERR_AUDIT_WINDOW_OVERLAP",
        )

        audits, meta = list_profile_audits(profile["id"])
        assert meta["total_count"] == 2
        assert {audit["id"] for audit in audits} == {first["id"], second["id"]}


def _client_holding_two_sessions_a_day_apart():
    """A client with capacity 2 whose first session sits exactly at the window edge."""
    set_clock("2026-08-10T09:00:00Z")
    env = setup_client_with_published_policy(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"daily_session_quota": 2, "granted_review_credits": 1},
        policy_overrides={"min_assurance_score": 60, "required_min_age_years": 0},
    )
    client_id = env["client"]["id"]
    env["first_session"] = open_session(
        client_id, external_subject_ref="subj-q1", requested_assurance_tier="BASIC"
    )
    set_clock("2026-08-11T09:00:00Z")
    env["second_session"] = open_session(
        client_id, external_subject_ref="subj-q2", requested_assurance_tier="BASIC"
    )
    return env


def _open_extra_session(api, client_id, external_subject_ref):
    return api.create_verification_session(
        create_verification_session_payload(
            client_id,
            external_subject_ref=external_subject_ref,
            requested_assurance_tier="BASIC",
        ),
        make_client_integrator_headers(client_id),
    )


class TestRollingQuotaWindowIsClosedAtBothEnds:
    def test_a_session_exactly_twenty_four_hours_old_still_consumes_capacity(self, api):
        """PRD §3.2: "The window spans the twenty-four hours ending at the current clock instant and
        is inclusive at both ends, so a session created exactly twenty-four hours before the clock
        still counts against the quota while advancing the clock one further second drops it out and
        frees capacity." "If usage has already reached `daily_session_quota`, the request is rejected
        with `ERR_CLIENT_DAILY_QUOTA_EXCEEDED`".

        Design: Difficulty/resource_temporal_overlap/client_rolling_quota_window_closed_at_both_ends_with_aggregate_capacity
        """
        env = _client_holding_two_sessions_a_day_apart()
        validate_error(
            _open_extra_session(api, env["client"]["id"], "subj-q3"),
            "ERR_CLIENT_DAILY_QUOTA_EXCEEDED",
            409,
        )

    def test_one_second_later_the_oldest_session_drops_out_and_frees_capacity(self, api):
        """PRD §3.2: "Usage is the number of that client's sessions whose `created_at` falls inside
        the window, counted regardless of their identity axis — expired and rejected sessions count
        exactly as verified ones do." "If usage has already reached `daily_session_quota`, the
        request is rejected with `ERR_CLIENT_DAILY_QUOTA_EXCEEDED`; otherwise the session is
        created."

        Design: Difficulty/resource_temporal_overlap/client_rolling_quota_window_closed_at_both_ends_with_aggregate_capacity
        """
        env = _client_holding_two_sessions_a_day_apart()
        validate_error(
            _open_extra_session(api, env["client"]["id"], "subj-q3"),
            "ERR_CLIENT_DAILY_QUOTA_EXCEEDED",
        )

        set_clock("2026-08-11T09:00:01Z")
        admitted = validate_success(
            _open_extra_session(api, env["client"]["id"], "subj-q4"), 201
        )
        assert admitted["expires_at"].startswith("2026-08-11T10:00:01")

    def test_each_admitted_session_expires_sixty_minutes_after_its_own_creation(self, api):
        """PRD §3.2: "`expires_at` is set to the session's `created_at` plus sixty minutes on the
        logical clock."

        Design: Difficulty/resource_temporal_overlap/client_rolling_quota_window_closed_at_both_ends_with_aggregate_capacity
        """
        env = _client_holding_two_sessions_a_day_apart()

        assert env["first_session"]["expires_at"].startswith("2026-08-10T10:00:00")
        assert env["second_session"]["expires_at"].startswith("2026-08-11T10:00:00")

    def test_the_refused_creation_leaves_no_session_row_behind(self, api):
        """PRD §3.2: "If usage has already reached `daily_session_quota`, the request is rejected
        with `ERR_CLIENT_DAILY_QUOTA_EXCEEDED`; otherwise the session is created."

        Design: Difficulty/resource_temporal_overlap/client_rolling_quota_window_closed_at_both_ends_with_aggregate_capacity
        """
        env = _client_holding_two_sessions_a_day_apart()
        client_id = env["client"]["id"]
        validate_error(
            _open_extra_session(api, client_id, "subj-q3"), "ERR_CLIENT_DAILY_QUOTA_EXCEEDED"
        )
        set_clock("2026-08-11T09:00:01Z")
        validate_success(_open_extra_session(api, client_id, "subj-q4"), 201)

        sessions, meta = validate_paginated(
            api.list_verification_sessions(
                make_client_integrator_headers(client_id),
                params={"client_id": client_id, "limit": 100},
            )
        )
        assert meta["total_count"] == 3
        assert "subj-q3" not in {session["external_subject_ref"] for session in sessions}
