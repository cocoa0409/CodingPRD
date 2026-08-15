"""Calculation claims: BED, planning charge tiers, delivery pricing, capacities."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan_payload, create_dose_constraint_payload, create_simulation_payload,
    create_fraction_session_payload,
    setup_patient, setup_machine, setup_course, setup_treatment_ready_linac,
    setup_on_treatment, setup_course_in_planning, book_session, deliver_session,
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


class TestBedCalculations:
    def test_bed_actual_zero_penalty_within_kickoff(self):
        """PRD §3.7: "`bed_actual_gy` is computed over the course's `DELIVERED`
        sessions only ... From the sum the system subtracts a repopulation
        penalty of 0.6 gray per whole day by which the whole-day span between
        the earliest and latest delivered session start times exceeds
        twenty-eight days (the span is zero when fewer than two sessions have
        been delivered)."
        PRD §3.1 (bed_nominal): "the planned fraction count multiplied by that
        gray figure, multiplied by the quantity one plus that same gray figure
        divided by ten".
        Five 2-Gy deliveries over a 4-day span: 5*2*(1+0.2) == 12.000 (zero
        penalty since 4 <= 28); nominal 10*2*1.2 == 24.000.

        Design: Corner/calculations/bed_actual_zero_penalty_within_kickoff
        """
        ctx = setup_on_treatment(num_delivered=5, technique="IMRT",
                                 total_dose=2000, fractions=10, mrn="MRN-C1",
                                 booking_start=__import__("datetime").date(2026, 8, 3))
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["bed_actual_gy"] == pytest.approx(12.000, abs=1e-6)
        assert course["bed_nominal_gy"] == pytest.approx(24.000, abs=1e-6)


class TestPlanningCharge:
    def test_planning_charge_adaptation_half_rate(self):
        """PRD §3.5: "An initial plan bills that product rounded half up to a
        whole cent; an adaptation plan (one whose `supersedes_plan_id` is set)
        bills half of it, likewise rounded half up once at the end." With
        technique SBRT (300,000 base) and 3 target volumes (multiplier 1.5):
        initial 450000, adaptation round_half_up(450000 * 0.5) == 225000.

        Design: Corner/calculations/planning_charge_adaptation_half_rate
        """
        ctx = setup_on_treatment(num_delivered=1, technique="SBRT", total_dose=3000,
                                 fractions=5, mrn="MRN-C2", immobilization="BODY_FRAME",
                                 contour_overrides={"target_volumes": ["PTV1", "PTV2", "PTV3"],
                                                    "oar_structures": ["LungL"]},
                                 patient_weight=90.0)
        plan_a = ctx["plan"]
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        # adaptation triggered by override (weight loss alone is ~2.2%)
        adapt = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 88.0, "physician_override": True}, ONC_A))
        assert adapt["status"] == "ADAPTATION_REQUIRED"
        # adaptation plan must equal prescribed minus delivered: 3000 - 600 = 2400
        plan_b = get_success_data(api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=2400, planned_fractions=4,
                                supersedes_plan_id=plan_a["id"],
                                expected_course_version=adapt["version"]),
            DOS_A))
        get_success_data(api_client.create_dose_constraint(
            plan_b["id"],
            create_dose_constraint_payload(structure_name="LungL", limit_cGy=1400,
                                           evaluated_value_cGy=1200),
            DOS_A))
        get_success_data(api_client.submit_plan_for_check(plan_b["id"], DOS_A))
        get_success_data(api_client.create_physics_check(
            plan_b["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, PHYS_A))
        get_success_data(api_client.create_physics_check(
            plan_b["id"], {"check_type": "SECOND", "outcome": "PASS"}, PHYS_B))
        lines = validate_paginated(api_client.list_charge_lines(claim["id"], BILL))[0]
        planning = [l for l in lines if l["code"] == "PLANNING"]
        assert len(planning) == 2, "initial + adaptation planning lines"
        by_ref = {l["event_ref_id"]: l["amount_cents"] for l in planning}
        assert by_ref[plan_a["id"]] == 450000, "round_half_up(300000 * 1.5)"
        assert by_ref[plan_b["id"]] == 225000, "round_half_up(300000 * 1.5 * 0.5)"
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        assert claim_now["status"] == "DRAFT"


class TestDeliveryPricing:
    def test_igrt_line_only_when_planned(self):
        """PRD §3.7: "up to three charge lines are appended, each with quantity
        one: a `FRACTION_DELIVERY` line at the technique's rate — 18,000 cents
        for `THREE_DCRT`, 32,000 cents for `IMRT`, 55,000 cents for `SBRT`; an
        `IGRT` line of 7,500 cents when the session's `igrt_planned` is true;
        and a `FIRST_FRACTION_SETUP` line of 12,000 cents when
        `is_first_fraction` is true."

        Design: Corner/calculations/igrt_line_only_when_planned
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-C3", technique="IMRT",
                                          total_dose=2000, fractions=10)
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        f2 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-04T09:00:00Z", "2026-08-04T09:20:00Z", igrt=True)
        deliver_session(f1["id"])
        deliver_session(f2["id"])
        lines = validate_paginated(api_client.list_charge_lines(claim["id"], BILL))[0]
        igrt = [l for l in lines if l["code"] == "IGRT"]
        assert len(igrt) == 1 and igrt[0]["amount_cents"] == 7500
        assert igrt[0]["event_ref_id"] == f2["id"], "IGRT only for the igrt_planned session"
        setup_lines = [l for l in lines if l["code"] == "FIRST_FRACTION_SETUP"]
        assert len(setup_lines) == 1 and setup_lines[0]["amount_cents"] == 12000
        assert setup_lines[0]["event_ref_id"] == f1["id"]
        delivery = [l for l in lines if l["code"] == "FRACTION_DELIVERY"]
        assert len(delivery) == 2
        assert all(l["amount_cents"] == 32000 for l in delivery), "IMRT rate 32000"


