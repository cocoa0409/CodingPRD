"""RBAC claims: role-exclusive denials and segregation-of-duties gates."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated, build_user_headers,
    ApiErrorId, TEST_USERS, make_oncologist_headers, make_dosimetrist_headers,
    make_physicist_headers,
    create_machine_payload, create_contour_set_payload,
    complete_simulation_payload, create_simulation_payload,
    create_dose_constraint_payload,
    setup_patient, setup_machine, setup_course, setup_course_with_simulation,
    setup_course_in_planning, setup_planning_with_draft_plan,
    setup_submitted_plan, setup_treatment_ready_linac, book_session,
)

SCHED = TEST_USERS["scheduler_headers"]
ONC_A = TEST_USERS["oncologist_headers"]
ONC_B = TEST_USERS["oncologist_b_headers"]
DOS_A = TEST_USERS["dosimetrist_headers"]
DOS_B = TEST_USERS["dosimetrist_b_headers"]
PHYS_A = TEST_USERS["physicist_headers"]
PHYS_B = TEST_USERS["physicist_b_headers"]
RTT_A = TEST_USERS["therapist_headers"]
BILL = TEST_USERS["billing_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestRoleExclusiveDenials:
    def test_scheduler_cannot_deliver_fraction(self):
        """PRD §2.1: "an otherwise-authenticated user attempting an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)". PRD §4 restricts POST
        /oncology/fraction-sessions/{id}/deliver ("Deliver a fraction") to the
        RadiationTherapist role, so a Scheduler attempt is rejected 403.

        Design: Corner/rbac/scheduler_cannot_deliver_fraction
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-R1", total_dose=2000, fractions=10)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                            "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        resp = api_client.deliver_fraction(sess["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        sessions = validate_paginated(
            api_client.list_fraction_sessions(ctx["course"]["id"], SCHED))[0]
        assert sessions[0]["status"] == "SCHEDULED", "rejected call must not deliver"

    def test_dosimetrist_cannot_record_physics_check(self):
        """PRD §2.1: "an otherwise-authenticated user attempting an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)". PRD §4 restricts POST
        /oncology/treatment-plans/{id}/physics-checks ("Record a physics check
        (PRIMARY then SECOND)") to the MedicalPhysicist role, so a
        MedicalDosimetrist attempt is rejected 403.

        Design: Corner/rbac/dosimetrist_cannot_record_physics_check
        """
        ctx = setup_submitted_plan(mrn="MRN-R2", total_dose=4000, fractions=8)
        resp = api_client.create_physics_check(
            ctx["plan"]["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, DOS_B)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], DOS_A))
        assert plan["status"] == "PENDING_PRIMARY_CHECK"

    def test_billing_cannot_approve_contour(self):
        """PRD §2.1: "an otherwise-authenticated user attempting an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)". PRD §4 restricts POST /oncology/contour-sets/{id}/approve
        ("Approve contours (different oncologist than creator)") to the
        RadiationOncologist role, so a BillingCoordinator attempt is rejected
        403.

        Design: Corner/rbac/billing_cannot_approve_contour
        """
        pat = setup_patient(mrn="MRN-R3")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-R3", room="SIM1")
        setup_course_with_simulation(course["id"], sim_m["id"])
        cs = get_success_data(api_client.create_contour_set(
            course["id"], create_contour_set_payload(), ONC_A))
        get_success_data(api_client.submit_contour_set(cs["id"], ONC_A))
        resp = api_client.approve_contour_set(cs["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_therapist_cannot_finalize_claim(self):
        """PRD §2.1: "an otherwise-authenticated user attempting an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)". PRD §4 restricts POST /oncology/billing-claims/{id}/finalize
        ("Finalize a claim (OCC-guarded)") to the BillingCoordinator role, so a
        RadiationTherapist attempt is rejected 403.

        Design: Corner/rbac/therapist_cannot_finalize_claim
        """
        pat = setup_patient(mrn="MRN-R4")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-R4", room="SIM1")
        sim = get_success_data(api_client.create_simulation(
            course["id"], create_simulation_payload(machine_id=sim_m["id"]), SCHED))
        claim = get_success_data(api_client.create_claim(course["id"], BILL))
        get_success_data(api_client.complete_simulation(
            sim["id"], complete_simulation_payload(patient_weight_kg=80.0), RTT_A))
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        resp = api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim_now["version"]}, RTT_A)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        claim_after = get_success_data(api_client.get_claim(claim["id"], BILL))
        assert claim_after["status"] == "DRAFT"

    def test_oncologist_cannot_register_machine(self):
        """PRD §2.1: "an otherwise-authenticated user attempting an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)". PRD §4 restricts POST /oncology/machines ("Register a
        treatment machine") to the SystemAdmin role, so a RadiationOncologist
        attempt is rejected 403.

        Design: Corner/rbac/oncologist_cannot_register_machine
        """
        resp = api_client.create_machine(
            create_machine_payload(name="Linac-R5", machine_type="LINAC", room="TX5"),
            ONC_A)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestSegregationOfDuties:
    def test_planner_cannot_primary_check_own_plan(self):
        """PRD §2.9: "The dosimetrist who built a plan may not perform its
        primary physics check — the primary checker's `X-User-ID` must differ
        from the plan's `planner_id`." Violations are "rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

        Design: Corner/rbac/planner_cannot_primary_check_own_plan
        """
        ctx = setup_submitted_plan(mrn="MRN-R6", total_dose=4000, fractions=8)
        # planner_id was recorded from X-User-ID "dos_a"; a physicist-role call
        # carrying the same operator id must be segregated out.
        as_planner = make_physicist_headers("dos_a")
        resp = api_client.create_physics_check(
            ctx["plan"]["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, as_planner)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        checks = validate_success(api_client.list_physics_checks(ctx["plan"]["id"], ONC_A))
        assert checks == [], "no PhysicsCheck may be persisted"

    def test_second_check_requires_different_physicist(self):
        """PRD §2.9: "the physicist who performed the primary check may not
        perform the second check — the second checker's identity must differ
        from the recorded `primary_checker_id`." Violations are "rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

        Design: Corner/rbac/second_check_requires_different_physicist
        """
        ctx = setup_submitted_plan(mrn="MRN-R7", total_dose=4000, fractions=8)
        get_success_data(api_client.create_physics_check(
            ctx["plan"]["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, PHYS_A))
        resp = api_client.create_physics_check(
            ctx["plan"]["id"], {"check_type": "SECOND", "outcome": "PASS"}, PHYS_A)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        get_success_data(api_client.create_physics_check(
            ctx["plan"]["id"], {"check_type": "SECOND", "outcome": "PASS"}, PHYS_B))
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], PHYS_B))
        assert plan["status"] == "APPROVED_FOR_DELIVERY"

    def test_oncologist_cannot_approve_own_contours(self):
        """PRD §2.9: "The oncologist who created a contour set may not approve
        it or return it — the approving or returning `X-User-ID` must differ
        from the set's `created_by_user_id`." Violations are "rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

        Design: Corner/rbac/oncologist_cannot_approve_own_contours
        """
        pat = setup_patient(mrn="MRN-R8")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-R8", room="SIM1")
        setup_course_with_simulation(course["id"], sim_m["id"])
        cs = get_success_data(api_client.create_contour_set(
            course["id"], create_contour_set_payload(), ONC_A))
        get_success_data(api_client.submit_contour_set(cs["id"], ONC_A))
        resp = api_client.approve_contour_set(cs["id"], ONC_A)  # creator onc_a
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        cs_now = get_success_data(api_client.get_contour_set(cs["id"], ONC_A))
        assert cs_now["status"] == "SUBMITTED"
