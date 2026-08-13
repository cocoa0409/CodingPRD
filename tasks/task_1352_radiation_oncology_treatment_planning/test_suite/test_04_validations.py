"""Validation claims: auth headers, role gates, conditional rules, referential
integrity, course-state gates, machine constraints, schema rules."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated, build_user_headers, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_patient_payload, create_course_payload, create_simulation_payload,
    create_plan_payload, create_dose_constraint_payload,
    create_contour_set_payload, complete_simulation_payload,
    create_machine_payload, create_fraction_session_payload,
    setup_patient, setup_machine, setup_course, setup_course_with_simulation,
    setup_approved_contour, setup_course_in_planning, setup_planning_with_draft_plan,
    setup_submitted_plan, setup_approved_plan, setup_treatment_ready_linac,
    setup_on_treatment, book_session, deliver_session,
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


class TestUserContext:
    def test_unknown_role_rejected_as_invalid_context(self):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/unknown_role_rejected_as_invalid_context
        """
        bad_headers = build_user_headers("someone", "UnregisteredRole")
        resp = api_client.create_patient(
            create_patient_payload(mrn="MRN-V1", full_name="Val One"), bad_headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)

    def test_forbidden_role_precedes_not_found(self):
        """PRD §2.5: "Every request that survives transport is validated in a
        fixed, system-wide priority order; when several checks could reject the
        same request, the earliest category in this cascade wins and produces
        the error". Category 2 is "Whether the declared role may perform the
        operation — `ERR_FORBIDDEN_ROLE` (HTTP 403)" and category 3 is
        existence — `ERR_NOT_FOUND` (HTTP 404). A Scheduler creating a course
        under a non-existent patient id therefore yields ERR_FORBIDDEN_ROLE.

        Design: Corner/validations/forbidden_role_precedes_not_found
        """
        resp = api_client.create_course(
            "00000000-0000-4000-8000-00000000dead",
            create_course_payload(technique="IMRT", prescribed_total_dose_cGy=2000,
                                  planned_fractions=10),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestConditionalMachineRules:
    def test_sbrt_immobilization_required(self):
        """PRD §3.2: "courses prescribed with the `SBRT` technique accept only
        `THERMOPLASTIC_MASK` or `BODY_FRAME`, and any other device on an SBRT
        course is rejected with `ERR_IMMOBILIZATION_REQUIRED`."

        Design: Corner/validations/sbrt_immobilization_required
        """
        pat = setup_patient(mrn="MRN-V3")
        course = setup_course(pat["id"], technique="SBRT",
                              prescribed_total_dose_cGy=3000, planned_fractions=5,
                              diagnosis_code="C34")
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-V3", room="SIM1")
        for device in ("NONE", "VACUUM_CRADLE"):
            resp = api_client.create_simulation(
                course["id"],
                create_simulation_payload(machine_id=sim_m["id"],
                                          start_time="2026-08-03T09:00:00Z",
                                          end_time="2026-08-03T09:30:00Z",
                                          immobilization_device=device),
                SCHED)
            validate_error(resp, ApiErrorId.ERR_IMMOBILIZATION_REQUIRED, expected_status=422)
        ok = validate_success(api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:00:00Z",
                                      end_time="2026-08-03T09:30:00Z",
                                      immobilization_device="BODY_FRAME"),
            SCHED), expected_status=201)
        assert ok["status"] == "SCHEDULED"

    def test_fraction_on_simulator_rejected(self):
        """PRD §3.6: "The machine must be a `LINAC` (`ERR_MACHINE_TYPE_MISMATCH`
        on a simulator) and `OPERATIONAL` (`ERR_MACHINE_NOT_OPERATIONAL`)."

        Design: Corner/validations/fraction_on_simulator_rejected
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-V4", total_dose=2000, fractions=10)
        resp = api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["sim_machine"]["id"],
                                            start_time="2026-08-03T10:00:00Z",
                                            end_time="2026-08-03T10:20:00Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_MACHINE_TYPE_MISMATCH, expected_status=422)

    def test_sim_booking_on_down_machine_rejected(self):
        """PRD §3.2: the referenced machine "must be `OPERATIONAL`, since a
        `DOWN` machine rejects new bookings with `ERR_MACHINE_NOT_OPERATIONAL`."

        Design: Corner/validations/sim_booking_on_down_machine_rejected
        """
        pat = setup_patient(mrn="MRN-V13")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-V13", room="SIM1")
        get_success_data(api_client.set_machine_status(sim_m["id"], {"status": "DOWN"}, ADMIN))
        resp = api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:00:00Z",
                                      end_time="2026-08-03T09:30:00Z",
                                      immobilization_device="NONE"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_OPERATIONAL, expected_status=422)
        get_success_data(api_client.set_machine_status(sim_m["id"], {"status": "OPERATIONAL"}, ADMIN))
        ok = validate_success(api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:00:00Z",
                                      end_time="2026-08-03T09:30:00Z",
                                      immobilization_device="NONE"),
            SCHED), expected_status=201)
        assert ok["status"] == "SCHEDULED"

    def test_machine_down_twice_and_restore_when_operational_rejected(self):
        """PRD §3.6: "setting `DOWN` requires the machine currently `OPERATIONAL`
        (`ERR_MACHINE_ALREADY_DOWN`, HTTP 409, otherwise) and ... restoring
        `OPERATIONAL` requires the machine currently `DOWN`
        (`ERR_MACHINE_NOT_DOWN`)."

        Design: Corner/validations/machine_down_twice_and_restore_when_operational_rejected
        """
        m = setup_machine("LINAC", name="Linac-V18", room="TX9")
        get_success_data(api_client.set_machine_status(m["id"], {"status": "DOWN"}, ADMIN))
        resp1 = api_client.set_machine_status(m["id"], {"status": "DOWN"}, ADMIN)
        validate_error(resp1, ApiErrorId.ERR_MACHINE_ALREADY_DOWN, expected_status=409)
        get_success_data(api_client.set_machine_status(m["id"], {"status": "OPERATIONAL"}, ADMIN))
        resp2 = api_client.set_machine_status(m["id"], {"status": "OPERATIONAL"}, ADMIN)
        validate_error(resp2, ApiErrorId.ERR_MACHINE_NOT_DOWN, expected_status=409)


class TestCourseStateGates:
    def test_adaptation_check_requires_on_treatment(self):
        """PRD §3.8: "The course must be `ON_TREATMENT`
        (`ERR_COURSE_NOT_ON_TREATMENT`) and necessarily has its
        `baseline_weight_kg` set, since reaching `ON_TREATMENT` implies a
        completed simulation." A PLANNING course (never delivered) is rejected
        regardless of the weight numbers supplied.

        Design: Corner/validations/adaptation_check_requires_on_treatment
        """
        ctx = setup_course_in_planning(mrn="MRN-V5", total_dose=2000, fractions=10)
        resp = api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 60.0}, ONC_A)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_ON_TREATMENT, expected_status=409)
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["status"] == "PLANNING"

    def test_plan_create_before_planning_state_wins_over_contour_check(self):
        """PRD §2.5: "Every request that survives transport is validated in a
        fixed, system-wide priority order; when several checks could reject the
        same request, the earliest category in this cascade wins and produces
        the error" — category 6 "State gates" precedes category 10
        "Cross-reference integrity". PRD §3.4: "an initial plan (no
        supersession) requires the course to be in `PLANNING` —
        `ERR_COURSE_NOT_PLANNING` (HTTP 409) otherwise". Creating a plan while
        the course is CONTOURING with a merely SUBMITTED contour therefore
        reports ERR_COURSE_NOT_PLANNING.

        Design: Corner/validations/plan_create_before_planning_state_wins_over_contour_check
        """
        pat = setup_patient(mrn="MRN-V6")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-V6", room="SIM1")
        setup_course_with_simulation(course["id"], sim_m["id"])
        cs = get_success_data(api_client.create_contour_set(
            course["id"], create_contour_set_payload(), ONC_A))
        get_success_data(api_client.submit_contour_set(cs["id"], ONC_A))
        course_now = get_success_data(api_client.get_course(course["id"], ONC_A))
        assert course_now["status"] == "CONTOURING"
        resp = api_client.create_plan(
            course["id"],
            create_plan_payload(contour_set_id=cs["id"], target_total_dose_cGy=2000,
                                planned_fractions=10,
                                expected_course_version=course_now["version"]),
            DOS_A)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_PLANNING, expected_status=409)

    def test_adaptation_plan_requires_adapting_state(self):
        """PRD §3.4: "an adaptation plan requires the course to be in
        `ADAPTATION_REQUIRED` — `ERR_COURSE_NOT_ADAPTING` (HTTP 409) otherwise".

        Design: Corner/validations/adaptation_plan_requires_adapting_state
        """
        ctx = setup_on_treatment(num_delivered=1, total_dose=2000, fractions=10, mrn="MRN-V7")
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["status"] == "ON_TREATMENT"
        resp = api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=1800, planned_fractions=9,
                                supersedes_plan_id=ctx["plan"]["id"],
                                expected_course_version=course["version"]),
            DOS_A)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_ADAPTING, expected_status=409)
        plans = validate_paginated(api_client.list_plans(ctx["course"]["id"], ONC_A))[0]
        assert len(plans) == 1, "no plan may be created"

    def test_plan_create_with_unapproved_contour_rejected(self):
        """PRD §3.4: "the contour set must belong to the same course and be
        `APPROVED`, else `ERR_CONTOUR_NOT_APPROVED` (HTTP 422)".

        Design: Corner/validations/plan_create_with_unapproved_contour_rejected
        """
        ctx = setup_course_in_planning(mrn="MRN-V8", total_dose=2000, fractions=10)
        cs2 = get_success_data(api_client.create_contour_set(
            ctx["course"]["id"], create_contour_set_payload(set_label="CT1-alt"), ONC_A))
        assert cs2["status"] == "DRAFT"
        course_now = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course_now["status"] == "PLANNING"
        resp = api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=cs2["id"], target_total_dose_cGy=2000,
                                planned_fractions=10,
                                expected_course_version=course_now["version"]),
            DOS_A)
        validate_error(resp, ApiErrorId.ERR_CONTOUR_NOT_APPROVED, expected_status=422)

    def test_supersedes_not_latest_rejected(self):
        """PRD §3.4: "when `supersedes_plan_id` is present it must reference the
        highest-`plan_version` plan of the same course, else
        `ERR_SUPERSEDES_NOT_LATEST` (HTTP 422)".

        Design: Corner/validations/supersedes_not_latest_rejected
        """
        ctx = setup_on_treatment(num_delivered=1, total_dose=2000, fractions=10, mrn="MRN-V9")
        plan_a = ctx["plan"]
        adapt1 = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 79.0, "physician_override": True}, ONC_A))
        plan_b = get_success_data(api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=1800, planned_fractions=9,
                                supersedes_plan_id=plan_a["id"],
                                expected_course_version=adapt1["version"]),
            DOS_A))
        get_success_data(api_client.create_dose_constraint(
            plan_b["id"], create_dose_constraint_payload(limit_cGy=1800,
                                                         evaluated_value_cGy=1400), DOS_A))
        get_success_data(api_client.submit_plan_for_check(plan_b["id"], DOS_A))
        get_success_data(api_client.create_physics_check(
            plan_b["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, PHYS_A))
        get_success_data(api_client.create_physics_check(
            plan_b["id"], {"check_type": "SECOND", "outcome": "PASS"}, PHYS_B))
        f2 = book_session(ctx["course"]["id"], plan_b["id"], ctx["linac"]["id"],
                          "2026-08-05T09:00:00Z", "2026-08-05T09:20:00Z")
        deliver_session(f2["id"])
        adapt2 = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 78.0, "physician_override": True}, ONC_A))
        assert adapt2["status"] == "ADAPTATION_REQUIRED"
        # referencing plan v1 (not the highest) must fail
        resp = api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=1600, planned_fractions=8,
                                supersedes_plan_id=plan_a["id"],
                                expected_course_version=adapt2["version"]),
            DOS_A)
        validate_error(resp, ApiErrorId.ERR_SUPERSEDES_NOT_LATEST, expected_status=422)


class TestBookingConstraints:
    def test_weekend_booking_without_allowance_rejected(self):
        """PRD §3.6: "a booking whose `start_time` falls on a UTC Saturday or
        Sunday — the session's derived `is_weekend` flag — requires the course's
        `weekend_makeup_allowance` to be greater than zero, failing with
        `ERR_WEEKEND_NOT_PERMITTED` (HTTP 422) otherwise".

        Design: Corner/validations/weekend_booking_without_allowance_rejected
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-V10", total_dose=2000, fractions=10)
        resp = api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-08T09:00:00Z",  # Saturday
                                            end_time="2026-08-08T09:20:00Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_WEEKEND_NOT_PERMITTED, expected_status=422)
        mon = validate_success(api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-10T09:00:00Z",  # Monday
                                            end_time="2026-08-10T09:20:00Z"),
            SCHED), expected_status=201)
        assert mon["status"] == "SCHEDULED"