class TestCapacities:
    def test_simulator_daily_capacity_ninth_rejected(self):
        """PRD §3.2: "a simulator accepts at most eight appointments in
        `SCHEDULED` or `COMPLETED` status whose `start_time` values fall on the
        same UTC calendar date, and the ninth such booking is rejected with
        `ERR_SIMULATOR_DAILY_CAPACITY` (HTTP 422)."

        Design: Corner/calculations/simulator_daily_capacity_ninth_rejected
        """
        pat = setup_patient(mrn="MRN-C5")
        course = setup_course(pat["id"], technique="IMRT",
                              prescribed_total_dose_cGy=2000, planned_fractions=10)
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-C5", room="SIM5")
        for hour in range(8, 16):  # 8 non-overlapping hourly slots
            get_success_data(api_client.create_simulation(
                course["id"],
                create_simulation_payload(machine_id=sim_m["id"],
                                          start_time=f"2026-08-03T{hour:02d}:00:00Z",
                                          end_time=f"2026-08-03T{hour:02d}:30:00Z",
                                          immobilization_device="NONE"),
                SCHED))
        resp = api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T16:00:00Z",
                                      end_time="2026-08-03T16:30:00Z",
                                      immobilization_device="NONE"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_SIMULATOR_DAILY_CAPACITY, expected_status=422)

    def test_fraction_count_limit_boundary(self):
        """PRD §3.6: "the plan's sessions in `SCHEDULED` plus `DELIVERED` status
        must remain strictly below the plan's `planned_fractions`, and a booking
        that would meet or exceed that ceiling is rejected with
        `ERR_FRACTION_COUNT_EXCEEDED` (HTTP 422)." For a 2-fraction plan the 2nd
        booking succeeds and the 3rd fails.

        Design: Corner/calculations/fraction_count_limit_boundary
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-C6", technique="THREE_DCRT",
                                          total_dose=400, fractions=2,
                                          intent="PALLIATIVE", diagnosis_code="C18",
                                          immobilization="NONE",
                                          contour_overrides={"target_volumes": ["PTV"]})
        # constraint was added by setup with default limit 2000 — fine (dose 400)
        book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                     "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                     "2026-08-04T09:00:00Z", "2026-08-04T09:20:00Z")
        resp = api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-05T09:00:00Z",
                                            end_time="2026-08-05T09:20:00Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_FRACTION_COUNT_EXCEEDED, expected_status=422)
