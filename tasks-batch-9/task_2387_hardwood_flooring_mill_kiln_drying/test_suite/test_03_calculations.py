"""The mill's derived arithmetic: the shrink constant a density class implies, the
schedule duration tiers and their clamp, the volume-weighted moisture of a load,
the kiln-dry conversion and the remaining ledger, byproduct settlement, core
reservation, tally valuation, and the warranty money at its tier boundaries."""

import pytest

from test_helpers import (
    adjudicate_claim_payload,
    allocate_receipt_payload,
    create_byproduct_sale_payload,
    create_drying_schedule_payload,
    create_flooring_lot_payload,
    create_grade_bundle_payload,
    create_species_profile_payload,
    create_warranty_claim_payload,
    deallocate_receipt_payload,
    record_stress_test_payload,
    reject_receipt_payload,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    BROKER,
    CLERK,
    INSPECTOR,
    OPERATOR,
    SUPERVISOR,
    create_accepted_receipt,
    create_core_stock,
    create_product_line,
    create_receipt,
    create_species,
    refetch_batch,
    refetch_charge,
    refetch_core_stock,
    refetch_product_line,
    set_logical_clock,
    setup_conditioning_charge,
    setup_draft_grade_run,
    setup_milled_lot,
    setup_released_charge,
    setup_scheduled_charge,
    setup_warranty_line,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    CLAIM_SUBMITTER_USER_ID,
    make_warranty_adjudicator_headers,
)

WHITE_ASH = {
    "species_code": "WHITE_ASH",
    "common_name": "White Ash",
    "density_class": "MEDIUM",
    "tangential_shrinkage_coefficient": 0.150,
    "target_moisture_pct": 7.0,
    "max_moisture_gradient_pp": 2.0,
}

POPLAR = {
    "species_code": "POPLAR",
    "common_name": "Yellow Poplar",
    "density_class": "SOFT",
    "tangential_shrinkage_coefficient": 0.122,
    "target_moisture_pct": 7.0,
    "max_moisture_gradient_pp": 2.5,
}

HICKORY = {
    "species_code": "HICKORY",
    "common_name": "Hickory",
    "density_class": "DENSE",
    "tangential_shrinkage_coefficient": 0.181,
    "target_moisture_pct": 6.0,
    "max_moisture_gradient_pp": 1.5,
}

ASH_RECEIPT = [
    {
        "received_board_feet": 5200,
        "accepted_board_feet": 5000,
        "moisture_pct_at_receipt": 45.0,
        "receipt_grade": "FAS",
    }
]

HEAVY_SAWDUST_MILLING = {
    "actual_milled_width_in": 3.190,
    "net_flooring_bf": 4500,
    "shorts_bf": 200,
    "sawdust_tons": 10.00,
    "shavings_tons": 0.00,
}


class TestGreenToDryShrinkConstant:
    """The shrink percentage is a lookup on the density class and on nothing
    else."""

    def test_the_three_density_classes_pick_their_own_shrink_percentage(self, api):
        """PRD 3.1: "From the density class the server derives
        `green_to_dry_shrink_pct`, the board-foot shrink from green to kiln-dry: 7.5
        percent for `DENSE`, 6.0 percent for `MEDIUM` and 5.0 percent for `SOFT`."

        Design: Corner/calculations/green_to_dry_shrink_constant_per_density_class
        """
        set_logical_clock(api)

        dense = validate_success(
            api.create_species_profile(create_species_profile_payload(), ADMIN),
            expected_status=201,
        )
        medium = validate_success(
            api.create_species_profile(create_species_profile_payload(**WHITE_ASH), ADMIN),
            expected_status=201,
        )
        soft = validate_success(
            api.create_species_profile(create_species_profile_payload(**POPLAR), ADMIN),
            expected_status=201,
        )

        assert dense["density_class"] == "DENSE"
        assert dense["green_to_dry_shrink_pct"] == pytest.approx(7.5, abs=0.01)
        assert medium["density_class"] == "MEDIUM"
        assert medium["green_to_dry_shrink_pct"] == pytest.approx(6.0, abs=0.01)
        assert soft["density_class"] == "SOFT"
        assert soft["green_to_dry_shrink_pct"] == pytest.approx(5.0, abs=0.01)

        # The dense row shrinks more while carrying the smaller shrinkage
        # coefficient, so the coefficient plainly does not drive the lookup.
        assert dense["tangential_shrinkage_coefficient"] == pytest.approx(0.145, abs=0.0001)
        assert medium["tangential_shrinkage_coefficient"] == pytest.approx(0.150, abs=0.0001)
        assert dense["green_to_dry_shrink_pct"] > medium["green_to_dry_shrink_pct"]


