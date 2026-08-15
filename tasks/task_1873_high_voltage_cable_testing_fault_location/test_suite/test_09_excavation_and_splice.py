"""Excavation orders and repair splices: creation gauntlet, curing maturity,
backfill gate, cross-references, and customer acceptance (PRD §3.8)."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_same_instant,
    setup_job_in_progress,
    setup_retest_accepted,
    create_fail_series_with_fault,
    pinpoint_fault,
    create_excavation,
    create_splice,
    drive_excavation_in_progress,
    drive_splice_curing,
    drive_splice_completed,
    accept_splice,
    set_clock,
    get_fault,
    get_circuit,
    get_job,
)

CREW_LEAD = TEST_USERS["fault_crew_lead_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
SUPERVISOR = TEST_USERS["test_supervisor_headers"]


def _excavating_ctx(circuit_ref, budget=800000, length_m=1000):
    """Fault pinpointed and excavation driven to IN_PROGRESS
    (fault PINPOINTED -> EXCAVATING)."""
    ctx = setup_job_in_progress(
        circuit_ref=circuit_ref, length_m=length_m, approved_budget_cents=budget,
    )
    _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
    pinpoint_fault(fault_id)
    excavation = create_excavation(fault_id)
    drive_excavation_in_progress(excavation["id"])
    ctx.update({"fault_id": fault_id, "excavation": excavation})
    return ctx


def _splice_planned_ctx(circuit_ref, budget=800000):
    """Excavation IN_PROGRESS plus a splice in PLANNED."""
    ctx = _excavating_ctx(circuit_ref, budget=budget)
    splice = create_splice(ctx["fault_id"], ctx["excavation"]["id"])
    ctx["splice"] = splice
    return ctx


class TestExcavationGauntlet:
    def test_dig_outside_outage_masks_budget_error(self, api):
        """PRD §3.8: "Creation runs a six-deep gauntlet after the
        request-shape and existence checks, in this exact order: the fault
        must be `PINPOINTED`, `EXCAVATING`, or `REPAIRING` (else
        `ERR_INVALID_STATE`); the dig interval must be contained in the outage
        window of the fault's job with both edges inclusive — `dig_start` at
        or after `window_start` and `dig_end` at or before `window_end` (else
        `ERR_DIG_OUTSIDE_OUTAGE`); the `target_location_m` must lie within the
        fault's corridor from `corridor_start_m` to `corridor_end_m`,
        inclusive of both bounds (else `ERR_CORRIDOR_VIOLATION`); the dig
        interval must not overlap, on half-open comparison, the dig interval
        of any other non-cancelled excavation of the same fault (else
        `ERR_DIG_WINDOW_OVERLAP`); no excavation order that has not been
        cancelled may already exist for the fault (else
        `ERR_EXCAVATION_EXISTS`); and the budget check — `estimate_cents` plus
        `committed_cost_cents` plus the new `cost_cents` must not exceed
        `approved_budget_cents` (else `ERR_BUDGET_EXCEEDED`)." The containment
        check fires before the budget check.

        Design: Difficulty/priority_pair_validation_conflict/temporal_error_masks_fiscal_error_on_excavation_create
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-PP2", approved_budget_cents=500000)
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        pinpoint_fault(fault_id)
        # Estimate 424000 + 80000 = 504000 > 500000, AND the dig interval
        # (2026-08-13) lies outside the outage window: the temporal error wins.
        resp = api.create_excavation(
            {
                "fault_record_id": fault_id,
                "target_location_m": 1560.0,
                "dig_start": "2026-08-13T09:00:00Z",
                "dig_end": "2026-08-13T10:00:00Z",
                "permit_ref": "MX-200",
                "cost_cents": 80000,
            },
            CREW_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_DIG_OUTSIDE_OUTAGE)
        excavations = validate_success(api.list_fault_excavations(fault_id, CREW_LEAD))
        assert excavations == [], "no excavation may be created"

    def test_budget_exceeded_isolated_on_excavation_create(self, api):
        """PRD §3.8: "the budget check — `estimate_cents` plus
        `committed_cost_cents` plus the new `cost_cents` must not exceed
        `approved_budget_cents` (else `ERR_BUDGET_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_error_masks_fiscal_error_on_excavation_create
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-PP2", approved_budget_cents=500000)
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        pinpoint_fault(fault_id)
        # Dig inside the window and on the corridor; only the budget fails
        # (424000 + 0 + 80000 = 504000 > 500000).
        resp = api.create_excavation(
            {
                "fault_record_id": fault_id,
                "target_location_m": 1560.0,
                "dig_start": "2026-08-10T09:30:00Z",
                "dig_end": "2026-08-10T11:00:00Z",
                "permit_ref": "MX-200",
                "cost_cents": 80000,
            },
            CREW_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)

    def test_second_open_excavation_rejected(self, api):
        """PRD §3.8: "no excavation order that has not been cancelled may
        already exist for the fault (else `ERR_EXCAVATION_EXISTS`)".

        Design: Corner/validations/excavation_exists_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V18", approved_budget_cents=900000)
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        pinpoint_fault(fault_id)
        create_excavation(fault_id)
        resp = api.create_excavation(
            {
                "fault_record_id": fault_id,
                "target_location_m": 1560.0,
                "dig_start": "2026-08-11T09:30:00Z",
                "dig_end": "2026-08-11T11:00:00Z",
                "permit_ref": "MX-2",
                "cost_cents": 50000,
            },
            CREW_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_EXCAVATION_EXISTS)

    def test_target_outside_corridor_rejected(self, api):
        """PRD §3.8: "the `target_location_m` must lie within the fault's
        corridor from `corridor_start_m` to `corridor_end_m`, inclusive of
        both bounds (else `ERR_CORRIDOR_VIOLATION`)".

        Design: Corner/validations/corridor_violation_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V19", approved_budget_cents=900000)
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        pinpoint_fault(fault_id)  # corridor [1404.0, 1716.0]
        resp = api.create_excavation(
            {
                "fault_record_id": fault_id,
                "target_location_m": 1000.0,
                "dig_start": "2026-08-10T09:30:00Z",
                "dig_end": "2026-08-10T11:00:00Z",
                "permit_ref": "MX-1",
                "cost_cents": 100040,
            },
            CREW_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_CORRIDOR_VIOLATION)

    def test_dig_end_equal_window_end_allowed(self, api):
        """PRD §3.8: "the dig interval must be contained in the outage window
        of the fault's job with both edges inclusive — `dig_start` at or after
        `window_start` and `dig_end` at or before `window_end` (else
        `ERR_DIG_OUTSIDE_OUTAGE`)". `dig_end` equal to `window_end` satisfies
        the inclusive edge.

        Design: Difficulty/resource_temporal_overlap/dig_contained_inclusive_edges
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-TO3")
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        pinpoint_fault(fault_id)
        created = validate_success(api.create_excavation(
            {
                "fault_record_id": fault_id,
                "target_location_m": 1560.0,
                "dig_start": "2026-08-11T00:00:00Z",
                "dig_end": "2026-08-12T12:00:00Z",
                "permit_ref": "MX-300",
                "cost_cents": 100040,
            },
            CREW_LEAD,
        ), 201)
        assert created["status"] == "DRAFT", (
            "dig_end equal to window_end satisfies the inclusive edge, so the "
            "excavation is created and starts in DRAFT (PRD §3.8)"
        )
        assert_same_instant(created["dig_end"], "2026-08-12T12:00:00Z")

    def test_dig_end_one_minute_past_window_end_rejected(self, api):
        """PRD §3.8: "`dig_end` at or before `window_end` (else
        `ERR_DIG_OUTSIDE_OUTAGE`)" — one minute beyond the inclusive edge is
        outside the outage.

        Design: Difficulty/resource_temporal_overlap/dig_contained_inclusive_edges
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-TO3")
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        pinpoint_fault(fault_id)
        resp = api.create_excavation(
            {
                "fault_record_id": fault_id,
                "target_location_m": 1560.0,
                "dig_start": "2026-08-11T00:00:00Z",
                "dig_end": "2026-08-12T12:01:00Z",
                "permit_ref": "MX-301",
                "cost_cents": 100040,
            },
            CREW_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_DIG_OUTSIDE_OUTAGE)


class TestBackfillAndCuring:
    def test_backfill_before_curing_rejected(self, api):
        """PRD §3.8: "Backfilling is permitted only once a repair splice
        referencing this excavation exists in `CURING` or `COMPLETED` status
        (else `ERR_SPLICE_NOT_CURING`) and moves the order `IN_PROGRESS` →
        `BACKFILLED`."

        Design: Corner/state_machines/excavation_backfill_before_curing_rejected
        """
        ctx = _splice_planned_ctx("CKT-S8")
        resp = api.backfill_excavation(ctx["excavation"]["id"], CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_SPLICE_NOT_CURING)

        drive_splice_curing(ctx["splice"]["id"])
        backfilled = validate_success(
            api.backfill_excavation(ctx["excavation"]["id"], CREW_LEAD)
        )
        assert backfilled["status"] == "BACKFILLED"

    def test_curing_exactly_24h_boundary(self, api):
        """PRD §3.8: "Finishing the cure is allowed only once at least
        twenty-four hours have elapsed since `cure_started_at` — finishing at
        exactly the twenty-four-hour mark is permitted — and an early attempt
        is rejected with `ERR_CURING_INCOMPLETE`; finishing stamps
        `completed_at` and moves the fault `REPAIRING` → `REPAIRED`".

        Design: Corner/validations/curing_exactly_24h_boundary
        """
        ctx = _splice_planned_ctx("CKT-V21")
        drive_splice_curing(ctx["splice"]["id"])  # cure_started_at = 2026-08-10T09:45Z

        set_clock("2026-08-11T09:44:00Z")
        early = api.finish_curing(ctx["splice"]["id"], CREW_LEAD)
        validate_error(early, ApiErrorId.ERR_CURING_INCOMPLETE)

        set_clock("2026-08-11T09:45:00Z")
        completed = validate_success(api.finish_curing(ctx["splice"]["id"], CREW_LEAD))
        assert completed["status"] == "COMPLETED", "exactly 24h is permitted"
        assert get_fault(ctx["fault_id"])["status"] == "REPAIRED"


class TestSpliceGates:
    def test_second_open_splice_rejected(self, api):
        """PRD §3.8: "creation is gated by the open-splice uniqueness rule —
        no splice of this fault may already exist in `PLANNED`, `SPLICING`,
        `CURING`, or `COMPLETED` (else `ERR_SPLICE_EXISTS`)".

        Design: Corner/validations/splice_exists_rejected
        """
        ctx = _splice_planned_ctx("CKT-V20")
        resp = api.create_splice(
            {
                "fault_record_id": ctx["fault_id"],
                "excavation_order_id": ctx["excavation"]["id"],
                "splice_type": "PREMOLDED",
                "cost_cents": 50000,
            },
            CREW_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_SPLICE_EXISTS)

    def test_cross_reference_mismatch_rejected(self, api):
        """PRD §3.8: "then by cross-reference consistency, where the
        referenced excavation's `fault_record_id` must equal the splice's own
        `fault_record_id` (else `ERR_CROSS_REFERENCE_MISMATCH`, HTTP 422)".

        Design: Corner/validations/cross_reference_mismatch_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V22", approved_budget_cents=900000)
        job_id = ctx["job"]["id"]
        _, fault1 = create_fail_series_with_fault(job_id, (90.0, 90.0, 90.0))
        _, fault2 = create_fail_series_with_fault(job_id, (91.0, 91.0, 91.0))
        pinpoint_fault(fault1, trace_time_us=20.0)
        pinpoint_fault(fault2, trace_time_us=24.0)  # distance 1872.0 m

        exc1 = create_excavation(fault1, target_location_m=1560.0, permit_ref="MX-1")
        exc2 = create_excavation(fault2, target_location_m=1872.0, permit_ref="MX-2")
        get_success_data(api_client.permit_excavation(exc1["id"], CREW_LEAD))
        get_success_data(api_client.permit_excavation(exc2["id"], CREW_LEAD))
        set_clock("2026-08-10T09:45:00Z")
        get_success_data(api_client.start_excavation(exc1["id"], CREW_LEAD))
        get_success_data(api_client.start_excavation(exc2["id"], CREW_LEAD))

        resp = api.create_splice(
            {
                "fault_record_id": fault1,
                "excavation_order_id": exc2["id"],
                "splice_type": "HEAT_SHRINK",
                "cost_cents": 200040,
            },
            CREW_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)
        splices = validate_success(api.list_fault_splices(fault1, CREW_LEAD))
        assert splices == [], "no splice may be created across faults"


