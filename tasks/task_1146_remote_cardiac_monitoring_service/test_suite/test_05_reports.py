"""Diagnostic report lifecycle and finalization gates (PRD §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_report_payload,
    create_transmission_payload,
    make_physician_headers,
    raise_alert,
    read_episode,
    read_report,
    set_clock,
    setup_completed_episode,
    setup_monitoring_episode,
    validate_error,
    validate_success,
)

GATEWAY = TEST_USERS["device_gateway_headers"]


class TestFinalReportReferentialGate:
    def test_final_report_requires_completed_episode(self, api):
        """PRD §3.7: "Then the referential gate: a `FINAL` report requires the
        episode's `clinical_status` to be `COMPLETED` or `TERMINATED_EARLY` —
        an `INTERIM` report may finalize while the episode is still
        `MONITORING`, but a `FINAL` one is rejected with
        `ERR_EPISODE_NOT_COMPLETED` (HTTP 422)."

        Design: Corner/validations/final_report_requires_completed_episode
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        validate_success(
            api.ingest_transmission(
                ctx["episode_id"],
                create_transmission_payload(seq_no=1, bytes_received=100, signal_quality=70),
                GATEWAY,
            ),
            201,
        )
        dr_headers = make_physician_headers(ctx["physician"]["id"])
        report = validate_success(
            api.create_report(
                ctx["episode_id"],
                create_report_payload(report_type="FINAL", findings_summary="too early"),
                dr_headers,
            ),
            201,
        )
        resp = api.finalize_report(report["id"], dr_headers)
        validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_COMPLETED)
        assert read_report(report["id"])["status"] == "DRAFT"


class TestAmendRefinalizeCycle:
    def test_report_amend_refinalize_cycle(self, api):
        """PRD §3.7: "The reading physician may amend a `FINALIZED` report with
        replacement `findings_summary`, moving it to `AMENDED` and incrementing
        `revision_count`; the cycle `FINALIZED` → `AMENDED` → `FINALIZED` may
        repeat indefinitely, and the report state machine has no terminal
        state."
        PRD §3.7: "`turnaround_hours` is the number of hours between the
        episode's `completed_at` and the report's `finalized_at`, rounded half
        up to two decimal places."
        PRD §3.7: "`sla_met` is true when `finalized_at` falls at or before
        seventy-two hours after the episode's `completed_at`; hitting the
        seventy-two-hour mark exactly still counts as met."

        Design: Corner/state_machines/report_amend_refinalize_cycle
        """
        ctx = setup_completed_episode(prescribed_days=10, transmissions=1)
        # episode completed_at == 2026-05-11T00:00:00Z (start + 10 days)
        dr_headers = make_physician_headers(ctx["physician"]["id"])
        report = validate_success(
            api.create_report(
                ctx["episode_id"],
                create_report_payload(report_type="FINAL", findings_summary="sinus rhythm"),
                dr_headers,
            ),
            201,
        )

        set_clock("2026-05-12T00:00:00Z")
        finalized = validate_success(api.finalize_report(report["id"], dr_headers))
        assert finalized["status"] == "FINALIZED"
        assert finalized["turnaround_hours"] == pytest.approx(24.0, abs=0.01)
        assert finalized["sla_met"] is True

        amended = validate_success(
            api.amend_report(
                report["id"], {"findings_summary": "sinus rhythm, corrected interval"}, dr_headers
            )
        )
        assert amended["status"] == "AMENDED"
        assert amended["revision_count"] == 1

        set_clock("2026-05-13T00:00:00Z")
        refinalized = validate_success(api.finalize_report(report["id"], dr_headers))
        assert refinalized["status"] == "FINALIZED"
        assert refinalized["turnaround_hours"] == pytest.approx(48.0, abs=0.01)
        assert refinalized["sla_met"] is True


class TestTurnaroundSlaBoundary:
    def test_turnaround_exactly_72h_boundary(self, api):
        """PRD §3.7: "`sla_met` is true when `finalized_at` falls at or before
        seventy-two hours after the episode's `completed_at`; hitting the
        seventy-two-hour mark exactly still counts as met."
        PRD §3.7: "`turnaround_hours` is the number of hours between the
        episode's `completed_at` and the report's `finalized_at`, rounded half
        up to two decimal places."

        Design: Corner/calculations/turnaround_exactly_72h_boundary
        """
        ctx = setup_completed_episode(prescribed_days=10)
        # completed_at == 2026-05-11T00:00:00Z; zero transmissions -> flag required
        dr_headers = make_physician_headers(ctx["physician"]["id"])
        report = validate_success(
            api.create_report(
                ctx["episode_id"],
                create_report_payload(
                    report_type="FINAL",
                    findings_summary="no transmissions received",
                    no_significant_findings=True,
                ),
                dr_headers,
            ),
            201,
        )

        set_clock("2026-05-14T00:00:00Z")  # exactly completed_at + 72h
        finalized = validate_success(api.finalize_report(report["id"], dr_headers))
        assert finalized["turnaround_hours"] == pytest.approx(72.0, abs=0.01)
        assert finalized["sla_met"] is True, "exactly 72h counts as met"

        validate_success(api.amend_report(report["id"], {"findings_summary": "addendum"}, dr_headers))
        set_clock("2026-05-15T00:00:00Z")  # completed_at + 96h
        refinalized = validate_success(api.finalize_report(report["id"], dr_headers))
        assert refinalized["turnaround_hours"] == pytest.approx(96.0, abs=0.01)
        assert refinalized["sla_met"] is False


