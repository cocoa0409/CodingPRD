"""Cross-cutting claims: optimistic concurrency, version bumps on cascades,
immediate read consistency."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan_payload, create_simulation_payload, complete_simulation_payload,
    setup_patient, setup_machine, setup_course, setup_course_with_simulation,
    setup_approved_contour, setup_course_in_planning,
    setup_treatment_ready_linac, book_session, deliver_session,
)

SCHED = TEST_USERS["scheduler_headers"]
ONC_A = TEST_USERS["oncologist_headers"]
ONC_B = TEST_USERS["oncologist_b_headers"]
DOS_A = TEST_USERS["dosimetrist_headers"]
RTT_A = TEST_USERS["therapist_headers"]
BILL = TEST_USERS["billing_headers"]


class TestOptimisticConcurrency:
    def test_occ_plan_create_stale_course_version(self):
        """PRD §2.7: "creating a treatment plan for a course requires the
        request to carry `expected_course_version`, the course `version` the
        client last observed. If another writer has advanced the course's
        version since that observation ... the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)". PRD §3.4: "the create increments the
        course's `version` by 1".

        Design: Corner/cross_cutting_layers/occ_plan_create_stale_course_version
        """
        ctx = setup_course_in_planning(mrn="MRN-X1", total_dose=2000, fractions=10)
        observed = ctx["course"]["version"]
        plan1 = get_success_data(api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=2000, planned_fractions=10,
                                expected_course_version=observed),
            DOS_A))
        assert plan1["plan_version"] == 1
        resp = api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=2000, planned_fractions=10,
                                expected_course_version=observed),
            DOS_A)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        plans = validate_paginated(api_client.list_plans(ctx["course"]["id"], ONC_A))[0]
        assert len(plans) == 1, "the stale replay must not create a second plan"

    def test_occ_finalize_stale_claim_version(self):
        """PRD §2.7: "finalizing a billing claim requires `expected_claim_version`
        matching the claim's current `version`; because a prior finalize, or an
        auto-reopen that appended new charge lines, legitimately changes the
        claim's totals, a stale finalize is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412)". PRD §3.9: "Finalizing also increments
        the claim's `version` by one."

        Design: Corner/cross_cutting_layers/occ_finalize_stale_claim_version
        """
        pat = setup_patient(mrn="MRN-X2")
        course = setup_course(pat["id"])
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-X2", room="SIM1")
        sim = get_success_data(api_client.create_simulation(
            course["id"], create_simulation_payload(machine_id=sim_m["id"]), SCHED))
        claim = get_success_data(api_client.create_claim(course["id"], BILL))
        get_success_data(api_client.complete_simulation(
            sim["id"], complete_simulation_payload(patient_weight_kg=80.0), RTT_A))
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        v_observed = claim_now["version"]
        fin = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": v_observed}, BILL))
        assert fin["status"] == "FINALIZED"
        get_success_data(api_client.reopen_claim(claim["id"], BILL))
        resp = api_client.finalize_claim(
            claim["id"], {"expected_claim_version": v_observed}, BILL)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        claim_after = get_success_data(api_client.get_claim(claim["id"], BILL))
        assert claim_after["status"] == "DRAFT"

    def test_version_increments_on_cascaded_mutation(self):
        """PRD §2.4: "`version` is an integer that increments on every mutation
        of the resource" and "Wherever §3 describes a cascade (a course counter
        advancing, a plan being superseded, a claim auto-reopening), each
        affected resource independently refreshes its `updated_at` and
        increments its `version`." A fresh course reads version 1; the
        CONSULT→SIMULATION_SCHEDULED auto-transition bumps to 2; the
        SIMULATION_SCHEDULED→SIMULATED auto-transition bumps to 3.

        Design: Corner/cross_cutting_layers/version_increments_on_cascaded_mutation
        """
        pat = setup_patient(mrn="MRN-X3")
        course = get_success_data(api_client.create_course(
            pat["id"],
            {"diagnosis_code": "C61", "intent": "CURATIVE", "technique": "IMRT",
             "prescribed_total_dose_cGy": 2000, "planned_fractions": 10},
            ONC_A))
        assert course["version"] == 1
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-X3", room="SIM1")
        sim = get_success_data(api_client.create_simulation(
            course["id"], create_simulation_payload(machine_id=sim_m["id"],
                                                    immobilization_device="NONE"),
            SCHED))
        v2 = get_success_data(api_client.get_course(course["id"], SCHED))["version"]
        assert v2 == 2, "first booking auto-transition bumps version by 1"
        get_success_data(api_client.complete_simulation(
            sim["id"], complete_simulation_payload(patient_weight_kg=80.0), RTT_A))
        v3 = get_success_data(api_client.get_course(course["id"], SCHED))["version"]
        assert v3 == 3, "completion auto-transition bumps version by 1 again"


class TestImmediateConsistency:
    def test_deliver_counters_immediately_visible(self):
        """PRD §3.7: "A successful delivery writes the session's
        `dose_delivered_cGy` ... and advances the course: `delivered_fractions`
        increments by one, `delivered_dose_cGy` grows by the delivered amount,
        and `fractions_since_chart_review` increments by one." The read issued
        directly after the deliver call reflects all three mutations.

        Design: Corner/consistency_model/deliver_counters_immediately_visible
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-CM-1", total_dose=2000, fractions=10)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                            "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        deliver_session(sess["id"])
        course = get_success_data(api_client.get_course(ctx["course"]["id"], RTT_A))
        assert course["delivered_fractions"] == 1
        assert course["delivered_dose_cGy"] == 200
        assert course["fractions_since_chart_review"] == 1
