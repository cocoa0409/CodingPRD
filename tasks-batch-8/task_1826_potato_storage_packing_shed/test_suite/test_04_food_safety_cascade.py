"""Food safety: wash-water thresholds, the posture state machine cycle, and the
quarantine cascade across runs, lots, orders, and contracts (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_grower_shed_bin_lot, setup_allocated_contract_order,
    create_shed, create_binned_lot, assess_lot, create_contract, create_order,
    allocate_order, record_pass_wash, record_fail_wash, record_wash_check,
    create_scheduled_run, set_clock, refresh_lot, refresh_order, refresh_contract,
    refresh_shed,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
QA = TEST_USERS["qa_headers"]
STORAGE = TEST_USERS["storage_headers"]
INTAKE = TEST_USERS["intake_headers"]


class TestWashResultThresholds:
    def test_turbidity_and_chlorine_inclusive_boundaries(self, api):
        """PRD §3.7: "The check's `result` is derived: it is `PASS` when turbidity is at most 4.0 NTU, chlorine is between 50 and 200 ppm inclusive, and water temperature is between 45 and 60 degrees Fahrenheit inclusive; otherwise it is `FAIL`. A turbidity reading of exactly 4.0 passes; 4.01 fails."

        Design: Corner/calculations/c_wash_turbidity_inclusive_boundary
        """
        shed = create_shed("Shed DD")

        r1 = record_wash_check(shed["id"], measured_at="2026-08-01T01:00:00Z",
                               turbidity_ntu=4.0, chlorine_ppm=50, water_temp_f=45)
        assert r1["result"] == "PASS"  # 4.0 <= 4.0; chlorine 50 and temp 45 on inclusive bounds

        r2 = record_wash_check(shed["id"], measured_at="2026-08-01T02:00:00Z",
                               turbidity_ntu=4.01, chlorine_ppm=100, water_temp_f=50)
        assert r2["result"] == "FAIL"  # 4.01 > 4.0

        r3 = record_wash_check(shed["id"], measured_at="2026-08-01T03:00:00Z",
                               turbidity_ntu=2.0, chlorine_ppm=200, water_temp_f=60)
        assert r3["result"] == "PASS"  # chlorine 200, temp 60 inclusive

        r4 = record_wash_check(shed["id"], measured_at="2026-08-01T04:00:00Z",
                               turbidity_ntu=2.0, chlorine_ppm=49, water_temp_f=50)
        assert r4["result"] == "FAIL"  # chlorine 49 < 50


class TestShedPostureCycle:
    def test_consecutive_failures_drive_restricted(self, api):
        """PRD §3.7: "A `FAIL` increments `consecutive_wash_failures`... A `PASS` resets `consecutive_wash_failures` to zero and clears `wash_quarantine_flag`."
        PRD §3.7: "The shed is `QUARANTINED` whenever either quarantine flag is set; otherwise it is `RESTRICTED` when `consecutive_wash_failures` has reached at least two; otherwise it is `NORMAL`."

        Design: Difficulty/non_linear_state_machine/shed_posture_cycle
        """
        shed = create_shed("Shed G")

        c1 = record_fail_wash(shed["id"], "2026-08-02T01:00:00Z")
        assert c1["result"] == "FAIL"  # 5.0 > 4.0
        p1 = refresh_shed(shed["id"])
        assert p1["posture"] == "NORMAL"  # only 1 consecutive failure

        c2 = record_fail_wash(shed["id"], "2026-08-02T02:00:00Z")
        assert c2["result"] == "FAIL"
        p2 = refresh_shed(shed["id"])
        assert p2["posture"] == "RESTRICTED"
        assert p2["consecutive_wash_failures"] == 2

    def test_pass_resets_counter_and_severe_fail_quarantines(self, api):
        """PRD §3.7: "if the failing check's turbidity exceeds 8.0 NTU it also sets `wash_quarantine_flag`."
        PRD §3.7: "After every check and every audit close, the shed's `posture` is recomputed. The shed is `QUARANTINED` whenever either quarantine flag is set; otherwise it is `RESTRICTED` when `consecutive_wash_failures` has reached at least two; otherwise it is `NORMAL`."

        Design: Difficulty/non_linear_state_machine/shed_posture_cycle
        """
        shed = create_shed("Shed G")

        record_fail_wash(shed["id"], "2026-08-02T01:00:00Z")
        record_fail_wash(shed["id"], "2026-08-02T02:00:00Z")

        c3 = record_pass_wash(shed["id"], "2026-08-02T03:00:00Z")
        assert c3["result"] == "PASS"
        p3 = refresh_shed(shed["id"])
        assert p3["posture"] == "NORMAL"  # counter reset

        c4 = record_wash_check(shed["id"], measured_at="2026-08-02T04:00:00Z",
                               turbidity_ntu=9.0, chlorine_ppm=100, water_temp_f=50)
        assert c4["result"] == "FAIL"
        p4 = refresh_shed(shed["id"])
        # 9.0 > 8.0 severe-turbidity flag: a single check suffices.
        assert p4["posture"] == "QUARANTINED"

        record_pass_wash(shed["id"], "2026-08-02T05:00:00Z")
        p5 = refresh_shed(shed["id"])
        assert p5["posture"] == "NORMAL"  # PASS cleared the quarantine flag
        assert p5["consecutive_wash_failures"] == 0


class TestRestrictedIntakeGate:
    def test_restricted_shed_blocks_new_bin_assignment(self, api):
        """PRD §3.7: "Posture gates intake and packing as described elsewhere: a `RESTRICTED` or `QUARANTINED` shed rejects new bin assignments (`ERR_SHED_RESTRICTED` and `ERR_SHED_QUARANTINED` respectively)".
        PRD §3.1: "The target bin must exist (else `ERR_BIN_NOT_FOUND`) and must belong to a shed whose posture is currently `NORMAL` — a `RESTRICTED` shed rejects the assignment with `ERR_SHED_RESTRICTED` and a `QUARANTINED` shed rejects it with `ERR_SHED_QUARANTINED`."

        Design: Corner/validations/c_restricted_shed_blocks_intake
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AG", grower_code="G-AG", shed_name="Shed DR",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        # Un-bin the setup lot's state by working with a fresh INTAKE lot instead.
        from test_helpers import create_lot
        lot = create_lot(ctx["grower"]["id"], harvest_date="2026-07-28",
                         original_weight_cwt=100.00)
        record_fail_wash(ctx["shed"]["id"], "2026-08-01T01:00:00Z")
        record_fail_wash(ctx["shed"]["id"], "2026-08-01T02:00:00Z")

        resp = api.assign_bin(lot["id"], {"bin_id": ctx["bin"]["id"]}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_SHED_RESTRICTED)

        lot = refresh_lot(lot["id"])
        assert lot["storage_status"] == "INTAKE"
        assert lot["quality_status"] == "CLEAR"  # no hold cascade on RESTRICTED


