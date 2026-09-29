"""The two independent state dimensions of a visit, and the capped resubmission loop
on the authorization row that feeds one of them."""

import pytest

from test_helpers import (
    AUTH_SPECIALIST,
    ApiClient,
    ApiErrorId,
    assert_instant_equals,
    AuthStatus,
    LabResultStatus,
    ReadinessStatus,
    ScheduleStatus,
    check_in_visit,
    confirm_visit,
    file_authorization,
    file_lab_result,
    make_nurse_headers,
    make_pend_decision_payload,
    read_appointment,
    read_authorization,
    read_lab_result,
    set_clock,
    setup_approved_authorization,
    setup_booked_visit,
    submit_authorization,
    validate_error,
    validate_success,
)


class TestReadinessFallsBackWhileScheduleAdvances:
    """A draw that ages out drives readiness backwards; the schedule keeps walking."""

    def _visit_with_ageing_draw(self, api: ApiClient):
        """A confirmed, fully cleared visit whose only resulted draw is 48 hours old
        at the moment of confirmation."""
        suite, appointment = setup_booked_visit(
            api,
            clock="2026-08-09T07:00:00Z",
            service_date="2026-08-10",
            requested_start_minute=540,
            drug_kind="gate",
        )
        lab = file_lab_result(
            api,
            suite.patient_id,
            collected_at="2026-08-07T07:00:00Z",
            anc_value=2.0,
            platelet_value=150,
        )
        auth = setup_approved_authorization(api, appointment["id"])
        confirmed = confirm_visit(api, appointment["id"])
        return suite, confirmed, lab, auth

    def test_moving_the_clock_alone_walks_readiness_back_without_a_version_bump(self, api):
        """A clock move mutates nothing, so once every resulted draw is older than the
        centre's validity window the visit simply reads AUTH_CLEARED on its next read.

        Design: Difficulty/non_linear_state_machine/readiness_reverts_to_auth_cleared_while_schedule_advances_to_checked_in
        """
        _suite, confirmed, _lab, _auth = self._visit_with_ageing_draw(api)

        assert confirmed["schedule_status"] == ScheduleStatus.CONFIRMED
        assert confirmed["readiness_status"] == ReadinessStatus.FULLY_CLEARED
        version_before = confirmed["version"]

        set_clock(api, "2026-08-10T08:00:00Z")

        aged = read_appointment(api, confirmed["id"])
        assert aged["readiness_status"] == ReadinessStatus.AUTH_CLEARED
        assert aged["version"] == version_before
        assert aged["schedule_status"] == ScheduleStatus.CONFIRMED

    def test_check_in_advances_the_schedule_dimension_over_a_lapsed_draw(self, api):
        """Neither dimension is a substate of the other: check-in names an approval and a
        calendar date among its bars, never the laboratory term, so it succeeds while
        readiness sits at AUTH_CLEARED.

        Design: Difficulty/non_linear_state_machine/readiness_reverts_to_auth_cleared_while_schedule_advances_to_checked_in
        """
        _suite, confirmed, _lab, _auth = self._visit_with_ageing_draw(api)
        set_clock(api, "2026-08-10T08:00:00Z")

        seated = check_in_visit(api, confirmed["id"])

        assert seated["schedule_status"] == ScheduleStatus.CHECKED_IN
        assert seated["readiness_status"] == ReadinessStatus.AUTH_CLEARED
        assert seated["version"] == confirmed["version"] + 1

    def test_start_infusion_is_the_moment_the_stale_draw_surfaces(self, api):
        """The lab gate is evaluated when the infusion is about to start, and a draw
        older than the validity window fails it.

        Design: Difficulty/non_linear_state_machine/readiness_reverts_to_auth_cleared_while_schedule_advances_to_checked_in
        """
        suite, confirmed, _lab, _auth = self._visit_with_ageing_draw(api)
        set_clock(api, "2026-08-10T08:00:00Z")
        check_in_visit(api, confirmed["id"])

        response = api.start_infusion(
            confirmed["id"], make_nurse_headers(suite.nurse_id)
        )

        validate_error(response, ApiErrorId.ERR_LAB_RESULT_STALE, 422)

        row = read_appointment(api, confirmed["id"])
        assert row["schedule_status"] == ScheduleStatus.CHECKED_IN
        assert row["actual_start_minute"] is None
        assert row["readiness_status"] == ReadinessStatus.AUTH_CLEARED

    def test_the_refusal_leaves_the_approval_and_the_draw_exactly_as_they_were(self, api):
        """The approval keeps clearing its half of the derivation because expires_at is
        not part of the authorization condition, and a draw is immutable.

        Design: Difficulty/non_linear_state_machine/readiness_reverts_to_auth_cleared_while_schedule_advances_to_checked_in
        """
        suite, confirmed, lab, auth = self._visit_with_ageing_draw(api)
        set_clock(api, "2026-08-10T08:00:00Z")
        check_in_visit(api, confirmed["id"])
        api.start_infusion(confirmed["id"], make_nurse_headers(suite.nurse_id))

        coverage = read_authorization(api, auth["id"])
        assert coverage["status"] == AuthStatus.APPROVED
        assert_instant_equals(coverage["expires_at"], "2026-09-08T07:00:00Z")

        draw = read_lab_result(api, lab["id"])
        assert draw["status"] == LabResultStatus.RESULTED
        assert_instant_equals(draw["collected_at"], "2026-08-07T07:00:00Z")
        assert draw["anc_value"] == pytest.approx(2.0, abs=0.005)
        assert draw["platelet_value"] == pytest.approx(150, abs=0.005)


