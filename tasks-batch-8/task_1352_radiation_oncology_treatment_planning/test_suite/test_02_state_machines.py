"""State-machine claims: initial states, invalid transitions, side effects."""
import pytest
from datetime import date

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    ApiErrorId, TEST_USERS,
    create_patient_payload, create_course_payload, create_simulation_payload,
    complete_simulation_payload, create_contour_set_payload, create_plan_payload,
    create_dose_constraint_payload, create_interruption_payload,
    create_chart_review_payload, create_fraction_session_payload,
    setup_patient, setup_machine, setup_course, setup_course_with_simulation,
    setup_approved_contour, setup_course_in_planning, setup_planning_with_draft_plan,
    setup_submitted_plan, setup_approved_plan, setup_treatment_ready_linac,
    setup_on_treatment, book_session, deliver_session, weekday_slot,
)

SCHED = TEST_USERS["scheduler_headers"]
ONC_A = TEST_USERS["oncologist_headers"]
ONC_B = TEST_USERS["oncologist_b_headers"]
DOS_A = TEST_USERS["dosimetrist_headers"]
PHYS_A = TEST_USERS["physicist_headers"]
PHYS_B = TEST_USERS["physicist_b_headers"]
RTT_A = TEST_USERS["therapist_headers"]
BILL = TEST_USERS["billing_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestSimulationLifecycle:
    def test_simulation_initial_state_and_course_advance(self):
        """PRD §3.2: "An appointment is born `SCHEDULED`" and "The first booking
        flips the course automatically from `CONSULT` to `SIMULATION_SCHEDULED`."

        Design: Corner/state_machines/simulation_initial_state_is_scheduled
        """
        pat = setup_patient(mrn="MRN-S1")
        course = setup_course(pat["id"], technique="IMRT",
                              prescribed_total_dose_cGy=2000, planned_fractions=10)
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-S1", room="SIM1")
        resp = api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-07-30T09:00:00Z",
                                      end_time="2026-07-30T09:30:00Z",
                                      immobilization_device="THERMOPLASTIC_MASK"),
            SCHED)
        sim = validate_success(resp, expected_status=201)
        assert sim["status"] == "SCHEDULED"
        course_now = get_success_data(api_client.get_course(course["id"], SCHED))
        assert course_now["status"] == "SIMULATION_SCHEDULED"

    def test_simulation_double_complete_rejected(self):
        """PRD §3.2: "Completion is rejected with `ERR_SIMULATION_NOT_SCHEDULED`
        (HTTP 409) unless the appointment is `SCHEDULED`" — a COMPLETED
        appointment is terminal, so a second complete fails and the recorded
        weight is not overwritten.

        Design: Corner/state_machines/simulation_double_complete_rejected
        """
        pat = setup_patient(mrn="MRN-S2")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-S2", room="SIM1")
        sim = setup_course_with_simulation(course["id"], sim_m["id"], weight=80.0)
        resp = api_client.complete_simulation(
            sim["id"], complete_simulation_payload(patient_weight_kg=99.9), RTT_A)
        validate_error(resp, ApiErrorId.ERR_SIMULATION_NOT_SCHEDULED, expected_status=409)
        lst = validate_paginated(api_client.list_simulations(course["id"], SCHED))[0]
        assert lst[0]["patient_weight_kg"] == 80.0, "weight must not be overwritten"


class TestDeliveryGates:
    def test_deliver_cancelled_session_rejected(self):
        """PRD §3.7: "the session must be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`,
        HTTP 409 — the same gate guards cancellation and no-show marking)".

        Design: Corner/state_machines/deliver_cancelled_session_rejected
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-S3", total_dose=2000, fractions=10)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                            "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        get_success_data(api_client.cancel_fraction(sess["id"], {"reason": "PATIENT"}, SCHED))
        resp = api_client.deliver_fraction(sess["id"], RTT_A)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED, expected_status=409)
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["delivered_fractions"] == 0, "no delivery counters may mutate"

    def test_first_delivery_flips_plan_active_course_on_treatment(self):
        """PRD §3.7: "The course's first delivered session is doubly significant —
        the course moves `TREATMENT_READY → ON_TREATMENT` and the treating plan
        moves `APPROVED_FOR_DELIVERY → ACTIVE`." Also: "`delivered_fractions`
        increments by one, `delivered_dose_cGy` grows by the delivered amount".

        Design: Corner/state_machines/first_delivery_flips_plan_active_course_on_treatment
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-S11", total_dose=2000, fractions=10)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                            "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        delivered = validate_success(api_client.deliver_fraction(sess["id"], RTT_A))
        assert delivered["status"] == "DELIVERED"
        assert delivered["dose_delivered_cGy"] == 200  # 2000/10 round_half_up
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], DOS_A))
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert plan["status"] == "ACTIVE"
        assert course["status"] == "ON_TREATMENT"
        assert course["delivered_dose_cGy"] == 200


