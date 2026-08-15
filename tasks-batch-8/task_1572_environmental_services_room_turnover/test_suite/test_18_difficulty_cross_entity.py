"""Difficulty queue A — cross_entity_state_dependency instances."""
from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    get_success_data,
    make_technician_headers,
    set_clock,
    setup_basic_scenario,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    create_request,
    start_request,
    submit_audit,
)

ANY = TEST_USERS["any_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestStartGatedByStaffShiftState:
    def test_start_blocked_while_technician_on_break(self, api):
        """PRD §3.5: "**Starting** a clean requires the request to be
        `ASSIGNED` (`ERR_REQUEST_ALREADY_TERMINAL` when terminal,
        `ERR_REQUEST_NOT_ASSIGNED` otherwise) and the technician to be
        `ON_SHIFT` (`ERR_STAFF_NOT_ON_SHIFT`)."

        Design: Difficulty/cross_entity_state_dependency/start_gated_by_staff_shift_state
        """
        ctx = setup_basic_scenario()
        tech = ctx["tech"]
        th = make_technician_headers(tech["id"])

        # Put the tech ON_BREAK; assignment does not check shift state.
        get_success_data(api.break_start_staff(tech["id"], th))
        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], tech["id"])

        r = api.start_clean_request(req["id"], th)
        validate_error(r, ApiErrorId.ERR_STAFF_NOT_ON_SHIFT)

        after = get_success_data(api.get_clean_request(req["id"], ANY))
        assert after["status"] == "ASSIGNED"

    def test_start_succeeds_after_break_end(self, api):
        """PRD §3.5: "On success the request stamps `started_at` with the
        current clock, ... and moves the bed `VACANT_DIRTY →
        CLEAN_IN_PROGRESS`."
        PRD §3.5: "**Starting** a clean requires the request to be `ASSIGNED`
        (`ERR_REQUEST_ALREADY_TERMINAL` when terminal, `ERR_REQUEST_NOT_ASSIGNED`
        otherwise) and the technician to be `ON_SHIFT` (`ERR_STAFF_NOT_ON_SHIFT`)."

        Design: Difficulty/cross_entity_state_dependency/start_gated_by_staff_shift_state
        """
        ctx = setup_basic_scenario()
        tech = ctx["tech"]
        th = make_technician_headers(tech["id"])

        get_success_data(api.break_start_staff(tech["id"], th))
        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], tech["id"])

        r = api.start_clean_request(req["id"], th)
        validate_error(r, ApiErrorId.ERR_STAFF_NOT_ON_SHIFT)

        get_success_data(api.break_end_staff(tech["id"], th))
        started = validate_success(api.start_clean_request(req["id"], th))
        assert started["status"] == "IN_PROGRESS"
        bed = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
        assert bed["bed_status"] == "CLEAN_IN_PROGRESS"


class TestAuditGatedByRequestPendingQa:
    def test_audit_rejected_while_request_in_progress(self, api):
        """PRD §3.6: "A `QualityAuditor` submits a **quality audit** against a
        request in `PENDING_QA` (`ERR_REQUEST_NOT_PENDING_QA` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/audit_gated_by_request_pending_qa
        """
        ctx = setup_basic_scenario()
        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])

        from test_helpers import make_auditor_headers

        r = api.create_quality_audit(
            {
                "clean_request_id": req["id"],
                "audit_method": "ATP_SWAB",
                "rlu_reading": 100,
            },
            make_auditor_headers(ctx["auditor"]["id"]),
        )
        validate_error(r, ApiErrorId.ERR_REQUEST_NOT_PENDING_QA)

        after = get_success_data(api.get_clean_request(req["id"], ANY))
        assert after["status"] == "IN_PROGRESS"

    def test_identical_audit_succeeds_after_complete(self, api):
        """PRD §3.6: "A `QualityAuditor` submits a **quality audit** against a
        request in `PENDING_QA` (`ERR_REQUEST_NOT_PENDING_QA` otherwise)."
        PRD §3.6: "A **PASS** cascade closes the loop. The request moves
        `PENDING_QA → VERIFIED` and stamps `verified_at`. ... The bed moves
        `AWAITING_VERIFICATION → READY`."

        Design: Difficulty/cross_entity_state_dependency/audit_gated_by_request_pending_qa
        """
        ctx = setup_basic_scenario()
        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])

        from test_helpers import make_auditor_headers

        r = api.create_quality_audit(
            {
                "clean_request_id": req["id"],
                "audit_method": "ATP_SWAB",
                "rlu_reading": 100,
            },
            make_auditor_headers(ctx["auditor"]["id"]),
        )
        validate_error(r, ApiErrorId.ERR_REQUEST_NOT_PENDING_QA)

        set_clock("2026-08-01T08:45:00Z")
        from test_helpers.fixtures import complete_request

        complete_request(req["id"], ctx["tech"]["id"])
        submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=100)

        final = get_success_data(api.get_clean_request(req["id"], ANY))
        assert final["status"] == "VERIFIED"
        bed = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
        assert bed["bed_status"] == "READY"