class TestPendedResubmissionCycleIsCapped:
    """DRAFT to SUBMITTED to PENDED to SUBMITTED is a real cycle with a hard stop."""

    def _thrice_pended(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock="2026-08-05T07:00:00Z",
            service_date="2026-08-10",
            requested_start_minute=540,
            drug_kind="gate",
            drug_overrides={
                "requires_lab_gate": False,
                "lab_min_anc": None,
                "lab_min_platelets": None,
            },
        )
        auth = file_authorization(api, appointment["id"])
        for reason in (
            "Chart notes requested",
            "Prior therapy documentation requested",
            "Peer-to-peer review requested",
        ):
            submit_authorization(api, auth["id"])
            validate_success(
                api.decide_authorization(
                    auth["id"], make_pend_decision_payload(reason), AUTH_SPECIALIST
                ),
                200,
            )
        return suite, appointment, auth

    def test_the_counter_climbs_once_per_submission_around_the_loop(self, api):
        """Each submission increases submission_count by one, and a pended request is
        back in the resubmission loop rather than terminal.

        Design: Difficulty/non_linear_state_machine/authorization_pended_resubmission_cycle_capped_at_three_submissions
        """
        _suite, _appointment, auth = self._thrice_pended(api)

        row = read_authorization(api, auth["id"])
        assert row["status"] == AuthStatus.PENDED
        assert row["submission_count"] == 3
        assert row["expires_at"] is None

    def test_the_fourth_submission_is_refused_by_the_cap(self, api):
        """submission_count must be below 3 for a submission to be accepted, so the
        fourth attempt around the cycle is refused.

        Design: Difficulty/non_linear_state_machine/authorization_pended_resubmission_cycle_capped_at_three_submissions
        """
        _suite, _appointment, auth = self._thrice_pended(api)

        response = api.submit_authorization(auth["id"], AUTH_SPECIALIST)

        validate_error(response, ApiErrorId.ERR_AUTH_RESUBMIT_LIMIT, 409)

    def test_the_capped_attempt_mutates_neither_the_request_nor_the_visit(self, api):
        """A refused submission leaves the request in PENDED with its counter unmoved,
        and the visit it covers never becomes cleared or committed.

        Design: Difficulty/non_linear_state_machine/authorization_pended_resubmission_cycle_capped_at_three_submissions
        """
        _suite, appointment, auth = self._thrice_pended(api)
        before = read_authorization(api, auth["id"])

        api.submit_authorization(auth["id"], AUTH_SPECIALIST)

        after = read_authorization(api, auth["id"])
        assert after["status"] == AuthStatus.PENDED
        assert after["submission_count"] == 3
        assert after["version"] == before["version"]

        visit = read_appointment(api, appointment["id"])
        assert visit["schedule_status"] == ScheduleStatus.TENTATIVE
