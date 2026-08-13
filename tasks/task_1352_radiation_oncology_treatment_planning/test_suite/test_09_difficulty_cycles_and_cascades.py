"""Difficulty queue: non-linear state machines (revision cycle, adaptation
cycle) and transitive cascades (adaptation cascade, machine-down cascade)."""
import pytest
from datetime import date

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan_payload, create_dose_constraint_payload,
    setup_patient, setup_machine, setup_course,
    setup_submitted_plan, setup_treatment_ready_linac, setup_on_treatment,
    book_session, deliver_session, weekday_slot,
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


class TestPlanRevisionCycle:
    def _fail_and_revise(self):
        """Plan goes DRAFT -> PENDING_PRIMARY_CHECK -> (FAIL) CHECK_FAILED ->
        DRAFT -> resubmitted; returns ctx with plan."""
        ctx = setup_submitted_plan(mrn="MRN-CYC-1", total_dose=4000, fractions=8,
                                   contour_overrides={"target_volumes": ["PTV"],
                                                      "oar_structures": ["Cord"]})
        # default constraint limit 2000 / evaluated 1500 satisfied
        plan = ctx["plan"]
        get_success_data(api_client.create_physics_check(
            plan["id"], {"check_type": "PRIMARY", "outcome": "FAIL",
                         "notes": "MU model off"}, PHYS_A))
        failed = get_success_data(api_client.get_plan(plan["id"], DOS_A))
        assert failed["status"] == "CHECK_FAILED"
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["status"] == "PLANNING"
        revised = get_success_data(api_client.revise_plan(plan["id"], DOS_A))
        assert revised["status"] == "DRAFT"
        ctx["plan"] = revised
        return ctx

    def test_primary_fail_returns_course_to_planning(self):
        """PRD §3.5: "A `FAIL` at either stage sends the plan to `CHECK_FAILED`
        and pushes the course back from `PHYSICS_REVIEW` to `PLANNING` — or to
        `REPLANNING` when the failed plan is an adaptation plan. The dosimetrist
        may then revise: the revision action returns a `CHECK_FAILED` plan to
        `DRAFT`."

        Design: Difficulty/non_linear_state_machine/plan_check_fail_revision_cycle
        """
        ctx = self._fail_and_revise()
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], DOS_A))
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert plan["status"] == "DRAFT", "revise returned the failed plan to DRAFT"
        assert course["status"] == "PLANNING", "course left PHYSICS_REVIEW on FAIL"

    def test_revision_cycle_completes_to_approved(self):
        """PRD §3.5: "This `DRAFT → PENDING_PRIMARY_CHECK → PENDING_SECOND_CHECK
        → APPROVED_FOR_DELIVERY` pipeline, with its `CHECK_FAILED → DRAFT` loop,
        is the plan's full working cycle" and "A `SECOND` check with `PASS` moves
        the plan `PENDING_SECOND_CHECK → APPROVED_FOR_DELIVERY` ... moves the
        course `PHYSICS_REVIEW → TREATMENT_READY`".

        Design: Difficulty/non_linear_state_machine/plan_check_fail_revision_cycle
        """
        ctx = self._fail_and_revise()
        plan = ctx["plan"]
        get_success_data(api_client.submit_plan_for_check(plan["id"], DOS_A))
        get_success_data(api_client.create_physics_check(
            plan["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, PHYS_A))
        get_success_data(api_client.create_physics_check(
            plan["id"], {"check_type": "SECOND", "outcome": "PASS"}, PHYS_B))
        plan_now = get_success_data(api_client.get_plan(plan["id"], DOS_A))
        course_now = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert plan_now["status"] == "APPROVED_FOR_DELIVERY"
        assert course_now["status"] == "TREATMENT_READY"


class TestCourseAdaptationCycle:
    def _setup_adaptation_cycle(self):
        """IMRT 2000/10 ON_TREATMENT with 2 delivered; adaptation by override at
        78.0 (2.5% loss, so override is the trigger); adaptation plan 1600/8
        approved. Returns ctx with plan_a, plan_b."""
        ctx = setup_on_treatment(num_delivered=2, technique="IMRT", total_dose=2000,
                                 fractions=10, mrn="MRN-CYC-2", patient_weight=80.0)
        plan_a = ctx["plan"]
        adapt = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 78.0, "physician_override": True},
            ONC_A))
        assert adapt["status"] == "ADAPTATION_REQUIRED"
        plan_b = get_success_data(api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=1600, planned_fractions=8,
                                supersedes_plan_id=plan_a["id"],
                                expected_course_version=adapt["version"]),
            DOS_A))
        get_success_data(api_client.create_dose_constraint(
            plan_b["id"],
            create_dose_constraint_payload(structure_name="Bladder", limit_cGy=1600,
                                           evaluated_value_cGy=1400),
            DOS_A))
        get_success_data(api_client.submit_plan_for_check(plan_b["id"], DOS_A))
        get_success_data(api_client.create_physics_check(
            plan_b["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, PHYS_A))
        get_success_data(api_client.create_physics_check(
            plan_b["id"], {"check_type": "SECOND", "outcome": "PASS"}, PHYS_B))
        ctx["plan_a"] = plan_a
        ctx["plan_b"] = plan_b
        return ctx

    def test_adaptation_cycle_supersedes_and_replans(self):
        """PRD §3.8: "the course moves `ON_TREATMENT → ADAPTATION_REQUIRED`, its
        `ACTIVE` plan becomes `SUPERSEDED`". PRD §3.4: "The server stamps each
        plan with a `plan_version` — 1 for the course's first plan, incrementing
        by 1 for each subsequent plan" and "Creating an adaptation plan ...
        moves the course automatically `ADAPTATION_REQUIRED → REPLANNING`,
        rewrites the course's `planned_fractions` to the sum of its
        `delivered_fractions` and the new plan's `planned_fractions`".

        Design: Difficulty/non_linear_state_machine/course_adaptation_cycle_returns_to_on_treatment
        """
        ctx = self._setup_adaptation_cycle()
        plan_a = get_success_data(api_client.get_plan(ctx["plan_a"]["id"], DOS_A))
        plan_b = get_success_data(api_client.get_plan(ctx["plan_b"]["id"], DOS_A))
        assert plan_a["status"] == "SUPERSEDED"
        assert plan_b["plan_version"] == 2
        assert plan_b["status"] == "APPROVED_FOR_DELIVERY"
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["planned_fractions"] == 10, "delivered 2 + new plan 8"
        assert course["status"] == "TREATMENT_READY"

    def test_delivery_under_adaptation_plan_closes_cycle(self):
        """PRD §3.7: "The course's first delivered session is doubly significant
        — the course moves `TREATMENT_READY → ON_TREATMENT`". PRD §3.6: "Each
        session receives a per-course `fraction_number`, assigned as one more
        than the maximum `fraction_number` over all existing sessions of the
        course and never reused". After 2 deliveries under plan A, the first
        session under adaptation plan B carries fraction_number 3 and its
        delivery returns the course to ON_TREATMENT.

        Design: Difficulty/non_linear_state_machine/course_adaptation_cycle_returns_to_on_treatment
        """
        ctx = self._setup_adaptation_cycle()
        f3 = book_session(ctx["course"]["id"], ctx["plan_b"]["id"], ctx["linac"]["id"],
                          "2026-08-05T09:00:00Z", "2026-08-05T09:20:00Z")
        assert f3["fraction_number"] == 3, "per-course sequence continues across plans"
        deliver_session(f3["id"])
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["status"] == "ON_TREATMENT"


class TestAdaptationCascade:
    def _setup_cascade_case(self):
        """IMRT 2000/10 ON_TREATMENT with 1 delivered + 2 scheduled; claim
        FINALIZED (gross 369000)."""
        ctx = setup_treatment_ready_linac(mrn="MRN-CAS-1", technique="IMRT",
                                          total_dose=2000, fractions=10)
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        f1 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        f2 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-04T09:00:00Z", "2026-08-04T09:20:00Z")
        f3 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-05T09:00:00Z", "2026-08-05T09:20:00Z")
        deliver_session(f1["id"])
        claim_now = get_success_data(api_client.get_claim(claim["id"], BILL))
        fin = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim_now["version"]}, BILL))
        assert fin["gross_total_cents"] == 369000
        ctx.update({"claim": claim, "f1": f1, "f2": f2, "f3": f3})
        return ctx

    def test_adaptation_supersedes_plan_and_cancels_sessions(self):
        """PRD §3.8: "When the trigger fires, the course moves `ON_TREATMENT →
        ADAPTATION_REQUIRED`, its `ACTIVE` plan becomes `SUPERSEDED`, every
        `SCHEDULED` session of the superseded plan is `CANCELLED` with
        `cancellation_reason` `ADAPTATION` (delivered, no-show, and
        already-cancelled sessions are untouched)".

        Design: Difficulty/transitive_cascade/adaptation_check_cascade_plan_sessions_claim
        """
        ctx = self._setup_cascade_case()
        resp = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 72.0}, ONC_A))
        assert resp["status"] == "ADAPTATION_REQUIRED"
        plan = get_success_data(api_client.get_plan(ctx["plan"]["id"], ONC_A))
        assert plan["status"] == "SUPERSEDED"
        sessions = validate_paginated(
            api_client.list_fraction_sessions(ctx["course"]["id"], ONC_A))[0]
        by_id = {s["id"]: s for s in sessions}
        assert by_id[ctx["f1"]["id"]]["status"] == "DELIVERED", "delivered untouched"
        for fid in (ctx["f2"]["id"], ctx["f3"]["id"]):
            assert by_id[fid]["status"] == "CANCELLED"
            assert by_id[fid]["cancellation_reason"] == "ADAPTATION"

    def test_adaptation_auto_reopens_finalized_claim_keeping_totals(self):
        """PRD §3.8: "a `FINALIZED` claim on the course auto-returns to `DRAFT`
        with its totals retained." PRD §3.9: "`gross_total_cents`,
        `discount_cents`, and `final_total_cents` are retained exactly and
        recomputed only on the next finalize."

        Design: Difficulty/transitive_cascade/adaptation_check_cascade_plan_sessions_claim
        """
        ctx = self._setup_cascade_case()
        get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 72.0}, ONC_A))
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        assert claim["status"] == "DRAFT"
        assert claim["final_total_cents"] == 369000, "monetary totals retained verbatim"
        assert claim["gross_total_cents"] == 369000
        assert claim["discount_cents"] == 0