class TestScheduleDurationTiersAndClamp:
    """Thick stock scales the drying leg, and the ceiling is applied last."""

    def test_the_thickness_tiers_scale_the_leg_and_the_ceiling_caps_the_result(self, api):
        """PRD 3.1: "It begins from a base drying time set by the species density
        class — 96 hours for `DENSE`, 72 hours for `MEDIUM`, 54 hours for `SOFT` — to
        which is added a per-point allowance for every percentage point of moisture the
        schedule must remove, that being the design green moisture less the design
        kiln-dry moisture, charged at 3.5 hours per point for `DENSE`, 2.5 hours per
        point for `MEDIUM` and 1.8 hours per point for `SOFT`."

        PRD 3.1: "That sum is the unscaled drying leg, and it is multiplied by a
        thickness tier factor: 1.00 for stock at most 1.00 inch thick, 1.45 for stock
        thicker than that but at most 1.25 inches, 1.95 for stock thicker than that but
        at most 1.50 inches, and 2.60 for anything thicker."

        PRD 3.1: "The result is rounded half up to one decimal place, and only then
        clamped into the range 48 to 360 hours: a computed 41.3 becomes 48.0 and a
        computed 402.7 becomes 360.0."

        Design: Corner/calculations/kiln_schedule_duration_upper_tiers_and_max_clamp
        """
        set_logical_clock(api)
        oak = create_species(api)
        ash = create_species(api, **WHITE_ASH)
        poplar = create_species(api, **POPLAR)
        hickory = create_species(api, **HICKORY)

        one_inch_dense = validate_success(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    oak["id"], oak["version"], schedule_code="RO-100", thickness_in=1.00
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert one_inch_dense["planned_dry_hours"] == pytest.approx(265.0, abs=0.01)

        inch_and_a_half_medium = validate_success(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    ash["id"],
                    ash["version"],
                    schedule_code="WA-150",
                    thickness_in=1.50,
                    conditioning_hours=12,
                    stress_relief_hours=6,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert inch_and_a_half_medium["planned_dry_hours"] == pytest.approx(343.7, abs=0.01)

        two_inch_soft = validate_success(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    poplar["id"],
                    poplar["version"],
                    schedule_code="PO-200",
                    thickness_in=2.00,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert two_inch_soft["planned_dry_hours"] == pytest.approx(354.2, abs=0.01)

        two_inch_dense = validate_success(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    hickory["id"],
                    hickory["version"],
                    schedule_code="HI-200",
                    thickness_in=2.00,
                    initial_moisture_pct=60.0,
                    final_moisture_pct=6.0,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        # A raw 777.0 hours, brought down to the ceiling rather than stored.
        assert two_inch_dense["planned_dry_hours"] == pytest.approx(360.0, abs=0.01)


class TestWeightedInitialMoisture:
    """The aggregate is drawn from the allocated set alone, and vanishes with
    it."""

    def test_only_the_allocated_receipts_feed_the_charge_aggregates(self, api):
        """PRD 3.4: "Every allocation and deallocation recomputes two derived
        quantities on the charge from the set of receipts currently pointing at it in
        `ALLOCATED` status."

        PRD 3.4: "The second, `weighted_initial_moisture_pct`, is the volume-weighted
        green moisture of the load: each receipt's `accepted_board_feet` is multiplied
        by its `moisture_pct_at_receipt`, those products are totalled, the total is
        divided by `charged_green_bf`, and the resulting ratio is rounded half up to one
        decimal place — once, on the aggregate, never per receipt."

        PRD 3.4: "When the allocated set is empty, `charged_green_bf` is 0 and
        `weighted_initial_moisture_pct` is null."

        Design: Corner/calculations/weighted_initial_moisture_excludes_unallocated_receipts
        """
        ctx = setup_scheduled_charge(api)
        charge_id = ctx["charge"]["id"]

        wet_bulk = create_accepted_receipt(
            api,
            ctx["species"],
            received_board_feet=6000,
            accepted_board_feet=5800,
            moisture_pct_at_receipt=46.0,
            receipt_grade="FAS",
        )
        second_course = create_accepted_receipt(
            api,
            ctx["species"],
            received_board_feet=4000,
            accepted_board_feet=3900,
            moisture_pct_at_receipt=44.0,
            receipt_grade="SELECT",
        )
        # Accepted but never allocated: air-dried stock at 20.0 percent that would
        # drag the aggregate down to 40.9 if it counted.
        create_accepted_receipt(
            api,
            ctx["species"],
            received_board_feet=2000,
            accepted_board_feet=2000,
            moisture_pct_at_receipt=20.0,
            receipt_grade="NO1_COMMON",
            supplier_name="Valley Sawmill",
        )
        turned_away = create_receipt(
            api,
            ctx["species"],
            received_board_feet=1000,
            moisture_pct_at_receipt=30.0,
            receipt_grade="NO2_COMMON",
            supplier_name="Valley Sawmill",
        )
        validate_success(
            api.reject_green_receipt(
                turned_away["id"],
                reject_receipt_payload(rejection_reason="Wet-stored blue stain"),
                CLERK,
            ),
            expected_status=200,
        )

        first = validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(wet_bulk["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert first["charged_green_bf"] == pytest.approx(5800, abs=0.01)
        assert first["weighted_initial_moisture_pct"] == pytest.approx(46.0, abs=0.01)

        both = validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(second_course["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert both["charged_green_bf"] == pytest.approx(9700, abs=0.01)
        assert both["weighted_initial_moisture_pct"] == pytest.approx(45.2, abs=0.01)

        back_to_one = validate_success(
            api.deallocate_receipt(
                charge_id, deallocate_receipt_payload(second_course["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert back_to_one["charged_green_bf"] == pytest.approx(5800, abs=0.01)
        assert back_to_one["weighted_initial_moisture_pct"] == pytest.approx(46.0, abs=0.01)

        emptied = validate_success(
            api.deallocate_receipt(
                charge_id, allocate_receipt_payload(wet_bulk["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert emptied["charged_green_bf"] == pytest.approx(0, abs=0.01)
        assert emptied["weighted_initial_moisture_pct"] is None

        _rows, meta = validate_paginated(
            api.list_green_receipts(ADMIN, params={"status": "ACCEPTED"})
        )
        assert meta["total_count"] == 3


class TestDryYieldConversionAndRemainingLedger:
    """A medium-class charge converts at its own rate, and the lot draw comes off
    the remaining ledger."""

    def test_a_medium_charge_converts_at_six_percent_and_the_lot_draws_it_down(self, api):
        """PRD 3.3: "From that snapshot the server derives `planned_end_utc`, which is
        `planned_start_utc` advanced by `planned_dry_hours` hours, and
        `blocked_until_utc`, which is `planned_end_utc` advanced by the 6-hour cooldown
        buffer."

        PRD 3.5: "The stored readings and both derived figures are retained, and the
        charge's kiln-dry output is computed: `dry_bf_out` is `charged_green_bf` reduced
        by the species' `green_to_dry_shrink_pct` — that is, multiplied by one minus that
        percentage expressed as a fraction — and rounded half up to two decimal places."

        PRD 3.6: "Planning a lot draws down the charge: the charge's `remaining_dry_bf`
        is reduced by `input_dry_bf`, and it is always `dry_bf_out` less the total
        `input_dry_bf` of the non-voided lots drawn from that charge. When that remainder
        reaches exactly 0 the charge has nothing left to give and auto-advances from
        `RELEASED` to `CLOSED`."

        Design: Corner/calculations/dry_yield_conversion_medium_class_and_remaining_ledger
        """
        ctx = setup_conditioning_charge(
            api,
            receipts=[dict(spec) for spec in ASH_RECEIPT],
            species_overrides=dict(WHITE_ASH),
            schedule_overrides={"schedule_code": "WA-100"},
            chamber_overrides={"chamber_code": "K2", "capacity_board_feet": 8000},
        )
        charge_id = ctx["charge"]["id"]

        scheduled = refetch_charge(api, charge_id)
        assert scheduled["planned_dry_hours"] == pytest.approx(203.0, abs=0.01)
        assert scheduled["planned_end_utc"] == "2026-08-13T11:00:00.000Z"
        assert scheduled["blocked_until_utc"] == "2026-08-13T17:00:00.000Z"

        line = create_product_line(
            api,
            ctx["species"],
            line_code="SOLID-WA-325",
            material_value_cents_per_sf=760,
        )

        released = validate_success(
            api.record_stress_test(
                charge_id, record_stress_test_payload(6.4, 8.2), OPERATOR
            ),
            expected_status=200,
        )
        assert released["status"] == "RELEASED"
        # 5000 green board feet at the medium six percent shrink, not the dense
        # seven and a half that would have given 4625.00.
        assert released["dry_bf_out"] == pytest.approx(4700.00, abs=0.01)
        assert released["remaining_dry_bf"] == pytest.approx(4700.00, abs=0.01)

        validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(line["id"], charge_id, 1700), SUPERVISOR
            ),
            expected_status=201,
        )

        drawn = refetch_charge(api, charge_id)
        assert drawn["remaining_dry_bf"] == pytest.approx(3000.00, abs=0.01)
        assert drawn["status"] == "RELEASED"


class TestByproductSettlementTierBoundary:
    """Milling opens the batches, and the volume discount has a hard edge at five
    tons."""

    def _milled_lot_with_ten_tons_of_sawdust(self, api):
        return setup_milled_lot(
            api, input_dry_bf=8000, milling=dict(HEAVY_SAWDUST_MILLING)
        )

    def test_the_milling_report_fixes_the_mass_balance_and_the_batch_tonnage(self, api):
        """PRD 3.6: "`residue_bf` is the board-foot equivalent of the residue streams:
        the sum of `sawdust_tons` and `shavings_tons` multiplied by 285 board feet per
        ton, rounded half up to two decimal places."

        PRD 3.6: "`waste_bf` is then the unaccounted remainder — `input_dry_bf` less
        `net_flooring_bf`, less `shorts_bf`, less `residue_bf` — likewise rounded half up
        to two decimal places, with residue computed before waste."

        PRD 3.6: "Three batches are created against the lot, one per stream, each with
        its `byproduct_type` set to `SAWDUST`, `SHAVINGS` and `SHORTS` respectively,
        `sold_tons` at 0, and `available_tons` fixed once from the milling report: the
        sawdust batch takes `sawdust_tons`, the shavings batch takes `shavings_tons`, and
        the shorts batch takes `shorts_bf` divided by the same 285 board feet per ton,
        rounded half up to two decimal places."

        Design: Corner/calculations/byproduct_discount_tier_boundary_at_five_tons
        """
        ctx = self._milled_lot_with_ten_tons_of_sawdust(api)

        assert ctx["lot"]["residue_bf"] == pytest.approx(2850.00, abs=0.01)
        assert ctx["lot"]["waste_bf"] == pytest.approx(450.00, abs=0.01)
        assert ctx["lot"]["provisional_yield_pct"] == pytest.approx(56.25, abs=0.01)

        assert ctx["batches"]["SAWDUST"]["available_tons"] == pytest.approx(10.00, abs=0.01)
        assert ctx["batches"]["SHAVINGS"]["available_tons"] == pytest.approx(0.00, abs=0.01)
        assert ctx["batches"]["SHORTS"]["available_tons"] == pytest.approx(0.70, abs=0.01)
        assert ctx["batches"]["SAWDUST"]["sold_tons"] == pytest.approx(0, abs=0.01)

    def test_at_exactly_five_tons_the_discount_bites_and_the_smaller_sale_nets_more(
        self, api
    ):
        """PRD 3.6: "The invoice is built in a fixed order, each amount rounded half up
        to whole cents: `gross_cents` is `quantity_tons` multiplied by
        `unit_price_cents_per_ton`; `discount_cents` applies a volume discount of nothing
        below 5 tons, 3 percent from 5 tons up to but not including 20 tons, and 6
        percent at 20 tons and above, taken against the gross; `haul_cents` is a flat
        2500 cents plus 180 cents per mile of `haul_distance_miles`; and `net_cents` is
        the gross less the discount plus the haulage."

        PRD 3.6: "The batch's `sold_tons` is at all times the total `quantity_tons` of
        the sales recorded against it, and a sale whose quantity would push `sold_tons`
        above the batch's `available_tons` is refused with
        `ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH`."

        Design: Corner/calculations/byproduct_discount_tier_boundary_at_five_tons
        """
        ctx = self._milled_lot_with_ten_tons_of_sawdust(api)
        sawdust_id = ctx["batches"]["SAWDUST"]["id"]

        at_the_tier = validate_success(
            api.create_byproduct_sale(
                create_byproduct_sale_payload(
                    sawdust_id,
                    quantity_tons=5.00,
                    unit_price_cents_per_ton=2200,
                    haul_distance_miles=20,
                    buyer_name="Ridge Pellet Fuels",
                ),
                BROKER,
            ),
            expected_status=201,
        )
        assert at_the_tier["gross_cents"] == 11000
        assert at_the_tier["discount_cents"] == 330
        assert at_the_tier["haul_cents"] == 6100
        assert at_the_tier["net_cents"] == 16770

        just_under = validate_success(
            api.create_byproduct_sale(
                create_byproduct_sale_payload(
                    sawdust_id,
                    quantity_tons=4.99,
                    unit_price_cents_per_ton=2200,
                    haul_distance_miles=20,
                    buyer_name="Ridge Pellet Fuels",
                ),
                BROKER,
            ),
            expected_status=201,
        )
        assert just_under["gross_cents"] == 10978
        assert just_under["discount_cents"] == 0
        assert just_under["haul_cents"] == 6100
        assert just_under["net_cents"] == 17078

        # Less tonnage, more money: the tier is chosen on the quantity with a hard
        # edge at five tons rather than interpolated across it.
        assert just_under["net_cents"] > at_the_tier["net_cents"]

        assert refetch_batch(api, sawdust_id)["sold_tons"] == pytest.approx(9.99, abs=0.01)


class TestCoreReservationAcrossLots:
    """Each lot reserves its own substrate; the stock row carries the running
    sum."""

    def test_two_lots_on_one_core_stock_reserve_separately_and_sum_together(self, api):
        """PRD 3.6: "For an engineered lot the server computes `reserved_core_sf` as
        the drawn `input_dry_bf` multiplied by 1.10 square feet of core per board foot,
        rounded half up to two decimal places — a draw of 2900 board feet reserves
        3190.00 square feet — and adds it to the core stock's `reserved_square_feet`,
        which is at all times the total `reserved_core_sf` of the non-voided lots on that
        stock."

        PRD 3.6: "Planning a lot draws down the charge: the charge's `remaining_dry_bf`
        is reduced by `input_dry_bf`, and it is always `dry_bf_out` less the total
        `input_dry_bf` of the non-voided lots drawn from that charge."

        Design: Corner/calculations/core_reservation_aggregates_across_two_lots
        """
        ctx = setup_released_charge(api)
        charge_id = ctx["charge"]["id"]
        assert ctx["charge"]["dry_bf_out"] == pytest.approx(8972.50, abs=0.01)

        engineered = create_product_line(
            api,
            ctx["species"],
            line_code="ENG-RO-500",
            construction_type="ENGINEERED",
            nominal_width_in=5.000,
            nominal_thickness_in=0.500,
            material_value_cents_per_sf=640,
        )
        core = create_core_stock(
            api,
            engineered,
            core_material="BIRCH_PLY",
            lot_reference="BP-2026-04",
            available_square_feet=4000.00,
        )

        big_lot = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    engineered["id"], charge_id, 2900, core_stock_id=core["id"]
                ),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert big_lot["reserved_core_sf"] == pytest.approx(3190.00, abs=0.01)

        offcut_lot = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    engineered["id"], charge_id, 100, core_stock_id=core["id"]
                ),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert offcut_lot["reserved_core_sf"] == pytest.approx(110.00, abs=0.01)

        stock = refetch_core_stock(api, core["id"])
        assert stock["reserved_square_feet"] == pytest.approx(3300.00, abs=0.01)
        assert stock["available_square_feet"] == pytest.approx(4000.00, abs=0.01)

        assert refetch_charge(api, charge_id)["remaining_dry_bf"] == pytest.approx(
            5972.50, abs=0.01
        )


class TestGradeBundleLengthFactors:
    """Average board length moves the bundle's value; the grade class moves its
    credit."""

    def test_the_length_tiers_reprice_three_otherwise_identical_bundles(self, api):
        """PRD 3.7: "Its `length_factor` is selected by average length: 0.83 for
        bundles averaging under 24 inches, 1.00 for bundles averaging at least 24 but
        under 48 inches, and 1.07 for bundles averaging 48 inches or more."

        PRD 3.7: "Its `credit_factor` is selected by grade class: 1.00 for `CLEAR`,
        0.95 for `SELECT`, 0.85 for `NO1_COMMON`, 0.70 for `NO2_COMMON`, 0.60 for
        `CHARACTER` and 0.40 for `CABIN`."

        PRD 3.7: "Its `tally_value_cents` is the bundle's board feet multiplied by the
        per-board-foot price of its grade class — 640 cents for `CLEAR`, 520 for
        `SELECT`, 395 for `NO1_COMMON`, 280 for `NO2_COMMON`, 240 for `CHARACTER` and 150
        for `CABIN` — multiplied by the length factor, and rounded half up to whole
        cents."

        PRD 3.7: "`tally_board_feet` is the total `bundle_board_feet` of the run's
        bundles, rounded half up to two decimal places. `credited_board_feet` is the
        total of each bundle's board feet multiplied by that bundle's credit factor,
        rounded half up to four decimal places."

        Design: Corner/calculations/grade_bundle_length_factor_tier_boundaries
        """
        ctx = setup_draft_grade_run(api, ruleset="NHLA", bundles=[])
        run_id = ctx["grade_run"]["id"]

        shorts = validate_success(
            api.create_grade_bundle(
                run_id,
                create_grade_bundle_payload("CLEAR", 100.00, 23.5),
                INSPECTOR,
            ),
            expected_status=201,
        )
        assert shorts["length_factor"] == pytest.approx(0.83, abs=0.01)
        assert shorts["tally_value_cents"] == 53120

        at_two_feet = validate_success(
            api.create_grade_bundle(
                run_id, create_grade_bundle_payload("CLEAR", 100.00, 24), INSPECTOR
            ),
            expected_status=201,
        )
        assert at_two_feet["length_factor"] == pytest.approx(1.00, abs=0.01)
        assert at_two_feet["tally_value_cents"] == 64000

        at_four_feet = validate_success(
            api.create_grade_bundle(
                run_id, create_grade_bundle_payload("CLEAR", 100.00, 48), INSPECTOR
            ),
            expected_status=201,
        )
        assert at_four_feet["length_factor"] == pytest.approx(1.07, abs=0.01)
        assert at_four_feet["tally_value_cents"] == 68480

        for bundle in (shorts, at_two_feet, at_four_feet):
            assert bundle["credit_factor"] == pytest.approx(1.00, abs=0.01)

        finalized = validate_success(
            api.finalize_grade_run(run_id, INSPECTOR), expected_status=200
        )
        assert finalized["tally_board_feet"] == pytest.approx(300.00, abs=0.01)
        assert finalized["credited_board_feet"] == pytest.approx(300.0000, abs=0.0001)
        assert finalized["tally_value_cents"] == 185600


class TestResponsibilitySplitBoundaries:
    """Where the moisture delta and the humidity band fall decides how much of the
    failure is the mill's."""

    CLAIM_TEMPLATE = {
        "affected_square_feet": 100,
        "installation_date": "2026-06-01",
    }

    def _three_claims_on_one_line(self, api):
        ctx = setup_warranty_line(api)
        submitter = make_warranty_adjudicator_headers(CLAIM_SUBMITTER_USER_ID)
        readings = ((9.0, 50, "CUPPING"), (9.1, 50, "CUPPING"), (9.1, 51, "GAPPING"))
        ctx["claims"] = [
            validate_success(
                api.create_warranty_claim(
                    create_warranty_claim_payload(
                        ctx["product_line"]["id"],
                        subfloor_moisture_pct_at_install=moisture,
                        ambient_rh_pct_at_install=humidity,
                        claim_type=claim_type,
                        **self.CLAIM_TEMPLATE,
                    ),
                    submitter,
                ),
                expected_status=201,
            )
            for moisture, humidity, claim_type in readings
        ]
        return ctx

    def test_the_claimant_figures_give_all_three_the_same_intake_estimate(self, api):
        """PRD 3.9: "Intake also computes an estimate, `estimated_liability_cents`,
        from the claimant's own figures, in four pinned steps each rounded half up to
        whole cents. First, a base is the `affected_square_feet` multiplied by the sum of
        the line's `material_value_cents_per_sf` and a remediation labour allowance of
        475 cents per square foot. Second, an administrative rate is selected by that
        base: 8 percent while the base is below 500000 cents, 6 percent while it is at
        most 1500000 cents, and 4.5 percent above that. Third, the administrative amount
        is the base multiplied by that rate. Fourth, the estimate is the base plus the
        administrative amount."

        Design: Corner/calculations/responsibility_split_tier_and_rh_penalty_boundaries
        """
        ctx = self._three_claims_on_one_line(api)

        for claim in ctx["claims"]:
            assert claim["adjudication_status"] == "SUBMITTED"
            # 100 square feet at 895 plus 475 is a base of 137000, under the
            # 500000-cent edge, so the eight percent rate adds 10960.
            assert claim["estimated_liability_cents"] == 147960

    def test_the_moisture_tier_and_the_humidity_penalty_move_the_mill_share(self, api):
        """PRD 3.9: "The moisture delta is the absolute difference between
        `adjudicated_subfloor_moisture_pct` and that reference, rounded half up to one
        decimal place, and it selects the `installer_share_pct` in whole percentages: 0
        when the delta is at most 2.0 points, 40 when it is above 2.0 but at most 4.0, 70
        when it is above 4.0 but at most 6.0, and 100 when it is above 6.0."

        PRD 3.9: "Ambient conditions add a penalty: when `adjudicated_ambient_rh_pct`
        falls outside the range 30 to 50 percent inclusive, the installer share is
        increased by 10 percentage points, capped at 100."

        PRD 3.9: "The reference moisture for that judgment is the average moisture
        content of the kiln charge behind the claim's installed lot when a
        `flooring_lot_id` was given, and the species' `target_moisture_pct` when it was
        not."

        PRD 3.9: "Step five ages the claim: `service_months` is the number of whole
        months from `installation_date` to the current logical date, `depreciation_pct` is
        0.5 percentage points per whole month of service capped at 40 percent, and the
        depreciated amount is the gross multiplied by one less that depreciation expressed
        as a fraction. Step six applies responsibility: `adjudicated_liability_cents` is
        the depreciated amount multiplied by `mill_share_pct` and divided by 100."

        PRD 3.9: "The `posture` is then `FROZEN` whenever `freeze_override` is true,
        regardless of money; otherwise it is `RESTRICTED` when `warranty_balance_cents` is
        below the restriction floor of 500000 cents; and otherwise it is `OPEN`."

        Design: Corner/calculations/responsibility_split_tier_and_rh_penalty_boundaries
        """
        ctx = self._three_claims_on_one_line(api)
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)
        first, second, third = ctx["claims"]

        # Delta exactly 2.0 against the species target of 7.0, humidity exactly at
        # the top of the band: the installer carries nothing.
        wholly_the_mill = validate_success(
            api.adjudicate_claim(
                first["id"],
                adjudicate_claim_payload(
                    adjudicated_affected_sf=100,
                    adjudicated_subfloor_moisture_pct=9.0,
                    adjudicated_ambient_rh_pct=50,
                ),
                adjudicator,
            ),
            expected_status=200,
        )
        assert wholly_the_mill["installer_share_pct"] == 0
        assert wholly_the_mill["mill_share_pct"] == 100
        assert wholly_the_mill["service_months"] == 2
        assert wholly_the_mill["depreciation_pct"] == pytest.approx(1.0, abs=0.01)
        assert wholly_the_mill["adjudicated_liability_cents"] == 146480

        # One tenth of a point further out and the installer takes the 40 tier.
        shared = validate_success(
            api.adjudicate_claim(
                second["id"],
                adjudicate_claim_payload(
                    adjudicated_affected_sf=100,
                    adjudicated_subfloor_moisture_pct=9.1,
                    adjudicated_ambient_rh_pct=50,
                ),
                adjudicator,
            ),
            expected_status=200,
        )
        assert shared["installer_share_pct"] == 40
        assert shared["mill_share_pct"] == 60
        assert shared["adjudicated_liability_cents"] == 87888

        # Same moisture, one point of humidity outside the band: ten points more.
        penalised = validate_success(
            api.adjudicate_claim(
                third["id"],
                adjudicate_claim_payload(
                    adjudicated_affected_sf=100,
                    adjudicated_subfloor_moisture_pct=9.1,
                    adjudicated_ambient_rh_pct=51,
                ),
                adjudicator,
            ),
            expected_status=200,
        )
        assert penalised["installer_share_pct"] == 50
        assert penalised["mill_share_pct"] == 50
        assert penalised["adjudicated_liability_cents"] == 73240

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_committed_cents"] == 307608
        assert line["warranty_balance_cents"] == 292392
        assert line["posture"] == "RESTRICTED"


class TestWarrantyAdminRateDiscontinuity:
    """The administrative rate steps down at 500000 cents, and the step is large
    enough to invert two neighbouring claims."""

    def test_a_base_of_exactly_five_hundred_thousand_takes_the_lower_rate(self, api):
        """PRD 3.9: "Intake also computes an estimate, `estimated_liability_cents`,
        from the claimant's own figures, in four pinned steps each rounded half up to
        whole cents. First, a base is the `affected_square_feet` multiplied by the sum of
        the line's `material_value_cents_per_sf` and a remediation labour allowance of
        475 cents per square foot. Second, an administrative rate is selected by that
        base: 8 percent while the base is below 500000 cents, 6 percent while it is at
        most 1500000 cents, and 4.5 percent above that. Third, the administrative amount
        is the base multiplied by that rate. Fourth, the estimate is the base plus the
        administrative amount."

        Design: Corner/calculations/warranty_admin_tier_discontinuity_at_five_hundred_thousand
        """
        # Material 525 plus the 475-cent labour allowance is exactly 1000 cents per
        # square foot, so the area names the base directly.
        ctx = setup_warranty_line(
            api,
            line_overrides={
                "line_code": "SOLID-RO-400",
                "nominal_width_in": 4.000,
                "material_value_cents_per_sf": 525,
                "warranty_funded_total_cents": 2000000,
            },
        )
        submitter = make_warranty_adjudicator_headers(CLAIM_SUBMITTER_USER_ID)
        line_id = ctx["product_line"]["id"]

        at_the_edge = validate_success(
            api.create_warranty_claim(
                create_warranty_claim_payload(
                    line_id,
                    affected_square_feet=500,
                    installation_date="2026-06-01",
                    subfloor_moisture_pct_at_install=9.0,
                    ambient_rh_pct_at_install=45,
                ),
                submitter,
            ),
            expected_status=201,
        )
        assert at_the_edge["estimated_liability_cents"] == 530000

        just_below = validate_success(
            api.create_warranty_claim(
                create_warranty_claim_payload(
                    line_id,
                    affected_square_feet=499.99,
                    installation_date="2026-06-01",
                    subfloor_moisture_pct_at_install=9.0,
                    ambient_rh_pct_at_install=45,
                ),
                submitter,
            ),
            expected_status=201,
        )
        # A base of 499990 at eight percent adds 39999 once the administrative step
        # is rounded on its own.
        assert just_below["estimated_liability_cents"] == 539989

        assert just_below["estimated_liability_cents"] > at_the_edge["estimated_liability_cents"]
