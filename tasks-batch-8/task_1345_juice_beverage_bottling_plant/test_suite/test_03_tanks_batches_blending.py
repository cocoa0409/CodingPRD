"""Tank booking, batch planning, blending transitions, and clean-in-place."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, plan_batch, blend_and_record,
    qa_verdict, set_clock, create_qa_passed_batch,
)

# Module-level alias of the session-scoped `api` fixture (conftest returns
# the same object) so module/class helpers can call the client without
# declaring the fixture parameter.
api = api_client


PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["blend_operator_headers"]
QA = TEST_USERS["qa_inspector_headers"]


def _customer_formula():
    customer = create_customer()
    formula = create_formula(customer["id"], approve=False)
    return customer, formula


class TestBatchCreate:
    def test_batch_create_copies_anchor_and_occupies_tank(self, api):
        """PRD §3.3: "Creating the batch lands it in `PLANNED`, stamps
        `initial_quantity_liters` equal to the requested volume — an anchor that
        is never overwritten — and flips the tank from `AVAILABLE` to `OCCUPIED`,
        pointing `occupying_batch_id` at the new batch and adopting the formula's
        allergen group as the tank's `allergen_group`."

        Design: Corner/entities/batch_create_side_effects_and_copies
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False, allergen_group="TREE_NUT")
        tank = create_tank()
        resp = api.create_batch(
            factories.create_batch_payload(formula["id"], tank["id"], quantity_liters=1500), OP)
        batch = validate_success(resp, 201)
        assert batch["status"] == "PLANNED"
        assert batch["initial_quantity_liters"] == 1500
        assert batch["quantity_liters"] == 1500
        assert batch["adjustment_count"] == 0
        tank_after = get_success_data(api.get_tank(tank["id"], PM))
        assert tank_after["posture"] == "OCCUPIED"
        assert tank_after["occupying_batch_id"] == batch["id"]
        assert tank_after["allergen_group"] == "TREE_NUT"

    def test_batch_create_zeroes_adjustment_counters(self, api):
        """PRD §3.4: "A successful correction accumulates into `added_water_liters`
        or `added_concentrate_liters` as appropriate, grows `quantity_liters` by
        the same addition, increments `adjustment_count` by one" — a fresh batch
        has accumulated nothing.

        Design: Corner/entities/batch_create_side_effects_and_copies
        """
        customer, formula = _customer_formula()
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1500)
        assert batch["added_water_liters"] == 0
        assert batch["added_concentrate_liters"] == 0
        # never recorded / never linked: unset or null are both faithful readings
        assert batch.get("measured_brix") is None
        assert batch.get("linked_run_id") is None


class TestBatchSizeBounds:
    def test_batch_below_floor_rejected(self, api):
        """PRD §3.3: "The initial `quantity_liters` must be at least 500 liters,
        else `ERR_BATCH_TOO_SMALL`, and must not exceed the tank's capacity, else
        `ERR_TANK_CAPACITY_EXCEEDED`."

        Design: Corner/validations/batch_create_size_bounds
        """
        customer, formula = _customer_formula()
        tank = create_tank(capacity_liters=5000)
        resp = api.create_batch(
            factories.create_batch_payload(formula["id"], tank["id"], quantity_liters=400), OP)
        validate_error(resp, ApiErrorId.ERR_BATCH_TOO_SMALL)
        assert resp.status_code == 422

    def test_batch_over_capacity_rejected(self, api):
        """PRD §3.3: "The initial `quantity_liters` must be at least 500 liters,
        else `ERR_BATCH_TOO_SMALL`, and must not exceed the tank's capacity, else
        `ERR_TANK_CAPACITY_EXCEEDED`."

        Design: Corner/validations/batch_create_size_bounds
        """
        customer, formula = _customer_formula()
        tank = create_tank(capacity_liters=5000)
        resp = api.create_batch(
            factories.create_batch_payload(formula["id"], tank["id"], quantity_liters=6000), OP)
        validate_error(resp, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED)
        assert resp.status_code == 422

    def test_batch_at_exactly_floor_accepted(self, api):
        """PRD §3.3: "The initial `quantity_liters` must be at least 500 liters,
        else `ERR_BATCH_TOO_SMALL`"

        Design: Corner/validations/batch_create_size_bounds
        """
        customer, formula = _customer_formula()
        tank = create_tank(capacity_liters=5000)
        # the failed attempts below/above leave the tank AVAILABLE
        resp = api.create_batch(
            factories.create_batch_payload(formula["id"], tank["id"], quantity_liters=400), OP)
        validate_error(resp, ApiErrorId.ERR_BATCH_TOO_SMALL)
        batch = get_success_data(api.create_batch(
            factories.create_batch_payload(formula["id"], tank["id"], quantity_liters=500), OP))
        assert batch["status"] == "PLANNED"


