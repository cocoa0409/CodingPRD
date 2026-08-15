"""Two-phase scrap accounting (provisional vs final credit), return-lot
consumption, contaminated assay downgrade, and the alloy-mass invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_charges,
    assert_alloy_mass_invariant,
    assert_scrap_record,
    create_assayed_lot,
    create_foundry,
    create_furnace,
    create_heat,
    create_return_lot,
    disposition,
    get_foundry,
    get_return_lot,
    get_scrap_records_for_casting,
    record_inspection,
    return_lot_addition,
    set_clock,
    setup_casting_at_final_inspection,
    validate_success,
)

MELT = TEST_USERS["melt_supervisor_headers"]
QI = TEST_USERS["qi_1_headers"]


def _scrapped_casting(ctx, lot, porosity_grade=6, defect_type="POROSITY",
                      scrap_code="POROSITY"):
    """SCRAP-disposition the context casting, crediting the given lot."""
    casting_id = ctx["castings"][0][0]["id"]
    insp = record_inspection(casting_id, porosity_grade=porosity_grade,
                             defect_type=defect_type, zone="A")
    disposition(insp["id"], "SCRAP", scrap_code=scrap_code,
                return_lot_id=lot["id"])
    records = get_scrap_records_for_casting(casting_id)
    assert len(records) == 1
    return records[0]


class TestScrapCreditVariants:
    def test_provisional_credit_at_disposition(self, api):
        """PRD §3.7: "the server creates a scrap record in `PROVISIONAL` status,
        keyed to the `casting_id` and the credited `return_lot_id`, coded with
        the disposition's `scrap_code`, and carrying a `provisional_weight_kg`
        equal to the casting's `casting_weight_kg` multiplied by the provisional
        yield factor 0.85, rounded half-up to two decimal places. That
        provisional weight is credited immediately: the lot's
        `scrap_credited_kg` grows by it, its `remaining_weight_kg` grows by it"

        Design: Difficulty/dual_variant_calc/scrap_credit_provisional_vs_final_reconciles_lot
        """
        ctx = setup_casting_at_final_inspection()
        lot = create_assayed_lot(ctx["foundry"]["id"], collected_weight_kg=500.0)
        record = _scrapped_casting(ctx, lot)
        assert_scrap_record(record)
        # casting_weight 200.0 * 0.85 = 170.0 provisional
        assert record["provisional_weight_kg"] == pytest.approx(170.0, abs=1e-9)
        assert record["actual_weight_kg"] is None
        assert record["status"] == "PROVISIONAL"
        assert get_return_lot(lot["id"])["remaining_weight_kg"] == pytest.approx(
            670.0, abs=1e-9)

    def test_final_credit_reconciles_delta_at_weigh(self, api):
        """PRD §3.7: "The credit delta — actual minus provisional — is then
        applied to the same lot: `scrap_credited_kg` and `remaining_weight_kg`
        each move by that delta, and `alloy_available_kg` is recomputed." and
        "A successful weigh moves the record `PROVISIONAL → WEIGHED`, which is
        terminal."

        Design: Difficulty/dual_variant_calc/scrap_credit_provisional_vs_final_reconciles_lot
        """
        ctx = setup_casting_at_final_inspection()
        lot = create_assayed_lot(ctx["foundry"]["id"], collected_weight_kg=500.0)
        record = _scrapped_casting(ctx, lot)

        weighed = validate_success(api.weigh_scrap_record(
            record["id"], {"actual_weight_kg": 190.0}, QI))
        assert weighed["actual_weight_kg"] == pytest.approx(190.0, abs=1e-9)
        assert weighed["status"] == "WEIGHED"

        lot_after = get_return_lot(lot["id"])
        # Delta +20.0 reconciled: 170.0 -> 190.0, 670.0 -> 690.0.
        assert lot_after["scrap_credited_kg"] == pytest.approx(190.0, abs=1e-9)
        assert lot_after["remaining_weight_kg"] == pytest.approx(690.0, abs=1e-9)
        # Identical scrap, different credit: provisional 170.0 != final 190.0.
        assert record["provisional_weight_kg"] != weighed["actual_weight_kg"]


class TestAlloyMassInvariant:
    def _setup_consume_and_weigh(self, api):
        """ASSAYED lot (500.0) credited 170.0 provisional, then drained 100.0 by
        a second heat, then reconciled by a 190.0 scale weigh."""
        ctx = setup_casting_at_final_inspection()
        lot = create_assayed_lot(ctx["foundry"]["id"], collected_weight_kg=500.0)
        record = _scrapped_casting(ctx, lot, porosity_grade=6,
                                   defect_type="INCLUSION", scrap_code="INCLUSION")
        heat2 = create_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        heat2 = add_charges(heat2, [return_lot_addition(lot["id"], 100.0)])
        return ctx, lot, record, heat2

    def test_consumption_moves_remaining_to_consumed(self, api):
        """PRD §3.4: "Return-lot additions also debit the lot at once: the
        weight moves from the lot's `remaining_weight_kg` into its
        `consumed_weight_kg`" and PRD §2.8: "`collected_weight_kg` plus
        `scrap_credited_kg` always equals the sum of `consumed_weight_kg`,
        `remaining_weight_kg`, and `downgraded_weight_kg`."

        Design: Difficulty/compensating_invariant/alloy_mass_conserved_across_credit_and_consume
        """
        ctx, lot, record, heat2 = self._setup_consume_and_weigh(api)
        mid = get_return_lot(lot["id"])
        # 500.0 collected + 170.0 credited - 100.0 consumed = 570.0 remaining.
        assert mid["remaining_weight_kg"] == pytest.approx(570.0, abs=1e-9)
        assert mid["consumed_weight_kg"] == pytest.approx(100.0, abs=1e-9)
        assert mid["scrap_credited_kg"] == pytest.approx(170.0, abs=1e-9)
        assert_alloy_mass_invariant(mid)

    def test_invariant_holds_across_credit_consume_and_weigh(self, api):
        """PRD §2.8: "`collected_weight_kg` plus `scrap_credited_kg` always
        equals the sum of `consumed_weight_kg`, `remaining_weight_kg`, and
        `downgraded_weight_kg`." and "These forward and compensating movements
        must always net out."

        Design: Difficulty/compensating_invariant/alloy_mass_conserved_across_credit_and_consume
        """
        ctx, lot, record, heat2 = self._setup_consume_and_weigh(api)
        validate_success(api.weigh_scrap_record(
            record["id"], {"actual_weight_kg": 190.0}, QI))
        final = get_return_lot(lot["id"])
        assert final["scrap_credited_kg"] == pytest.approx(190.0, abs=1e-9)
        assert final["remaining_weight_kg"] == pytest.approx(590.0, abs=1e-9)
        # 500.0 + 190.0 == 100.0 + 590.0 + 0.0
        assert (final["collected_weight_kg"] + final["scrap_credited_kg"]) == pytest.approx(
            final["consumed_weight_kg"] + final["remaining_weight_kg"]
            + final["downgraded_weight_kg"], abs=1e-9)
        assert_alloy_mass_invariant(final)


class TestReturnLotLifecycle:
    def test_return_lot_consumed_at_exact_zero(self, api):
        """PRD §3.4: "a lot whose remainder reaches exactly zero transitions
        `ASSAYED → CONSUMED` automatically."

        Design: Corner/state_machines/return_lot_consumed_at_exact_zero
        """
        set_clock("2026-08-10T08:00:00Z")
        foundry = create_foundry()
        furnace = create_furnace(foundry["id"])
        lot = create_assayed_lot(foundry["id"], collected_weight_kg=300.0)
        heat = create_heat(foundry["id"], furnace["id"])
        add_charges(heat, [return_lot_addition(lot["id"], 300.0)])
        after = get_return_lot(lot["id"])
        assert after["remaining_weight_kg"] == pytest.approx(0.0, abs=1e-9)
        assert after["consumed_weight_kg"] == pytest.approx(300.0, abs=1e-9)
        assert after["status"] == "CONSUMED"
        assert_alloy_mass_invariant(after)

    def test_assay_contaminated_lot_downgraded(self, api):
        """PRD §3.7: "If any element falls outside its range the lot is
        contaminated: it transitions `COLLECTED → DOWNGRADED`, its entire
        `remaining_weight_kg` is moved into `downgraded_weight_kg` (leaving
        zero), and `alloy_available_kg` is recomputed."

        Design: Corner/state_machines/assay_contaminated_lot_downgraded
        """
        foundry = create_foundry()
        lot = create_return_lot(foundry["id"], collected_weight_kg=400.0)
        # C 4.10 lies outside the spec's [3.2, 3.6] band.
        after = validate_success(api.assay_return_lot(
            lot["id"],
            {"assay_composition": {"C": 4.10},
             "chemistry_spec": {"elements": {"C": {"min": 3.2, "max": 3.6}}}},
            TEST_USERS["spectro_1_headers"]))
        assert after["status"] == "DOWNGRADED"
        assert after["remaining_weight_kg"] == pytest.approx(0.0, abs=1e-9)
        assert after["downgraded_weight_kg"] == pytest.approx(400.0, abs=1e-9)
        assert get_foundry(foundry["id"])["alloy_available_kg"] == pytest.approx(
            0.0, abs=1e-9)
        assert_alloy_mass_invariant(after)
