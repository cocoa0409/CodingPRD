"""Sanitation-run and pre-op inspection lifecycles, segregation of duties,
and the open-production gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_sanitation_run, assert_preop_inspection,
    create_sanitation_run_payload, create_preop_inspection_payload,
    create_flock_lot_payload, receive_flock_lot_payload, create_line_run_payload,
    create_shift_payload,
    make_line, make_shift, create_verified_sanitation, create_passed_preop,
    book_and_receive_lot, queue_run, open_shift, setup_running_shift_with_run,
    TEST_USERS, make_qa_technician_headers, make_sanitation_lead_headers,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
RCV = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["line_operator_headers"]
QA = TEST_USERS["qa_technician_headers"]
SAN = TEST_USERS["sanitation_lead_headers"]


class TestSanitationLifecycle:

    def test_sanitation_failed_recheck_rewash_cycle(self, api):
        """PRD §3.2: "The sanitation run's lifecycle is `SCHEDULED` →
        `IN_PROGRESS` → `COMPLETED` → `VERIFIED`, with a re-wash cycle from
        `COMPLETED` to `FAILED_RECHECK` and back to `IN_PROGRESS`."
        PRD §3.2: "When the lead completes the wash (`IN_PROGRESS` →
        `COMPLETED`) the system records their header identity in
        `completer_user_id`, anchoring the segregation check that follows. A
        `QATechnician` then adjudicates the completed run: advancing it to
        `VERIFIED` (permitted only from `COMPLETED`, else
        `ERR_INVALID_STATE_TRANSITION`) or to `FAILED_RECHECK`, in either case
        recording themselves in `verifier_user_id`."

        Design: Corner/state_machines/sanitation_failed_recheck_rewash_cycle
        """
        line = make_line()
        shift = make_shift()
        run = get_success_data(api.create_sanitation_run(
            create_sanitation_run_payload(shift["id"], line["id"]), SAN))

        san = make_sanitation_lead_headers("san-1")
        qa = make_qa_technician_headers("qa-1")
        get_success_data(api.advance_sanitation_run(run["id"], {"to_status": "IN_PROGRESS"}, san))
        get_success_data(api.advance_sanitation_run(run["id"], {"to_status": "COMPLETED"}, san))
        failed = validate_success(
            api.advance_sanitation_run(run["id"], {"to_status": "FAILED_RECHECK"}, qa))
        assert failed["status"] == "FAILED_RECHECK"

        rewash = validate_success(
            api.advance_sanitation_run(run["id"], {"to_status": "IN_PROGRESS"}, san))
        assert rewash["status"] == "IN_PROGRESS"

        get_success_data(api.advance_sanitation_run(run["id"], {"to_status": "COMPLETED"}, san))
        verified = validate_success(
            api.advance_sanitation_run(run["id"], {"to_status": "VERIFIED"}, qa))
        assert verified["status"] == "VERIFIED"
        assert verified["completer_user_id"] == "san-1"
        assert verified["verifier_user_id"] == "qa-1"

    def test_sanitation_advance_from_verified_rejected(self, api):
        """PRD §3.2: "`VERIFIED` is terminal for the run."
        PRD §2.6: "anything else unreachable from the current state is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409 throughout)."

        Design: Corner/state_machines/sanitation_advance_from_verified_rejected
        """
        line = make_line()
        shift = make_shift()
        run = create_verified_sanitation(shift["id"], line["id"])
        assert run["status"] == "VERIFIED"

        resp = api.advance_sanitation_run(
            run["id"], {"to_status": "IN_PROGRESS"}, make_sanitation_lead_headers("san-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_sanitation_run(run["id"], SAN))
        assert after["status"] == "VERIFIED"

    def test_sanitation_start_during_production_rejected(self, api):
        """PRD §3.2: "Work may only begin — `SCHEDULED` → `IN_PROGRESS`, and
        likewise the re-wash return `FAILED_RECHECK` → `IN_PROGRESS` — while
        the parent shift is in `SCHEDULED` or `SUSPENDED`, never during
        `RUNNING` production, and only when no line run of that shift and line
        is in `RUNNING`; violations are rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/sanitation_start_during_production_rejected
        """
        env = setup_running_shift_with_run()
        assert env["shift"]["status"] == "RUNNING"
        assert env["run"]["status"] == "RUNNING"
        run2 = get_success_data(api.create_sanitation_run(
            create_sanitation_run_payload(env["shift"]["id"], env["line"]["id"],
                                          window_start="2026-08-01T12:00:00Z",
                                          window_end="2026-08-01T13:00:00Z"), SAN))
        resp = api.advance_sanitation_run(
            run2["id"], {"to_status": "IN_PROGRESS"}, make_sanitation_lead_headers("san-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_sanitation_run(run2["id"], SAN))
        assert after["status"] == "SCHEDULED"


class TestPreOpLifecycle:

    def test_preop_failed_correcting_pending_cycle_count(self, api):
        """PRD §3.2: "Failing — `PENDING` → `FAILED` — requires a `findings`
        note (absent, the request is `ERR_INVALID_REQUEST`) and likewise records
        `inspector_user_id`. From `FAILED`, a `SanitationLead` or `QATechnician`
        moves the inspection to `CORRECTING`, and a `QATechnician` returns it
        from `CORRECTING` to `PENDING` for re-inspection, each return
        incrementing the inspection's `cycle_count` by one."

        Design: Corner/state_machines/preop_failed_correcting_pending_cycle_count
        """
        line = make_line()
        shift = make_shift()
        create_verified_sanitation(shift["id"], line["id"])
        preop = get_success_data(api.create_preop_inspection(
            create_preop_inspection_payload(shift["id"], line["id"]), QA))

        qa2 = make_qa_technician_headers("qa-2")
        failed = validate_success(api.advance_preop_inspection(
            preop["id"], {"to_status": "FAILED", "findings": "debris on shackle line"}, qa2))
        assert failed["status"] == "FAILED"
        assert failed["inspector_user_id"] == "qa-2"

        correcting = validate_success(api.advance_preop_inspection(
            preop["id"], {"to_status": "CORRECTING"}, make_sanitation_lead_headers("san-1")))
        assert correcting["status"] == "CORRECTING"

        pending = validate_success(api.advance_preop_inspection(
            preop["id"], {"to_status": "PENDING"}, qa2))
        assert pending["status"] == "PENDING"
        assert pending["cycle_count"] == 1

        passed = validate_success(api.advance_preop_inspection(
            preop["id"], {"to_status": "PASSED"}, qa2))
        assert passed["status"] == "PASSED"


class TestSegregationOfDuties:

    def test_sod_preop_pass_by_sanitation_completer(self, api):
        """PRD §3.2: "the inspector's `X-User-ID` must differ from the
        `completer_user_id` of every sanitation run at `COMPLETED` or beyond
        for that shift and line — the person who washed the line may not pass
        its inspection, and a violation is rejected with
        `ERR_SOD_PREOP_SANITATION`."

        Design: Corner/validations/sod_preop_pass_by_sanitation_completer
        """
        line = make_line()
        shift = make_shift()
        create_verified_sanitation(shift["id"], line["id"], completer_user_id="san-1")
        preop = get_success_data(api.create_preop_inspection(
            create_preop_inspection_payload(shift["id"], line["id"]), QA))

        # Same operator id that completed sanitation, acting as QATechnician.
        resp = api.advance_preop_inspection(
            preop["id"], {"to_status": "PASSED"}, make_qa_technician_headers("san-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_PREOP_SANITATION)

        # Control: a different operator id passes the same inspection.
        ctrl = validate_success(api.advance_preop_inspection(
            preop["id"], {"to_status": "PASSED"}, make_qa_technician_headers("qa-2")))
        assert ctrl["status"] == "PASSED"

    def test_sanitation_lead_cannot_pass_preop(self, api):
        """PRD §4 (pre-op advance row): "Pre-op lifecycle: PASSED/FAILED/PENDING
        by QATechnician; CORRECTING by SanitationLead or QATechnician".
        PRD §2.1: "An authenticated operator who attempts an operation outside
        their role's mandate is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)".

        Design: Corner/rbac/sanitation_lead_cannot_pass_preop
        """
        line = make_line()
        shift = make_shift()
        create_verified_sanitation(shift["id"], line["id"])
        preop = get_success_data(api.create_preop_inspection(
            create_preop_inspection_payload(shift["id"], line["id"]), QA))

        resp = api.advance_preop_inspection(
            preop["id"], {"to_status": "PASSED"}, make_sanitation_lead_headers("san-9"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = get_success_data(api.get_preop_inspection(preop["id"], QA))
        assert after["status"] == "PENDING"


class TestOpenProductionGates:

    def _shift_line_with_queue(self, api, sanitation=False, preop=False):
        line = make_line()
        shift = make_shift()
        if sanitation:
            create_verified_sanitation(shift["id"], line["id"])
        if preop:
            create_passed_preop(shift["id"], line["id"])
        lot = book_and_receive_lot(shift["id"])
        run = queue_run(shift["id"], line["id"], lot["id"])
        return line, shift, run

    def test_open_production_without_preop_rejected(self, api):
        """PRD §3.2: "then, for every line referenced by a `QUEUED` run, at
        least one sanitation run must be `VERIFIED` for that shift and line,
        else `ERR_SANITATION_NOT_VERIFIED` — the sanitation gate is checked
        before the pre-op gate; and finally, for every such line, at least one
        pre-operational inspection must be `PASSED`, else
        `ERR_PREOP_NOT_PASSED`."

        Design: Corner/validations/open_production_without_preop_rejected
        """
        line, shift, run = self._shift_line_with_queue(api, sanitation=True, preop=False)
        # pre-op exists but stays PENDING
        get_success_data(api.create_preop_inspection(
            create_preop_inspection_payload(shift["id"], line["id"]), QA))
        resp = api.transition_shift(shift["id"], {"to_status": "RUNNING"}, SUP)
        validate_error(resp, ApiErrorId.ERR_PREOP_NOT_PASSED)
        after = get_success_data(api.get_shift(shift["id"], SUP))
        assert after["status"] == "SCHEDULED"

    def test_open_production_without_verified_sanitation_rejected(self, api):
        """PRD §3.2: "then, for every line referenced by a `QUEUED` run, at
        least one sanitation run must be `VERIFIED` for that shift and line,
        else `ERR_SANITATION_NOT_VERIFIED` — the sanitation gate is checked
        before the pre-op gate".

        Design: Corner/validations/open_production_without_verified_sanitation_rejected
        """
        line = make_line()
        shift = make_shift()
        # Sanitation COMPLETED but never VERIFIED
        run_san = get_success_data(api.create_sanitation_run(
            create_sanitation_run_payload(shift["id"], line["id"]), SAN))
        san = make_sanitation_lead_headers("san-1")
        get_success_data(api.advance_sanitation_run(run_san["id"], {"to_status": "IN_PROGRESS"}, san))
        get_success_data(api.advance_sanitation_run(run_san["id"], {"to_status": "COMPLETED"}, san))
        get_success_data(api.create_preop_inspection(
            create_preop_inspection_payload(shift["id"], line["id"]), QA))
        lot = book_and_receive_lot(shift["id"])
        queue_run(shift["id"], line["id"], lot["id"])

        resp = api.transition_shift(shift["id"], {"to_status": "RUNNING"}, SUP)
        validate_error(resp, ApiErrorId.ERR_SANITATION_NOT_VERIFIED)
        after = get_success_data(api.get_shift(shift["id"], SUP))
        assert after["status"] == "SCHEDULED"

    def test_open_production_no_queued_runs_rejected(self, api):
        """PRD §3.2: "at least one line run must be `QUEUED` for the shift,
        else `ERR_NO_RUNS_QUEUED` — this empty-set check runs first among the
        gates".

        Design: Corner/validations/open_production_no_queued_runs_rejected
        """
        line = make_line()
        shift = make_shift()
        create_passed_preop(shift["id"], line["id"])
        resp = api.transition_shift(shift["id"], {"to_status": "RUNNING"}, SUP)
        validate_error(resp, ApiErrorId.ERR_NO_RUNS_QUEUED)
        after = get_success_data(api.get_shift(shift["id"], SUP))
        assert after["status"] == "SCHEDULED"

    def test_open_production_twice_rejected(self, api):
        """PRD §3.2: "the shift must currently be `SCHEDULED`, else
        `ERR_SHIFT_NOT_OPENABLE`".
        PRD §3.5: "One classification rule pins an ambiguity in the lifecycle
        payload: a transition request targeting `RUNNING` from a state that is
        neither `SCHEDULED` nor `SUSPENDED` is classified by what it carries —
        carrying `resolution_note` makes it a resume attempt, rejected with
        `ERR_SHIFT_NOT_SUSPENDED`; without `resolution_note` it is an open
        attempt, rejected with `ERR_SHIFT_NOT_OPENABLE`."

        Design: Corner/validations/open_production_twice_rejected
        """
        line, shift, run = self._shift_line_with_queue(api, sanitation=True, preop=True)
        opened = open_shift(shift["id"])
        assert opened["status"] == "RUNNING"
        resp = api.transition_shift(shift["id"], {"to_status": "RUNNING"}, SUP)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPENABLE)
        after = get_success_data(api.get_shift(shift["id"], SUP))
        assert after["status"] == "RUNNING"