class TestContourLifecycle:
    def test_contour_approve_from_draft_rejected(self):
        """PRD §3.3: "Approval and return require the set to be `SUBMITTED` —
        return additionally tolerates `APPROVED`, reopening an already-approved
        set — and violations surface as `ERR_CONTOUR_NOT_SUBMITTED` (HTTP 409)."

        Design: Corner/state_machines/contour_approve_from_draft_rejected
        """
        pat = setup_patient(mrn="MRN-S4")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-S4", room="SIM1")
        setup_course_with_simulation(course["id"], sim_m["id"])
        cs = get_success_data(api_client.create_contour_set(
            course["id"], create_contour_set_payload(), ONC_A))
        assert cs["status"] == "DRAFT"
        resp = api_client.approve_contour_set(cs["id"], ONC_B)
        validate_error(resp, ApiErrorId.ERR_CONTOUR_NOT_SUBMITTED, expected_status=409)
        cs_now = get_success_data(api_client.get_contour_set(cs["id"], ONC_A))
        assert cs_now["status"] == "DRAFT"

    def test_contour_return_resubmit_cycle_bumps_version(self):
        """PRD §3.3: "submission moves `DRAFT → SUBMITTED` (and likewise
        `RETURNED → SUBMITTED` on resubmission)" and "Every mutation of a contour
        set bumps its `version`".

        Design: Corner/state_machines/contour_return_resubmit_cycle_bumps_version
        """
        pat = setup_patient(mrn="MRN-S10")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-S10", room="SIM1")
        setup_course_with_simulation(course["id"], sim_m["id"])
        cs = get_success_data(api_client.create_contour_set(
            course["id"], create_contour_set_payload(), ONC_A))
        submitted = get_success_data(api_client.submit_contour_set(cs["id"], ONC_A))
        v2 = submitted["version"]
        returned = get_success_data(api_client.return_contour_set(
            cs["id"], {"return_notes": "widen margin"}, ONC_B))
        assert returned["status"] == "RETURNED"
        assert returned["version"] == v2 + 1, "return bumps version by 1"
        resubmitted = get_success_data(api_client.submit_contour_set(cs["id"], ONC_A))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["version"] == v2 + 2, "resubmission bumps version again"


class TestPlanCheckLifecycle:
    def test_second_check_before_primary_rejected(self):
        """PRD §3.5: "The check type must match the plan's awaiting state: a
        `PRIMARY` check is recordable only while the plan is
        `PENDING_PRIMARY_CHECK`, and a `SECOND` check only while
        `PENDING_SECOND_CHECK`; a mismatched check is rejected with
        `ERR_PLAN_NOT_AWAITING_CHECK` (HTTP 409)."

        Design: Corner/state_machines/physics_second_check_before_primary_rejected
        """
        ctx = setup_submitted_plan(mrn="MRN-S5", total_dose=4000, fractions=8)
        plan = ctx["plan"]
        resp = api_client.create_physics_check(
            plan["id"], {"check_type": "SECOND", "outcome": "PASS"}, PHYS_B)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_AWAITING_CHECK, expected_status=409)
        plan_now = get_success_data(api_client.get_plan(plan["id"], DOS_A))
        assert plan_now["status"] == "PENDING_PRIMARY_CHECK"
        checks = validate_success(api_client.list_physics_checks(plan["id"], ONC_A))
        assert checks == [], "no PhysicsCheck record may be persisted"

    def test_plan_revise_from_draft_rejected(self):
        """PRD §3.5: "revision from any other state is rejected with
        `ERR_PLAN_NOT_REVISABLE` (HTTP 409)" — only a `CHECK_FAILED` plan may be
        revised, so revising a `DRAFT` plan fails.

        Design: Corner/state_machines/plan_revise_from_draft_rejected
        """
        ctx = setup_planning_with_draft_plan(mrn="MRN-S6", total_dose=4000, fractions=8)
        plan = ctx["plan"]
        resp = api_client.revise_plan(plan["id"], DOS_A)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_REVISABLE, expected_status=409)
        plan_now = get_success_data(api_client.get_plan(plan["id"], DOS_A))
        assert plan_now["status"] == "DRAFT"


