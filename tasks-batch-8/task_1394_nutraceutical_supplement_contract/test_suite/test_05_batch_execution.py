"""Batch start/consumption/complete rules, lot quantity reconciliation, voids."""
from test_helpers import (
    TEST_USERS,
    WINDOW_DAY1,
    ApiErrorId,
    assert_batch_consumption,
    assert_lot_mass_invariant,
    coa_review,
    create_raw_material,
    create_released_lot,
    get_batch,
    get_material_lot,
    make_catalog,
    place_order,
    record_consumption,
    run_batch,
    schedule_order,
    start_batch,
    submit_identity_test,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestBatchStart:
    def test_batch_start_twice_rejected(self, api):
        """PRD §3.4: "A `ProductionOperator` may start a batch whose
        `production_status` is `CREATED` (`ERR_BATCH_STATE` otherwise)."

        Design: Corner/state_machines/batch_start_twice_rejected
        """
        ctx = make_catalog()
        run = run_batch(ctx, window=WINDOW_DAY1, stage="IN_PROCESS")
        batch_id = run["batch"]["id"]

        resp = api.start_batch(batch_id, {}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BATCH_STATE)
        assert resp.status_code == 409
        assert get_batch(batch_id)["production_status"] == "IN_PROCESS"


class TestConsumptionGates:
    def test_consumption_rejected_while_lot_quarantined(self, api):
        """PRD §3.4: "Three gates apply: the lot must be `RELEASED`
        (`ERR_LOT_NOT_RELEASED`), the lot's raw material must appear among the
        ordered formula's lines (`ERR_FORMULA_MATERIAL_MISMATCH`, HTTP 400), and the
        consumed quantity must not exceed the lot's `qty_remaining` — equality is
        allowed — with violations rejected as `ERR_INSUFFICIENT_LOT_QUANTITY`
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/consumption_gated_on_lot_release
        """
        ctx = make_catalog(release_lot=False)
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(batch["id"])
        assert ctx["lot"]["status"] == "QUARANTINE"

        resp = api.record_consumption(
            batch["id"],
            {"material_lot_id": ctx["lot"]["id"], "qty_consumed": 5500000},
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_RELEASED)
        assert resp.status_code == 409

    def test_consumption_allowed_once_lot_released(self, api):
        """PRD §3.4: "The row is created in `ACTIVE` status with `batch_id` pointing
        at its batch, and the lot's `qty_remaining` is recomputed as `qty_received`
        minus the sum of `qty_consumed` over all `ACTIVE` consumption rows for that
        lot."

        Design: Difficulty/cross_entity_state_dependency/consumption_gated_on_lot_release
        """
        ctx = make_catalog(release_lot=False)
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(batch["id"])

        test = submit_identity_test(ctx["lot"]["id"], result="PASS", coa_match=True)
        coa_review(test["id"], "APPROVE")
        assert get_material_lot(ctx["lot"]["id"])["status"] == "RELEASED"

        resp = api.record_consumption(
            batch["id"],
            {"material_lot_id": ctx["lot"]["id"], "qty_consumed": 5500000},
            OPERATOR,
        )
        consumption = validate_success(resp, 201)
        assert_batch_consumption(consumption)
        assert consumption["status"] == "ACTIVE"
        assert consumption["batch_id"] == batch["id"]

        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["qty_remaining"] == 10000000 - 5500000  # 4500000

    def test_consumption_of_material_not_in_formula_rejected(self, api):
        """PRD §3.4: "the lot's raw material must appear among the ordered
        formula's lines (`ERR_FORMULA_MATERIAL_MISMATCH`, HTTP 400)".

        Design: Corner/validations/consumption_material_not_in_formula_rejected
        """
        ctx = make_catalog()
        other_material = create_raw_material("Magnesium", "NONE")
        other_lot = create_released_lot(other_material["id"], qty_received=100000)

        run = run_batch(ctx, window=WINDOW_DAY1, stage="IN_PROCESS")
        resp = api.record_consumption(
            run["batch"]["id"],
            {"material_lot_id": other_lot["id"], "qty_consumed": 1000},
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORMULA_MATERIAL_MISMATCH)
        assert resp.status_code == 400

    def test_consumption_beyond_lot_remaining_rejected_equality_allowed(self, api):
        """PRD §3.4: "the consumed quantity must not exceed the lot's
        `qty_remaining` — equality is allowed — with violations rejected as
        `ERR_INSUFFICIENT_LOT_QUANTITY` (HTTP 422)."

        Design: Corner/validations/consumption_exceeds_lot_remaining_rejected
        """
        # Walk to IN_PROCESS without consuming so the lot stays at 600000.
        ctx = make_catalog(lot_qty=600000)
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(batch["id"])

        over = api.record_consumption(
            batch["id"],
            {"material_lot_id": ctx["lot"]["id"], "qty_consumed": 600001},
            OPERATOR,
        )
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)
        assert over.status_code == 422

        exact = api.record_consumption(
            batch["id"],
            {"material_lot_id": ctx["lot"]["id"], "qty_consumed": 600000},
            OPERATOR,
        )
        consumption = validate_success(exact, 201)
        assert consumption["status"] == "ACTIVE"
        assert get_material_lot(ctx["lot"]["id"])["qty_remaining"] == 0, (
            "consuming exactly qty_remaining is allowed and drains the lot to zero"
        )