class TestQuarantineCascade:
    @staticmethod
    def _setup_allocated_pool():
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Eight", grower_code="G-EIGHT", shed_name="Shed H",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=500.00, price_cents_per_cwt=2000,
                                   grade_min_us1_pct=80.0, buyer_name="Buyer F")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=200.00, grade_min_us1_pct=80.0)
        allocate_order(order["id"])
        return {**ctx, "contract": contract, "order": order}

    def test_severe_fail_cascades_posture_to_lot_hold(self, api):
        """PRD §3.7: "Entering `QUARANTINED` fires a cascade. Every `SCHEDULED` pack run whose order names this shed auto-transitions to `ABORTED`, and each such run's order drops from `PACKING` back to `ALLOCATED` with its reservations retained. Every `CLEAR` lot in the shed's bins transitions to `ON_HOLD`."

        Design: Difficulty/transitive_cascade/wash_fail_quarantine_cascade
        """
        ctx = self._setup_allocated_pool()

        w = record_wash_check(ctx["shed"]["id"], measured_at="2026-08-02T06:00:00Z",
                              turbidity_ntu=9.0, chlorine_ppm=100, water_temp_f=50)
        assert w["result"] == "FAIL"
        shed = refresh_shed(ctx["shed"]["id"])
        assert shed["posture"] == "QUARANTINED"  # hop 1: check -> posture

        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["quality_status"] == "ON_HOLD"  # hop 2: posture -> lot hold
        assert abs(lot["reserved_cwt"] - 0.00) <= 0.005  # hop 3: hold -> release

    def test_cascade_resets_order_and_restores_contract(self, api):
        """PRD §3.7: "Then, for every order holding a reservation on any newly held lot, that lot's reservation is released (the lot's `reserved_cwt` decremented) and the order's coverage is rechecked: if the remaining reservations no longer cover the outstanding need, the full de-allocation reset of §3.6 applies; a `CONTRACT` order's commitment ledger is restored on the full reset".
        PRD §3.6: "Every remaining reservation is released (each lot's `reserved_cwt` decremented accordingly), the contract ledger is restored as on a cancellation from `ALLOCATED` (decrementing `allocated_active_cwt` and incrementing `remaining_committed_cwt` by the outstanding need), and the order's status moves from `ALLOCATED` or `PACKING` back to `REQUESTED`."

        Design: Difficulty/transitive_cascade/wash_fail_quarantine_cascade
        """
        ctx = self._setup_allocated_pool()
        record_wash_check(ctx["shed"]["id"], measured_at="2026-08-02T06:00:00Z",
                          turbidity_ntu=9.0, chlorine_ppm=100, water_temp_f=50)

        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "REQUESTED"  # hop 3b: coverage 0 < need 200 -> full reset
        assert order["reservations"] == []

        contract = refresh_contract(ctx["contract"]["id"])
        # hop 4: order reset -> contract commitment restored 300 -> 500
        assert abs(contract["remaining_committed_cwt"] - 500.00) <= 0.005
        assert abs(contract["allocated_active_cwt"] - 0.00) <= 0.005

    def test_quarantine_auto_aborts_scheduled_run(self, api):
        """PRD §3.7: "Entering `QUARANTINED` fires a cascade. Every `SCHEDULED` pack run whose order names this shed auto-transitions to `ABORTED`, and each such run's order drops from `PACKING` back to `ALLOCATED` with its reservations retained."

        Design: Corner/cross_cutting_complexity_layers/c_quarantine_aborts_scheduled_runs
        """
        ctx = setup_allocated_contract_order(
            lot_weight_cwt=500.00, committed_cwt=300.00, requested_packed_cwt=75.00,
            set_clock_to="2026-08-02T00:00:00Z",
        )
        record_pass_wash(ctx["shed"]["id"], "2026-08-02T06:00:00Z")
        run = create_scheduled_run(ctx["order"]["id"], "2026-08-02T08:00:00Z",
                                   "2026-08-02T10:00:00Z")

        record_wash_check(ctx["shed"]["id"], measured_at="2026-08-02T07:00:00Z",
                          turbidity_ntu=9.0, chlorine_ppm=100, water_temp_f=50)

        run = get_success_data(api.get_pack_run(run["id"], TEST_USERS["supervisor_headers"]))
        assert run["status"] == "ABORTED"  # auto-aborted by the cascade
        order = refresh_order(ctx["order"]["id"])
        # The subsequent lot-hold hop releases reservations and resets the order fully.
        assert order["status"] in ("ALLOCATED", "REQUESTED")


