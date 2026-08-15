"""Time-based boundary tests: consult SLA strictly-greater; observation
48h conversion equality; LOS alert strictly-greater; cross-cover load formula;
monitor-run idempotency; clock startup default.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, create_consult_for, create_coverage_window,
    setup_assigned_patient,
)

ADMIN = TEST_USERS["group_admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


class TestConsultSlaStrictlyGreaterBoundary:
    """Difficulty instance: consult_sla_strictly_greater_boundary."""

    def _setup_two_consults(self, api):
        """H1 ACTIVE shift holds P1; STAT consult C1 created at 10:00
        (deadline 10:15); URGENT consult C2 created at 10:15 (deadline 10:45)."""
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T10:00:00Z")
        p1 = create_patient(mrn="M931", acuity="HIGH", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T09:00:00Z")
        admit_and_accept(p1["id"])
        c1 = create_consult_for(p1["id"], h1["id"], "CARDIOLOGY", "STAT", "rule out MI")
        return h1, p1, c1

    def test_acknowledge_exactly_at_deadline_not_a_breach(self, api):
        """PRD §3.7: "`sla_deadline` is `requested_at` plus fifteen minutes
        for `STAT`, thirty for `URGENT`, or two hours for `ROUTINE`".
        PRD §3.7: "Each acknowledge stamps `acknowledged_at`, increments
        `version`, and evaluates `sla_breached`: true when `acknowledged_at`
        is strictly later than `sla_deadline`, with equality not a breach,
        compared at millisecond precision."

        Design: Difficulty/boundary_precision_check/consult_sla_strictly_greater_boundary
        """
        h1, p1, c1 = self._setup_two_consults(api)
        # sla_deadline = 10:00 + 15min = 10:15:00.000Z
        assert c1["sla_deadline"] == "2026-05-01T10:15:00.000Z"
        # Advance clock to exactly the deadline; acknowledge then
        set_clock("2026-05-01T10:15:00.000Z")
        ack = get_success_data(api.acknowledge_consult(c1["id"], SPECIALIST))
        assert ack["sla_breached"] is False
        assert ack["status"] == "ACKNOWLEDGED"

    def test_acknowledge_one_ms_after_deadline_is_a_breach(self, api):
        """PRD §3.7: "evaluates `sla_breached`: true when `acknowledged_at`
        is strictly later than `sla_deadline`, with equality not a breach,
        compared at millisecond precision."

        Design: Difficulty/boundary_precision_check/consult_sla_strictly_greater_boundary
        """
        h1, p1, c1 = self._setup_two_consults(api)
        # Create URGENT consult at 10:15 -> deadline 10:45
        set_clock("2026-05-01T10:15:00.000Z")
        c2 = create_consult_for(p1["id"], h1["id"], "NEUROLOGY", "URGENT", "weakness")
        assert c2["sla_deadline"] == "2026-05-01T10:45:00.000Z"
        # Acknowledge 1 ms past deadline
        set_clock("2026-05-01T10:45:00.001Z")
        ack = get_success_data(api.acknowledge_consult(c2["id"], SPECIALIST))
        assert ack["sla_breached"] is True
        assert ack["status"] == "ACKNOWLEDGED"


class TestObsConversionAtExactly48h:
    """Corner instance: obs_conversion_at_exactly_48h."""

    def test_47_59_59_does_not_convert_48_00_00_does(self, api):
        """PRD §3.2: "the operations checkpoint carries it to `OBS_CONVERTED`,
        flipping `stay_type` to `INPATIENT` in the same mutation, once the
        elapsed time since `observation_started_at` reaches at least 48.0
        hours — equality converts, evaluated at second precision, so 47:59:59
        elapsed does not convert while exactly 48:00:00 does."

        Design: Corner/calculations/obs_conversion_at_exactly_48h
        """
        p = create_patient(mrn="K004", acuity="LOW", admit_source="ED",
                           stay_type="OBSERVATION", admitted_at="2026-05-01T08:00:00Z")
        # 47:59:59 elapsed
        set_clock("2026-05-03T07:59:59Z")
        r1 = get_success_data(api.monitor_run(ADMIN))
        assert p["id"] not in r1["obs_converted_patient_ids"]
        p_now = get_success_data(api.get_patient(p["id"], ADMIN))
        assert p_now["observation_status"] == "OBS_ACTIVE"
        # Exactly 48:00:00 elapsed
        set_clock("2026-05-03T08:00:00Z")
        r2 = get_success_data(api.monitor_run(ADMIN))
        assert p["id"] in r2["obs_converted_patient_ids"]
        p_now = get_success_data(api.get_patient(p["id"], ADMIN))
        assert p_now["observation_status"] == "OBS_CONVERTED"
        assert p_now["stay_type"] == "INPATIENT"


class TestLosAlertThresholdStrictGreater:
    """Corner instance: los_alert_threshold_strict_greater."""

    def test_six_midnights_not_alert_seven_is(self, api):
        """PRD §3.2: "`los_alert_flag` turns true when `los_midnights`
        strictly exceeds the expected stay for the patient's current
        `stay_type` and `acuity` multiplied by 1.5 — equality is not an
        alert. Expected stays, in days: for `INPATIENT`, 6 at `HIGH`, 4 at
        `MEDIUM`, 2 at `LOW`."

        Design: Corner/calculations/los_alert_threshold_strict_greater
        """
        p = create_patient(mrn="K003", acuity="MEDIUM", admit_source="ED",
                           stay_type="INPATIENT", admitted_at="2026-05-01T12:00:00Z")
        # 6 midnights (2026-05-02 through 2026-05-07) — not strictly > 6
        set_clock("2026-05-07T12:00:00Z")
        api.monitor_run(ADMIN)
        p_now = get_success_data(api.get_patient(p["id"], ADMIN))
        assert p_now["los_midnights"] == 6
        assert p_now["los_alert_flag"] is False
        # 7 midnights -> alert
        set_clock("2026-05-08T12:00:00Z")
        api.monitor_run(ADMIN)
        p_now = get_success_data(api.get_patient(p["id"], ADMIN))
        assert p_now["los_midnights"] == 7
        assert p_now["los_alert_flag"] is True


class TestCrossCoverLoadFormula:
    """Corner instance: cross_cover_load_formula."""

    def test_locked_window_load_computed(self, api):
        """PRD §3.9: "While a window is `LOCKED`, each checkpoint also
        recomputes its `current_load`: take the group-wide count of `ACTIVE`
        assignments, weighted double for a `NIGHT_CROSS_COVER` window and
        single for `NIGHT_PRIMARY`; add the group-wide count of consults in
        `OPEN` or `ESCALATED` at one point each; add the group-wide count of
        handoffs in `SUBMITTED` at two points each; round half up to two
        decimals; and clamp the result at a maximum of 40, the clamp applied
        last."
        PRD §2.9: "coverage-window locks and closures at their boundaries"
        advance at the operations checkpoint; "a window in `OPEN` or `FULL`
        locks — moving to `LOCKED` — once the logical clock reaches
        `start_at`" (PRD §3.9).

        Design: Corner/calculations/cross_cover_load_formula
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        h2 = create_hospitalist("H Two", "INTERNAL_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        # 3 ACTIVE assignments for H1
        for mrn, ac, adm in [("K012", "MEDIUM", "ED"), ("K013", "LOW", "DIRECT"), ("K014", "LOW", "ED")]:
            p = create_patient(mrn=mrn, acuity=ac, admit_source=adm,
                               stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
            admit_and_accept(p["id"])
        # 1 OPEN consult (ROUTINE, far from deadline)
        rows, _meta = validate_paginated(api.list_patients(ADMIN, params={"limit": 1}))
        p1 = rows[0]
        create_consult_for(p1["id"], h1["id"], "NEPHROLOGY", "ROUTINE", "fluid review")
        # Window + enrollment by H2
        w = create_coverage_window(window_date="2026-05-01",
                                   window_type="NIGHT_CROSS_COVER",
                                   start_at="2026-05-01T19:00:00Z",
                                   end_at="2026-05-02T07:00:00Z",
                                   capacity=3)
        get_success_data(api.enroll_coverage_window(w["id"], make_hospitalist_headers(h2["id"])))
        # Move clock past start_at; monitor-run locks the window
        set_clock("2026-05-01T20:00:00Z")
        mr = get_success_data(api.monitor_run(ADMIN))
        assert w["id"] in mr["locked_window_ids"]
        w_now = get_success_data(api.get_coverage_window(w["id"], ADMIN))
        assert w_now["status"] == "LOCKED"
        # load = min(40, 3 ACTIVE * 2.0 + 1 OPEN * 1 + 0 SUBMITTED * 2) = 7.0
        assert w_now["current_load"] == pytest.approx(7.0, abs=0.001)


class TestMonitorRunRepeatIsNoop:
    """Corner instance: monitor_run_repeat_is_noop."""

    def test_second_run_at_same_clock_converts_nothing(self, api):
        """PRD §2.9: "One run sweeps, in whatever order the server chooses
        but in one consistent pass: observation-status conversions for
        observation patients past their threshold ... Each swept mutation
        increments the affected entity's `version` and refreshes its
        `updated_at`, and every effect is visible in the same response's
        aftermath and in subsequent reads."
        PRD §3.2: "the operations checkpoint carries it to `OBS_CONVERTED`"
        — once the axis is `OBS_CONVERTED`, it is no longer `OBS_ACTIVE` and
        the conversion precondition no longer holds.

        Design: Corner/endpoints/monitor_run_repeat_is_noop
        """
        p = create_patient(mrn="E001", acuity="LOW", admit_source="ED",
                           stay_type="OBSERVATION", admitted_at="2026-05-01T08:00:00Z")
        set_clock("2026-05-03T08:00:00Z")
        r1 = get_success_data(api.monitor_run(ADMIN))
        assert p["id"] in r1["obs_converted_patient_ids"]
        # Second run at the same clock — nothing left to convert
        r2 = get_success_data(api.monitor_run(ADMIN))
        assert r2["obs_converted_patient_ids"] == []
        p_now = get_success_data(api.get_patient(p["id"], ADMIN))
        assert p_now["observation_status"] == "OBS_CONVERTED"


class TestClockDefaultBeforeAnySet:
    """Corner instance: clock_default_before_any_set."""

    def test_monitor_run_evaluates_at_startup_default(self, api):
        """PRD §2.4: "At server startup the logical clock reads
        2026-05-01T00:00:00Z, and it advances only through an admin-only
        test-driving capability, `POST /_clock/set_current_utc`".
        PRD §2.9: "The checkpoint answers with `evaluated_at` — the logical
        instant of evaluation — plus five arrays naming what moved:
        `obs_converted_patient_ids`, `escalated_consult_ids`,
        `closed_consult_ids`, `locked_window_ids`, and `closed_window_ids`."
        PRD §2.2: "All timestamps are ISO 8601 UTC with three fractional
        digits" — so the instant renders as 2026-05-01T00:00:00.000Z.

        Design: Corner/endpoints/clock_default_before_any_set
        """
        # No set_current_utc call has been made in this test; the logical
        # clock reads the startup default.
        resp = api.monitor_run(ADMIN)
        data = validate_success(resp)
        assert data["evaluated_at"] == "2026-05-01T00:00:00.000Z"
        assert data["obs_converted_patient_ids"] == []
        assert data["escalated_consult_ids"] == []
        assert data["closed_consult_ids"] == []
        assert data["locked_window_ids"] == []
        assert data["closed_window_ids"] == []


class TestConsultEscalationOnMonitorRun:
    """Corner instance: consult_escalation_on_monitor_run."""

    def test_open_consult_past_deadline_escalates(self, api):
        """PRD §3.7: "Any consult still `OPEN` with the logical clock
        strictly past `sla_deadline` escalates — `OPEN` → `ESCALATED`,
        `escalation_count` incrementing by one, `version` incrementing."
        PRD §2.9: "consult escalations for unanswered requests past deadline".

        Design: Corner/state_machines/consult_escalation_on_monitor_run
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T10:00:00Z")
        p1 = create_patient(mrn="S010", acuity="HIGH", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T09:00:00Z")
        admit_and_accept(p1["id"])
        c1 = create_consult_for(p1["id"], h1["id"], "CARDIOLOGY", "STAT", "troponin rising")
        # Advance past 10:15 deadline
        set_clock("2026-05-01T10:16:00Z")
        mr = get_success_data(api.monitor_run(ADMIN))
        assert c1["id"] in mr["escalated_consult_ids"]
        c_now = get_success_data(api.get_consult_request(c1["id"], ADMIN))
        assert c_now["status"] == "ESCALATED"
        assert c_now["escalation_count"] == 1
