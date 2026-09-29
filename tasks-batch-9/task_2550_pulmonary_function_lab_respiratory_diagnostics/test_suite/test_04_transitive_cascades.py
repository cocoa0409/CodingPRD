"""One request in this laboratory routinely rewrites records four hops away.

A single failing biologic control condemns the device, aborts the study standing
on it, hands that study's order back to the schedulable pool and settles the
rescue lot the study's provocation run had drawn on.  A single signature runs a
different spine, ending on a counter held by the patient.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_2dp,
    assert_device_quarantined,
    assert_dose_ledger_balanced,
    assert_instant,
    assert_reservation_matches_live_runs,
    assert_signed_interpretation,
)
from test_helpers.test_users import LAB_MANAGER


def _provoked_study_on_a_controlled_device(api):
    """A methacholine run in progress on a device carrying a passing control."""
    lab = fx.build_lab(api)
    lot = fx.receive_rescue_lot(api)
    order = fx.build_ready_order(
        api,
        lab,
        indication_code="ASTHMA_DIAGNOSIS",
        challenge_type="METHACHOLINE",
    )
    session = fx.schedule_session(
        api,
        order["id"],
        lab.device_id,
        lab.tech1,
        "2026-08-03T09:00:00Z",
        "2026-08-03T09:30:00Z",
    )
    fx.append_maneuver_series(api, session["id"], lab.tech1)
    run = fx.arm_challenge_run(api, session["id"], lot["id"], lab.tech1)
    fx.record_challenge_step(api, run["id"], 25, 2.300, lab.tech1)
    return lab, lot, order, session, run


class TestBiologicControlFailureCascade:
    """A condemned device drags the whole live chain down with it."""

    def test_the_failure_travels_from_device_to_study_to_order(self, api):
        """The device is quarantined, the study aborts, the order is schedulable again.

        PRD 2.8: "A single failing biologic control submitted against one device
        therefore travels four hops inside one request: the device is
        quarantined, every live study on it aborts, each of those studies hands
        its order back to `READY`, and each aborted study's live challenge run
        terminates and settles the rescue lot it had reserved doses from."

        Design: Difficulty/transitive_cascade/biologic_control_failure_cascades_device_session_order_run_lot
        """
        lab, lot, order, session, run = _provoked_study_on_a_controlled_device(api)

        failure = validate_success(
            api.create_quality_event(
                lab.device_id,
                f.biologic_control_event_payload(lab.bcs_id, 3.599, 4.800),
                lab.tech1,
            ),
            expected_status=201,
        )
        assert_2dp(failure["deviation_pct"], 10.03)
        assert failure["outcome"] == "FAIL"
        assert failure["failure_reason"] == "BCS_DEVIATION_EXCEEDED"

        device = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert_device_quarantined(
            device, "BIOLOGIC_CONTROL_FAILED", trigger_staff_id=lab.tech1_id
        )
        assert device["consecutive_biologic_failures"] == 1
        assert device["last_biologic_control_date"] == "2026-08-03", (
            "a failure never advances the daily-quality date"
        )

        aborted = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert aborted["session_status"] == "ABORTED"
        assert aborted["abort_reason"] == "DEVICE_QUARANTINED"

        handed_back = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert handed_back["status"] == "READY"
        assert handed_back["abort_count"] == 1

    def test_the_run_terminates_and_settles_the_rescue_ledger(self, api):
        """A dosed run spends its allotment even though the abort came from outside.

        PRD 3.7: "And when a study is aborted from outside — by a device
        quarantine or an order cancellation — every run on it whose `status` is
        `ARMED` or `IN_PROGRESS` is driven to `ABORTED_SAFETY` with `stop_reason`
        `SESSION_ABORTED`, each one settling its own ledger movement by the same
        step-count rule."

        Design: Difficulty/transitive_cascade/biologic_control_failure_cascades_device_session_order_run_lot
        """
        lab, lot, order, session, run = _provoked_study_on_a_controlled_device(api)

        fx.append_quality_event(
            api,
            lab.device_id,
            f.biologic_control_event_payload(lab.bcs_id, 3.599, 4.800),
            lab.tech1,
        )

        settled = validate_success(api.get_challenge_run(run["id"], LAB_MANAGER))
        assert settled["status"] == "ABORTED_SAFETY"
        assert settled["stop_reason"] == "SESSION_ABORTED"
        assert settled["rescue_doses_administered"] == 4

        stock = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert stock["doses_remaining"] == 6
        assert stock["status"] == "STOCKED"
        assert_reservation_matches_live_runs(stock, live_runs=0)
        assert_dose_ledger_balanced(stock, [settled["rescue_doses_administered"]])

        device = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert device["status"] == "QUARANTINED", (
            "a quarantined device is not downgraded to merely soiled"
        )
        assert_instant(device["last_session_end_at"], "2026-08-03T09:30:00Z")
        assert device["sessions_since_filter_change"] == 1


def _report_awaiting_signature(api):
    """A routine study accepted, assigned, and left a day short of its deadline."""
    lab = fx.build_lab(api, clock="2026-08-03T10:00:00Z", interpreters=1)
    session = fx.build_accepted_session(
        api,
        lab,
        scheduled_start_at="2026-08-03T11:00:00Z",
        scheduled_end_at="2026-08-03T11:30:00Z",
    )
    report = fx.assign_report(api, session["id"], session["version"])
    fx.set_clock(api, "2026-08-04T10:00:00Z")
    return lab, session, report


class TestReportSignatureCascade:
    """A signature closes the study, the order and the patient's count."""

    def test_the_signature_derives_the_interpretation_and_the_turnaround(self, api):
        """A restrictive picture signed exactly a day later is not a breach.

        PRD 3.9: "`sla_breached` is true when `signed_at` is **strictly after**
        `due_at`, so signing at exactly the deadline is not a breach."

        Design: Difficulty/transitive_cascade/report_signature_cascades_report_staff_session_order_patient
        """
        lab, session, report = _report_awaiting_signature(api)

        signed = fx.sign_report(
            api, report["id"], lab.roster.rad1, "Restrictive pattern, moderate severity."
        )

        assert_signed_interpretation(
            signed, "RESTRICTION", "MODERATE", signed_at="2026-08-04T10:00:00Z"
        )
        assert signed["turnaround_minutes"] == 1440
        assert signed["sla_breached"] is False

    def test_one_signature_reaches_the_study_the_order_and_the_patient(self, api):
        """The interpreter's workload falls and the patient's completed count rises.

        PRD 3.9: "Signing also cascades: the interpreter's `open_report_count`
        drops by one because the report has left the open set, the study moves
        from `ACCEPTED` to `REPORTED` and copies `turnaround_minutes` onto its
        own field of the same name, and the order moves from `IN_TESTING` to
        `COMPLETED`, which raises the patient's `completed_order_count` by one."

        Design: Difficulty/transitive_cascade/report_signature_cascades_report_staff_session_order_patient
        """
        lab, session, report = _report_awaiting_signature(api)

        fx.sign_report(
            api, report["id"], lab.roster.rad1, "Restrictive pattern, moderate severity."
        )

        interpreter = validate_success(api.get_staff(lab.roster.rad1_id, LAB_MANAGER))
        assert interpreter["open_report_count"] == 0

        reported = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert reported["session_status"] == "REPORTED"
        assert reported["turnaround_minutes"] == 1440

        order = validate_success(api.get_test_order(session["order_id"], LAB_MANAGER))
        assert order["status"] == "COMPLETED"

        patient = validate_success(api.get_patient(lab.patient_id, LAB_MANAGER))
        assert patient["completed_order_count"] == 1

        device = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert device["status"] == "SOILED"