class TestQuarantineHoldReleaseGate:
    def test_hold_release_blocked_until_quarantine_clears(self, api):
        """PRD §3.8: "Releasing a hold is a transition whose `to_status` is `CLEAR`. It requires the lot to be `ON_HOLD` and its shed's posture not to be `QUARANTINED` (`ERR_SHED_QUARANTINED`); success returns the lot to `CLEAR`."

        Design: Corner/validations/c_quarantine_blocks_hold_release
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AH", grower_code="G-AH", shed_name="Shed DS",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        # Severe FAIL quarantines the shed and auto-holds the lot.
        record_wash_check(ctx["shed"]["id"], measured_at="2026-08-01T01:00:00Z",
                          turbidity_ntu=9.0, chlorine_ppm=100, water_temp_f=50)

        resp = api.quality_transition(ctx["lot"]["id"], {"to_status": "CLEAR"}, QA)
        validate_error(resp, ApiErrorId.ERR_SHED_QUARANTINED)

        # A PASS clears the quarantine flag; the hold can now be released.
        record_pass_wash(ctx["shed"]["id"], "2026-08-01T02:00:00Z")
        lot = get_success_data(api.quality_transition(ctx["lot"]["id"], {"to_status": "CLEAR"}, QA))
        assert lot["quality_status"] == "CLEAR"
