"""Difficulty queue: cross-entity state dependencies, resource temporal overlap
semantics, and compensating invariants."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan_payload, create_dose_constraint_payload,
    create_fraction_session_payload, create_simulation_payload,
    create_contour_set_payload,
    setup_patient, setup_machine, setup_course,
    setup_treatment_ready_linac, setup_on_treatment, setup_course_with_simulation,
    book_session, deliver_session,
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


class TestCrossEntityDependencies:
    def _setup_down_delivery_case(self):
        """ON_TREATMENT course with 1 delivered (2026-08-03) + 1 SCHEDULED
        2026-08-05; logical clock advanced to 2026-08-06 so the DOWN cascade
        spares the session; then the LINAC is set DOWN."""
        ctx = setup_treatment_ready_linac(mrn="MRN-XS-1", technique="IMRT",
                                          total_dose=2000, fractions=10)
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        deliver_session(f1["id"])
        f2 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-05T09:00:00Z", "2026-08-05T09:20:00Z")
        get_success_data(api_client.set_clock({"to_iso8601": "2026-08-06T00:00:00Z"}, ADMIN))
        get_success_data(api_client.set_machine_status(ctx["linac"]["id"], {"status": "DOWN"}, ADMIN))
        ctx["f2"] = f2
        return ctx

    def test_deliver_blocked_when_machine_down(self):
        """PRD §3.7: delivery requires "the machine must be `OPERATIONAL`
        (`ERR_MACHINE_NOT_OPERATIONAL`)". PRD §3.8: only sessions "with a
        `start_time` at or after the current logical time" are cancelled when
        the machine goes DOWN — a session starting 2026-08-05 with the logical
        clock at 2026-08-06 survives the cascade in SCHEDULED but still cannot
        be delivered while the machine is DOWN.

        Design: Difficulty/cross_entity_state_dependency/deliver_blocked_when_machine_down
        """
        ctx = self._setup_down_delivery_case()
        resp = api_client.deliver_fraction(ctx["f2"]["id"], RTT_A)
        validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_OPERATIONAL, expected_status=422)
        sessions = validate_paginated(
            api_client.list_fraction_sessions(ctx["course"]["id"], SCHED))[0]
        target = [s for s in sessions if s["id"] == ctx["f2"]["id"]][0]
        assert target["status"] == "SCHEDULED", "cascade spared the past session"

    def test_past_session_spared_cascade_creates_no_interruption(self):
        """PRD §3.8: "Then, for each affected course, the system creates an
        interruption of its own". When the cascade cancels zero sessions for a
        course, that course is not an affected course — no MACHINE_DOWN
        interruption appears.

        Design: Difficulty/cross_entity_state_dependency/deliver_blocked_when_machine_down
        """
        ctx = self._setup_down_delivery_case()
        interruptions = validate_paginated(
            api_client.list_interruptions(ctx["course"]["id"], ONC_A))[0]
        machine_down = [i for i in interruptions if i["reason"] == "MACHINE_DOWN"]
        assert machine_down == [], "zero cancellations -> no auto-created interruption"

    def test_submit_blocked_when_contour_reopened_after_plan_pin(self):
        """PRD §3.5: "the pinned contour set must still be `APPROVED` with its
        current `version` still equal to `pinned_contour_version` — contour
        rework since plan creation breaks this and yields
        `ERR_STALE_CONTOUR_SET` (HTTP 409)". PRD §3.3: "Every mutation of a
        contour set bumps its `version`".

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_contour_reopened_after_plan_pin
        """
        from test_helpers import setup_course_in_planning
        ctx = setup_course_in_planning(mrn="MRN-XS-2", technique="IMRT",
                                       total_dose=4000, fractions=8,
                                       diagnosis_code="C73",
                                       contour_overrides={"target_volumes": ["PTV"],
                                                          "oar_structures": ["Cord"]})
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        plan = get_success_data(api_client.create_plan(
            course["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=4000, planned_fractions=8,
                                expected_course_version=course["version"]),
            DOS_A))
        pin_v = plan["pinned_contour_version"]
        get_success_data(api_client.create_dose_constraint(
            plan["id"], create_dose_constraint_payload(limit_cGy=4500,
                                                       evaluated_value_cGy=4000), DOS_A))
        cs_id = ctx["contour"]["id"]
        get_success_data(api_client.return_contour_set(
            cs_id, {"return_notes": "expand CTV margin"}, ONC_B))
        get_success_data(api_client.submit_contour_set(cs_id, ONC_A))
        get_success_data(api_client.approve_contour_set(cs_id, ONC_B))
        cs_now = get_success_data(api_client.get_contour_set(cs_id, ONC_A))
        assert cs_now["status"] == "APPROVED"
        assert cs_now["version"] == pin_v + 3, "return + submit + approve each bump"
        resp = api_client.submit_plan_for_check(plan["id"], DOS_A)
        validate_error(resp, ApiErrorId.ERR_STALE_CONTOUR_SET, expected_status=409)

    def test_stale_contour_rejection_leaves_plan_draft(self):
        """PRD §3.5: "the pinned contour set must still be `APPROVED` with its
        current `version` still equal to `pinned_contour_version` — contour
        rework since plan creation breaks this and yields
        `ERR_STALE_CONTOUR_SET` (HTTP 409)". A rejected submission performs no
        transition: the plan stays DRAFT.

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_contour_reopened_after_plan_pin
        """
        from test_helpers import setup_course_in_planning
        ctx = setup_course_in_planning(mrn="MRN-XS-2", technique="IMRT",
                                       total_dose=4000, fractions=8,
                                       diagnosis_code="C73",
                                       contour_overrides={"target_volumes": ["PTV"],
                                                          "oar_structures": ["Cord"]})
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        plan = get_success_data(api_client.create_plan(
            course["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=4000, planned_fractions=8,
                                expected_course_version=course["version"]),
            DOS_A))
        get_success_data(api_client.create_dose_constraint(
            plan["id"], create_dose_constraint_payload(limit_cGy=4500,
                                                       evaluated_value_cGy=4000), DOS_A))
        cs_id = ctx["contour"]["id"]
        get_success_data(api_client.return_contour_set(
            cs_id, {"return_notes": "expand CTV margin"}, ONC_B))
        get_success_data(api_client.submit_contour_set(cs_id, ONC_A))
        get_success_data(api_client.approve_contour_set(cs_id, ONC_B))
        api_client.submit_plan_for_check(plan["id"], DOS_A)  # rejected
        plan_now = get_success_data(api_client.get_plan(plan["id"], DOS_A))
        assert plan_now["status"] == "DRAFT"

    def test_claim_submit_requires_terminal_course(self):
        """PRD §3.9: "Submission, the terminal step, requires a `FINALIZED`
        claim (`ERR_CLAIM_NOT_FINALIZED`) and a course that has reached
        `COMPLETED` or `DISCONTINUED` (`ERR_COURSE_NOT_TERMINAL`, HTTP 409)".
        A FINALIZED claim on an ON_TREATMENT course is rejected.

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_terminal_course
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-XS-3", technique="IMRT",
                                          total_dose=2000, fractions=10)
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        deliver_session(f1["id"])
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        fin = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim_now["version"]}, BILL))
        assert fin["status"] == "FINALIZED"
        resp = api_client.submit_claim(claim["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_TERMINAL, expected_status=409)

    def test_claim_submit_rejection_keeps_claim_finalized(self):
        """PRD §3.9: "Submission, the terminal step, requires a `FINALIZED`
        claim (`ERR_CLAIM_NOT_FINALIZED`) and a course that has reached
        `COMPLETED` or `DISCONTINUED` (`ERR_COURSE_NOT_TERMINAL`, HTTP 409), and
        moves the claim `FINALIZED → SUBMITTED`." A submission rejected by the
        terminal-course gate performs no move — the claim stays FINALIZED.

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_terminal_course
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-XS-3", technique="IMRT",
                                          total_dose=2000, fractions=10)
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        deliver_session(f1["id"])
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        get_success_data(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim_now["version"]}, BILL))
        api_client.submit_claim(claim["id"], BILL)  # rejected
        claim_after = get_success_data(api_client.get_claim(claim["id"], BILL))
        assert claim_after["status"] == "FINALIZED"


class TestTemporalOverlap:
    def _setup_linac_with_first_slot(self):
        ctx = setup_treatment_ready_linac(mrn="MRN-OV-1", technique="IMRT",
                                          total_dose=2000, fractions=10)
        s1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        ctx["s1"] = s1
        return ctx

    def test_linac_turnover_buffer_blocks_back_to_back(self):
        """PRD §3.6: "the LINAC honors a ten-minute turnover buffer: a new
        session conflicts with an existing `SCHEDULED` or `DELIVERED` session on
        the same machine whenever the new start falls before the existing end
        plus ten minutes *and* the existing start falls before the new end plus
        ten minutes, producing `ERR_MACHINE_SLOT_CONFLICT` (HTTP 409).
        Back-to-back scheduling is therefore not permitted on a LINAC — a
        session beginning exactly when another ends still collides, because both
        buffered comparisons hold."

        Design: Difficulty/resource_temporal_overlap/linac_turnover_buffer_blocks_back_to_back
        """
        ctx = self._setup_linac_with_first_slot()
        resp = api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-03T09:20:00Z",
                                            end_time="2026-08-03T09:40:00Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_MACHINE_SLOT_CONFLICT, expected_status=409)

    def test_linac_first_slot_after_buffer_succeeds(self):
        """PRD §3.6: the conflict window closes exactly at end plus the
        ten-minute buffer (both comparisons are strict), so a start at 09:30
        after a 09:00-09:20 session is permitted. PRD §3.6: "Each session
        receives a per-course `fraction_number`, assigned as one more than the
        maximum `fraction_number` over all existing sessions of the course".

        Design: Difficulty/resource_temporal_overlap/linac_turnover_buffer_blocks_back_to_back
        """
        ctx = self._setup_linac_with_first_slot()
        s2 = validate_success(api_client.create_fraction_session(
            ctx["course"]["id"],
            create_fraction_session_payload(plan_id=ctx["plan"]["id"],
                                            machine_id=ctx["linac"]["id"],
                                            start_time="2026-08-03T09:30:00Z",
                                            end_time="2026-08-03T09:50:00Z"),
            SCHED), expected_status=201)
        assert s2["fraction_number"] == 2
        assert s2["status"] == "SCHEDULED"

    def test_simulator_half_open_adjacency_no_buffer(self):
        """PRD §3.2: "Interval occupation is pure half-open overlap: a new
        appointment conflicts with an existing `SCHEDULED` appointment on the
        same simulator only when each starts strictly before the other ends —
        so an appointment beginning exactly when another ends is permitted — and
        a violating booking is rejected with `ERR_SIMULATOR_SLOT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/simulator_half_open_adjacency_no_buffer
        """
        pat = setup_patient(mrn="MRN-OV-2", full_name="Overlap Two", date_of_birth="1966-02-02")
        course = setup_course(pat["id"], technique="THREE_DCRT",
                              prescribed_total_dose_cGy=3000, planned_fractions=10,
                              intent="PALLIATIVE", diagnosis_code="C18")
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-OV2", room="SIM2")
        sa = get_success_data(api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:00:00Z",
                                      end_time="2026-08-03T09:30:00Z",
                                      immobilization_device="NONE"),
            SCHED))
        assert sa["status"] == "SCHEDULED"
        sb = validate_success(api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:30:00Z",
                                      end_time="2026-08-03T10:00:00Z",
                                      immobilization_device="NONE"),
            SCHED), expected_status=201)
        assert sb["status"] == "SCHEDULED", "half-open adjacency is allowed"

    def test_simulator_straddling_booking_rejected(self):
        """PRD §3.2: "a new appointment conflicts with an existing `SCHEDULED`
        appointment on the same simulator only when each starts strictly before
        the other ends ... and a violating booking is rejected with
        `ERR_SIMULATOR_SLOT_CONFLICT` (HTTP 409)." A 09:15-09:45 booking
        straddles the 09:00-09:30 appointment's interior and is rejected.

        Design: Difficulty/resource_temporal_overlap/simulator_half_open_adjacency_no_buffer
        """
        pat = setup_patient(mrn="MRN-OV-2", full_name="Overlap Two", date_of_birth="1966-02-02")
        course = setup_course(pat["id"], technique="THREE_DCRT",
                              prescribed_total_dose_cGy=3000, planned_fractions=10,
                              intent="PALLIATIVE", diagnosis_code="C18")
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-OV2", room="SIM2")
        get_success_data(api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:00:00Z",
                                      end_time="2026-08-03T09:30:00Z",
                                      immobilization_device="NONE"),
            SCHED))
        resp = api_client.create_simulation(
            course["id"],
            create_simulation_payload(machine_id=sim_m["id"],
                                      start_time="2026-08-03T09:15:00Z",
                                      end_time="2026-08-03T09:45:00Z",
                                      immobilization_device="NONE"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_SIMULATOR_SLOT_CONFLICT, expected_status=409)


class TestCompensatingInvariants:
    def _setup_invariant_case(self):
        """IMRT 2000/10 ON_TREATMENT with 2 delivered (400 cGy); adaptation
        triggered at 72.0 (10.0% loss). Returns ctx with adaptation response."""
        ctx = setup_on_treatment(num_delivered=2, technique="IMRT", total_dose=2000,
                                 fractions=10, mrn="MRN-INV-1", patient_weight=80.0)
        adapt = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 72.0}, ONC_A))
        ctx["adapt"] = adapt
        return ctx

    def test_wrong_replan_target_rejected_remaining_dose_mismatch(self):
        """PRD §3.4: "an adaptation plan requires the course to be in
        `ADAPTATION_REQUIRED` — `ERR_COURSE_NOT_ADAPTING` (HTTP 409) otherwise —
        and its target must equal the prescribed total minus the
        already-`delivered_dose_cGy`. Either target violation is
        `ERR_REMAINING_DOSE_MISMATCH` (HTTP 422)." A 1500-cGy target against a
        1600-cGy remainder (2000 - 400) is rejected.

        Design: Difficulty/compensating_invariant/adaptation_preserves_total_prescribed_dose
        """
        ctx = self._setup_invariant_case()
        resp = api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=1500, planned_fractions=8,
                                supersedes_plan_id=ctx["plan"]["id"],
                                expected_course_version=ctx["adapt"]["version"]),
            DOS_A)
        validate_error(resp, ApiErrorId.ERR_REMAINING_DOSE_MISMATCH, expected_status=422)

    def test_exact_remainder_replan_conserves_prescribed_dose(self):
        """PRD §3.4: "[the adaptation plan's] target must equal the prescribed
        total minus the already-`delivered_dose_cGy`" and "rewrites the course's
        `planned_fractions` to the sum of its `delivered_fractions` and the new
        plan's `planned_fractions`". The 1600-cGy replan (2000 - 400) succeeds
        and prescribed == delivered + target: 2000 == 400 + 1600.

        Design: Difficulty/compensating_invariant/adaptation_preserves_total_prescribed_dose
        """
        ctx = self._setup_invariant_case()
        plan_b = get_success_data(api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=1600, planned_fractions=8,
                                supersedes_plan_id=ctx["plan"]["id"],
                                expected_course_version=ctx["adapt"]["version"]),
            DOS_A))
        assert plan_b["target_total_dose_cGy"] == 1600
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["prescribed_total_dose_cGy"] == \
            course["delivered_dose_cGy"] + plan_b["target_total_dose_cGy"]
        assert course["planned_fractions"] == 10, "delivered 2 + new plan 8"

    def _setup_roundtrip_case(self):
        """IMRT 2000/10 ON_TREATMENT 1 delivered; claim opened after approval +
        delivery -> lines 65000+50000+210000+32000+12000 = 369000."""
        ctx = setup_treatment_ready_linac(mrn="MRN-INV-2", technique="IMRT",
                                          total_dose=2000, fractions=10)
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        deliver_session(f1["id"])
        ctx["claim"] = claim
        return ctx

    def test_finalize_reopen_conserves_monetary_totals(self):
        """PRD §3.9: "The monetary fields survive the round trip verbatim:
        `gross_total_cents`, `discount_cents`, and `final_total_cents` are
        retained exactly and recomputed only on the next finalize."

        Design: Difficulty/compensating_invariant/claim_finalize_reopen_roundtrip_conserves_totals
        """
        ctx = self._setup_roundtrip_case()
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        fin = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, BILL))
        assert fin["gross_total_cents"] == 369000
        assert fin["discount_cents"] == 0
        assert fin["final_total_cents"] == 369000
        reopened = validate_success(api_client.reopen_claim(claim["id"], BILL))
        assert reopened["status"] == "DRAFT"
        after = get_success_data(api_client.get_claim(claim["id"], BILL))
        assert after["gross_total_cents"] == 369000
        assert after["discount_cents"] == 0
        assert after["final_total_cents"] == 369000

    def test_refinalize_after_reopen_reproduces_identical_totals(self):
        """PRD §3.9: "`gross_total_cents`, `discount_cents`, and
        `final_total_cents` are retained exactly and recomputed only on the
        next finalize", and the pinned finalize order computes
        `final_total_cents` as "the gross minus the discount" from the same
        line set — so a second finalize after a reopen reproduces identical
        totals (369000 / 0 / 369000) with no drift across the round trip.

        Design: Difficulty/compensating_invariant/claim_finalize_reopen_roundtrip_conserves_totals
        """
        ctx = self._setup_roundtrip_case()
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        get_success_data(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, BILL))
        get_success_data(api_client.reopen_claim(claim["id"], BILL))
        claim2 = get_success_data(api_client.get_claim(claim["id"], BILL))
        fin2 = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim2["version"]}, BILL))
        assert fin2["gross_total_cents"] == 369000
        assert fin2["discount_cents"] == 0
        assert fin2["final_total_cents"] == 369000