class TestTankWindowGap:
    def _tank_with_occupying_batch(self):
        """A batch holding its 08:00-12:00 window while the tank is AVAILABLE
        again. Per PRD §3.3 a batch keeps holding its window through PROCESSING,
        and the tank returns to AVAILABLE only once the batch has entered
        PROCESSING and the CIP cycle has completed — the sole state in which the
        tank-window check (category 8) is reachable past the tank-availability
        gate (category 5)."""
        customer, formula = _customer_formula()
        tank = create_tank()
        batch_e = create_qa_passed_batch(formula, tank, quantity_liters=1000,
                                         planned_start_at="2026-08-10T08:00:00Z",
                                         planned_end_at="2026-08-10T12:00:00Z")
        prun = get_success_data(api.create_process_run(
            factories.create_process_run_payload(batch_e["id"], "PASTEURIZATION"), OP))
        get_success_data(api.start_process_run(prun["id"], OP))  # tank -> AWAITING_CIP
        get_success_data(api.start_cip(tank["id"], OP))
        # NONE allergen group requires two hours; finishing at exactly +2h is allowed
        set_clock("2026-08-01T02:00:00Z")
        tank_after = get_success_data(api.complete_cip(tank["id"], OP))
        assert tank_after["posture"] == "AVAILABLE"
        return formula, tank, batch_e

    def test_touching_window_conflicts_closed_interval(self, api):
        """PRD §2.4: "Tank occupation windows are **closed intervals**: a batch
        booked from its `planned_start_at` through its `planned_end_at` occupies
        the tank at both endpoints." and §3.3: "crowding is rejected with
        `ERR_TANK_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tank_closed_interval_flat_gap
        """
        formula, tank, _ = self._tank_with_occupying_batch()
        # start exactly at the occupant's end: closed intervals share the endpoint
        resp = api.create_batch(
            factories.create_batch_payload(
                formula["id"], tank["id"], quantity_liters=1000,
                planned_start_at="2026-08-10T12:00:00Z",
                planned_end_at="2026-08-10T16:00:00Z"), OP)
        validate_error(resp, ApiErrorId.ERR_TANK_WINDOW_CONFLICT)

    def test_gap_one_minute_short_conflicts(self, api):
        """PRD §3.3: "Two windows on the same tank coexist only when a flat
        three-hour hygiene gap fits between them — the later window's start must
        fall at least three hours after the earlier window's end, in either order,
        and a gap of exactly three hours suffices; crowding is rejected with
        `ERR_TANK_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tank_closed_interval_flat_gap
        """
        formula, tank, _ = self._tank_with_occupying_batch()
        # 2h59m after the occupant's end: one minute short of the 3h gap
        resp = api.create_batch(
            factories.create_batch_payload(
                formula["id"], tank["id"], quantity_liters=1000,
                planned_start_at="2026-08-10T14:59:00Z",
                planned_end_at="2026-08-10T18:00:00Z"), OP)
        validate_error(resp, ApiErrorId.ERR_TANK_WINDOW_CONFLICT)

    def test_exactly_three_hour_gap_accepted(self, api):
        """PRD §3.3: "a gap of exactly three hours suffices"

        Design: Difficulty/resource_temporal_overlap/tank_closed_interval_flat_gap
        """
        formula, tank, batch_e = self._tank_with_occupying_batch()
        batch_n = get_success_data(api.create_batch(
            factories.create_batch_payload(
                formula["id"], tank["id"], quantity_liters=1000,
                planned_start_at="2026-08-10T15:00:00Z",
                planned_end_at="2026-08-10T18:00:00Z"), OP))
        assert batch_n["status"] == "PLANNED"
        tank_after = get_success_data(api.get_tank(tank["id"], PM))
        assert tank_after["posture"] == "OCCUPIED"


