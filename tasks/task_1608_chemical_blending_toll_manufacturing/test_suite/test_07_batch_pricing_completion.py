"""Batch pricing variants, completion-time derivations, completion gates, and
the terminal cascades (PRD §3.6, §2.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_batch_job,
    author_and_issue_sds,
    author_sds,
    create_and_post_heel_disposal,
    create_batch_job,
    create_package_config,
    get_tank,
    setup_batch_context,
    setup_batch_in_hold_qa,
    setup_batch_ready_for_completion,
    setup_completed_batch,
    setup_released_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

QA = TEST_USERS["qa_validator_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestTheoreticalOutput:
    def test_theoretical_output_kg_correct_value(self, api):
        """PRD §3.6: "The `theoretical_output_kg` is the ordered litres
        multiplied by the recipe's `target_density_kg_per_l`, multiplied by
        the recipe's `theoretical_yield_pct` divided by one hundred, rounded
        half-up to three decimal places, and frozen for the life of the
        batch."

        Design: Corner/calculations/theoretical_output_kg_correct_value
        """
        ctx = setup_batch_context(density=1.5, yield_pct=80, batch_size_l=200)
        batch = ctx["batch"]
        assert_batch_job(batch)
        assert batch["theoretical_output_kg"] == pytest.approx(240.0,
                                                               abs=1e-3), (
            f"200 L * 1.5 kg/L * 0.80 = 240.000 kg, got "
            f"{batch['theoretical_output_kg']}")


class TestFormulatedPricingVariants:
    def _setup_formulated_batch(self, api, **overrides):
        kwargs = dict(pricing_mode="FORMULATED_PRICE", density=1.2,
                      yield_pct=80, batch_size_l=500, lot_quantity_kg=1000,
                      charge_qty_kg=400, heel_returned_kg=50,
                      pricing_overrides={
                          "formulated_price_per_kg_cents": 200,
                          "over_yield_split_pct": 50},
                      package_overrides={"package_count": 3,
                                         "un_rated": False})
        kwargs.update(overrides)
        return setup_batch_ready_for_completion(**kwargs)

    def test_provisional_quote_uses_theoretical_output(self, api):
        """PRD §3.6: "Under `FORMULATED_PRICE`, the provisional quote
        multiplies `formulated_price_per_kg_cents` by the theoretical output
        as the best pre-run estimate" and "The batch is born in `INTAKE` with
        `version` 1, and with `actual_output_kg`, `density_corrected_output_l`,
        `yield_variance_pct`, and `invoiced_price_cents` all null."

        Design: Difficulty/dual_variant_calc/price_batch_job_provisional_vs_final_formulated_mode
        """
        ctx = self._setup_formulated_batch(api)
        batch = validate_success(api.get_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], QM))
        assert batch["theoretical_output_kg"] == pytest.approx(480.0,
                                                               abs=1e-3), (
            f"500 L * 1.2 kg/L * 0.80 = 480.000 kg, got "
            f"{batch['theoretical_output_kg']}")
        assert batch["quoted_price_cents"] == 96000, (
            f"PROVISIONAL: 200 cents/kg * 480 kg = 96000, got "
            f"{batch['quoted_price_cents']}")

    def test_final_invoice_applies_over_yield_credit(self, api):
        """PRD §3.6: "the final invoice multiplies it by `actual_output_kg`;
        when the actual output exceeds the theoretical, the excess kilograms
        generate an over-yield credit — the excess mass multiplied by the
        per-kilogram formulated rate, multiplied by the agreement's
        `over_yield_split_pct` divided by one hundred — which is subtracted
        from the invoice, the blender retaining the unsplit remainder."
        PRD §3.6: "`yield_variance_pct` is the difference between actual and
        theoretical output, divided by the theoretical output, expressed as a
        percentage".

        Design: Difficulty/dual_variant_calc/price_batch_job_provisional_vs_final_formulated_mode
        """
        ctx = self._setup_formulated_batch(api)
        completed = validate_success(api.complete_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], 500, QA))
        assert completed["status"] == "COMPLETED"
        # FINAL: 200 * 500 - (500 - 480) * 200 * 0.50 = 100000 - 2000 = 98000.
        assert completed["invoiced_price_cents"] == 98000, (
            f"FINAL with over-yield credit: expected 98000, got "
            f"{completed['invoiced_price_cents']}")
        assert completed["yield_variance_pct"] == pytest.approx(4.166667,
                                                                abs=1e-3)
        assert completed["density_corrected_output_l"] == pytest.approx(
            416.667, abs=1e-3)


class TestFormulatedPricingCombinatorial:
    def _setup_sixty_split_batch(self, api):
        return setup_batch_ready_for_completion(
            pricing_mode="FORMULATED_PRICE", density=1.0, yield_pct=90,
            batch_size_l=1000, lot_quantity_kg=2000, charge_qty_kg=900,
            heel_returned_kg=100,
            pricing_overrides={"formulated_price_per_kg_cents": 150,
                               "over_yield_split_pct": 60},
            package_overrides={"package_count": 5, "un_rated": False})

    def test_final_invoice_with_sixty_percent_split(self, api):
        """PRD §3.6: "the final invoice multiplies it by `actual_output_kg`;
        when the actual output exceeds the theoretical, the excess kilograms
        generate an over-yield credit — the excess mass multiplied by the
        per-kilogram formulated rate, multiplied by the agreement's
        `over_yield_split_pct` divided by one hundred — which is subtracted
        from the invoice".

        Design: Difficulty/combinatorial_formula/price_batch_job_formulated_over_yield_credit_combinatorial
        """
        ctx = self._setup_sixty_split_batch(api)
        completed = validate_success(api.complete_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], 950, QA))
        # theo = 1000 * 1.0 * 0.90 = 900; base = 150 * 950 = 142500;
        # credit = (950-900) * 150 * 0.60 = 4500; invoiced = 138000.
        assert completed["theoretical_output_kg"] == pytest.approx(900.0,
                                                                   abs=1e-3)
        assert completed["invoiced_price_cents"] == 138000, (
            f"Expected 142500 - 4500 = 138000, got "
            f"{completed['invoiced_price_cents']}")

    def test_variance_and_provisional_quote_at_create(self, api):
        """PRD §3.6: "Under `FORMULATED_PRICE`, the provisional quote
        multiplies `formulated_price_per_kg_cents` by the theoretical output
        as the best pre-run estimate" and "`yield_variance_pct` is the
        difference between actual and theoretical output, divided by the
        theoretical output, expressed as a percentage".

        Design: Difficulty/combinatorial_formula/price_batch_job_formulated_over_yield_credit_combinatorial
        """
        ctx = self._setup_sixty_split_batch(api)
        batch = ctx["batch"]
        assert batch["theoretical_output_kg"] == pytest.approx(900.0, abs=1e-3)
        assert batch["quoted_price_cents"] == 135000, (
            f"PROVISIONAL: 150 * 900 = 135000, got {batch['quoted_price_cents']}")

        completed = validate_success(api.complete_batch_job(
            ctx["customer"]["id"], batch["id"], 950, QA))
        assert completed["yield_variance_pct"] == pytest.approx(5.555556,
                                                                abs=1e-3), (
            f"100 * (950 - 900) / 900 = 5.555556%, got "
            f"{completed['yield_variance_pct']}")


class TestCompletionCascades:
    def test_complete_cascades_tank_available_dirty_with_last_product(
            self, api):
        """PRD §3.6: "The tank then cascades from `IN_USE` back to
        `AVAILABLE`: `occupied_by_batch_id` clears to null,
        `last_product_ghs` takes the batch's
        `highest_component_ghs_snapshot`, and `cleaning_state` returns to
        `DIRTY` — the vessel cannot be reserved again until it has been
        cleaned and validated anew."

        Design: Difficulty/transitive_cascade/batch_complete_cascades_tank_release_and_sds_lock
        """
        ctx = setup_completed_batch(
            ghs_class="FLAMMABLE", density=0.79, yield_pct=98,
            batch_size_l=300, charge_qty_kg=250, actual_output_kg=240,
            heel_returned_kg=10,
            package_overrides={"package_count": 2, "un_rated": True},
            tank_overrides={"capacity_l": 500, "working_capacity_l": 500})
        assert ctx["batch"]["status"] == "COMPLETED"
        tank = ctx["tank"]
        assert tank["operational_state"] == "AVAILABLE"
        assert tank["occupied_by_batch_id"] is None
        assert tank["last_product_ghs"] == "FLAMMABLE"
        assert tank["cleaning_state"] == "DIRTY"

    def test_release_on_recently_completed_tank_rejected_until_recleaned(
            self, api):
        """PRD §3.6: "the vessel cannot be reserved again until it has been
        cleaned and validated anew" and "the tank `CLEAN_VALIDATED` (else
        `ERR_TANK_NOT_CLEAN_VALIDATED`, HTTP 409)".

        Design: Difficulty/transitive_cascade/batch_complete_cascades_tank_release_and_sds_lock
        """
        ctx = setup_completed_batch(
            ghs_class="FLAMMABLE", density=0.79, yield_pct=98,
            batch_size_l=300, charge_qty_kg=250, actual_output_kg=240,
            heel_returned_kg=10,
            package_overrides={"package_count": 2, "un_rated": True},
            tank_overrides={"capacity_l": 500, "working_capacity_l": 500})
        # Third hop: a fresh batch pointing at the now-DIRTY tank.
        batch_b = create_batch_job(
            ctx["customer"]["id"], ctx["recipe"]["id"], ctx["agreement"]["id"],
            ctx["tank"]["id"], batch_size_l=100,
            scheduled_start="2026-10-02T08:00:00Z",
            scheduled_end="2026-10-02T12:00:00Z")
        resp = api.release_batch_job(ctx["customer"]["id"], batch_b["id"],
                                     batch_b["version"],
                                     TEST_USERS["batch_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_TANK_NOT_CLEAN_VALIDATED)


class TestTankOccupancyInvariant:
    def test_release_marks_tank_occupied(self, api):
        """PRD §3.6: "A successful release cascades the tank from `AVAILABLE`
        to `RESERVED`, writes the batch's `id` into the tank's
        `occupied_by_batch_id`, and increments both the tank's and the batch's
        `version`."

        Design: Difficulty/compensating_invariant/tank_occupancy_invariant_via_complete_reverses_reservation
        """
        ctx = setup_released_batch()
        tank = validate_success(api.get_tank(ctx["tank"]["id"], QM))
        assert tank["operational_state"] == "RESERVED"
        assert tank["occupied_by_batch_id"] == ctx["batch"]["id"]

    def test_complete_clears_tank_occupancy(self, api):
        """PRD §3.6: "The tank then cascades from `IN_USE` back to
        `AVAILABLE`: `occupied_by_batch_id` clears to null,
        `last_product_ghs` takes the batch's
        `highest_component_ghs_snapshot`, and `cleaning_state` returns to
        `DIRTY`".

        Design: Difficulty/compensating_invariant/tank_occupancy_invariant_via_complete_reverses_reservation
        """
        ctx = setup_completed_batch(actual_output_kg=95, charge_qty_kg=100,
                                    heel_returned_kg=5)
        tank = ctx["tank"]
        assert tank["operational_state"] == "AVAILABLE"
        assert tank["occupied_by_batch_id"] is None
        assert tank["cleaning_state"] == "DIRTY"
        assert tank["last_product_ghs"] == "NON_HAZ", (
            "The batch's NON_HAZ snapshot becomes the tank's last product")


class TestCompletionGateOrdering:
    def _setup_flammable_hold_qa(self, api, issue_the_sds):
        ctx = setup_batch_in_hold_qa(
            ghs_class="FLAMMABLE", density=0.785, yield_pct=99,
            batch_size_l=1000, lot_quantity_kg=5000, charge_qty_kg=800,
            tank_overrides={"capacity_l": 1500, "working_capacity_l": 1500})
        customer_id, batch_id = ctx["customer"]["id"], ctx["batch"]["id"]
        if issue_the_sds:
            ctx["sds"] = author_and_issue_sds(customer_id, batch_id,
                                              "FLAMMABLE")
        else:
            # Author the SDS but leave it in DRAFT (never issued).
            ctx["sds"] = author_sds(customer_id, batch_id, "FLAMMABLE")
        # 1 x IBC_1000L = 1000 L >= 454: placarding becomes required, but no
        # shipment exists to mount the placard on.
        ctx["package_config"] = create_package_config(
            customer_id, batch_id, package_type="IBC_1000L", un_rated=True,
            package_count=1)
        assert ctx["package_config"]["placard_required"] is True
        lot = next(iter(ctx["lots"].values()))
        create_and_post_heel_disposal(customer_id, batch_id, lot["id"],
                                      heel_returned_kg=5)
        return ctx

    def test_complete_reports_sds_not_issued_before_placard(self, api):
        """PRD §2.9: "When several rules could reject the same request, the
        system evaluates them in a fixed order and reports the first failure"
        — "SDS issuance (`ERR_SDS_NOT_ISSUED`) ahead of UN-rated packaging
        (`ERR_UN_RATED_PACKAGE_REQUIRED`) ahead of package volume
        (`ERR_PACKAGE_VOLUME_INSUFFICIENT`) ahead of placarding
        (`ERR_PLACARD_MISSING`)". PRD §3.6: "An SDS for the batch must exist
        in `ISSUED` status (else `ERR_SDS_NOT_ISSUED`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/complete_blocked_sds_vs_placard_priority
        """
        ctx = self._setup_flammable_hold_qa(api, issue_the_sds=False)
        resp = api.complete_batch_job(ctx["customer"]["id"],
                                      ctx["batch"]["id"], 780, QA)
        validate_error(resp, ApiErrorId.ERR_SDS_NOT_ISSUED)
        after = validate_success(api.get_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], QM))
        assert after["status"] == "HOLD_QA", "Rejected completion leaves HOLD_QA"

    def test_complete_placard_missing_when_no_shipment(self, api):
        """PRD §3.6: "When `placard_required` is true, the configuration's
        `placard_class` must be set and the shipment's `vehicle_placards`
        must contain it (else `ERR_PLACARD_MISSING`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/complete_blocked_sds_vs_placard_priority
        """
        ctx = self._setup_flammable_hold_qa(api, issue_the_sds=True)
        resp = api.complete_batch_job(ctx["customer"]["id"],
                                      ctx["batch"]["id"], 780, QA)
        validate_error(resp, ApiErrorId.ERR_PLACARD_MISSING)


class TestRejectQaRevertPath:
    def test_reject_qa_releases_tank_and_marks_dirty(self, api):
        """PRD §3.6: "Rejection by a `QAValidator` moves the batch from
        `HOLD_QA` to `REJECTED_QA`: the tank cascades back to `AVAILABLE`
        with `last_product_ghs` set and `cleaning_state` returned to
        `DIRTY`, and every charge still `COMMITTED` flips to `RELEASED`,
        returning its promised mass to the lot's available balance with a lot
        `version` increment; charges already `CONSUMED` are not
        auto-released, because that material is physically in the tank."

        Design: Difficulty/non_linear_state_machine/batch_job_reject_qa_and_cancel_revert_paths
        """
        ctx = setup_batch_in_hold_qa(ghs_class="NON_HAZ", charge_qty_kg=100)
        rejected = validate_success(api.reject_qa_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], QA))
        assert rejected["status"] == "REJECTED_QA"

        tank = get_tank(ctx["tank"]["id"])
        assert tank["operational_state"] == "AVAILABLE"
        assert tank["occupied_by_batch_id"] is None
        assert tank["last_product_ghs"] == "NON_HAZ"
        assert tank["cleaning_state"] == "DIRTY"

        # The charge was CONSUMED (material in the tank), not auto-released.
        charges, _meta = validate_paginated(
            api.list_batch_charges(ctx["customer"]["id"], ctx["batch"]["id"],
                                   QM))
        assert charges[0]["status"] == "CONSUMED"


class TestPackageVolumeGate:
    def test_complete_with_insufficient_package_volume_rejected(self, api):
        """PRD §3.6: "The package configuration must exist and its
        `total_volume_l` must reach at least the batch's drained volume — the
        `density_corrected_output_l` computed below — rounded up to the next
        whole litre (else `ERR_PACKAGE_VOLUME_INSUFFICIENT`, HTTP 422)."

        Design: Corner/errors/complete_without_package_config_returns_err
        """
        ctx = setup_batch_ready_for_completion(
            density=1.0, yield_pct=100, batch_size_l=100, charge_qty_kg=100,
            heel_returned_kg=5,
            package_overrides={"package_type": "PAIL_20L", "package_count": 1,
                               "un_rated": False})
        assert ctx["package_config"]["total_volume_l"] == 20
        # Drained volume: 95 kg / 1.0 kg/L = 95 L > 20 L configured.
        resp = api.complete_batch_job(ctx["customer"]["id"],
                                      ctx["batch"]["id"], 95, QA)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_VOLUME_INSUFFICIENT)
