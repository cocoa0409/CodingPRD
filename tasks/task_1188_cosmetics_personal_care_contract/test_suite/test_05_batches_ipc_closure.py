"""Compounding: IPC evaluation boundaries, retry loop, scale-up gate, release
gates, closure charging, and the append-only check log."""
from test_helpers import (
    ApiErrorId,
    adjust_batch,
    allocate_lots,
    allocation_item,
    assert_batch,
    assert_ipc_check,
    confirm_order,
    create_active_formula,
    create_batch,
    create_chamber,
    create_component,
    create_customer,
    create_lot,
    create_order,
    create_study,
    ipc_passed_batch_ctx,
    make_qa_manager_headers,
    mixing_batch_ctx,
    record_ipc_check,
    record_reading,
    reject_batch,
    release_batch,
    start_mixing,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import QA1, QA2


class TestClosureChargeVariants:
    def test_batch_closure_actual_vs_standard(self, api, qa_manager_headers):
        """PRD §3.6: "First, the materials subtotal sums one line per `CONSUMED`
        allocation: the allocation's `quantity` multiplied by the lot's effective
        cost — the lot's `unit_cost_per_kg_cents` when one was recorded at
        receipt, otherwise the component's `standard_cost_per_kg_cents` — with
        each line rounded half-up to whole cents before the lines are summed."
        PRD §3.6: "A parallel figure, `batch_charge_standard_cents`, is computed
        identically but prices every allocation at the component's standard cost,
        giving finance a variance view against actual lot costs; the two diverge
        whenever actual lot costs differ from standard."
        PRD §3.6: "Rejection moves the batch to `REJECTED` and consumes its
        materials as waste".

        Design: Difficulty/dual_variant_calc/batch_closure_actual_vs_standard
        """
        ctx = confirmed_order_for_closure(component_cost=1000)
        batch = create_batch(ctx["order"]["id"], 100)
        lot_a1 = create_lot(ctx["component"]["id"], lot_code="A1", quantity_received=60,
                            unit_cost_per_kg_cents=1200)
        lot_a2 = create_lot(ctx["component"]["id"], lot_code="A2", quantity_received=40,
                            unit_cost_per_kg_cents=800)
        allocate_lots(ctx["order"]["id"], [
            allocation_item(lot_a1["id"], 60, batch_id=batch["id"]),
            allocation_item(lot_a2["id"], 40, batch_id=batch["id"]),
        ])
        start_mixing(batch["id"])

        rejected = reject_batch(batch["id"], reason="contamination", headers=qa_manager_headers)
        assert_batch(rejected)
        assert rejected["status"] == "REJECTED"
        # actual: 60*1200 + 40*800 = 104000; 2% surcharge => 106080
        assert rejected["batch_charge_cents"] == 106080
        # standard: 100*1000 = 100000; 2% surcharge => 102000
        assert rejected["batch_charge_standard_cents"] == 102000
        assert rejected["batch_charge_cents"] != rejected["batch_charge_standard_cents"]

    def test_batch_charge_fields_null_until_closure(self, api, qa_manager_headers):
        """PRD §3.6: "Both charge fields remain null until the batch closes."

        Design: Difficulty/dual_variant_calc/batch_closure_actual_vs_standard
        """
        ctx = mixing_batch_ctx()
        fetched = validate_success(api.get_batch(ctx["batch"]["id"], qa_manager_headers), 200)
        assert_batch(fetched)
        assert fetched["status"] == "MIXING"
        assert fetched["batch_charge_cents"] is None
        assert fetched["batch_charge_standard_cents"] is None


class TestClosureSurchargeBracket:
    def test_batch_closure_bracket_read_pre_surcharge(self, api, qa_manager_headers):
        """PRD §3.6: "Second, the surcharge rate is read from that pre-surcharge
        materials subtotal alone: two percent when the subtotal is below one
        million cents, five percent otherwise; the bracket is never read from the
        post-surcharge total."

        Design: Difficulty/combinatorial_formula/batch_closure_bracket_read_pre_surcharge
        """
        ctx = confirmed_order_for_closure(component_cost=2475)
        batch = create_batch(ctx["order"]["id"], 400)
        lot = create_lot(ctx["component"]["id"], lot_code="D1", quantity_received=400,
                         unit_cost_per_kg_cents=2475)
        allocate_lots(ctx["order"]["id"], [allocation_item(lot["id"], 400, batch_id=batch["id"])])
        start_mixing(batch["id"])

        rejected = reject_batch(batch["id"], reason="off-spec", headers=qa_manager_headers)
        # materials 400*2475 = 990000 < 1000000 => 2% => 990000 + 19800 = 1009800
        assert rejected["batch_charge_cents"] == 1009800

    def test_batch_closure_high_surcharge_bracket(self, api, qa_manager_headers):
        """PRD §3.6: "Second, the surcharge rate is read from that pre-surcharge
        materials subtotal alone: two percent when the subtotal is below one
        million cents, five percent otherwise; the bracket is never read from the
        post-surcharge total."

        Design: Difficulty/combinatorial_formula/batch_closure_bracket_read_pre_surcharge
        """
        ctx = confirmed_order_for_closure(component_cost=2600)
        batch = create_batch(ctx["order"]["id"], 400)
        lot = create_lot(ctx["component"]["id"], lot_code="D1", quantity_received=400,
                         unit_cost_per_kg_cents=2600)
        allocate_lots(ctx["order"]["id"], [allocation_item(lot["id"], 400, batch_id=batch["id"])])
        start_mixing(batch["id"])

        rejected = reject_batch(batch["id"], reason="off-spec", headers=qa_manager_headers)
        # materials 400*2600 = 1040000 >= 1000000 => 5% => 1040000 + 52000 = 1092000
        assert rejected["batch_charge_cents"] == 1092000


class TestIpcRetryCycle:
    def test_batch_ipc_retry_cycle(self, api, qa_manager_headers):
        """PRD §3.6: "The applied tolerance tightens as failures accumulate:
        after a given number of failed rounds, the effective tolerance equals the
        base tolerance multiplied by the larger of one-half and the quantity one
        minus one-tenth times the number of failed rounds — each failure shrinks
        the band by ten percent of the base, never below half of it."
        PRD §3.6: "An `IPC_FAILED` batch may be sent back to `MIXING` for
        adjustment by a `QAManager`, optionally annotated with an
        `adjustment_note`; both round flags reset to `NONE` and a new round
        begins."

        Design: Difficulty/non_linear_state_machine/batch_ipc_retry_cycle
        """
        ctx = mixing_batch_ctx()
        batch_id = ctx["batch"]["id"]

        # Round 1: viscosity band 4000*10% = 400; |5000-4000| = 1000 > 400 -> FAIL.
        check1 = record_ipc_check(batch_id, "VISCOSITY", 5000, QA1)
        assert check1["result"] == "FAIL"

        adjusted = adjust_batch(batch_id, QA1)
        assert adjusted["failed_check_count"] == 1
        assert adjusted["status"] == "MIXING"
        assert adjusted["round_viscosity_result"] == "NONE"
        assert adjusted["round_ph_result"] == "NONE"

        # Round 2: tightened band 400 * (1 - 0.10*1) = 360; |4300-4000| = 300 <= 360 -> PASS.
        check2 = record_ipc_check(batch_id, "VISCOSITY", 4300, QA1)
        assert check2["effective_tolerance"] == 360
        assert check2["result"] == "PASS"
        check3 = record_ipc_check(batch_id, "PH", 5.5, QA1)
        assert check3["result"] == "PASS"

        fetched = validate_success(api.get_batch(batch_id, qa_manager_headers), 200)
        assert fetched["status"] == "IPC_PASSED"

    def test_ipc_adjust_rejected_after_budget_exhausted(self, api, qa_manager_headers):
        """PRD §3.6: "The retry budget is three failed rounds: once
        `failed_check_count` has reached three, adjustment is rejected with
        `ERR_IPC_ATTEMPTS_EXHAUSTED` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/batch_ipc_retry_cycle
        """
        ctx = mixing_batch_ctx()
        batch_id = ctx["batch"]["id"]

        for _ in range(3):
            record_ipc_check(batch_id, "VISCOSITY", 5000, QA1)  # FAIL each round
            # Rounds 1 and 2 may be adjusted back to MIXING; round 3 exhausts.
            batch = validate_success(api.get_batch(batch_id, qa_manager_headers), 200)
            if batch["failed_check_count"] < 3:
                adjust_batch(batch_id, QA1)

        exhausted = validate_success(api.get_batch(batch_id, qa_manager_headers), 200)
        assert exhausted["failed_check_count"] == 3
        resp = api.adjust_batch(batch_id, {"adjustment_note": "again"}, QA1)
        validate_error(resp, ApiErrorId.ERR_IPC_ATTEMPTS_EXHAUSTED, 422)


class TestIpcToleranceBoundary:
    def test_ph_and_viscosity_exactly_at_tolerance_pass(self, api, qa_manager_headers):
        """PRD §3.6: "For a `VISCOSITY` check, the band is the formula's
        `viscosity_target_cps` scaled by `viscosity_tolerance_pct` percent and
        then by the tightening factor, and the check passes when the absolute
        deviation of `measured_value` from `viscosity_target_cps` is within the
        band — a reading exactly at the band edge passes."
        PRD §3.6: "For a `PH` check, the band is the formula's `ph_tolerance`
        scaled by the tightening factor, compared the same way against
        `ph_target` with the same inclusive edge."

        Design: Difficulty/boundary_precision_check/ph_and_viscosity_exactly_at_tolerance_pass
        """
        ctx = mixing_batch_ctx()
        batch_id = ctx["batch"]["id"]

        visc = record_ipc_check(batch_id, "VISCOSITY", 4400, QA1)  # deviation 400 == band 400
        assert visc["result"] == "PASS"
        ph = record_ipc_check(batch_id, "PH", 6.0, QA1)  # deviation 0.5 == tolerance 0.5
        assert ph["result"] == "PASS"

        fetched = validate_success(api.get_batch(batch_id, qa_manager_headers), 200)
        assert fetched["status"] == "IPC_PASSED"

    def test_viscosity_one_tick_beyond_band_fails(self, api, qa_manager_headers):
        """PRD §3.6: "the check passes when the absolute deviation of
        `measured_value` from `viscosity_target_cps` is within the band — a
        reading exactly at the band edge passes."
        PRD §3.6: "any `FAIL` immediately moves the batch to `IPC_FAILED`, sets
        the failing check's round flag to `FAIL`, and increments
        `failed_check_count` by one."

        Design: Difficulty/boundary_precision_check/ph_and_viscosity_exactly_at_tolerance_pass
        """
        ctx = mixing_batch_ctx()
        batch_id = ctx["batch"]["id"]

        check = record_ipc_check(batch_id, "VISCOSITY", 4401, QA1)  # deviation 401 > band 400
        assert check["result"] == "FAIL"

        fetched = validate_success(api.get_batch(batch_id, qa_manager_headers), 200)
        assert_batch(fetched)
        assert fetched["status"] == "IPC_FAILED"
        assert fetched["failed_check_count"] == 1


class TestIpcRecordShape:
    def test_ipc_check_immutable_event_record(self, api):
        """PRD §2.4: "Two kinds of records are append-only quality records and
        depart from this convention: an in-process check recorded against a
        batch, and a stability reading recorded against a study. Both carry only
        `id` and `created_at`; `updated_at` and `version` are absent from them
        entirely."
        PRD §3.6: "Every record is stamped with a `round_index` of one plus the
        batch's `failed_check_count` at record time, the `effective_tolerance`
        actually applied, the computed `result` of `PASS` or `FAIL`, and the
        recorder's identity as `recorded_by_user_id`".

        Design: Corner/entities/ipc_check_immutable_event_record
        """
        ctx = mixing_batch_ctx()
        resp = api.record_ipc_check(
            ctx["batch"]["id"], {"check_type": "VISCOSITY", "measured_value": 4100},
            make_qa_manager_headers("qa-1"))
        check = validate_success(resp, 201)
        assert_ipc_check(check)
        assert check["recorded_by_user_id"] == "qa-1"
        assert check["result"] == "PASS"


class TestReleaseGates:
    def test_batch_release_from_mixing_rejected(self, api, qa_manager_headers):
        """PRD §3.6: "A `QAManager` releases an `IPC_PASSED` batch, subject to
        two gates evaluated in this order".
        PRD §2.9: "Every stateful resource moves only along the transitions
        declared for its lifecycle in §3; terminal states reject every further
        transition."

        Design: Corner/state_machines/batch_release_from_mixing_rejected
        """
        ctx = mixing_batch_ctx()
        batch_id = ctx["batch"]["id"]
        record_ipc_check(batch_id, "VISCOSITY", 4000, QA1)

        # qa-2 is not the last IPC recorder, so the segregation gate passes and
        # the state gate is what fires.
        resp = api.release_batch(batch_id, QA2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        fetched = validate_success(api.get_batch(batch_id, qa_manager_headers), 200)
        assert fetched["status"] == "MIXING"

    def test_batch_release_blocked_by_failed_study(self, api):
        """PRD §3.6: "segregation of duties — the releasing user's identity must
        differ from the batch's `last_ipc_recorded_by_user_id`, failing with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and study clearance — no
        stability study of the order's formula may stand `COMPLETED_FAIL`,
        failing with `ERR_STUDY_FAILED_BLOCKS_RELEASE` (HTTP 409)."
        PRD §3.7: "a `FAIL` reading at any point ends the study as
        `COMPLETED_FAIL`, freeing one unit of chamber capacity and blocking all
        future batch releases for the formula per §3.6".

        Design: Difficulty/cross_entity_state_dependency/batch_release_blocked_by_failed_study
        """
        ctx = ipc_passed_batch_ctx()
        chamber = create_chamber(chamber_code="CH1", capacity_studies=4)
        study = create_study(ctx["formula"]["id"], chamber["id"], "ACCELERATED")
        record_reading(study["id"], 30, "FAIL")  # study -> COMPLETED_FAIL

        resp = api.release_batch(ctx["batch"]["id"], QA2)
        validate_error(resp, ApiErrorId.ERR_STUDY_FAILED_BLOCKS_RELEASE, 409)

    def test_completed_pass_study_does_not_block_release(self, api):
        """PRD §3.6: "study clearance — no stability study of the order's
        formula may stand `COMPLETED_FAIL`, failing with
        `ERR_STUDY_FAILED_BLOCKS_RELEASE` (HTTP 409)."
        PRD §3.7: "a `PASS` recorded against the final required interval ends the
        study as `COMPLETED_PASS`, likewise freeing chamber capacity."

        Design: Difficulty/cross_entity_state_dependency/batch_release_blocked_by_failed_study
        """
        ctx = ipc_passed_batch_ctx()
        chamber = create_chamber(chamber_code="CH1", capacity_studies=4)
        study = create_study(ctx["formula"]["id"], chamber["id"], "PRESERVATIVE_EFFICACY")
        record_reading(study["id"], 28, "PASS")  # study -> COMPLETED_PASS

        released = release_batch(ctx["batch"]["id"], QA2)
        assert_batch(released)
        assert released["status"] == "RELEASED_TO_FILLING"


class TestScaleUpGate:
    def test_scale_up_threshold_boundary(self, api, plant_director_headers,
                                         production_planner_headers):
        """PRD §3.6: "the system derives its `scale_up_factor` as the planned
        bulk mass divided by the fifty-kilogram laboratory reference mass."
        PRD §3.6: "When a batch's `scale_up_factor` exceeds ten, mixing may not
        begin until a `PlantDirector` approves scale-up for that batch, setting
        `scale_up_approved` to true; attempting to start without the approval is
        rejected with `ERR_SCALE_UP_APPROVAL_REQUIRED` (HTTP 422)."

        Design: Corner/calculations/scale_up_threshold_boundary
        """
        ctx = confirmed_order_for_closure(component_cost=1000)
        batch_500 = create_batch(ctx["order"]["id"], 500)
        batch_600 = create_batch(ctx["order"]["id"], 600)
        lot = create_lot(ctx["component"]["id"], lot_code="A1", quantity_received=1200)
        allocate_lots(ctx["order"]["id"], [
            allocation_item(lot["id"], 500, batch_id=batch_500["id"]),
            allocation_item(lot["id"], 600, batch_id=batch_600["id"]),
        ])

        assert batch_500["scale_up_factor"] == 10
        assert batch_600["scale_up_factor"] == 12

        started = start_mixing(batch_500["id"])
        assert started["status"] == "MIXING", "factor exactly 10 must not require approval"

        resp = api.start_mixing(batch_600["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_SCALE_UP_APPROVAL_REQUIRED, 422)

        approved = validate_success(api.approve_scale_up(batch_600["id"], plant_director_headers), 200)
        assert approved["scale_up_approved"] is True
        started_600 = start_mixing(batch_600["id"])
        assert started_600["status"] == "MIXING"


def confirmed_order_for_closure(component_cost=1000):
    """Customer + raw component + ACTIVE 100%-AQUA formula + CONFIRMED 2000-unit
    order. Shared preamble for closure-charge and scale-up tests."""
    customer = create_customer()
    component = create_component(standard_cost_per_kg_cents=component_cost)
    formula = create_active_formula(customer["id"], component_id=component["id"])
    order = create_order(customer["id"], formula["id"], 2000)
    confirm_order(order["id"], customer["id"])
    return {"customer": customer, "component": component, "formula": formula, "order": order}
