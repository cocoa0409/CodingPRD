"""Incident lifecycle: deadlines, resubmit cycle, terminal lockdown (PRD 3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    create_incident_payload,
    get_success_data,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency_with_clinical_staff,
    setup_enrolled_individual,
    setup_home,
    api_client,
    validate_error,
)

ANY = TEST_USERS["any_headers"]


def _setup_incident_base(api, clock_iso="2026-06-02T09:00:00Z"):
    base = setup_agency_with_clinical_staff()
    home = setup_home(base["agency"], certified_bed_count=2)
    ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
    set_clock(clock_iso)
    return base, home, ind


class TestIncidentDeadlineStrictlyGreater:
    """is_late is strict-greater against report_due_at (PRD 3.7)."""

    def _setup_critical_incident_at_deadline(self, api):
        base, home, ind = _setup_incident_base(api, clock_iso="2026-06-03T08:30:00Z")
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(ind["id"], home["id"]),
            make_dsp_headers(base["d1"]["id"]),
        ))
        return base, inc

    def test_submission_exactly_at_deadline_is_not_late(self, api):
        """PRD 3.7: "The `is_late` flag is then computed as whether
        `submitted_at` is strictly later than `report_due_at`; submission
        exactly at `report_due_at` is not late."

        Design: Difficulty/boundary_precision_check/incident_deadline_strictly_greater
        """
        base, inc = self._setup_critical_incident_at_deadline(api)
        submitted = get_success_data(api_client.submit_incident(
            inc["id"], make_dsp_headers(base["d1"]["id"]),
        ))
        assert_same_instant(
            submitted["report_due_at"], "2026-06-03T08:30:00Z", "report_due_at",
        )
        assert_same_instant(
            submitted["submitted_at"], "2026-06-03T08:30:00Z", "submitted_at",
        )
        assert submitted["is_late"] is False

    def test_report_due_at_is_discovered_plus_24h_for_critical(self, api):
        """PRD 3.7: "computes `report_due_at` as `discovered_at` plus a
        severity-dependent window: 24 hours when `severity` is `CRITICAL`".

        Design: Difficulty/boundary_precision_check/incident_deadline_strictly_greater
        """
        base, inc = self._setup_critical_incident_at_deadline(api)
        submitted = get_success_data(api_client.submit_incident(
            inc["id"], make_dsp_headers(base["d1"]["id"]),
        ))
        assert_same_instant(
            submitted["report_due_at"], "2026-06-03T08:30:00Z", "report_due_at",
        )
        assert submitted["status"] == "SUBMITTED"


class TestIncidentSeverityWindows:
    """24/48/72h windows keyed by severity (PRD 3.7)."""

    def _submit_pair(self, api):
        from test_helpers import make_dsp_headers
        base, home, ind = _setup_incident_base(api)
        d1_h = make_dsp_headers(base["d1"]["id"])
        inc_hi = get_success_data(api_client.create_incident(
            create_incident_payload(
                ind["id"], home["id"], severity="HIGH",
                description="Resident cut hand on broken glass",
            ), d1_h,
        ))
        inc_lo = get_success_data(api_client.create_incident(
            create_incident_payload(
                ind["id"], home["id"], category="BEHAVIOR", severity="LOW",
                description="Resident verbal outburst at breakfast",
            ), d1_h,
        ))
        return d1_h, inc_hi, inc_lo

    def test_high_severity_window_is_48_hours(self, api):
        """PRD 3.7: "48 hours when `severity` is `HIGH`".

        Design: Corner/calculations/incident_severity_windows_applied
        """
        d1_h, inc_hi, _inc_lo = self._submit_pair(api)
        submitted = get_success_data(api_client.submit_incident(inc_hi["id"], d1_h))
        assert_same_instant(
            submitted["report_due_at"], "2026-06-04T08:30:00Z", "report_due_at",
        )
        assert submitted["is_late"] is False

    def test_low_severity_window_is_72_hours(self, api):
        """PRD 3.7: "and 72 hours otherwise."

        Design: Corner/calculations/incident_severity_windows_applied
        """
        d1_h, _inc_hi, inc_lo = self._submit_pair(api)
        submitted = get_success_data(api_client.submit_incident(inc_lo["id"], d1_h))
        assert_same_instant(
            submitted["report_due_at"], "2026-06-05T08:30:00Z", "report_due_at",
        )
        assert submitted["is_late"] is False


class TestIncidentResubmitCycle:
    """NEEDS_INFO -> resubmit recomputes is_late vs original due (PRD 3.7)."""

    def _setup_needs_info_incident(self, api):
        from test_helpers import make_dsp_headers
        base, home, ind = _setup_incident_base(api)
        d1_h = make_dsp_headers(base["d1"]["id"])
        q_h = make_qidp_headers(base["q"]["id"])
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(ind["id"], home["id"]), d1_h,
        ))
        first = get_success_data(api_client.submit_incident(inc["id"], d1_h))
        get_success_data(api_client.start_incident_review(inc["id"], q_h))
        get_success_data(api_client.request_incident_info(inc["id"], q_h))
        # Advance past the original due (2026-06-03T08:30).
        set_clock("2026-06-04T09:00:00Z")
        return d1_h, q_h, inc, first

    def test_first_submit_on_time_then_request_info_moves_needs_info(self, api):
        """PRD 3.7: "From `UNDER_REVIEW`, a `QIDP` may request more
        information, moving the incident to `NEEDS_INFO`."

        Design: Corner/state_machines/incident_resubmit_cycle_recomputes_lateness
        """
        d1_h, q_h, inc, first = self._setup_needs_info_incident(api)
        assert first["is_late"] is False
        current = get_success_data(api_client.get_incident(inc["id"], ANY))
        assert current["status"] == "NEEDS_INFO"

    def test_resubmit_after_due_flips_is_late_against_original_due(self, api):
        """PRD 3.7: "resubmission enforces the same ownership rule against
        `submitted_by_staff_id`, updates `submitted_at` to now, and recomputes
        `is_late` against the original `report_due_at` (the due date is not
        extended by resubmission)."

        Design: Corner/state_machines/incident_resubmit_cycle_recomputes_lateness
        """
        d1_h, _q_h, inc, first = self._setup_needs_info_incident(api)
        resubmitted = get_success_data(api_client.resubmit_incident(inc["id"], d1_h))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["report_due_at"] == first["report_due_at"]
        assert resubmitted["is_late"] is True


class TestIncidentCloseTerminalLockdown:
    """CLOSED incidents reject further transitions (PRD 3.7)."""

    def _setup_closed_incident(self, api):
        from test_helpers import make_dsp_headers
        base, home, ind = _setup_incident_base(api)
        d1_h = make_dsp_headers(base["d1"]["id"])
        q_h = make_qidp_headers(base["q"]["id"])
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(
                ind["id"], home["id"], category="BEHAVIOR", severity="LOW",
                description="Resident verbal outburst at breakfast",
            ), d1_h,
        ))
        get_success_data(api_client.submit_incident(inc["id"], d1_h))
        get_success_data(api_client.start_incident_review(inc["id"], q_h))
        closed = get_success_data(api_client.close_incident(inc["id"], q_h))
        return q_h, closed

    def test_incident_reaches_closed(self, api):
        """PRD 3.7: "From `UNDER_REVIEW`, a `QIDP` closes the incident, moving
        it to the terminal state `CLOSED`".

        Design: Corner/state_machines/incident_close_terminal_lockdown
        """
        _q_h, closed = self._setup_closed_incident(api)
        assert closed["status"] == "CLOSED"

    def test_start_review_on_closed_rejected(self, api):
        """PRD 3.7: review begins "From `SUBMITTED`" — a CLOSED incident is in
        no transition's from-state, so the request fails the state check.

        Design: Corner/state_machines/incident_close_terminal_lockdown
        """
        q_h, closed = self._setup_closed_incident(api)
        resp = api_client.start_incident_review(closed["id"], q_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
