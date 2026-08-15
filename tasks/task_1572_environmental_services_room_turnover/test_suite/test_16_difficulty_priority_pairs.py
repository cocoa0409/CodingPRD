"""Difficulty queue A — priority_pair_validation_conflict instances."""
from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    get_success_data,
    set_clock,
    validate_error,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    create_all_standards,
    create_bed,
    create_request,
    create_technician,
    create_unit,
    seed_supplies,
    start_request,
)
from test_helpers import make_technician_headers

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


class TestStateErrorBeatsSafetyErrorOnAssign:
    def test_assign_in_progress_reports_not_queued_not_certification(self, api):
        """PRD §2.10: "Only then do state and business rules run. State
        validity comes first ... After state checks, the infection-control
        gates evaluate in a fixed sequence — certification coverage first
        (`ERR_STAFF_CERTIFICATION_MISMATCH`), then STAT-tier eligibility
        (`ERR_STAFF_NOT_STAT_ELIGIBLE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_assign
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies("DISINFECTANT", "PPE_PACK", "CLOTH")
        t1 = create_technician("T1", certifications=["ISO_CERT"])
        t2 = create_technician("T2")  # no ISO_CERT
        get_success_data(
            api.clock_in_staff(t1["id"], make_technician_headers(t1["id"]))
        )
        bi1 = create_bed(unit["id"], "BI1", "ISOLATION")

        req = create_request(bi1["id"], "ISOLATION")
        assign_request(req["id"], t1["id"])
        start_request(req["id"], t1["id"])

        # IN_PROGRESS (state) AND T2 lacks ISO_CERT (safety): state wins.
        r = api.assign_clean_request(req["id"], {"staff_id": t2["id"]}, DISPATCHER)
        validate_error(r, ApiErrorId.ERR_REQUEST_NOT_QUEUED)

        after = get_success_data(api.get_clean_request(req["id"], ANY))
        assert after["status"] == "IN_PROGRESS"
        assert after["assigned_staff_id"] == t1["id"]

    def test_assign_terminal_reports_already_terminal_not_certification(self, api):
        """PRD §2.10: "State validity comes first, and within it a
        terminal-state rejection always precedes a wrong-state rejection: a
        clean request that has reached `VERIFIED` or `CANCELLED` answers
        `ERR_REQUEST_ALREADY_TERMINAL` to any further transition attempt, never
        a wrong-state error."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_assign
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies()
        t1 = create_technician("T1")  # no certs — would fail safety if reached
        bed = create_bed(unit["id"], "B1", "STANDARD")

        # Drive a request to CANCELLED from QUEUED.
        req = create_request(bed["id"], "ROUTINE")
        get_success_data(api.cancel_clean_request(req["id"], DISPATCHER))

        # CANCELLED (terminal) AND T1 lacks ISOLATION coverage: terminal wins.
        r = api.assign_clean_request(req["id"], {"staff_id": t1["id"]}, DISPATCHER)
        validate_error(r, ApiErrorId.ERR_REQUEST_ALREADY_TERMINAL)

        after = get_success_data(api.get_clean_request(req["id"], ANY))
        assert after["status"] == "CANCELLED"
        assert after["assigned_staff_id"] is None


class TestSafetyErrorBeatsTemporalErrorOnAssign:
    def test_certification_mismatch_beats_double_booking(self, api):
        """PRD §2.10: "After state checks, the infection-control gates evaluate
        in a fixed sequence — certification coverage first
        (`ERR_STAFF_CERTIFICATION_MISMATCH`), then STAT-tier eligibility
        (`ERR_STAFF_NOT_STAT_ELIGIBLE`), then the second-set-of-hands rule for
        recleans (`ERR_RECLEAN_SAME_TECHNICIAN`), then segregation between
        auditor and cleaner (`ERR_AUDITOR_IS_CLEANER`). The temporal
        double-booking check (`ERR_STAFF_DOUBLE_BOOKED`) follows."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_assign
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies("DISINFECTANT", "CLOTH")
        t2 = create_technician("T2")  # no certs
        bi1 = create_bed(unit["id"], "BI1", "ISOLATION")
        b2 = create_bed(unit["id"], "B2", "STANDARD")

        # T2 already holds a ROUTINE assignment with window [09:00, 09:45).
        r2 = create_request(b2["id"], "ROUTINE")
        assign_request(r2["id"], t2["id"], planned_start_at="2026-08-01T09:00:00Z")

        # ISOLATION request targeted at T2 with planned_start 09:10: safety and
        # temporal both fail; safety must win.
        r1 = create_request(bi1["id"], "ISOLATION")
        r = api.assign_clean_request(
            r1["id"],
            {"staff_id": t2["id"], "planned_start_at": "2026-08-01T09:10:00Z"},
            DISPATCHER,
        )
        validate_error(r, ApiErrorId.ERR_STAFF_CERTIFICATION_MISMATCH)

        after = get_success_data(api.get_clean_request(r1["id"], ANY))
        assert after["status"] == "QUEUED"
        assert after["assigned_staff_id"] is None

    def test_temporal_error_reported_once_safety_passes(self, api):
        """PRD §3.4: "The **buffer rule** keeps a technician's commitments
        separated. Two planned windows on the same staff member conflict unless
        at least ten full minutes separate them in one direction or the other."
        PRD §2.10: "After state checks, the infection-control gates evaluate in
        a fixed sequence — certification coverage first
        (`ERR_STAFF_CERTIFICATION_MISMATCH`) ... The temporal double-booking
        check (`ERR_STAFF_DOUBLE_BOOKED`) follows."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_assign
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies("DISINFECTANT", "PPE_PACK", "CLOTH")
        # Certified tech: safety passes, so the temporal gate is what fires.
        t1 = create_technician("T1", certifications=["ISO_CERT"])
        bi1 = create_bed(unit["id"], "BI1", "ISOLATION")
        b2 = create_bed(unit["id"], "B2", "STANDARD")

        r2 = create_request(b2["id"], "ROUTINE")
        assign_request(r2["id"], t1["id"], planned_start_at="2026-08-01T09:00:00Z")

        r1 = create_request(bi1["id"], "ISOLATION")
        r = api.assign_clean_request(
            r1["id"],
            {"staff_id": t1["id"], "planned_start_at": "2026-08-01T09:10:00Z"},
            DISPATCHER,
        )
        validate_error(r, ApiErrorId.ERR_STAFF_DOUBLE_BOOKED)

        after = get_success_data(api.get_clean_request(r1["id"], ANY))
        assert after["status"] == "QUEUED"
        assert after["assigned_staff_id"] is None
