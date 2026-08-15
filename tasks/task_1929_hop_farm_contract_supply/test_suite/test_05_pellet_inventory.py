"""Pelletizing, blend accounting, inventory listing, and warehouse aging."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_pellet_lot_payload, setup_harvesting_plan_with_kiln, create_dried_lot,
    create_moisture_check_lot, create_pellet_lot, setup_field_with_plan,
    setup_pellet_lot_single_source, create_spot_sale, set_clock,
)


class TestPelletBlendRoundingOrder:
    def _setup_two_104_lots(self, api):
        """Two DRIED lots of 104 lbs each (final alphas 12.0 and 14.0)."""
        ctx = setup_harvesting_plan_with_kiln()
        lot_a = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                 wet_lbs=390, dried_lbs=104, final_alpha=12.0)
        lot_b = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                 wet_lbs=390, dried_lbs=104,
                                 window_start="2026-08-20T12:30:00Z",
                                 window_end="2026-08-20T16:00:00Z",
                                 final_alpha=14.0)
        return ctx, lot_a, lot_b

    def test_qty_aggregate_then_round(self, api, farm_manager_headers):
        """PRD §3.4: "The `qty_lbs` is the total dried weight of the source lots
        reduced by an 8 percent processing loss, rounded half-up once to a whole
        pound — the rounding applies to the aggregate, never per source lot.
        Consider two source lots of 104 dried lbs each: together 208 lbs, reduced
        by 8 percent is 191.36, which rounds half-up to 191 lbs. Rounding each
        lot first would give 96 plus 96, a total of 192 — a different, forbidden
        order."

        Design: Difficulty/combinatorial_formula/pellet_blend_rounding_order
        """
        ctx, lot_a, lot_b = self._setup_two_104_lots(api)
        pellet = validate_success(api.create_pellet_lot(
            create_pellet_lot_payload([lot_a["id"], lot_b["id"]]),
            farm_manager_headers), 201)
        assert pellet["qty_lbs"] == 191, (
            "aggregate-then-round: 208 x 0.92 = 191.36 -> 191, not 192")

    def test_blend_weighted_alpha_and_source_consumption(self, api, farm_manager_headers):
        """PRD §3.4: "the blend is the sum of each lot's dried weight times its
        effective alpha, divided by the sum of the dried weights, rounded half-up
        to 2 decimal places, applied once after aggregation." (104 x 12.0 +
        104 x 14.0) / 208 = 13.0. And: "A successful pelletize moves every source
        lot from `DRIED` to `CONSUMED`".

        Design: Difficulty/combinatorial_formula/pellet_blend_rounding_order
        """
        ctx, lot_a, lot_b = self._setup_two_104_lots(api)
        pellet = validate_success(api.create_pellet_lot(
            create_pellet_lot_payload([lot_a["id"], lot_b["id"]]),
            farm_manager_headers), 201)
        assert pellet["blended_alpha_pct"] == 13.0
        assert pellet["variety"] == "CASCADE"
        assert pellet["crop_year"] == 2026
        for lot in (lot_a, lot_b):
            after = validate_success(
                api.get_harvest_lot(lot["id"], farm_manager_headers), 200)
            assert after["status"] == "CONSUMED"


class TestPelletizeConstraints:
    def _setup_two_variety_lots(self, api, release_b=True):
        """Lot A CASCADE 2026 DRIED on field F1; lot B CITRA 2026 on field F2,
        DRIED when release_b else MOISTURE_CHECK."""
        ctx_a = setup_harvesting_plan_with_kiln(field_name="F1", variety="CASCADE")
        lot_a = create_dried_lot(ctx_a["plan"]["id"], ctx_a["kiln"]["id"],
                                 wet_lbs=1875, dried_lbs=500)
        field_b, plan_b = setup_field_with_plan(
            field_name="F2", variety="CITRA", plan_state="HARVESTING")
        if release_b:
            lot_b = create_dried_lot(plan_b["id"], ctx_a["kiln"]["id"],
                                     wet_lbs=1875, dried_lbs=500,
                                     window_start="2026-08-20T12:30:00Z",
                                     window_end="2026-08-20T16:00:00Z")
        else:
            lot_b = create_moisture_check_lot(
                plan_b["id"], ctx_a["kiln"]["id"], wet_lbs=1875, dried_lbs=500,
                window_start="2026-08-20T12:30:00Z",
                window_end="2026-08-20T16:00:00Z")
        return lot_a, lot_b

    def test_mixed_variety_rejected(self, api, farm_manager_headers):
        """PRD §3.4: "all source lots must share one `variety`, otherwise
        `ERR_MIXED_VARIETY`".

        Design: Corner/validations/pelletize_mixed_variety_alone
        """
        lot_a, lot_b = self._setup_two_variety_lots(api, release_b=True)
        res = api.create_pellet_lot(
            create_pellet_lot_payload([lot_a["id"], lot_b["id"]]),
            farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_MIXED_VARIETY)

    def test_mixed_crop_year_rejected(self, api, farm_manager_headers):
        """PRD §3.4: "and all must share one `crop_year`, otherwise
        `ERR_MIXED_CROP_YEAR`."

        Design: Corner/validations/pelletize_mixed_crop_year
        """
        ctx = setup_harvesting_plan_with_kiln(crop_year=2026, variety="CASCADE")
        plan_2027 = validate_success(api.create_planting_plan(
            {"field_id": ctx["field"]["id"], "crop_year": 2027, "variety": "CASCADE",
             "planned_acreage": 40}, farm_manager_headers), 201)
        validate_success(api.approve_plan(plan_2027["id"], farm_manager_headers), 200)
        validate_success(api.open_harvest(plan_2027["id"], farm_manager_headers), 200)
        lot_a = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                 wet_lbs=1875, dried_lbs=500)
        lot_b = create_dried_lot(plan_2027["id"], ctx["kiln"]["id"],
                                 wet_lbs=1875, dried_lbs=500,
                                 window_start="2027-08-20T08:00:00Z",
                                 window_end="2027-08-20T12:00:00Z")
        res = api.create_pellet_lot(
            create_pellet_lot_payload([lot_a["id"], lot_b["id"]]),
            farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_MIXED_CROP_YEAR)


class TestPelletizeReferentialBeforeConstraint:
    def test_non_dried_source_reports_lot_not_dried(self, api, farm_manager_headers):
        """PRD §2.8: "a failure at any tier masks every lower tier" with
        "11. Linked-entity usability — ... source lots are dried for pelletizing
        ... each surfacing its referential error (`ERR_LOT_NOT_DRIED`, ...)"
        ahead of "12. Aggregate and uniqueness constraints — ... single-variety
        and single-crop-year blending". A CITRA lot still in MOISTURE_CHECK plus
        a DRIED CASCADE lot fails both tiers and surfaces the referential one.

        Design: Difficulty/priority_pair_validation_conflict/pelletize_referential_beats_constraint
        """
        ctx_a = setup_harvesting_plan_with_kiln(field_name="F1", variety="CASCADE")
        lot_a = create_dried_lot(ctx_a["plan"]["id"], ctx_a["kiln"]["id"],
                                 wet_lbs=1875, dried_lbs=500)
        field_b, plan_b = setup_field_with_plan(
            field_name="F2", variety="CITRA", plan_state="HARVESTING")
        lot_b = create_moisture_check_lot(
            plan_b["id"], ctx_a["kiln"]["id"], wet_lbs=1875, dried_lbs=500,
            window_start="2026-08-20T12:30:00Z", window_end="2026-08-20T16:00:00Z")
        res = api.create_pellet_lot(
            create_pellet_lot_payload([lot_a["id"], lot_b["id"]]),
            farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_DRIED)

    def test_rejected_pelletize_leaves_sources_untouched(self, api, farm_manager_headers):
        """PRD §3.4: "A successful pelletize moves every source lot from `DRIED`
        to `CONSUMED`" — a rejected pelletize is not a successful pelletize, so
        neither source changes state.

        Design: Difficulty/priority_pair_validation_conflict/pelletize_referential_beats_constraint
        """
        ctx_a = setup_harvesting_plan_with_kiln(field_name="F1", variety="CASCADE")
        lot_a = create_dried_lot(ctx_a["plan"]["id"], ctx_a["kiln"]["id"],
                                 wet_lbs=1875, dried_lbs=500)
        field_b, plan_b = setup_field_with_plan(
            field_name="F2", variety="CITRA", plan_state="HARVESTING")
        lot_b = create_moisture_check_lot(
            plan_b["id"], ctx_a["kiln"]["id"], wet_lbs=1875, dried_lbs=500,
            window_start="2026-08-20T12:30:00Z", window_end="2026-08-20T16:00:00Z")
        validate_error(api.create_pellet_lot(
            create_pellet_lot_payload([lot_a["id"], lot_b["id"]]),
            farm_manager_headers), ApiErrorId.ERR_LOT_NOT_DRIED)
        after_a = validate_success(api.get_harvest_lot(lot_a["id"], farm_manager_headers), 200)
        after_b = validate_success(api.get_harvest_lot(lot_b["id"], farm_manager_headers), 200)
        assert after_a["status"] == "DRIED"
        assert after_b["status"] == "MOISTURE_CHECK"


class TestPelletLotListing:
    def test_pellet_lot_list_pagination(self, api, farm_manager_headers):
        """PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/pellet_lot_listing_pagination
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot1 = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                wet_lbs=3750, dried_lbs=1000)
        lot2 = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                wet_lbs=3000, dried_lbs=800,
                                window_start="2026-08-20T12:30:00Z",
                                window_end="2026-08-20T16:00:00Z")
        pellet1 = create_pellet_lot([lot1["id"]], storage_room="R1")
        pellet2 = create_pellet_lot([lot2["id"]], storage_room="R1")

        page1, meta1 = validate_paginated(api.list_pellet_lots(
            farm_manager_headers, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_pellet_lots(
            farm_manager_headers, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert page2[0]["id"] != page1[0]["id"]
        assert meta2["has_more"] is False
        assert {page1[0]["id"], page2[0]["id"]} == {pellet1["id"], pellet2["id"]}


class TestParallelDimensions:
    def test_spot_draft_reserves_without_aging(self, api, contract_manager_headers):
        """PRD §3.4: "A pellet lot carries two independent state dimensions."
        and "drafting a spot sale or confirming an allocation reserves it"; the
        `age_class` — `CURRENT` at creation — "tracks warehouse age and flips
        only at crop-year rollover."

        Design: Difficulty/non_linear_state_machine/pellet_lot_parallel_dimensions
        """
        ctx = setup_pellet_lot_single_source(wet_lbs=3000, dried_lbs=800,
                                             final_alpha=12.0)
        pellet = ctx["pellet"]
        assert pellet["inventory_status"] == "AVAILABLE"
        assert pellet["age_class"] == "CURRENT"
        create_spot_sale(pellet["id"], buyer_name="CraftBrew",
                         price_cents_per_lb=650, buyer_credit_limit_cents=1_000_000)
        after = validate_success(
            api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
        assert after["inventory_status"] == "RESERVED"
        assert after["age_class"] == "CURRENT", (
            "the inventory dimension moved; the age dimension did not")

    def test_rollover_ages_reserved_lot_with_decay(self, api, farm_manager_headers):
        """PRD §3.9: "Every pellet lot whose `age_class` is `CURRENT`, whose
        `crop_year` is before the clock's year, and whose `inventory_status` is
        `AVAILABLE` or `RESERVED` flips to `CARRYOVER`" and "shrink the lot's
        `blended_alpha_pct` by 1 percent per remaining decay month, compounding —
        formally, multiplied by 0.99 raised to the power of the number of decay
        months — rounding the result half-up to 2 decimal places." Stored
        2026-08-01 to 2027-08-01: 12 months less the 6-month grace, so
        12.00 x 0.99^6 = 11.30.

        Design: Difficulty/non_linear_state_machine/pellet_lot_parallel_dimensions
        """
        ctx = setup_pellet_lot_single_source(wet_lbs=3000, dried_lbs=800,
                                             final_alpha=12.0)
        pellet = ctx["pellet"]
        assert pellet["blended_alpha_pct"] == 12.0
        create_spot_sale(pellet["id"], buyer_name="CraftBrew",
                         price_cents_per_lb=650, buyer_credit_limit_cents=1_000_000)
        set_clock("2027-08-01T00:00:00Z")
        rollover = validate_success(api.crop_year_rollover(farm_manager_headers), 200)
        assert pellet["id"] in rollover["carried_over_lot_ids"]
        after = validate_success(api.get_pellet_lot(pellet["id"], farm_manager_headers), 200)
        assert after["age_class"] == "CARRYOVER"
        assert after["inventory_status"] == "RESERVED", (
            "aging does not disturb the inventory dimension")
        assert after["blended_alpha_pct"] == pytest.approx(11.30, abs=1e-9), (
            "carryover decay: 12.00 x 0.99^6 rounded half-up to 2 dp")