class TestCompletionCoverage:
    def test_complete_without_consumption_rejected(self, api):
        """PRD §3.4: "the completion is rejected with `ERR_INCOMPLETE_CONSUMPTION`
        unless every line of the ordered formula has at least one `ACTIVE`
        consumption row."

        Design: Corner/state_machines/batch_complete_without_consumption_rejected
        """
        ctx = make_catalog()
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(batch["id"])

        resp = api.complete_batch(
            batch["id"],
            {"actual_yield_units": 9800, "actual_bulk_mass_g": 5390},
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_CONSUMPTION)
        assert resp.status_code == 409
        assert get_batch(batch["id"])["production_status"] == "IN_PROCESS"


class TestLotMassConservation:
    def test_consume_debits_lot_remaining(self, api):
        """PRD §3.4: "the lot's `qty_remaining` is recomputed as `qty_received`
        minus the sum of `qty_consumed` over all `ACTIVE` consumption rows for that
        lot."

        Design: Difficulty/compensating_invariant/lot_mass_conserved_on_consume_and_void
        """
        ctx = make_catalog(lot_qty=1000000)
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(batch["id"])

        resp = api.record_consumption(
            batch["id"],
            {"material_lot_id": ctx["lot"]["id"], "qty_consumed": 400000},
            OPERATOR,
        )
        consumption = validate_success(resp, 201)
        assert consumption["status"] == "ACTIVE"

        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["qty_remaining"] == 600000
        assert_lot_mass_invariant(lot, 400000)

    def test_void_restores_lot_mass_exactly(self, api):
        """PRD §3.4: "The void moves the row to `VOIDED`, records the operator in
        `voided_by_id`, and restores the lot's `qty_remaining` by the same
        reconciliation rule, since voided rows no longer contribute to the active
        sum."

        Design: Difficulty/compensating_invariant/lot_mass_conserved_on_consume_and_void
        """
        ctx = make_catalog(lot_qty=1000000)
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(batch["id"])
        consumption = record_consumption(batch["id"], ctx["lot"]["id"], 400000)
        assert get_material_lot(ctx["lot"]["id"])["qty_remaining"] == 600000

        resp = api.void_consumption(batch["id"], consumption["id"], {}, OPERATOR)
        voided = validate_success(resp, 200)
        assert voided["status"] == "VOIDED"
        assert voided["voided_by_id"] == "op-1"

        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["qty_remaining"] == 1000000, (
            "compensation must restore the lot mass exactly"
        )
        assert_lot_mass_invariant(lot, 0)


class TestImmediateConsistency:
    def test_consumption_response_and_lot_read_agree_immediately(self, api):
        """PRD §3.4: "The row is created in `ACTIVE` status with `batch_id` pointing
        at its batch, and the lot's `qty_remaining` is recomputed as `qty_received`
        minus the sum of `qty_consumed` over all `ACTIVE` consumption rows for that
        lot. This reconciliation runs on every consumption event".

        Design: Corner/consistency_model/immediate_read_after_write_across_cascade
        """
        ctx = make_catalog(lot_qty=1000000)
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(batch["id"])

        resp = api.record_consumption(
            batch["id"],
            {"material_lot_id": ctx["lot"]["id"], "qty_consumed": 400000},
            OPERATOR,
        )
        validate_success(resp, 201)
        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["qty_remaining"] == 600000, (
            "the very next read must reflect the debited quantity (no async lag)"
        )