class TestMachineDownCascade:
    def _setup_two_course_case(self):
        """Course A IMRT 2000/10 ON_TREATMENT (1 delivered 2026-08-03, 2
        scheduled 2026-08-10/11); course B THREE_DCRT 3000/10 TREATMENT_READY
        (1 scheduled 2026-08-12); both plans treat on the same LINAC; logical
        clock set to 2026-08-08."""
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-D", room="SIM1")
        lin_m = setup_machine("LINAC", name="Linac-D", room="TX4")
        # course A
        ctx_a = setup_on_treatment(num_delivered=1, technique="IMRT", total_dose=2000,
                                   fractions=10, mrn="MRN-CAS-A",
                                   sim_machine=sim_m)
        # note: setup_on_treatment creates its own linac; rebook on shared linac:
        fa2 = book_session(ctx_a["course"]["id"], ctx_a["plan"]["id"], lin_m["id"],
                           "2026-08-10T09:00:00Z", "2026-08-10T09:20:00Z")
        fa3 = book_session(ctx_a["course"]["id"], ctx_a["plan"]["id"], lin_m["id"],
                           "2026-08-11T09:00:00Z", "2026-08-11T09:20:00Z")
        ctx_a.update({"fa2": fa2, "fa3": fa3, "shared_linac": lin_m})
        # course B
        ctx_b = setup_treatment_ready_linac(mrn="MRN-CAS-B", technique="THREE_DCRT",
                                            total_dose=3000, fractions=10,
                                            intent="PALLIATIVE", diagnosis_code="C18",
                                            immobilization="NONE",
                                            sim_machine=sim_m)
        fb1 = book_session(ctx_b["course"]["id"], ctx_b["plan"]["id"], lin_m["id"],
                           "2026-08-12T09:00:00Z", "2026-08-12T09:20:00Z")
        ctx_b["fb1"] = fb1
        # advance logical clock so all scheduled sessions are future
        get_success_data(api_client.set_clock({"to_iso8601": "2026-08-08T00:00:00Z"}, ADMIN))
        return ctx_a, ctx_b

    def test_down_cancels_future_sessions_and_skips_delivered(self):
        """PRD §3.8: "When a `SystemAdmin` sets a machine `DOWN`, every fraction
        session on that machine still `SCHEDULED` with a `start_time` at or
        after the current logical time is cancelled with `cancellation_reason`
        `MACHINE_DOWN`."

        Design: Difficulty/transitive_cascade/machine_down_cascade_sessions_interruption_course_counter
        """
        ctx_a, ctx_b = self._setup_two_course_case()
        lin_m = ctx_a["shared_linac"]
        m = validate_success(api_client.set_machine_status(lin_m["id"], {"status": "DOWN"}, ADMIN))
        assert m["status"] == "DOWN"
        sessions_a = validate_paginated(
            api_client.list_fraction_sessions(ctx_a["course"]["id"], SCHED))[0]
        by_id = {s["id"]: s for s in sessions_a}
        # the delivered f1 (booked on setup's own linac) remains DELIVERED
        assert by_id[ctx_a["sessions"][0]["id"]]["status"] == "DELIVERED"
        for fid in (ctx_a["fa2"]["id"], ctx_a["fa3"]["id"]):
            assert by_id[fid]["status"] == "CANCELLED"
            assert by_id[fid]["cancellation_reason"] == "MACHINE_DOWN"
        sessions_b = validate_paginated(
            api_client.list_fraction_sessions(ctx_b["course"]["id"], SCHED))[0]
        assert sessions_b[0]["status"] == "CANCELLED"
        assert sessions_b[0]["cancellation_reason"] == "MACHINE_DOWN"

    def test_down_creates_per_course_interruptions_and_increments_counters(self):
        """PRD §3.8: "for each affected course, the system creates an
        interruption of its own: `reason` `MACHINE_DOWN`, `missed_count` set to
        the number of sessions cancelled for that course, `start_date` and
        `end_date` both equal to the date of the earliest cancelled session,
        status `OPEN` — and each such creation increments that course's
        `open_interruption_count` by one".

        Design: Difficulty/transitive_cascade/machine_down_cascade_sessions_interruption_course_counter
        """
        ctx_a, ctx_b = self._setup_two_course_case()
        lin_m = ctx_a["shared_linac"]
        get_success_data(api_client.set_machine_status(lin_m["id"], {"status": "DOWN"}, ADMIN))
        itr_a = validate_paginated(
            api_client.list_interruptions(ctx_a["course"]["id"], ONC_A))[0]
        assert len(itr_a) == 1
        assert itr_a[0]["reason"] == "MACHINE_DOWN"
        assert itr_a[0]["missed_count"] == 2
        assert itr_a[0]["status"] == "OPEN"
        itr_b = validate_paginated(
            api_client.list_interruptions(ctx_b["course"]["id"], ONC_A))[0]
        assert len(itr_b) == 1
        assert itr_b[0]["missed_count"] == 1
        course_a = get_success_data(api_client.get_course(ctx_a["course"]["id"], ONC_A))
        course_b = get_success_data(api_client.get_course(ctx_b["course"]["id"], ONC_A))
        assert course_a["open_interruption_count"] == 1
        assert course_b["open_interruption_count"] == 1