class TestBillingLifecycle:
    def test_claim_submit_from_draft_rejected(self):
        """PRD §3.9: "Submission, the terminal step, requires a `FINALIZED`
        claim (`ERR_CLAIM_NOT_FINALIZED`) and a course that has reached
        `COMPLETED` or `DISCONTINUED` (`ERR_COURSE_NOT_TERMINAL`, HTTP 409)".

        Design: Corner/state_machines/claim_submit_from_draft_rejected
        """
        pat = setup_patient(mrn="MRN-S7")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-S7", room="SIM1")
        sim = get_success_data(api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"]), SCHED))
        claim = get_success_data(api_client.create_claim(course["id"], BILL))
        get_success_data(api_client.complete_simulation(
            sim["id"], complete_simulation_payload(patient_weight_kg=80.0), RTT_A))
        resp = api_client.submit_claim(claim["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FINALIZED, expected_status=409)
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        assert claim_now["status"] == "DRAFT"


class TestCourseTermination:
    def test_discontinued_course_rejects_new_bookings(self):
        """PRD §3.9: "Discontinuation ... runs the full teardown cascade: every
        `SCHEDULED` simulation appointment is cancelled (recorded as `OTHER`)".
        PRD §3.2: completion is rejected "with `ERR_COURSE_TERMINAL` (HTTP 409)
        when the owning course is already `COMPLETED` or `DISCONTINUED`"; the
        same terminal-course lockout rejects new bookings on a discontinued
        course.

        Design: Corner/state_machines/discontinued_course_rejects_new_bookings
        """
        pat = setup_patient(mrn="MRN-S8")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-S8", room="SIM1")
        sim = get_success_data(api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"]), SCHED))
        disc = validate_success(api_client.discontinue_course(
            course["id"], {"reason": "patient declined"}, ONC_A))
        assert disc["status"] == "DISCONTINUED"
        sims = validate_paginated(api_client.list_simulations(course["id"], SCHED))[0]
        assert sims[0]["status"] == "CANCELLED", "discontinue cascade cancels appointment"
        resp = api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:00:00Z",
                                      end_time="2026-08-03T09:30:00Z",
                                      immobilization_device="NONE"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_COURSE_TERMINAL, expected_status=409)

    def test_complete_course_with_open_sessions_rejected_then_succeeds(self):
        """PRD §3.9: "Completion ... requires the course `ON_TREATMENT`
        (`ERR_COURSE_NOT_ON_TREATMENT`; ...) and no session of the course still
        `SCHEDULED` (`ERR_OPEN_SESSIONS_EXIST`, HTTP 409); the course becomes
        `COMPLETED` and its `ACTIVE` plan becomes `COMPLETED` too."

        Design: Corner/state_machines/complete_course_with_open_sessions_rejected_then_succeeds
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-S9", total_dose=2000, fractions=10)
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        f2 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-04T09:00:00Z", "2026-08-04T09:20:00Z")
        deliver_session(f1["id"])
        resp = api_client.complete_course(ctx["course"]["id"], ONC_A)
        validate_error(resp, ApiErrorId.ERR_OPEN_SESSIONS_EXIST, expected_status=409)
        get_success_data(api_client.cancel_fraction(f2["id"], {"reason": "PATIENT"}, SCHED))
        done = validate_success(api_client.complete_course(ctx["course"]["id"], ONC_A))
        assert done["status"] == "COMPLETED"
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], ONC_A))
        assert plan["status"] == "COMPLETED", "course completion completes the ACTIVE plan"


class TestChartReviewGate:
    def test_chart_review_fail_leaves_gate_counter(self):
        """PRD §3.7: "A `PASS` resets `fractions_since_chart_review` to zero; a
        `FAIL` leaves the counter unchanged."

        Design: Corner/state_machines/chart_review_fail_leaves_gate_counter
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-S12", total_dose=2000, fractions=10)
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        f2 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-04T09:00:00Z", "2026-08-04T09:20:00Z")
        deliver_session(f1["id"])
        deliver_session(f2["id"])
        get_success_data(api_client.create_chart_review(
            ctx["course"]["id"], {"outcome": "FAIL", "notes": "isocenter drift"}, PHYS_A))
        course = get_success_data(api_client.get_course(ctx["course"]["id"], PHYS_A))
        assert course["fractions_since_chart_review"] == 2, "FAIL must not reset the gate"


class TestNoShowBilling:
    def test_no_show_marks_session_and_bills_fee(self):
        """PRD §3.7: "A `RadiationTherapist` may mark a `SCHEDULED` session
        `NO_SHOW`, which — again auto-reopening a `FINALIZED` claim first —
        appends a `NO_SHOW_FEE` line while a `DRAFT` claim exists." The no-show
        fee is 5,000 cents; the session is not a delivery, so
        `delivered_fractions` stays 0.

        Design: Corner/state_machines/no_show_marks_session_and_bills_fee
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-S13", total_dose=2000, fractions=10)
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                            "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        marked = validate_success(api_client.no_show_fraction(sess["id"], RTT_A))
        assert marked["status"] == "NO_SHOW"
        lines = validate_paginated(api_client.list_charge_lines(claim["id"], BILL))[0]
        noshow_lines = [l for l in lines if l["code"] == "NO_SHOW_FEE"]
        assert len(noshow_lines) == 1, "exactly one NO_SHOW_FEE line"
        assert noshow_lines[0]["amount_cents"] == 5000
        assert noshow_lines[0]["event_ref_id"] == sess["id"]
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["delivered_fractions"] == 0


class TestCompensationStrategies:
    def _setup_open_interruption(self, mrn, missed_count=2, technique="IMRT",
                                 total_dose=2000, fractions=10,
                                 start_date="2026-08-04", end_date="2026-08-05",
                                 interrupt_as=None):
        ctx = setup_on_treatment(num_delivered=1, technique=technique,
                                 total_dose=total_dose, fractions=fractions, mrn=mrn)
        creator = interrupt_as or ONC_A
        itr = get_success_data(api_client.create_interruption(
            ctx["course"]["id"],
            create_interruption_payload(reason="PATIENT_ILLNESS", missed_count=missed_count,
                                        start_date=start_date, end_date=end_date),
            creator))
        ctx["interruption"] = itr
        return ctx

    def test_compensate_add_fractions_extends_plan_and_course(self):
        """PRD §3.8: "`ADD_FRACTIONS` adds the `missed_count` to both the
        course's `planned_fractions` and the `ACTIVE` plan's `planned_fractions`,
        leaving the per-fraction dose unchanged" and "The system derives
        `gap_days` as the whole-day difference between the two dates plus one"
        and "`open_interruption_count` decrements by one".

        Design: Corner/state_machines/compensate_add_fractions_extends_plan_and_course
        """
        ctx = self._setup_open_interruption("MRN-S14", missed_count=2)
        itr = ctx["interruption"]
        assert itr["gap_days"] == 2, "2026-08-04..2026-08-05 inclusive == 2"
        done = validate_success(api_client.compensate_interruption(
            itr["id"], {"strategy": "ADD_FRACTIONS"}, ONC_A))
        assert done["status"] == "COMPENSATED"
        assert done["applied_strategy"] == "ADD_FRACTIONS"
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], DOS_A))
        assert course["planned_fractions"] == 12, "10 + 2 missed"
        assert plan["planned_fractions"] == 12, "ACTIVE plan extended by missed_count"
        assert course["dose_per_fraction_cGy"] == 200, "dose per fraction unchanged"
        assert course["open_interruption_count"] == 0

    def test_compensate_dose_increase_reallocates_remaining_dose(self):
        """PRD §3.8: "`DOSE_PER_FRACTION_INCREASE` leaves planned counts untouched
        but reruns the §3.4 allocation over the `ACTIVE` plan's remainder — the
        plan's `target_total_dose_cGy` minus the dose already delivered under
        that plan, spread across its `planned_fractions` minus the count already
        delivered under it, with the same base-then-remainder rule".
        For 2005/10 with 2 delivered: base 201, remainder (2005-402) over 8
        fractions -> round_half_up(1603/8) == 200.

        Design: Corner/state_machines/compensate_dose_increase_reallocates_remaining_dose
        """
        ctx = setup_on_treatment(num_delivered=2, technique="THREE_DCRT",
                                 total_dose=2005, fractions=10, mrn="MRN-S15",
                                 intent="PALLIATIVE", diagnosis_code="C18")
        assert ctx["sessions"][0]["dose_delivered_cGy"] == 201
        assert ctx["sessions"][1]["dose_delivered_cGy"] == 201
        plan0 = get_success_data(api_client.get_plan(ctx["plan"]["id"], DOS_A))
        assert plan0["dose_per_fraction_cGy"] == 201, "round_half_up(2005/10)"
        itr = get_success_data(api_client.create_interruption(
            ctx["course"]["id"],
            create_interruption_payload(reason="PATIENT_ILLNESS", missed_count=1,
                                        start_date="2026-08-05", end_date="2026-08-05"),
            RTT_A))
        done = validate_success(api_client.compensate_interruption(
            itr["id"], {"strategy": "DOSE_PER_FRACTION_INCREASE"}, ONC_A))
        assert done["status"] == "COMPENSATED"
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], DOS_A))
        # round_half_up((2005-402)/8) = round_half_up(200.375) = 200
        assert plan["dose_per_fraction_cGy"] == 200
        assert plan["planned_fractions"] == 10, "counts unchanged"

    def test_weekend_makeup_grants_then_consumes_allowance(self):
        """PRD §3.8: "`WEEKEND_MAKEUP` adds the `missed_count` to the course's
        `weekend_makeup_allowance`, funding the weekend bookings of §3.6."
        PRD §3.6: "a booking whose `start_time` falls on a UTC Saturday or Sunday
        ... requires the course's `weekend_makeup_allowance` to be greater than
        zero, failing with `ERR_WEEKEND_NOT_PERMITTED` (HTTP 422) otherwise, and
        creating such a session decrements the allowance by one."

        Design: Corner/state_machines/weekend_makeup_grants_then_consumes_allowance
        """
        ctx = self._setup_open_interruption("MRN-S16", missed_count=2)
        get_success_data(api_client.compensate_interruption(
            ctx["interruption"]["id"], {"strategy": "WEEKEND_MAKEUP"}, ONC_A))
        # 2026-08-08 is a Saturday, 2026-08-09 a Sunday, 2026-08-15 a Saturday
        sat = get_success_data(api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-08T09:00:00Z",
                                            end_time="2026-08-08T09:20:00Z"),
            SCHED))
        assert sat["is_weekend"] is True
        get_success_data(api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-09T09:00:00Z",
                                            end_time="2026-08-09T09:20:00Z"),
            SCHED))
        resp = api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-15T09:00:00Z",
                                            end_time="2026-08-15T09:20:00Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_WEEKEND_NOT_PERMITTED, expected_status=422)
        course = get_success_data(api_client.get_course(ctx["course"]["id"], SCHED))
        assert course["weekend_makeup_allowance"] == 0, "2 granted - 2 consumed"

    def test_compensate_twice_rejected(self):
        """PRD §3.8: compensation is "applied to an `OPEN` interruption
        (`ERR_INTERRUPTION_NOT_OPEN`, HTTP 409, otherwise)" — a COMPENSATED
        interruption is terminal, so a second compensate is rejected and does
        not re-apply the strategy.

        Design: Corner/state_machines/compensate_twice_rejected
        """
        ctx = self._setup_open_interruption("MRN-S17", missed_count=1,
                                            start_date="2026-08-04", end_date="2026-08-04")
        get_success_data(api_client.compensate_interruption(
            ctx["interruption"]["id"], {"strategy": "ADD_FRACTIONS"}, ONC_A))
        resp = api_client.compensate_interruption(
            ctx["interruption"]["id"], {"strategy": "ADD_FRACTIONS"}, ONC_A)
        validate_error(resp, ApiErrorId.ERR_INTERRUPTION_NOT_OPEN, expected_status=409)
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["planned_fractions"] == 11, "first ADD_FRACTIONS applied exactly once"