class TestSpliceAcceptance:
    def test_accept_without_qualifying_retest_rejected(self, api):
        """PRD §3.8: "Customer acceptance of the repair is the
        `NetworkPlanner`'s final gate and requires a qualifying re-test: a
        test series whose `retest_of_fault_id` names the splice's fault, whose
        status is `ACCEPTED`, whose official verdict is `PASS`, and whose
        `created_at` is strictly after the splice's `completed_at` — a re-test
        created at the same instant does not qualify, and the absence of a
        qualifying re-test rejects acceptance with `ERR_RETEST_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/splice_acceptance_requires_passing_retest
        """
        ctx = _splice_planned_ctx("CKT-CE2")
        drive_splice_completed(ctx["splice"]["id"])
        assert get_fault(ctx["fault_id"])["status"] == "REPAIRED"
        resp = api.accept_splice(ctx["splice"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_RETEST_REQUIRED)

    def test_accept_succeeds_after_qualifying_retest(self, api):
        """PRD §3.8: "Acceptance moves the splice `COMPLETED` → `ACCEPTED` and
        the fault `RETESTING` → `CLOSED_VERIFIED`, firing the full closure
        cascade of §3.7."

        Design: Difficulty/cross_entity_state_dependency/splice_acceptance_requires_passing_retest
        """
        ctx = setup_retest_accepted(circuit_ref="CKT-CE2")
        assert get_fault(ctx["fault_id"])["status"] == "RETESTING", (
            "creating the re-test series moved the fault REPAIRED → RETESTING"
        )
        accepted = accept_splice(ctx["splice"]["id"])
        assert accepted["status"] == "ACCEPTED"
        assert get_fault(ctx["fault_id"])["status"] == "CLOSED_VERIFIED"

    def test_acceptance_cascade_closes_fault(self, api):
        """PRD §3.8: "Acceptance moves the splice `COMPLETED` → `ACCEPTED` and
        the fault `RETESTING` → `CLOSED_VERIFIED`, firing the full closure
        cascade of §3.7." PRD §3.7: "`closed_at` is set to the logical clock,
        the circuit's `unresolved_fault_count` is decremented by one,
        `resolved_fault_count_24m` is recomputed, the circuit's `splice_count`
        is incremented by one".

        Design: Difficulty/transitive_cascade/splice_accept_cascade_closes_fault_and_advances_job
        """
        ctx = setup_retest_accepted(circuit_ref="CKT-TC1", accept_original_series=True)
        accepted = accept_splice(ctx["splice"]["id"])
        assert accepted["status"] == "ACCEPTED"
        fault = get_fault(ctx["fault_id"])
        assert fault["status"] == "CLOSED_VERIFIED", "hop 1, caused by the acceptance"
        assert fault["closed_at"] is not None
        circuit = get_circuit(ctx["circuit"]["id"])
        assert circuit["unresolved_fault_count"] == 0
        assert circuit["resolved_fault_count_24m"] == 1
        assert circuit["splice_count"] == 1, "hop 2: circuit counters mutated"

    def test_acceptance_cascade_advances_job_and_circuit(self, api):
        """PRD §3.3: "the moment at least one test series exists for the job,
        every series of the job sits in a terminal state (`ACCEPTED` or
        `INVALID`), and every fault of the job is `CLOSED_VERIFIED`, the job
        moves itself `IN_PROGRESS` → `EVALUATION`, and the circuit follows
        `UNDER_TEST` → `TEST_COMPLETE`."

        Design: Difficulty/transitive_cascade/splice_accept_cascade_closes_fault_and_advances_job
        """
        ctx = setup_retest_accepted(circuit_ref="CKT-TC1", accept_original_series=True)
        accept_splice(ctx["splice"]["id"])
        assert get_job(ctx["job"]["id"])["status"] == "EVALUATION", (
            "hop 3: the closure satisfied the job's evaluation gate"
        )
        assert get_circuit(ctx["circuit"]["id"])["status"] == "TEST_COMPLETE", (
            "hop 4: job evaluation drives the circuit"
        )