class TestBatchInvalidTransitions:
    def test_planned_accepts_only_start_blend(self, api):
        """PRD §3.3: "When the operator begins blending (`PLANNED` → `BLENDING`),
        the batch must stand in `PLANNED` (else `ERR_BATCH_STATE_INVALID`)" and
        §3.4: "A `QAInspector` may condemn a batch standing in `QA_FAILED`,
        `PROCESSED`, or `RELEASED` — any other state draws
        `ERR_BATCH_STATE_INVALID`" and §3.4: "From either source the batch must
        currently stand in `PROCESSED` or `PROCESSING`, else
        `ERR_BATCH_STATE_INVALID`"

        Design: Corner/state_machines/batch_invalid_transition_sweep
        """
        customer, formula = _customer_formula()
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        bid = batch["id"]
        for resp in (
            api.record_blend(bid, {"measured_brix": 12.1}, OP),
            api.qa_verdict(bid, {"verdict": "PASS"}, QA),
            api.apply_adjustment(bid, OP),
            api.condemn_batch(bid, QA),
            api.release_batch(bid, QA),
        ):
            validate_error(resp, ApiErrorId.ERR_BATCH_STATE_INVALID)
        assert get_success_data(api.get_batch(bid, PM))["status"] == "PLANNED"

    def test_blending_and_awaiting_qa_gates(self, api):
        """PRD §3.4: "The verdict on a batch standing in `AWAITING_QA` — any other
        state draws `ERR_BATCH_STATE_INVALID` — takes a `verdict` of `PASS` or
        `FAIL`."

        Design: Corner/state_machines/batch_invalid_transition_sweep
        """
        customer, formula = _customer_formula()
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        bid = batch["id"]
        blending = get_success_data(api.start_blend(bid, OP))
        assert blending["status"] == "BLENDING"
        # verdict needs AWAITING_QA; re-start needs PLANNED
        validate_error(api.qa_verdict(bid, {"verdict": "PASS"}, QA),
                       ApiErrorId.ERR_BATCH_STATE_INVALID)
        validate_error(api.start_blend(bid, OP), ApiErrorId.ERR_BATCH_STATE_INVALID)
        awaiting = get_success_data(api.record_blend(bid, {"measured_brix": 12.1}, OP))
        assert awaiting["status"] == "AWAITING_QA"
        # re-record and start from AWAITING_QA are both state errors
        validate_error(api.record_blend(bid, {"measured_brix": 12.2}, OP),
                       ApiErrorId.ERR_BATCH_STATE_INVALID)
        validate_error(api.start_blend(bid, OP), ApiErrorId.ERR_BATCH_STATE_INVALID)


class TestCipCycle:
    def _two_tanks_awaiting_cip(self):
        """Tank A held a TREE_NUT batch, tank B a NONE batch; both batches are now
        PROCESSING, so both tanks stand AWAITING_CIP. Also returns a fresh tank C."""
        customer = create_customer()
        formula_nut = create_formula(customer["id"], approve=False, allergen_group="TREE_NUT")
        formula_none = create_formula(customer["id"], approve=False, allergen_group="NONE",
                                      target_brix=12.0)
        tank_a = create_tank()
        tank_b = create_tank()
        tank_c = create_tank()
        for formula, tank in ((formula_nut, tank_a), (formula_none, tank_b)):
            batch = create_qa_passed_batch(formula, tank, quantity_liters=1000)
            prun = get_success_data(api.create_process_run(
                factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
            get_success_data(api.start_process_run(prun["id"], OP))
        return tank_a, tank_b, tank_c

    def test_cip_required_hours_by_allergen_group(self, api):
        """PRD §3.3: "From `AWAITING_CIP`, a `BlendOperator` begins clean-in-place
        (any other posture draws `ERR_TANK_STATE_INVALID`), which stamps
        `cip_started_at` from the logical clock and computes `cip_required_hours`
        — six hours when the tank's recorded allergen group is anything other than
        `NONE`, two hours otherwise."

        Design: Corner/state_machines/tank_cip_cycle_duration_and_guards
        """
        tank_a, tank_b, tank_c = self._two_tanks_awaiting_cip()
        set_clock("2026-08-10T08:00:00Z")
        started_a = get_success_data(api.start_cip(tank_a["id"], OP))
        started_b = get_success_data(api.start_cip(tank_b["id"], OP))
        assert started_a["cip_required_hours"] == 6
        assert started_b["cip_required_hours"] == 2
        assert started_a["cip_started_at"] is not None
        # posture gates
        validate_error(api.start_cip(tank_c["id"], OP), ApiErrorId.ERR_TANK_STATE_INVALID)
        validate_error(api.start_cip(tank_a["id"], OP), ApiErrorId.ERR_TANK_STATE_INVALID)

    def test_cip_duration_equality_and_shortfall(self, api):
        """PRD §3.3: "Completing the wash is allowed only from `IN_CIP` and only
        once the clock has reached `cip_started_at` plus the required hours;
        finishing at exactly the required instant is permitted, while an earlier
        attempt is refused with `ERR_CIP_DURATION_INSUFFICIENT`."

        Design: Corner/state_machines/tank_cip_cycle_duration_and_guards
        """
        tank_a, tank_b, _ = self._two_tanks_awaiting_cip()
        set_clock("2026-08-10T08:00:00Z")
        get_success_data(api.start_cip(tank_a["id"], OP))
        get_success_data(api.start_cip(tank_b["id"], OP))
        set_clock("2026-08-10T10:00:00Z")  # exactly +2h
        done_b = get_success_data(api.complete_cip(tank_b["id"], OP))
        assert done_b["posture"] == "AVAILABLE"
        assert done_b["allergen_group"] == "NONE"
        resp = api.complete_cip(tank_a["id"], OP)  # +2h < 6h required
        validate_error(resp, ApiErrorId.ERR_CIP_DURATION_INSUFFICIENT)
        set_clock("2026-08-10T14:00:00Z")  # exactly +6h
        done_a = get_success_data(api.complete_cip(tank_a["id"], OP))
        assert done_a["posture"] == "AVAILABLE"
        assert done_a["allergen_group"] == "NONE"