class TestClaimGates:
    def test_empty_claim_finalize_rejected(self):
        """PRD §3.9: the claim "must hold at least one charge line
        (`ERR_EMPTY_CLAIM`, HTTP 422)" at finalize.

        Design: Corner/validations/empty_claim_finalize_rejected
        """
        pat = setup_patient(mrn="MRN-V11")
        course = setup_course(pat["id"])
        claim = get_success_data(api_client.create_claim(course["id"], BILL))
        resp = api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, BILL)
        validate_error(resp, ApiErrorId.ERR_EMPTY_CLAIM, expected_status=422)
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        assert claim_now["status"] == "DRAFT"

    def test_claim_already_open_rejected(self):
        """PRD §3.9: "A course may have only one open claim — one in `DRAFT` or
        `FINALIZED` status — and opening a second is rejected with
        `ERR_CLAIM_ALREADY_OPEN` (HTTP 422)."

        Design: Corner/validations/claim_already_open_rejected
        """
        pat = setup_patient(mrn="MRN-V12")
        course = setup_course(pat["id"])
        get_success_data(api_client.create_claim(course["id"], BILL))
        resp = api_client.create_claim(course["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_OPEN, expected_status=422)


class TestSchemaRules:
    def test_invalid_time_range_rejected(self):
        """PRD §2.5 (priority 4): "Required fields present, types correct, enum
        values within their declared domains, `end_time` strictly after
        `start_time`, and numeric ranges respected ... — `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/validations/invalid_time_range_rejected
        """
        pat = setup_patient(mrn="MRN-V14")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-V14", room="SIM1")
        resp = api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:30:00Z",
                                      end_time="2026-08-03T09:30:00Z",
                                      immobilization_device="NONE"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestDoseConstraintGates:
    def test_dose_constraint_violation_blocks_submit(self):
        """PRD §3.5: "every constraint must have `satisfied` true
        (`ERR_DOSE_CONSTRAINT_VIOLATION`, HTTP 422)". PRD §3.4: "The system
        derives `satisfied` as true exactly when the evaluated value is no
        greater than the limit — equality satisfies." An evaluated value of
        4501 against a limit of 4500 is a violation.

        Design: Corner/validations/dose_constraint_violation_blocks_submit
        """
        ctx = setup_planning_with_draft_plan(mrn="MRN-V15", total_dose=4000, fractions=8)
        dc = get_success_data(api_client.create_dose_constraint(
            ctx["plan"]["id"],
            create_dose_constraint_payload(limit_cGy=4500, evaluated_value_cGy=4501),
            DOS_A))
        assert dc["satisfied"] is False
        resp = api_client.submit_plan_for_check(ctx["plan"]["id"], DOS_A)
        validate_error(resp, ApiErrorId.ERR_DOSE_CONSTRAINT_VIOLATION, expected_status=422)

    def test_no_dose_constraints_blocks_submit(self):
        """PRD §3.5: "at least one dose constraint must exist
        (`ERR_NO_DOSE_CONSTRAINTS`, HTTP 422)" for submit-for-check.

        Design: Corner/validations/no_dose_constraints_blocks_submit
        """
        ctx = setup_planning_with_draft_plan(mrn="MRN-V16", total_dose=4000, fractions=8)
        resp = api_client.submit_plan_for_check(ctx["plan"]["id"], DOS_A)
        validate_error(resp, ApiErrorId.ERR_NO_DOSE_CONSTRAINTS, expected_status=422)

    def test_dose_constraint_on_non_draft_plan_rejected(self):
        """PRD §3.4: "Constraint creation on a plan that has left `DRAFT` is
        rejected with `ERR_PLAN_NOT_DRAFT` (HTTP 409)."

        Design: Corner/validations/dose_constraint_on_non_draft_plan_rejected
        """
        ctx = setup_submitted_plan(mrn="MRN-V17", total_dose=4000, fractions=8)
        resp = api_client.create_dose_constraint(
            ctx["plan"]["id"],
            create_dose_constraint_payload(structure_name="Bowel",
                                           constraint_type="MEAN_DOSE",
                                           limit_cGy=3000, evaluated_value_cGy=2500),
            DOS_A)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT, expected_status=409)