class TestZeroTransmissionFinalGate:
    def _setup_zero_transmission_episode(self):
        ctx = setup_completed_episode(prescribed_days=10)
        assert read_episode(ctx["episode_id"])["transmission_count"] == 0
        return ctx

    def test_zero_transmission_final_report_rejected_without_flag(self, api):
        """PRD §3.7: "Last, the constraint gate: a `FINAL` report on an episode
        whose `transmission_count` is zero must carry `no_significant_findings`
        true, else `ERR_EMPTY_MONITORING_DATA` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/zero_transmission_final_report_gate
        """
        ctx = self._setup_zero_transmission_episode()
        dr_headers = make_physician_headers(ctx["physician"]["id"])
        report = validate_success(
            api.create_report(
                ctx["episode_id"],
                create_report_payload(
                    report_type="FINAL",
                    findings_summary="no data",
                    no_significant_findings=False,
                ),
                dr_headers,
            ),
            201,
        )
        resp = api.finalize_report(report["id"], dr_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_MONITORING_DATA)

    def test_zero_transmission_final_report_admitted_with_flag(self, api):
        """PRD §3.7: "Last, the constraint gate: a `FINAL` report on an episode
        whose `transmission_count` is zero must carry `no_significant_findings`
        true, else `ERR_EMPTY_MONITORING_DATA` (HTTP 422)."
        PRD §3.7: "`turnaround_hours` is the number of hours between the
        episode's `completed_at` and the report's `finalized_at`, rounded half
        up to two decimal places."
        PRD §3.7: "`sla_met` is true when `finalized_at` falls at or before
        seventy-two hours after the episode's `completed_at`; hitting the
        seventy-two-hour mark exactly still counts as met."

        Design: Difficulty/boundary_precision_check/zero_transmission_final_report_gate
        """
        ctx = self._setup_zero_transmission_episode()
        # clock still equals completed_at (2026-05-11T00:00:00Z) at finalize
        dr_headers = make_physician_headers(ctx["physician"]["id"])
        report = validate_success(
            api.create_report(
                ctx["episode_id"],
                create_report_payload(
                    report_type="FINAL",
                    findings_summary="no data, waived",
                    no_significant_findings=True,
                ),
                dr_headers,
            ),
            201,
        )
        finalized = validate_success(api.finalize_report(report["id"], dr_headers))
        assert finalized["status"] == "FINALIZED"
        assert finalized["turnaround_hours"] == pytest.approx(0.0, abs=0.01)
        assert finalized["sla_met"] is True


class TestSafetyBeatsReferential:
    def _setup_monitoring_with_critical_and_final_draft(self, api):
        ctx = setup_monitoring_episode(prescribed_days=30)
        raise_alert(ctx["episode_id"], severity="CRITICAL", arrhythmia_type="VTACH")
        dr_headers = make_physician_headers(ctx["physician"]["id"])
        report = validate_success(
            api.create_report(
                ctx["episode_id"],
                create_report_payload(
                    report_type="FINAL",
                    findings_summary="premature",
                    no_significant_findings=True,
                ),
                dr_headers,
            ),
            201,
        )
        return ctx, report, dr_headers

    def test_finalize_with_open_critical_alert_rejected(self, api):
        """PRD §3.7: "Then the safety gate: every `CRITICAL` alert on the
        episode must be `CLOSED`, and finalizing while one remains open is
        rejected with `ERR_CRITICAL_ALERTS_OPEN` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_finalize
        """
        ctx, report, dr_headers = self._setup_monitoring_with_critical_and_final_draft(api)
        resp = api.finalize_report(report["id"], dr_headers)
        validate_error(resp, ApiErrorId.ERR_CRITICAL_ALERTS_OPEN)

    def test_safety_gate_precedes_referential_gate(self, api):
        """PRD §3.7: "Finalization is the most heavily gated write in the
        system, and its guards fire in a fixed relative order."
        PRD §3.7: "Then the safety gate: every `CRITICAL` alert on the episode
        must be `CLOSED`, and finalizing while one remains open is rejected
        with `ERR_CRITICAL_ALERTS_OPEN` (HTTP 422)."
        PRD §3.7: "Then the referential gate: a `FINAL` report requires the
        episode's `clinical_status` to be `COMPLETED` or `TERMINATED_EARLY` —
        an `INTERIM` report may finalize while the episode is still
        `MONITORING`, but a `FINAL` one is rejected with
        `ERR_EPISODE_NOT_COMPLETED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_finalize
        """
        ctx, report, dr_headers = self._setup_monitoring_with_critical_and_final_draft(api)
        # The episode is still MONITORING (referential gate would also fail);
        # the pinned guard order must surface the safety failure.
        resp = api.finalize_report(report["id"], dr_headers)
        error = validate_error(resp, ApiErrorId.ERR_CRITICAL_ALERTS_OPEN)
        assert error["error_id"] != "ERR_EPISODE_NOT_COMPLETED"
