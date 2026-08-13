"""Survey windows: participation threshold branch, boundary, close endpoint,
duplicate window, role exclusivity (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_survey_window_payload,
    get_success_data,
    set_clock,
    setup_open_survey_window,
    setup_self_study_term,
    submit_responses,
    validate_error,
    validate_success,
    create_instrument_payload,
)


class TestThresholdBranch:
    def test_under_subscribed_manual_close_invalidates(self, api, officer_headers):
        """PRD §3.4: "The comparison is performed in integer space: the window
        passes if `response_count` multiplied by 100 is greater than or equal to
        `min_participation_pct` multiplied by `eligible_count`, in which case it
        lands in `CLOSED`; if the product of responses and 100 is strictly less
        than the threshold product, the window fails and lands in `INVALIDATED`
        instead."
        PRD §3.4: "An officer may also close an `OPEN` window manually, provided
        the current time has reached `opens_at`; the same participation
        threshold check applies on manual close, so an under-subscribed window
        is forced to `INVALIDATED` exactly as on auto-close rather than landing
        in `CLOSED`."

        Design: Difficulty/non_linear_state_machine/survey_window_threshold_branch_invalidate_vs_close
        """
        ctx, instrument, window = setup_open_survey_window(
            min_participation_pct=67, eligible_count=3,
            stakeholder_group="PARENTS", title="Parent Survey")
        submit_responses(window["id"], ["tok-low-01", "tok-low-02"])

        closed = validate_success(api.close_survey_window(window["id"],
                                                          officer_headers))
        # 2*100 = 200 < 67*3 = 201 -> below threshold -> INVALIDATED, not CLOSED
        assert closed["status"] == "INVALIDATED"
        assert closed["response_count"] == 2

    def test_under_subscribed_auto_close_invalidates(self, api, officer_headers):
        """PRD §2.8: "an `OPEN` window whose `closes_at` has been reached closes
        (or invalidates — see §3.4)".
        PRD §3.4: "if the product of responses and 100 is strictly less than the
        threshold product, the window fails and lands in `INVALIDATED` instead."

        Design: Difficulty/non_linear_state_machine/survey_window_threshold_branch_invalidate_vs_close
        """
        ctx, instrument, window = setup_open_survey_window(
            min_participation_pct=67, eligible_count=3,
            stakeholder_group="PARENTS", title="Parent Survey")
        submit_responses(window["id"], ["tok-low-01", "tok-low-02"])

        set_clock("2026-11-01T00:00:00Z")  # reaches closes_at -> auto close
        after = get_success_data(api.get_survey_window(window["id"], officer_headers))
        assert after["status"] == "INVALIDATED"
        assert after["response_count"] == 2


class TestThresholdExactEquality:
    def test_exact_threshold_manual_close_lands_closed(self, api, officer_headers):
        """PRD §3.4: "The comparison is performed in integer space: the window
        passes if `response_count` multiplied by 100 is greater than or equal to
        `min_participation_pct` multiplied by `eligible_count`, in which case it
        lands in `CLOSED`".

        Design: Difficulty/boundary_precision_check/survey_threshold_exact_equality_passes
        """
        ctx, instrument, window = setup_open_survey_window(
            min_participation_pct=50, eligible_count=4,
            stakeholder_group="STUDENTS", title="Student Survey")
        submit_responses(window["id"], ["tok-eq-01", "tok-eq-02"])

        closed = validate_success(api.close_survey_window(window["id"],
                                                          officer_headers))
        # 2*100 = 200 >= 50*4 = 200 -> equality passes -> CLOSED
        assert closed["status"] == "CLOSED"
        assert closed["response_count"] == 2

    def test_exact_threshold_auto_close_lands_closed(self, api, officer_headers):
        """PRD §3.4: "The comparison is performed in integer space: the window
        passes if `response_count` multiplied by 100 is greater than or equal to
        `min_participation_pct` multiplied by `eligible_count`, in which case it
        lands in `CLOSED`".
        PRD §2.8: "an `OPEN` window whose `closes_at` has been reached closes
        (or invalidates — see §3.4)".

        Design: Difficulty/boundary_precision_check/survey_threshold_exact_equality_passes
        """
        ctx, instrument, window = setup_open_survey_window(
            min_participation_pct=50, eligible_count=4,
            stakeholder_group="STUDENTS", title="Student Survey")
        submit_responses(window["id"], ["tok-eq-01", "tok-eq-02"])

        set_clock("2026-11-01T00:00:00Z")
        after = get_success_data(api.get_survey_window(window["id"], officer_headers))
        assert after["status"] == "CLOSED"
        assert after["response_count"] == 2


class TestCloseEndpointTransition:
    def test_close_endpoint_transitions_open_window_to_closed(
            self, api, officer_headers):
        """PRD §3.4: "An officer may also close an `OPEN` window manually,
        provided the current time has reached `opens_at`; the same participation
        threshold check applies on manual close, so an under-subscribed window
        is forced to `INVALIDATED` exactly as on auto-close rather than landing
        in `CLOSED`."
        PRD §3.4: "A successful submission creates the `SurveyResponse` stamped
        with the server's `submitted_at`, increments the window's
        `response_count` by 1, and increments the window's `version`."

        Design: Corner/endpoints/action_endpoint_close_window_transition
        """
        ctx, instrument, window = setup_open_survey_window(
            min_participation_pct=50, eligible_count=4,
            stakeholder_group="STAFF", title="Staff Survey")
        submit_responses(window["id"], ["tok-ep-1", "tok-ep-2"])

        closed = validate_success(api.close_survey_window(window["id"],
                                                          officer_headers))
        assert closed["status"] == "CLOSED"
        assert closed["response_count"] == 2


class TestDuplicateWindow:
    def test_duplicate_window_per_term_campus_instrument_rejected(
            self, api, officer_headers):
        """PRD §3.4: "only one window may exist per (term, campus, instrument)
        combination; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/errors/error_duplicate_survey_window
        """
        ctx = setup_self_study_term(system_name="DupWin County",
                                    system_type="DISTRICT",
                                    campuses=[("North Campus", 500)])
        instrument = get_success_data(api.create_survey_instrument(
            create_instrument_payload(stakeholder_group="STAFF",
                                      title="Staff Survey",
                                      min_participation_pct=50),
            officer_headers))
        first = create_survey_window_payload(
            ctx["campuses"][0]["id"], instrument["id"],
            opens_at="2026-10-01T00:00:00Z", closes_at="2026-11-01T00:00:00Z",
            eligible_count=4)
        validate_success(api.create_survey_window(ctx["term"]["id"], first,
                                                  officer_headers),
                         expected_status=201)
        second = create_survey_window_payload(
            ctx["campuses"][0]["id"], instrument["id"],
            opens_at="2026-11-02T00:00:00Z", closes_at="2026-12-01T00:00:00Z",
            eligible_count=4)
        resp = api.create_survey_window(ctx["term"]["id"], second, officer_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


class TestAnonymousOnlyEndpoint:
    def test_officer_cannot_submit_survey_response(self, api, officer_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.4: "An unauthenticated caller — role `Anonymous` — submits a
        response to a window with a one-time `respondent_token`".

        Design: Corner/rbac/anonymous_only_survey_response
        """
        ctx, instrument, window = setup_open_survey_window(
            min_participation_pct=50, eligible_count=4)
        resp = api.submit_survey_response(window["id"],
                                          {"respondent_token": "tok-officer"},
                                          officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
