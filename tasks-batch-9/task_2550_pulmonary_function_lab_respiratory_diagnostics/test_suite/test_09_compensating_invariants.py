"""Two ledgers here must reconcile after every single operation.

The rescue-dose ledger restores itself by two different compensations depending
on whether the provoking agent ever reached the patient, and the laboratory's
open-report total is conserved when work moves between interpreters and reopened
by an amendment.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_dose_ledger_balanced,
    assert_instant,
    assert_open_report_totals,
    assert_reservation_matches_live_runs,
)
from test_helpers.test_users import LAB_MANAGER

UNDOSED_ABORT = "Patient declined provocation before any dose was given."
DOSED_ABORT = "Patient reported chest tightness after the first dose."


def _armed_run_on_a_full_lot(api):
    """An in-progress provocation study with one armed run and no dose given."""
    lab = fx.build_lab(api)
    lot = fx.receive_rescue_lot(api)
    session = fx.build_session_with_maneuvers(
        api, lab, indication_code="ASTHMA_DIAGNOSIS", challenge_type="METHACHOLINE"
    )
    run = fx.arm_challenge_run(api, session["id"], lot["id"], lab.tech1)
    return lab, session, lot["id"], run


def _abort(api, run_id, reason, tech_headers):
    return validate_success(
        api.abort_challenge_run(
            run_id, f.abort_challenge_run_payload(reason), tech_headers
        )
    )


class TestRescueDoseLedgerCompensations:
    """One reservation, two ways of settling it."""

    def test_an_abort_before_any_dose_releases_the_reservation_whole(self, api):
        """Nothing reached the patient, so the four held doses go back to stock.

        PRD 3.7: "An abort with `current_step_index` still 0 means nothing was
        administered, so `rescue_doses_administered` stays 0, the lot's
        `doses_reserved` drops by 4 with `doses_remaining` untouched — a clean
        release of the whole reservation — and the study's `session_status` is
        left entirely alone, because the patient was never provoked."

        Design: Difficulty/compensating_invariant/rescue_dose_reservation_released_whole_on_undosed_abort_then_spent_on_dosed_abort
        """
        lab, session, lot_id, run = _armed_run_on_a_full_lot(api)

        aborted = _abort(api, run["id"], UNDOSED_ABORT, lab.tech1)

        assert aborted["status"] == "ABORTED_SAFETY"
        assert aborted["stop_reason"] == "TECHNOLOGIST_ABORT"
        assert aborted["rescue_doses_administered"] == 0
        lot = validate_success(api.get_rescue_lot(lot_id, LAB_MANAGER))
        assert lot["doses_reserved"] == 0
        assert lot["doses_remaining"] == 10
        assert_dose_ledger_balanced(lot, [aborted["rescue_doses_administered"]])
        assert_reservation_matches_live_runs(lot, 0)
        study = validate_success(api.get_test_session(session["id"], lab.tech1))
        assert study["session_status"] == "IN_PROGRESS"
        order = validate_success(api.get_test_order(study["order_id"], lab.doc1))
        assert order["status"] == "IN_TESTING"

    def test_an_abort_after_one_dose_turns_the_reservation_into_a_spend(self, api):
        """The agent reached the patient, so the allotment is consumed and the study falls.

        PRD 3.7: "An abort after at least one step means the agent did reach the
        patient, so `rescue_doses_administered` becomes 4, the lot's
        `doses_remaining` drops by 4 and its `doses_reserved` drops by 4, and the
        study is aborted with `abort_reason` `CHALLENGE_SAFETY_ABORT`, which in
        turn drives the order back from `IN_TESTING` to `READY` with
        `abort_count` incremented."

        Design: Difficulty/compensating_invariant/rescue_dose_reservation_released_whole_on_undosed_abort_then_spent_on_dosed_abort
        """
        lab, session, lot_id, first = _armed_run_on_a_full_lot(api)
        released = _abort(api, first["id"], UNDOSED_ABORT, lab.tech1)

        second = fx.arm_challenge_run(api, session["id"], lot_id, lab.tech1)
        rearmed = validate_success(api.get_rescue_lot(lot_id, LAB_MANAGER))
        assert rearmed["doses_reserved"] == 4
        assert rearmed["doses_remaining"] == 10
        assert_3dp(second["baseline_fev1_l"], 2.400)

        stepped = fx.record_challenge_step(api, second["id"], 25, 2.300, lab.tech1)
        assert stepped["status"] == "IN_PROGRESS"
        assert stepped["current_step_index"] == 1
        assert_3dp(stepped["cumulative_dose_units"], 25.000)
        assert_2dp(stepped["max_fev1_drop_pct"], 4.17)

        aborted = _abort(api, second["id"], DOSED_ABORT, lab.tech1)

        assert aborted["status"] == "ABORTED_SAFETY"
        assert aborted["rescue_doses_administered"] == 4
        lot = validate_success(api.get_rescue_lot(lot_id, LAB_MANAGER))
        assert lot["doses_remaining"] == 6
        assert lot["doses_reserved"] == 0
        assert lot["status"] == "STOCKED"
        assert_dose_ledger_balanced(
            lot,
            [released["rescue_doses_administered"], aborted["rescue_doses_administered"]],
        )
        assert_reservation_matches_live_runs(lot, 0)
        study = validate_success(api.get_test_session(session["id"], lab.tech1))
        assert study["session_status"] == "ABORTED"
        assert study["abort_reason"] == "CHALLENGE_SAFETY_ABORT"
        order = validate_success(api.get_test_order(study["order_id"], lab.doc1))
        assert order["status"] == "READY"
        assert order["abort_count"] == 1


def _study_reassigned_from_one_interpreter_to_the_other(api):
    """One accepted study, two interpreters of capacity one, and two assignments."""
    lab = fx.build_lab(api, clock="2026-08-03T10:00:00Z", interpreters=2)
    closed = fx.build_accepted_session(
        api,
        lab,
        scheduled_start_at="2026-08-03T11:00:00Z",
        scheduled_end_at="2026-08-03T11:30:00Z",
    )
    first = fx.assign_report(api, closed["id"], closed["version"])
    reread = validate_success(api.get_test_session(closed["id"], LAB_MANAGER))
    second = fx.assign_report(api, closed["id"], reread["version"])
    return lab, closed, first, second


def _interpreter_rows(api, lab):
    return [
        validate_success(api.get_staff(staff_id, LAB_MANAGER))
        for staff_id in lab.roster.interpreter_ids
    ]


class TestOpenReportTotalConservation:
    """Work moves between interpreters without the laboratory-wide total moving."""

    def test_a_superseding_assignment_moves_the_load_and_keeps_the_total_at_one(self, api):
        """R-001 hands its seat to R-002, and the deadline is measured on one open report.

        PRD 3.9: "A second assignment on the same study is legitimate: any prior
        report on that study whose `status` is `ASSIGNED` moves to `REASSIGNED`
        with `superseded_by_report_id` pointing at the new report, and the losing
        interpreter's `open_report_count` drops by one while the winning
        interpreter's rises by one, so the laboratory-wide open total is
        unchanged."

        Design: Difficulty/compensating_invariant/interpreter_open_report_total_conserved_across_reassignment_and_amendment
        """
        lab, _, first, second = _study_reassigned_from_one_interpreter_to_the_other(api)

        assert first["interpreter_staff_id"] == lab.roster.rad1_id
        assert second["interpreter_staff_id"] == lab.roster.rad2_id

        superseded = validate_success(
            api.get_interpretation_report(first["id"], LAB_MANAGER)
        )
        assert superseded["status"] == "REASSIGNED"
        assert superseded["superseded_by_report_id"] == second["id"]

        rows = _interpreter_rows(api, lab)
        assert rows[0]["open_report_count"] == 0
        assert rows[1]["open_report_count"] == 1
        assert_open_report_totals(rows, 1)

        assert_instant(second["assigned_at"], "2026-08-03T10:00:00Z")
        # The deadline figures of the superseding assignment are deliberately not
        # asserted here: PRD 3.9 makes the five deadline steps normative ("First
        # the report is inserted ... Second, the laboratory-wide open workload is
        # counted ... including the row just inserted") but never states whether
        # the prior report on this study has already moved to REASSIGNED at the
        # moment step two counts, so the open count is either 1 or 2 on a faithful
        # reading and queue_load_pct is not uniquely derivable.

    def test_an_amendment_reopens_the_seat_but_never_the_deadline(self, api):
        """The re-signature is judged against the deadline the first assignment set.

        PRD 3.9: "Crucially, **an amendment does not reopen the deadline**:
        `assigned_at` and `due_at` keep their original values, and re-signing the
        amended report recomputes `turnaround_minutes` against that original
        `assigned_at` and re-evaluates `sla_breached` against that original
        `due_at`."

        Design: Difficulty/compensating_invariant/interpreter_open_report_total_conserved_across_reassignment_and_amendment
        """
        lab, closed, _, second = _study_reassigned_from_one_interpreter_to_the_other(api)
        fx.set_clock(api, "2026-08-04T10:00:00Z")

        signed = fx.sign_report(api, second["id"], lab.roster.rad2)
        assert signed["status"] == "SIGNED"
        assert signed["turnaround_minutes"] == 1440
        assert signed["sla_breached"] is False
        assert_open_report_totals(_interpreter_rows(api, lab), 0)
        reported = validate_success(api.get_test_session(closed["id"], lab.tech1))
        assert reported["session_status"] == "REPORTED"
        order = validate_success(api.get_test_order(reported["order_id"], lab.doc1))
        assert order["status"] == "COMPLETED"
        patient = validate_success(api.get_patient(lab.patient_id, LAB_MANAGER))
        assert patient["completed_order_count"] == 1

        amended = validate_success(
            api.amend_interpretation_report(
                second["id"],
                f.amend_report_payload("Corrected the clinical comment on the DLCO context."),
                lab.roster.rad2,
            )
        )
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1
        rows = _interpreter_rows(api, lab)
        assert rows[1]["open_report_count"] == 1
        assert_open_report_totals(rows, 1)
        unchanged = validate_success(api.get_test_session(closed["id"], lab.tech1))
        assert unchanged["session_status"] == "REPORTED"

        # PRD 3.9: "A report amended and re-signed a week late is therefore
        # breached" — the re-signature lands a week after the first one, which is
        # past the deadline whatever base allowance the assignment computed.
        fx.set_clock(api, "2026-08-10T10:00:00Z")
        resigned = fx.sign_report(
            api, second["id"], lab.roster.rad2, clinical_comment="Amended comment signed off."
        )

        assert_instant(resigned["assigned_at"], "2026-08-03T10:00:00Z")
        # An amendment does not reopen the deadline, so due_at still carries the
        # value the original assignment computed.
        assert_instant(resigned["due_at"], second["due_at"])
        assert resigned["turnaround_minutes"] == 10080
        assert resigned["sla_breached"] is True
        assert_open_report_totals(_interpreter_rows(api, lab), 0)
        # The study's own turnaround_minutes is not re-asserted after the second
        # signature: PRD 3.9 ties the copy to the transition ("the study moves
        # from `ACCEPTED` to `REPORTED` and copies `turnaround_minutes` onto its
        # own field of the same name"), and a study that is already `REPORTED`
        # makes no such move, so whether a re-signature refreshes the copy is not
        # uniquely derivable from the PRD.
        study = validate_success(api.get_test_session(closed["id"], lab.tech1))
        assert study["session_status"] == "REPORTED"
