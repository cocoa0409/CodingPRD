"""Finished-goods lots: pack-out math, expiry variants, release gates, billing
(PRD §3.5, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_batch,
    create_approved_recipe,
    create_batch,
    create_copack_customer,
    create_film_lot,
    create_freezer_cell,
    create_order,
    create_packaging_line,
    get_batch,
    get_lot,
    get_lot_of_batch,
    kit_batch,
    cook_batch,
    make_qa_manager_headers,
    pin_clock,
    record_both_ccp_passes,
    record_ccp,
    release_lot,
    schedule_run,
    setup_qa_pending_lot,
    setup_releasable_lot,
    book_cycle,
    start_and_verify_cycle,
    start_run,
    complete_run,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
QA_MGR = TEST_USERS["qa_manager_headers"]


class TestPackOutMath:
    def test_pack_out_math_cases_weight_yield(self, api):
        """PRD §3.5: "the lot's `cases_produced` is `units_packed` divided by the
        case pack of the order's pack format — twelve units per case for `RETAIL`,
        six for `FOODSERVICE` — rounded up to a whole case, and its `net_weight_kg`
        is `units_packed` multiplied by the recipe's `portion_weight_g` and divided
        by one thousand, rounded half up to three decimal places"
        PRD §3.3: "`yield_pct` — null until the first completed run — expresses that
        accumulation as a percentage of the batch's `units_planned`, rounded half
        up to two decimal places."
        PRD §3.5: "The order's `units_packed_total` grows by the same
        `units_packed`, and the run's `version` increments."

        Design: Corner/calculations/pack_out_math_cases_weight_yield
        """
        pin_clock()
        env = setup_qa_pending_lot(
            run_over={"units_planned": 6000},
            complete_run_over={"units_packed": 5700, "film_meters_consumed": 2671},
        )
        lot = env["lot"]
        # ceil(5700 / 12) = 475 cases; 5700 * 340 / 1000 = 1938.000 kg.
        assert lot["cases_produced"] == 475, (
            f"ceil(5700/12) = 475, got {lot['cases_produced']}"
        )
        assert lot["net_weight_kg"] == pytest.approx(1938.000, abs=1e-6)
        assert lot["release_status"] == "QA_PENDING", "a lot is born QA_PENDING"

        batch = get_batch(env["batch"]["id"])
        # round_half_up(5700 / 6000 * 100, 2) = 95.00
        assert batch["yield_pct"] == pytest.approx(95.00, abs=1e-9)
        assert batch["status"] == "PACKED", (
            f"run completion auto-advances the batch FROZEN -> PACKED, got {batch['status']}"
        )
        order = validate_success(api.get_production_order(env["order"]["id"], PLANNER))
        assert order["units_packed_total"] == 5700


class TestShelfLifeDualVariant:
    def _expiry_lot(self):
        """Lot whose cycle was PLANNED to start 2026-08-02 but VERIFIED with an
        actual end on 2026-08-03 — the two expiry variants diverge by one day."""
        pin_clock()
        return setup_qa_pending_lot(
            recipe_over={"name": "R-Expiry", "shelf_life_days": 365},
            order_over={"units_planned": 12000},
            batch_units=6000,
            cycle_over={"planned_start": "2026-08-02T22:00:00Z"},
            complete_over={"actual_end": "2026-08-03T03:00:00Z", "final_core_temp_c": -20},
        )

    def test_provisional_expiry_anchors_to_planned_start(self, api):
        """PRD §3.7: "The `provisional_expiry_date` is the calendar date of that
        cycle's `planned_start` plus the recipe's `shelf_life_days`; it serves
        planning, labels, and pre-verification projections."

        Design: Difficulty/dual_variant_calc/shelf_life_provisional_vs_final_expiry
        """
        env = self._expiry_lot()
        lot = get_lot(env["lot"]["id"])
        # date(planned_start 2026-08-02) + 365 days.
        assert lot["provisional_expiry_date"] == "2027-08-02", (
            f"provisional variant anchors to the planned start date, got "
            f"{lot['provisional_expiry_date']}"
        )

    def test_final_expiry_anchors_to_actual_end(self, api):
        """PRD §3.7: "The `final_expiry_date` is the calendar date of that cycle's
        `actual_end` plus the recipe's `shelf_life_days`; it governs release
        gating, shipment gating, and the complaint day math of §3.8"
        PRD §3.7: "The two variants diverge whenever the cycle verifies on a
        different calendar date than planned"

        Design: Difficulty/dual_variant_calc/shelf_life_provisional_vs_final_expiry
        """
        env = self._expiry_lot()
        lot = get_lot(env["lot"]["id"])
        # date(actual_end 2026-08-03) + 365 days.
        assert lot["final_expiry_date"] == "2027-08-03", (
            f"final variant anchors to the actual verified end date, got "
            f"{lot['final_expiry_date']}"
        )
        assert lot["provisional_expiry_date"] != lot["final_expiry_date"], (
            "the variants diverge when verification lands on a different calendar date"
        )


class TestCoPackBillingVariants:
    def _billed_order(self, customer_over):
        """Full chain through lot release for one co-pack customer:
        6000 RETAIL units packed -> 500 cases, 2040.000 kg net."""
        pin_clock()
        recipe = create_approved_recipe(name="R-Bill")
        customer = create_copack_customer(**customer_over)
        order = create_order(
            recipe["id"], units_planned=6000, copack_customer_id=customer["id"]
        )
        batch = create_batch(order["id"], units_planned=6000)
        kit_batch(batch["id"])
        cook_batch(batch["id"], cooked_mass_kg=1550)
        cell = create_freezer_cell()
        cycle = book_cycle(batch["id"], cell_id=cell["id"])
        start_and_verify_cycle(cycle["id"])
        line = create_packaging_line()
        film = create_film_lot(rolls_received=20)
        run = schedule_run(line["id"], batch["id"], film["id"], units_planned=6000)
        start_run(run["id"])
        complete_run(run["id"], units_packed=6000, film_meters_consumed=2671)
        lot = get_lot_of_batch(batch["id"])
        record_both_ccp_passes(batch["id"], "qa-tech-1")
        complete_batch(batch["id"])
        release_lot(lot["id"], "qa-mgr-1")
        return order

    def test_billing_per_case_variant(self, api):
        """PRD §3.7: "Under `PER_CASE`, the order's `billed_amount_cents` is the
        sum of `cases_produced` across all of the order's `RELEASED` lots,
        multiplied by the customer's `case_rate_cents`."
        PRD §3.7: "On success the lot's `release_status` becomes `RELEASED`, its
        `final_expiry_date` is recomputed per the final variant, the owning order's
        `releasable_cases` grows by the lot's `cases_on_hand`, the order's
        `billed_amount_cents` is recomputed per the customer's billing variant"

        Design: Difficulty/dual_variant_calc/copack_billing_per_case_vs_per_kg
        """
        order = self._billed_order(
            {"name": "Cust A", "billing_method": "PER_CASE", "case_rate_cents": 1500}
        )
        after = validate_success(api.get_production_order(order["id"], PLANNER))
        # 500 cases (6000 RETAIL units / 12) * 1500 cents.
        assert after["billed_amount_cents"] == 750000, (
            f"PER_CASE bills 500 * 1500 = 750000, got {after['billed_amount_cents']}"
        )

    def test_billing_per_kg_variant(self, api):
        """PRD §3.7: "Under `PER_KG`, it is the sum of `net_weight_kg` across those
        same released lots, multiplied by the customer's `kg_rate_cents`, with the
        product rounded half up to whole cents exactly once, on the aggregate —
        never per lot."
        PRD §3.7: "Identical physical output can therefore bill differently under
        the two variants, and the variant in force is always the customer's
        declared method."

        Design: Difficulty/dual_variant_calc/copack_billing_per_case_vs_per_kg
        """
        order = self._billed_order(
            {"name": "Cust B", "billing_method": "PER_KG", "kg_rate_cents": 120}
        )
        after = validate_success(api.get_production_order(order["id"], PLANNER))
        # 2040.000 kg (6000 * 340 / 1000) * 120 cents = 244800.
        assert after["billed_amount_cents"] == 244800, (
            f"PER_KG bills round_half_up(2040.000 * 120) = 244800, got "
            f"{after['billed_amount_cents']}"
        )


class TestLotRejectReworkLoop:
    def test_lot_reject_then_rework_returns_to_qa_pending(self, api):
        """PRD §3.7: "A `QAManager` may reject a lot — supplying a `reason` —
        moving it from `QA_PENDING` or `QUARANTINED` to `REJECTED`; rejection is
        not terminal, because the same authority may send a `REJECTED` lot back to
        `QA_PENDING` through the rework loop, again supplying a `reason`."

        Design: Difficulty/non_linear_state_machine/lot_reject_rework_release_cycle
        """
        pin_clock()
        env = setup_releasable_lot()
        rejected = validate_success(
            api.reject_lot(env["lot"]["id"], {"reason": "seal integrity"}, QA_MGR),
            expected_status=200,
        )
        assert rejected["release_status"] == "REJECTED"
        reworked = validate_success(
            api.rework_lot(env["lot"]["id"], {"reason": "re-seal"}, QA_MGR),
            expected_status=200,
        )
        assert reworked["release_status"] == "QA_PENDING", (
            f"the rework loop returns the lot to QA_PENDING, got {reworked['release_status']}"
        )

    def test_lot_reworked_lot_releases_successfully(self, api):
        """PRD §3.7: "Release is the `QAManager`'s central disposition, moving a
        lot from `QA_PENDING` to `RELEASED`, or from `QUARANTINED` back to
        `RELEASED`."
        PRD §3.7: "rejection is not terminal, because the same authority may send
        a `REJECTED` lot back to `QA_PENDING` through the rework loop"

        Design: Difficulty/non_linear_state_machine/lot_reject_rework_release_cycle
        """
        pin_clock()
        env = setup_releasable_lot()
        validate_success(
            api.reject_lot(env["lot"]["id"], {"reason": "seal integrity"}, QA_MGR),
            expected_status=200,
        )
        validate_success(
            api.rework_lot(env["lot"]["id"], {"reason": "re-seal"}, QA_MGR),
            expected_status=200,
        )
        released = release_lot(env["lot"]["id"], "qa-mgr-1")
        assert released["release_status"] == "RELEASED", (
            "a lot that walked QA_PENDING -> REJECTED -> QA_PENDING must still "
            "pass the release gates"
        )


class TestLatestCcpGate:
    def _lot_with_stale_xray_fail(self):
        """Releasable lot, then a NEWER XRAY FAIL recorded on the COMPLETED batch."""
        env = setup_releasable_lot()
        # FAIL on a COMPLETED batch places no hold; the latest-check gate bites at
        # release time instead.
        record_ccp(env["batch"]["id"], "XRAY", False, "qa-tech-2")
        return env

    def test_release_blocked_by_newer_xray_fail(self, api):
        """PRD §3.7: "for each of `METAL_DETECTOR` and `XRAY`, the latest check of
        that type on the batch must exist and be `PASS`, otherwise
        `ERR_CCP_NOT_CURRENT`"
        PRD §3.6: "When a `FAIL` is recorded while the batch is `COMPLETED`, by
        contrast, no hold is placed — the product is already packed and past
        intervention, and enforcement instead lands at release time through the
        latest-check gate of §3.7."

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_latest_ccp_pass
        """
        pin_clock()
        env = self._lot_with_stale_xray_fail()
        batch = get_batch(env["batch"]["id"])
        assert batch["status"] == "COMPLETED", "a FAIL on a COMPLETED batch places no hold"
        resp = api.release_lot(env["lot"]["id"], make_qa_manager_headers("qa-mgr-1"))
        validate_error(resp, ApiErrorId.ERR_CCP_NOT_CURRENT, expected_status=409)

    def test_release_unblocked_by_newer_xray_pass(self, api):
        """PRD §3.7: "for each of `METAL_DETECTOR` and `XRAY`, the latest check of
        that type on the batch must exist and be `PASS`, otherwise
        `ERR_CCP_NOT_CURRENT`"
        PRD §3.7: "On success the lot's `release_status` becomes `RELEASED`"

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_latest_ccp_pass
        """
        pin_clock()
        env = self._lot_with_stale_xray_fail()
        resp = api.release_lot(env["lot"]["id"], make_qa_manager_headers("qa-mgr-1"))
        validate_error(resp, ApiErrorId.ERR_CCP_NOT_CURRENT, expected_status=409)
        # A newer XRAY PASS restores currency; the release gate then opens.
        record_ccp(env["batch"]["id"], "XRAY", True, "qa-tech-1")
        released = validate_success(
            api.release_lot(env["lot"]["id"], make_qa_manager_headers("qa-mgr-1")),
            expected_status=200,
        )
        assert released["release_status"] == "RELEASED"


class TestReleaseRejectedLotPriority:
    def _rejected_lot(self, api, with_ccp: bool):
        env = setup_qa_pending_lot()
        if with_ccp:
            record_both_ccp_passes(env["batch"]["id"], "qa-tech-1")
        complete_batch(env["batch"]["id"])
        validate_success(
            api.reject_lot(env["lot"]["id"], {"reason": "failed lab panel"}, QA_MGR),
            expected_status=200,
        )
        return env

    def test_release_rejected_lot_state_beats_safety(self, api):
        """PRD §2.4: "When several checks could reject the same request, the
        earliest failing stage in the order below determines the error that is
        returned; later stages are never consulted for that request." — "8. **State
        preconditions.**" is listed before "9. **Critical-control safety.**"
        PRD §3.7: "any lot transition attempted from a status where it is undefined
        is rejected with `ERR_LOT_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/release_rejected_lot_state_beats_safety
        """
        pin_clock()
        env = self._rejected_lot(api, with_ccp=False)
        # No CCP checks exist, so the safety gate would also fail; the state
        # stage (8) must surface first.
        resp = api.release_lot(env["lot"]["id"], make_qa_manager_headers("qa-mgr-1"))
        validate_error(resp, ApiErrorId.ERR_LOT_STATE, expected_status=409)

    def test_release_rejected_lot_with_current_ccp_still_state_error(self, api):
        """PRD §3.7: "Release is the `QAManager`'s central disposition, moving a
        lot from `QA_PENDING` to `RELEASED`, or from `QUARANTINED` back to
        `RELEASED`." — release is not defined from `REJECTED`.
        PRD §3.7: "any lot transition attempted from a status where it is undefined
        is rejected with `ERR_LOT_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/release_rejected_lot_state_beats_safety
        """
        pin_clock()
        env = self._rejected_lot(api, with_ccp=True)
        # Both CCP types PASS, so only the state gate can fire: the error must
        # still be ERR_LOT_STATE, never ERR_CCP_NOT_CURRENT.
        resp = api.release_lot(env["lot"]["id"], make_qa_manager_headers("qa-mgr-1"))
        validate_error(resp, ApiErrorId.ERR_LOT_STATE, expected_status=409)
