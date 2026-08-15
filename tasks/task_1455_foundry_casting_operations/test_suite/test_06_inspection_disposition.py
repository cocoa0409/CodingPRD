"""Casting finishing routing, X-ray inspection gating, MRB disposition
branches, and the order fulfillment boundary."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_casting,
    advance_casting,
    cool_and_shakeout,
    create_assayed_lot,
    disposition,
    get_casting,
    get_inspection,
    get_order,
    get_return_lot,
    get_foundry,
    get_scrap_records_for_casting,
    pour_molds,
    record_inspection,
    setup_casting_at_final_inspection,
    setup_shop,
    validate_error,
)

QI = TEST_USERS["qi_1_headers"]
LINE = TEST_USERS["line_operator_headers"]


class TestFulfillmentBoundary:
    def _two_castings_at_inspection(self, api):
        """Order qty 2; two single-impression molds poured on one slot; both
        castings advanced to FINAL_INSPECTION."""
        ctx = setup_shop(order_quantity=2)
        pour_molds(ctx,
                   [{"sand_weight_kg": 50, "metal_weight_kg": 200,
                     "cooling_hours": 2},
                    {"sand_weight_kg": 50, "metal_weight_kg": 200,
                     "cooling_hours": 2}],
                   tap_weight_kg=1000)
        cool_and_shakeout(ctx)
        for casting_list in ctx["castings"]:
            for casting in casting_list:
                advance_casting(casting["id"], steps=3)
        return ctx

    def test_first_accept_leaves_order_in_production(self, api):
        """PRD §3.3: "The moment `accepted_count` reaches `quantity` — equality
        alone triggers, nothing beyond is required — an order in `IN_PRODUCTION`
        transitions to `FULFILLED`, and `fulfilled_at` is stamped with the
        logical now."

        Design: Difficulty/boundary_precision_check/order_fulfills_at_exact_quantity
        """
        ctx = self._two_castings_at_inspection(api)
        c1 = ctx["castings"][0][0]
        accept_casting(c1["id"])
        order = get_order(ctx["order"]["id"])
        assert order["accepted_count"] == 1
        assert order["status"] == "IN_PRODUCTION"

    def test_second_accept_fulfills_at_exact_quantity(self, api):
        """PRD §3.3: "The moment `accepted_count` reaches `quantity` — equality
        alone triggers, nothing beyond is required — an order in `IN_PRODUCTION`
        transitions to `FULFILLED`, and `fulfilled_at` is stamped with the
        logical now."

        Design: Difficulty/boundary_precision_check/order_fulfills_at_exact_quantity
        """
        ctx = self._two_castings_at_inspection(api)
        accept_casting(ctx["castings"][0][0]["id"])
        accept_casting(ctx["castings"][1][0]["id"])
        order = get_order(ctx["order"]["id"])
        assert order["accepted_count"] == 2
        assert order["status"] == "FULFILLED"
        # fulfilled_at is the logical now at the fulfilling disposition (13:00).
        assert order["fulfilled_at"] is not None
        assert order["fulfilled_at"].startswith("2026-08-10T13:00:00")


class TestCastingRoutingGuards:
    def test_casting_advance_requires_mold_shaken_out(self, api):
        """PRD §3.6: "Leaving `SHAKEOUT` additionally requires the mold to be
        `SHAKEOUT` or `CLOSED` and the casting's `quality_status` not `SCRAPPED`
        (`ERR_INVALID_STATE` otherwise)"

        Design: Corner/state_machines/casting_advance_requires_mold_shaken_out
        """
        ctx = setup_shop()
        pour_molds(ctx, [{"sand_weight_kg": 50, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=500)
        casting_id = ctx["castings"][0][0]["id"]
        # Mold is POURED, not SHAKEOUT.
        res = api.advance_casting(casting_id, LINE)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        assert get_casting(casting_id)["routing_status"] == "SHAKEOUT"

    def test_casting_complete_requires_accepted_quality(self, api):
        """PRD §3.6: "and the final step into `COMPLETE` requires quality to be
        `ACCEPTED` or `USE_AS_IS` — a casting whose quality is still open cannot
        leave inspection."

        Design: Corner/state_machines/casting_complete_requires_accepted_quality
        """
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        assert get_casting(casting_id)["quality_status"] == "PENDING"
        res = api.advance_casting(casting_id, LINE)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        assert get_casting(casting_id)["routing_status"] == "FINAL_INSPECTION"


class TestReworkLoop:
    def test_casting_rework_loop_and_reinspection_reset(self, api):
        """PRD §3.6: "`REWORK` requires a `defect_type` of `POROSITY`,
        `SHRINKAGE`, or `INCLUSION` (otherwise `ERR_DISPOSITION_RULE_VIOLATED`);
        the casting's quality becomes `REWORK` and its routing returns from
        `FINAL_INSPECTION` to `GRINDING` for another pass." and "If the
        casting's quality was `REWORK` when the report is recorded — a
        re-inspection after a rework loop — recording the report resets its
        quality to `PENDING`."

        Design: Corner/state_machines/casting_rework_loop_and_reinspection_reset
        """
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        insp = record_inspection(casting_id, porosity_grade=3,
                                 defect_type="POROSITY", zone="B")
        disposition(insp["id"], "REWORK")
        mid = get_casting(casting_id)
        assert mid["quality_status"] == "REWORK"
        assert mid["routing_status"] == "GRINDING"

        # Advance GRINDING -> FINAL_INSPECTION; quality stays REWORK.
        re_advanced = advance_casting(casting_id, steps=1)
        assert re_advanced["routing_status"] == "FINAL_INSPECTION"
        assert re_advanced["quality_status"] == "REWORK"

        # Re-inspection resets quality REWORK -> PENDING.
        record_inspection(casting_id, porosity_grade=1, defect_type="NONE", zone="B")
        assert get_casting(casting_id)["quality_status"] == "PENDING"


class TestDispositionOneShot:
    def test_second_disposition_rejected(self, api):
        """PRD §3.6: "A report already `DISPOSITIONED` rejects a second
        disposition with `ERR_DISPOSITION_EXISTS` rather than the generic
        terminal error."

        Design: Corner/state_machines/second_disposition_rejected
        """
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        insp = record_inspection(casting_id)
        disposition(insp["id"], "ACCEPT")

        res = api.disposition_inspection(
            insp["id"], {"disposition": "SCRAP", "scrap_code": "MISRUN"}, QI)
        validate_error(res, "ERR_DISPOSITION_EXISTS", expected_status=409)
        assert get_inspection(insp["id"])["disposition"] == "ACCEPT"
        assert get_order(ctx["order"]["id"])["accepted_count"] == 1
        assert get_scrap_records_for_casting(casting_id) == []


class TestUseAsIs:
    def test_use_as_is_disposition_counts_as_accepted(self, api):
        """PRD §3.6: "`USE_AS_IS` requires a `porosity_grade` of at most 4
        (otherwise `ERR_DISPOSITION_RULE_VIOLATED`, HTTP 422) and otherwise
        behaves exactly like `ACCEPT`: quality `USE_AS_IS`, `accepted_count`
        incremented, fulfillment checked."

        Design: Corner/state_machines/use_as_is_disposition_counts_as_accepted
        """
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        insp = record_inspection(casting_id, porosity_grade=4,
                                 defect_type="POROSITY", zone="A")
        disposition(insp["id"], "USE_AS_IS", mrb_reference="MRB-77")
        assert get_casting(casting_id)["quality_status"] == "USE_AS_IS"
        order = get_order(ctx["order"]["id"])
        assert order["accepted_count"] == 1
        assert order["status"] == "FULFILLED"

    def test_use_as_is_requires_grade_at_most_four(self, api):
        """PRD §3.6: "`USE_AS_IS` requires a `porosity_grade` of at most 4
        (otherwise `ERR_DISPOSITION_RULE_VIOLATED`, HTTP 422)"

        Design: Corner/errors/use_as_is_requires_grade_at_most_four
        """
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        insp = record_inspection(casting_id, porosity_grade=7,
                                 defect_type="POROSITY", zone="A")
        res = api.disposition_inspection(
            insp["id"], {"disposition": "USE_AS_IS", "mrb_reference": "MRB-1"}, QI)
        validate_error(res, "ERR_DISPOSITION_RULE_VIOLATED", expected_status=422)
        # The rejection leaves the report open for a valid disposition.
        assert get_inspection(insp["id"])["status"] == "RECORDED"

    def test_rework_with_non_reworkable_defect_violated(self, api):
        """PRD §3.6: "`REWORK` requires a `defect_type` of `POROSITY`,
        `SHRINKAGE`, or `INCLUSION` (otherwise `ERR_DISPOSITION_RULE_VIOLATED`)"

        Design: Corner/errors/rework_with_non_reworkable_defect_violated
        """
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        insp = record_inspection(casting_id, porosity_grade=2,
                                 defect_type="MISRUN", zone="B")
        res = api.disposition_inspection(insp["id"], {"disposition": "REWORK"}, QI)
        validate_error(res, "ERR_DISPOSITION_RULE_VIOLATED", expected_status=422)


class TestInspectionGating:
    def test_inspection_before_final_inspection_rejected(self, api):
        """PRD §3.6: "A `QualityInspector` records an inspection on a casting
        that has reached routing `FINAL_INSPECTION`; attempting it at any
        earlier routing step, or on a casting whose quality is `SCRAPPED`, is
        rejected with `ERR_CASTING_NOT_INSPECTABLE`."

        Design: Corner/errors/inspection_before_final_inspection_rejected
        """
        ctx = setup_shop()
        pour_molds(ctx, [{"sand_weight_kg": 50, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=500)
        cool_and_shakeout(ctx)
        casting_id = ctx["castings"][0][0]["id"]
        advance_casting(casting_id, steps=2)  # SHAKEOUT -> CLEANING -> GRINDING
        res = api.create_inspection(
            {"casting_id": casting_id, "porosity_grade": 2,
             "defect_type": "POROSITY", "zone": "B"}, QI)
        validate_error(res, "ERR_CASTING_NOT_INSPECTABLE", expected_status=409)


class TestScrapCascade:
    def _setup_scrap_scenario(self, api):
        """Casting at FINAL_INSPECTION; ASSAYED return lot (500.0 kg)."""
        ctx = setup_casting_at_final_inspection()
        lot = create_assayed_lot(ctx["foundry"]["id"], collected_weight_kg=500.0)
        ctx["lot"] = lot
        return ctx

    def test_scrap_disposition_cascade_casting_and_scrap_record(self, api):
        """PRD §3.6: "The casting's quality becomes `SCRAPPED`, the order's
        `scrapped_count` is incremented, and the remelt accounting cascade of
        §3.7 fires: a scrap record is created and a return lot, named by the
        payload's `return_lot_id`, is credited with the provisional recovery."
        PRD §3.7: "the server creates a scrap record in `PROVISIONAL` status,
        keyed to the `casting_id` and the credited `return_lot_id`, coded with
        the disposition's `scrap_code`, and carrying a `provisional_weight_kg`
        equal to the casting's `casting_weight_kg` multiplied by the provisional
        yield factor 0.85, rounded half-up to two decimal places."

        Design: Difficulty/transitive_cascade/scrap_disposition_cascade_depth4
        """
        ctx = self._setup_scrap_scenario(api)
        casting_id = ctx["castings"][0][0]["id"]
        insp = record_inspection(casting_id, porosity_grade=7,
                                 defect_type="SHRINKAGE", zone="A")
        disposition(insp["id"], "SCRAP", scrap_code="SHRINKAGE",
                    return_lot_id=ctx["lot"]["id"])

        casting = get_casting(casting_id)
        assert casting["quality_status"] == "SCRAPPED"
        assert casting["routing_status"] == "FINAL_INSPECTION"
        assert get_order(ctx["order"]["id"])["scrapped_count"] == 1

        records = get_scrap_records_for_casting(casting_id)
        assert len(records) == 1
        record = records[0]
        # casting_weight 200.0 * 0.85 = 170.0
        assert record["provisional_weight_kg"] == pytest.approx(170.0, abs=1e-9)
        assert record["scrap_code"] == "SHRINKAGE"
        assert record["status"] == "PROVISIONAL"

    def test_scrap_disposition_cascade_lot_and_foundry_credit(self, api):
        """PRD §3.7: "That provisional weight is credited immediately: the lot's
        `scrap_credited_kg` grows by it, its `remaining_weight_kg` grows by it,
        and the foundry's `alloy_available_kg` — the sum of `remaining_weight_kg`
        over the foundry's `ASSAYED` lots — is recomputed."

        Design: Difficulty/transitive_cascade/scrap_disposition_cascade_depth4
        """
        ctx = self._setup_scrap_scenario(api)
        casting_id = ctx["castings"][0][0]["id"]
        alloy_before = get_foundry(ctx["foundry"]["id"])["alloy_available_kg"]
        assert alloy_before == pytest.approx(500.0, abs=1e-9)

        insp = record_inspection(casting_id, porosity_grade=7,
                                 defect_type="SHRINKAGE", zone="A")
        disposition(insp["id"], "SCRAP", scrap_code="SHRINKAGE",
                    return_lot_id=ctx["lot"]["id"])

        lot = get_return_lot(ctx["lot"]["id"])
        assert lot["scrap_credited_kg"] == pytest.approx(170.0, abs=1e-9)
        assert lot["remaining_weight_kg"] == pytest.approx(670.0, abs=1e-9)
        assert get_foundry(ctx["foundry"]["id"])["alloy_available_kg"] == pytest.approx(
            670.0, abs=1e-9)
