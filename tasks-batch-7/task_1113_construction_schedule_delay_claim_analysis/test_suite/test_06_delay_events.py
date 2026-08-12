"""Delay events: notice timeliness against the contract notice window and
role exclusivity of TIA adjudication (PRD §2.1, §3.5)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_project,
    create_delay_event,
    set_clock,
)


def _noticed_event_at(notice_instant, event_start_date, notice_window_days=21,
                      causation="OWNER_CAUSED"):
    """Create a project and a delay event, pin the clock, then lodge notice."""
    project = create_project(notice_window_days=notice_window_days)
    event = create_delay_event(
        project["id"],
        causation=causation,
        event_start_date=event_start_date,
    )
    set_clock(notice_instant)
    return project["id"], event["id"]


class TestNoticeWindowBoundary:
    def test_notice_window_exactly_at_21_days(self, api, contractor_headers):
        """PRD §3.5: "notice is within the window when it is lodged no earlier than
        the `event_start_date` and no later than that date plus the project's
        `notice_window_days` — equivalently, when the elapsed calendar days from
        event start to notice do not exceed the window."

        Design: Difficulty/boundary_precision_check/notice_window_exactly_at_21_days
        """
        # 2026-05-22 is exactly 21 calendar days after 2026-05-01: the boundary is
        # inclusive ("do not exceed"), so notice is within the window.
        pid, did = _noticed_event_at("2026-05-22T00:00:00Z", "2026-05-01T00:00:00Z")
        resp = api.notice_delay_event(pid, did, contractor_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "NOTICED"
        assert data["notice_within_window"] is True, (
            "notice lodged exactly notice_window_days after event start is within the window"
        )

    def test_notice_one_day_beyond_window_is_late_but_succeeds(
        self, api, contractor_headers
    ):
        """PRD §3.5: "when the elapsed calendar days from event start to notice do
        not exceed the window" the notice is within it; and "Late notice never
        fails the step; instead, when notice is late for an `OWNER_CAUSED` or
        `THIRD_PARTY` event, the time component of the claim is flagged as forfeit
        while the cost component may still be evaluated."

        Design: Difficulty/boundary_precision_check/notice_window_exactly_at_21_days
        """
        # 2026-05-23 is 22 calendar days after 2026-05-01: beyond the 21-day window.
        pid, did = _noticed_event_at("2026-05-23T00:00:00Z", "2026-05-01T00:00:00Z")
        resp = api.notice_delay_event(pid, did, contractor_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "NOTICED", "late notice must not fail the step"
        assert data["notice_within_window"] is False


class TestNoticeWindowMultifactor:
    def test_notice_twenty_days_after_event_start_is_within_window(
        self, api, contractor_headers
    ):
        """PRD §3.5: "notice is within the window when it is lodged no earlier than
        the `event_start_date` and no later than that date plus the project's
        `notice_window_days` — equivalently, when the elapsed calendar days from
        event start to notice do not exceed the window."

        Design: Difficulty/combinatorial_formula/concurrent_delay_apportionment_multifactor_mode_a
        """
        # 2026-05-25 is 20 calendar days after 2026-05-05: inside 21 days.
        pid, did = _noticed_event_at(
            "2026-05-25T00:00:00Z",
            "2026-05-05T00:00:00Z",
        )
        resp = api.notice_delay_event(pid, did, contractor_headers)
        data = validate_success(resp, expected_status=200)
        assert data["notice_within_window"] is True

    def test_late_notice_marks_event_outside_window_without_failing(
        self, api, contractor_headers
    ):
        """PRD §3.5: "Late notice never fails the step; instead, when notice is late
        for an `OWNER_CAUSED` or `THIRD_PARTY` event, the time component of the claim
        is flagged as forfeit while the cost component may still be evaluated."

        Design: Difficulty/combinatorial_formula/concurrent_delay_apportionment_multifactor_mode_a
        """
        # 2026-06-10 is 36 calendar days after 2026-05-05: well past 21 days.
        pid, did = _noticed_event_at("2026-06-10T00:00:00Z", "2026-05-05T00:00:00Z")
        resp = api.notice_delay_event(pid, did, contractor_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "NOTICED", "late notice must still succeed"
        assert data["notice_within_window"] is False


class TestTiaAdjudicationRoles:
    def test_insufficient_permissions_for_tia_accept_by_contractor(
        self, api, contractor_headers
    ):
        """PRD §2.1: "A `ClaimsConsultant` is an independent scheduler who accepts or
        rejects time impact analyses." and "A request whose role is not authorized
        for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/errors/insufficient_permissions_for_tia_accept_by_contractor
        """
        project = create_project()
        event = create_delay_event(project["id"], causation="FORCE_MAJEURE")
        resp = api.accept_tia(project["id"], event["id"], contractor_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
