"""Retail contracts: lifecycle branch, termination cascade, weekly settlement,
fill-rate variants, penalty threshold, and fiscal floors (PRD §3.4, §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_crop, create_crop_with_active_recipe, create_loop_rack, create_growing_batch,
    mark_harvest_ready, harvest_batch, safety_release, pack_batch,
    set_clock, schedule_cycle, start_cycle, record_cycle_result,
    setup_packed_batch, create_contract, create_shipment, get_shipment_lines,
    confirm_pack, setup_reserved_shipment, setup_packed_shipment,
    make_quality_assurance_headers,
    SEED_CLOCK, QA_USER_ID_2, SANITATION_USER_1,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]
CM = TEST_USERS["contracts_manager_headers"]


class TestContractLifecycleBranch:
    def _packed_batch_and_contract(self, api):
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=4)
        contract = create_contract(ctx["crop"]["id"])
        return ctx, contract

    def test_suspend_blocks_shipment_create_and_reinstate_restores(self, api):
        """PRD §3.5: "while `SUSPENDED`, new shipment creation is refused with
        `ERR_CONTRACT_NOT_ACTIVE`" and "Reinstatement returns a suspended contract to
        `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/contract_suspension_cycle_and_termination_branch
        """
        ctx, contract = self._packed_batch_and_contract(api)
        suspended = validate_success(api.suspend_contract(contract["id"], CM))
        assert suspended["contract_status"] == "SUSPENDED"

        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T08:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": suspended["version"],
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 10.0}]}, CM)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

        reinstated = validate_success(api.reinstate_contract(contract["id"], CM))
        assert reinstated["contract_status"] == "ACTIVE", "the suspend loop is reversible"
        shipment = create_shipment(contract["id"],
                                   [{"batch_id": ctx["batch"]["id"], "reserved_lb": 10.0}])
        assert shipment["shipment_status"] == "RESERVED"

    def test_terminate_is_terminal_and_locks_reinstate(self, api):
        """PRD §3.5: "Termination, available from `ACTIVE` or `SUSPENDED`, is terminal".
        A reinstate on a `TERMINATED` contract is an invalid lifecycle transition
        (PRD §2.10 tier 5, `ERR_INVALID_STATE_TRANSITION`).

        Design: Difficulty/non_linear_state_machine/contract_suspension_cycle_and_termination_branch
        """
        ctx, contract = self._packed_batch_and_contract(api)
        terminated = validate_success(api.terminate_contract(contract["id"], CM))
        assert terminated["contract_status"] == "TERMINATED"

        resp = api.reinstate_contract(contract["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestContractTerminateCascade:
    def test_terminate_cancels_open_shipment_and_releases_lines(self, api):
        """PRD §3.5: "Termination ... fires the §2.8 cascade in reverse: every shipment
        still `RESERVED` or `PACKED` is canceled, each canceled shipment's lines in
        `RESERVED`, `PACKED`, or `SHORTED` are released".

        Design: Difficulty/transitive_cascade/contract_terminate_release_cascade
        """
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=4)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=25.0)

        validate_success(api.terminate_contract(ship_ctx["contract"]["id"], CM))
        shipment = validate_success(api.get_shipment(ship_ctx["shipment"]["id"], CM))
        assert shipment["shipment_status"] == "CANCELED"
        lines = get_shipment_lines(ship_ctx["shipment"]["id"])
        assert lines[0]["line_status"] == "RELEASED"

    def test_terminate_restores_batch_reservation_pools(self, api):
        """PRD §3.5: "each affected batch's `reserved_lb` and `packed_available_lb` are
        recomputed." PRD §3.5 (cancel cascade): "each release subtracts the line's
        reserved pounds from the batch's `reserved_lb` and returns any packed pounds to
        `packed_available_lb`".

        Design: Difficulty/transitive_cascade/contract_terminate_release_cascade
        """
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=4)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=25.0)
        batch_mid = validate_success(api.get_batch(ctx["batch"]["id"], GR))
        assert batch_mid["reserved_lb"] == pytest.approx(25.00)
        assert batch_mid["packed_available_lb"] == pytest.approx(75.00)

        validate_success(api.terminate_contract(ship_ctx["contract"]["id"], CM))
        batch_end = validate_success(api.get_batch(ctx["batch"]["id"], GR))
        assert batch_end["reserved_lb"] == pytest.approx(0.00)
        assert batch_end["packed_available_lb"] == pytest.approx(100.00)


class TestFillRateVariants:
    def _settlement_scenario(self, api):
        """Two packed batches (300.00 / 190.00 lb); contract 500 lb/wk; S1 SHIPPED 300,
        S2 RESERVED 190 (never ships)."""
        crop, _ = create_crop_with_active_recipe()
        loop, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=8)
        cy1 = schedule_cycle(loop["id"], "2026-08-22T01:00:00Z", "2026-08-22T03:00:00Z")
        b1 = create_growing_batch(crop["id"], [t["id"] for t in towers[0:4]], seed_clock=SEED_CLOCK)
        b2 = create_growing_batch(crop["id"], [t["id"] for t in towers[4:8]], seed_clock=SEED_CLOCK)
        start_cycle(cy1["id"], "2026-08-22T01:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-22T03:30:00Z",
                            recorded_by=SANITATION_USER_1)
        for b, pounds in ((b1, 300.0), (b2, 190.0)):
            mark_harvest_ready(b["id"])
            harvest_batch(b["id"], pounds)
            safety_release(b["id"])
            pack_batch(b["id"], pounds)
        contract = create_contract(crop["id"])
        s1 = create_shipment(contract["id"], [{"batch_id": b1["id"], "reserved_lb": 300.0}],
                             window_start="2026-08-24T08:00:00Z",
                             window_end="2026-08-24T20:00:00Z")
        confirm_pack(s1["id"])
        set_clock("2026-08-24T15:00:00Z")
        validate_success(api.ship_shipment(s1["id"], CM))
        s2 = create_shipment(contract["id"], [{"batch_id": b2["id"], "reserved_lb": 190.0}],
                             window_start="2026-08-24T17:00:00Z",
                             window_end="2026-08-24T21:00:00Z")
        return crop, contract, b2, s2

    def test_provisional_counts_reserved_final_counts_only_shipped(self, api):
        """PRD §3.5: "the provisional figure optimistically counts `RESERVED` and
        `PACKED` pounds as if they will ship, while the final figure counts only what
        shipped."

        Design: Difficulty/dual_variant_calc/fill_rate_provisional_vs_final_settlement
        """
        _, contract, _, _ = self._settlement_scenario(api)
        summary = validate_success(api.get_contract_week_summary(
            contract["id"], CM, params={"week_start_date": "2026-08-24"}))
        # provisional: (300 shipped + 190 reserved) / 500; final: 300 / 500
        assert summary["provisional_fill_rate"] == pytest.approx(0.9800)
        assert summary["final_fill_rate"] == pytest.approx(0.6000)

    def test_settle_sweeps_unshipped_and_accrues_penalty(self, api):
        """PRD §3.5: "Settlement first sweeps: every still-open shipment whose
        `ship_date` falls inside the week is moved to `EXPIRED` with the release cascade
        above" and "When the final fill rate is strictly below `fill_rate_threshold` —
        equality pays nothing — the penalty is the shortfall pounds times
        `penalty_cents_per_short_lb`, multiplied by 1.25 when `consecutive_short_weeks`
        is at least one ... and by 1.0 otherwise".

        Design: Difficulty/dual_variant_calc/fill_rate_provisional_vs_final_settlement
        """
        _, contract, b2, s2 = self._settlement_scenario(api)
        set_clock("2026-08-31T00:00:00Z")  # week [2026-08-24, 2026-08-31) fully ended
        validate_success(api.settle_contract_week(contract["id"],
                                                  {"week_start_date": "2026-08-24"}, CM))

        s2_after = validate_success(api.get_shipment(s2["id"], CM))
        assert s2_after["shipment_status"] == "EXPIRED", "settle sweep expires the unshipped shipment"
        summary = validate_success(api.get_contract_week_summary(
            contract["id"], CM, params={"week_start_date": "2026-08-24"}))
        assert summary["final_fill_rate"] == pytest.approx(0.6000)
        assert summary["penalty_cents"] == 30000, "short 200 lb x 150 cents, multiplier 1.0"
        contract_after = validate_success(api.get_contract(contract["id"], CM))
        assert contract_after["consecutive_short_weeks"] == 1
        batch_after = validate_success(api.get_batch(b2["id"], GR))
        assert batch_after["packed_available_lb"] == pytest.approx(190.00)
        assert batch_after["reserved_lb"] == pytest.approx(0.00)


class TestFillRateThresholdBoundary:
    def _shipped_contract(self, api, pounds: float):
        ctx = setup_packed_batch(packed_lb=pounds, grade_a_lb=pounds, tower_count=8)
        contract = create_contract(ctx["crop"]["id"])
        s = create_shipment(contract["id"], [{"batch_id": ctx["batch"]["id"], "reserved_lb": pounds}])
        confirm_pack(s["id"])
        set_clock("2026-08-24T15:00:00Z")
        validate_success(api.ship_shipment(s["id"], CM))
        return contract

    def test_fill_rate_exactly_at_threshold_pays_nothing(self, api):
        """PRD §3.5: "When the final fill rate is strictly below `fill_rate_threshold` —
        equality pays nothing".

        Design: Difficulty/boundary_precision_check/fill_rate_threshold_exact_equality_pays_nothing
        """
        contract = self._shipped_contract(api, 490.0)  # 490/500 == 0.9800 == threshold
        set_clock("2026-08-31T00:00:00Z")
        validate_success(api.settle_contract_week(contract["id"],
                                                  {"week_start_date": "2026-08-24"}, CM))
        summary = validate_success(api.get_contract_week_summary(
            contract["id"], CM, params={"week_start_date": "2026-08-24"}))
        assert summary["final_fill_rate"] == pytest.approx(0.9800)
        assert summary["penalty_cents"] == 0
        contract_after = validate_success(api.get_contract(contract["id"], CM))
        assert contract_after["consecutive_short_weeks"] == 0

    def test_fill_rate_one_pound_below_threshold_pays_penalty(self, api):
        """PRD §3.5: "Shortfall pounds are the commitment minus shipped pounds, floored
        at zero" and the penalty is "the shortfall pounds times
        `penalty_cents_per_short_lb`, multiplied by ... 1.0 otherwise, rounded half-up
        to whole cents at the final step; `consecutive_short_weeks` then increments by
        one."

        Design: Difficulty/boundary_precision_check/fill_rate_threshold_exact_equality_pays_nothing
        """
        contract = self._shipped_contract(api, 489.0)  # 489/500 == 0.9780 < 0.9800
        set_clock("2026-08-31T00:00:00Z")
        validate_success(api.settle_contract_week(contract["id"],
                                                  {"week_start_date": "2026-08-24"}, CM))
        summary = validate_success(api.get_contract_week_summary(
            contract["id"], CM, params={"week_start_date": "2026-08-24"}))
        assert summary["final_fill_rate"] == pytest.approx(0.9780)
        assert summary["penalty_cents"] == 1650, "11 short lb x 150 cents, first short week"
        contract_after = validate_success(api.get_contract(contract["id"], CM))
        assert contract_after["consecutive_short_weeks"] == 1


class TestContractSuspendGate:
    def _packed_shipment_scenario(self, api):
        ctx = setup_packed_batch(packed_lb=46.0, tower_count=4)
        ship_ctx = setup_packed_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=10.0)
        return ctx, ship_ctx

    def test_suspend_blocked_while_shipment_packed(self, api):
        """PRD §3.5: "a `ContractsManager` may suspend an `ACTIVE` contract only while
        none of its shipments is `PACKED` — a mid-flight packed shipment blocks the move
        with `ERR_SHIPMENT_IN_FLIGHT`".

        Design: Difficulty/cross_entity_state_dependency/contract_suspend_blocked_by_packed_shipment
        """
        _, ship_ctx = self._packed_shipment_scenario(api)
        resp = api.suspend_contract(ship_ctx["contract"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_IN_FLIGHT)

    def test_suspend_succeeds_after_shipment_ships(self, api):
        """PRD §3.5: "a `ContractsManager` may suspend an `ACTIVE` contract only while
        none of its shipments is `PACKED`" — once the shipment has shipped, the gate
        opens.

        Design: Difficulty/cross_entity_state_dependency/contract_suspend_blocked_by_packed_shipment
        """
        _, ship_ctx = self._packed_shipment_scenario(api)
        set_clock("2026-08-24T15:00:00Z")
        validate_success(api.ship_shipment(ship_ctx["shipment"]["id"], CM))
        suspended = validate_success(api.suspend_contract(ship_ctx["contract"]["id"], CM))
        assert suspended["contract_status"] == "SUSPENDED"


class TestContractCreationValidation:
    def test_price_below_floor_rejected(self, api):
        """PRD §3.5: "a `price_per_pound_cents` that may not undercut the crop's
        `floor_price_cents_per_lb` (`ERR_PRICE_BELOW_FLOOR`)".

        Design: Corner/errors/price_below_floor_rejected
        """
        crop = create_crop(crop_code="KALE-01", floor_price_cents_per_lb=100)
        resp = api.create_contract(
            {"retailer_name": "FreshMart", "crop_id": crop["id"], "weekly_commitment_lb": 500,
             "price_per_pound_cents": 99, "penalty_cents_per_short_lb": 150,
             "fill_rate_threshold": 0.98, "week_start_day": "MONDAY",
             "start_date": "2026-08-24", "end_date": "2026-09-20"}, CM)
        validate_error(resp, ApiErrorId.ERR_PRICE_BELOW_FLOOR)
        # Exactly at the floor does not undercut it.
        ok = api.create_contract(
            {"retailer_name": "FreshMart", "crop_id": crop["id"], "weekly_commitment_lb": 500,
             "price_per_pound_cents": 100, "penalty_cents_per_short_lb": 150,
             "fill_rate_threshold": 0.98, "week_start_day": "MONDAY",
             "start_date": "2026-08-24", "end_date": "2026-09-20"}, CM)
        validate_success(ok, expected_status=201)

    def test_contract_window_invalid_rejected(self, api):
        """PRD §3.5: "the end must fall strictly after the start
        (`ERR_CONTRACT_WINDOW_INVALID`)".

        Design: Corner/errors/contract_window_invalid_rejected
        """
        crop = create_crop(crop_code="KALE-01")
        resp = api.create_contract(
            {"retailer_name": "FreshMart", "crop_id": crop["id"], "weekly_commitment_lb": 500,
             "price_per_pound_cents": 245, "penalty_cents_per_short_lb": 150,
             "fill_rate_threshold": 0.98, "week_start_day": "MONDAY",
             "start_date": "2026-08-24", "end_date": "2026-08-24"}, CM)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_INVALID)


class TestSettleWeekChronology:
    def test_settle_week_chronology_enforced(self, api):
        """PRD §3.5: "A `ContractsManager` settles by supplying a `week_start_date` that
        must equal the contract's `next_unsettled_week_start`, and only once the week
        has fully ended — settling any other week, or a week still in progress, is
        `ERR_WEEK_NOT_SETTLABLE`" and "the first settlement week begins on the first
        `week_start_day` on or after `start_date`; that date is stored as
        `next_unsettled_week_start`" and "`next_unsettled_week_start` advances by seven
        days".

        Design: Corner/calculations/settle_week_chronology_enforced
        """
        crop = create_crop(crop_code="KALE-01")
        contract = create_contract(crop["id"], start_date="2026-08-03", end_date="2026-09-28")
        assert contract["next_unsettled_week_start"] == "2026-08-03", \
            "2026-08-03 is itself the MONDAY anchor"

        set_clock("2026-08-05T00:00:00Z")  # inside week 1
        resp_early = api.settle_contract_week(contract["id"], {"week_start_date": "2026-08-03"}, CM)
        validate_error(resp_early, ApiErrorId.ERR_WEEK_NOT_SETTLABLE)

        set_clock("2026-08-17T00:00:00Z")  # weeks 1 and 2 have both ended
        resp_skip = api.settle_contract_week(contract["id"], {"week_start_date": "2026-08-10"}, CM)
        validate_error(resp_skip, ApiErrorId.ERR_WEEK_NOT_SETTLABLE)

        settled = validate_success(api.settle_contract_week(
            contract["id"], {"week_start_date": "2026-08-03"}, CM))
        assert settled["next_unsettled_week_start"] == "2026-08-10"

        resp_again = api.settle_contract_week(contract["id"], {"week_start_date": "2026-08-03"}, CM)
        validate_error(resp_again, ApiErrorId.ERR_WEEK_NOT_SETTLABLE)


class TestCondemnCascade:
    def test_condemn_releases_lines_and_cancels_emptied_shipment(self, api):
        """PRD §3.4: "A `CONDEMNED` decision — reachable from `PENDING`, `QUARANTINED`,
        or even `RELEASED` — is destructive: every shipment line on the batch in
        `RESERVED`, `PACKED`, or `SHORTED` flips to `RELEASED`, each shipment's
        `reserved_lb` is recomputed, a shipment whose lines have all been released
        collapses to `CANCELED`, and the batch's `packed_available_lb` is forced to
        zero."

        Design: Corner/errors/condemn_releases_lines_and_cancels_emptied_shipment
        """
        ctx = setup_packed_batch(packed_lb=46.0, tower_count=1)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=10.0)

        condemned = validate_success(api.safety_release_batch(
            ctx["batch"]["id"], {"decision": "CONDEMNED", "lab_ref": "LAB-E10"},
            make_quality_assurance_headers(QA_USER_ID_2)))
        assert condemned["safety_status"] == "CONDEMNED"
        assert condemned["packed_available_lb"] == pytest.approx(0.00)

        line = get_shipment_lines(ship_ctx["shipment"]["id"])[0]
        assert line["line_status"] == "RELEASED", "condemn force-releases the reserved line"
        shipment = validate_success(api.get_shipment(ship_ctx["shipment"]["id"], CM))
        assert shipment["shipment_status"] == "CANCELED", \
            "a shipment whose lines have all been released collapses to CANCELED"
