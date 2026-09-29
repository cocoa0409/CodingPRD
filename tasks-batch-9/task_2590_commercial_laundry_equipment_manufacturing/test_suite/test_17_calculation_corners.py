"""Derived-figure corners: rebate ranking, stock projection, yield, money and windows.

Pins the rebate winner chosen on the uncapped value while the capped amount is
stored, the inclusive LOW stock boundary, the first-pass yield computed over
terminal units only, the payment-module surcharges inside the quantity
multiplication, the pro-rata settlement governed by the month ratio, and the
closed-interval station occupation window at a zero changeover buffer.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    ENERGY_REVIEWER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    WARRANTY_ANALYST,
    WATER_REVIEWER,
    make_distributor_headers,
    make_quality_inspector_headers,
    make_technician_headers,
)


class TestRebateQualificationRanking:
    def test_01_winner_is_ranked_uncapped_but_pays_its_capped_amount(self, api):
        """The richest uncapped program wins the ranking yet settles at its own cap.

        PRD: "`rebate_amount_cents` on the dossier is the *payable* value of the top-ranked program, so a program can win the ranking on a large uncapped figure and still pay less than a runner-up whose cap was more generous."
        Design: Corner/calculations/rebate_ranking_uses_uncapped_amount_but_stores_capped
        """
        fx.make_rebate_program(
            api,
            program_code="UTIL-A-BIG",
            utility_code="UTIL-A",
            program_class="COMBINED",
            eligible_product_lines=["ON_PREMISES"],
            max_water_gal_per_cwt=1.10,
            max_kwh_per_cwt=0.45,
            min_capacity_rating_lb=40,
            rebate_base_cents=60000,
            capacity_bonus_cents_per_10lb=5000,
            rebate_cap_cents=90000,
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z",
        )
        fx.make_rebate_program(
            api,
            program_code="UTIL-B-RICH",
            utility_code="UTIL-B",
            program_class="COMBINED",
            eligible_product_lines=["ON_PREMISES"],
            max_water_gal_per_cwt=1.10,
            max_kwh_per_cwt=0.45,
            min_capacity_rating_lb=40,
            rebate_base_cents=50000,
            capacity_bonus_cents_per_10lb=20000,
            rebate_cap_cents=70000,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-09-30T00:00:00Z",
        )
        model = fx.make_model(
            api,
            model_code="OPL-100-A",
            product_line="ON_PREMISES",
            capacity_rating_lb=100,
            rated_water_gal_per_cwt=1.05,
            rated_kwh_per_cwt=0.42,
            drum_alloy_grade="AISI_304",
            list_price_cents=1650000,
        )
        dossier = fx.make_dossier(
            api,
            model["id"],
            measured_water_gal_per_cwt=1.05,
            measured_kwh_per_cwt=0.40,
            test_cycle_count=120,
        )
        validate_success(
            api.create_dossier_review(
                dossier["id"], f.review_payload("ENERGY", "APPROVE"), ENERGY_REVIEWER
            ),
            expected_status=200,
        )

        certified = validate_success(
            api.create_dossier_review(
                dossier["id"], f.review_payload("WATER", "APPROVE"), WATER_REVIEWER
            ),
            expected_status=200,
        )
        assert certified["dossier_state"] == "CERTIFIED"
        assert certified["certified_at"][:19] == "2026-08-01T00:00:00"
        assert certified["qualified_program_codes"] == ["UTIL-A-BIG", "UTIL-B-RICH"]
        a.assert_cents(certified["rebate_amount_cents"], 70000)

        stored_model = validate_success(
            api.get_machine_model(model["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert stored_model["rebate_program_codes"] == ["UTIL-A-BIG", "UTIL-B-RICH"]
        a.assert_cents(stored_model["rebate_amount_cents"], 70000)
        assert stored_model["certification_state"] == "CERTIFIED"


class TestPartStockProjection:
    def test_01_on_hand_equal_to_the_reorder_point_projects_low(self, api):
        """Walking a part's shelf position pins all three projected stock states.

        PRD: "The part's `stock_state` is re-projected from the new on-hand position: it becomes `BACKORDERED` when `on_hand_qty` has reached exactly 0, `LOW` when `on_hand_qty` is above 0 but at or below `reorder_point_qty` — the boundary is inclusive, so an on-hand position exactly equal to the reorder point reads `LOW` and not `IN_STOCK` — and `IN_STOCK` otherwise."
        Design: Corner/calculations/part_stock_projection_low_boundary_is_inclusive
        """
        part = fx.make_service_part(api)
        assert part["on_hand_qty"] == 0
        assert part["stock_state"] == "BACKORDERED"
        assert part["reorder_point_qty"] == 2

        received = validate_success(
            api.create_stock_adjustment(
                part["id"], f.stock_adjustment_payload(3, "RECEIPT"), PLANT_MANAGER
            ),
            expected_status=200,
        )
        assert received["on_hand_qty"] == 3
        assert received["stock_state"] == "IN_STOCK"
        assert received["reserved_qty"] == 0

        at_reorder_point = validate_success(
            api.create_stock_adjustment(
                part["id"],
                f.stock_adjustment_payload(-1, "CYCLE_COUNT"),
                PLANT_MANAGER,
            ),
            expected_status=200,
        )
        assert at_reorder_point["on_hand_qty"] == 2
        assert at_reorder_point["stock_state"] == "LOW"
        assert at_reorder_point["reserved_qty"] == 0

        emptied = validate_success(
            api.create_stock_adjustment(
                part["id"],
                f.stock_adjustment_payload(-2, "CYCLE_COUNT"),
                PLANT_MANAGER,
            ),
            expected_status=200,
        )
        assert emptied["on_hand_qty"] == 0
        assert emptied["stock_state"] == "BACKORDERED"
        assert emptied["reserved_qty"] == 0
        assert emptied["version"] == 4


class TestFirstPassYield:
    def test_01_units_still_on_the_floor_leave_the_yield_untouched(self, api):
        """A unit still on the floor is in neither half of the yield fraction.

        PRD: "Units still on the floor, in rework, or sitting on quality hold are excluded from both numerator and denominator, and an accepted unit that needed one or more rework rounds counts in the denominator but not in the numerator."
        Design: Corner/calculations/first_pass_yield_excludes_units_still_on_the_floor
        """
        env = fx.make_floor_environment(
            api,
            model_overrides={"max_rework_cycles": 0, "min_first_pass_yield_pct": 40.00},
        )
        accepted = fx.make_accepted_unit(api, env, serial_number="SN-0001")

        second = fx.make_build_order(
            api, env["model"]["id"], serial_number="SN-0002"
        )
        fx.release_build(api, second["id"])
        fx.walk_build_to_qa_hold(
            api,
            second["id"],
            env["stations"],
            env["technician"]["id"],
            drum_start="2026-08-01T12:00:00Z",
            drum_end="2026-08-01T13:00:00Z",
            bearing_start="2026-08-01T13:00:00Z",
            bearing_end="2026-08-01T14:00:00Z",
            control_start="2026-08-01T14:00:00Z",
            control_end="2026-08-01T15:00:00Z",
        )

        third = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0003")
        fx.release_build(api, third["id"])

        scrapped = validate_success(
            api.qa_signoff(
                second["id"],
                f.qa_signoff_payload("REJECT", defect_code="BEARING_PRELOAD"),
                make_quality_inspector_headers(env["inspector"]["id"]),
            ),
            expected_status=200,
        )
        assert scrapped["build_state"] == "SCRAPPED"
        assert scrapped["rework_count"] == 1
        assert scrapped["scrap_reason"] == "REWORK_LIMIT"

        first = validate_success(
            api.get_build_order(accepted["build"]["id"], PLANT_MANAGER),
            expected_status=200,
        )
        assert first["build_state"] == "ACCEPTED"
        assert first["rework_count"] == 0

        floor_unit = validate_success(
            api.get_build_order(third["id"], PLANT_MANAGER), expected_status=200
        )
        assert floor_unit["build_state"] == "ON_FLOOR"

        model = validate_success(
            api.get_machine_model(env["model"]["id"], PRODUCT_ENGINEER),
            expected_status=200,
        )
        assert model["accepted_unit_count"] == 1
        assert model["scrapped_unit_count"] == 1
        a.assert_pct(model["first_pass_yield_pct"], 50.00)
        assert model["certification_state"] == "CERTIFIED"
        assert model["suspended_reason"] == "NONE"

        dossier = validate_success(
            api.get_certification_dossier(env["dossier"]["id"], COMPLIANCE_OFFICER),
            expected_status=200,
        )
        assert dossier["dossier_state"] == "CERTIFIED"
        assert dossier["resurvey_count"] == 0


class TestQuoteMoneyRollup:
    def test_01_every_payment_module_surcharge_rides_inside_the_quantity(self, api):
        """Four lines, one per payment module, roll up into the package total.

        PRD: "The unit price and the per-unit surcharge are added together; that per-unit figure is multiplied by the `quantity`, because the surcharge is charged per machine and therefore sits inside the quantity multiplication; the product is then multiplied by one minus the `line_discount_pct` divided by one hundred; and only that final extended amount is rounded half up to a whole number of cents."
        Design: Corner/calculations/quote_rollup_sums_all_four_payment_module_surcharges
        """
        model = fx.make_vended_model(api)
        distributor = fx.make_distributor(api)
        channel = {
            "distributor": distributor,
            "headers": make_distributor_headers(distributor["id"]),
        }
        quote = fx.make_quote(
            api,
            channel,
            customer_name="Wash Barn LLC",
            laundromat_site_code="SITE-88",
            stated_credit_score=700,
            financing_program="NONE",
            down_payment_cents=0,
            package_discount_pct=10.00,
            freight_cents=125000,
        )

        coin_line = fx.add_quote_line(
            api, quote["id"], channel, model["id"], quantity=1, payment_module="COIN"
        )
        a.assert_cents(coin_line["payment_surcharge_cents"], 3500)
        a.assert_cents(coin_line["line_total_cents"], 783500)
        a.assert_cents(coin_line["unit_price_cents"], 780000)

        mobile_line = fx.add_quote_line(
            api, quote["id"], channel, model["id"], quantity=2, payment_module="MOBILE"
        )
        a.assert_cents(mobile_line["payment_surcharge_cents"], 9000)
        a.assert_cents(mobile_line["line_total_cents"], 1578000)

        plain_line = fx.add_quote_line(
            api, quote["id"], channel, model["id"], quantity=1, payment_module="NONE"
        )
        a.assert_cents(plain_line["payment_surcharge_cents"], 0)
        a.assert_cents(plain_line["line_total_cents"], 780000)

        card_line = validate_success(
            api.create_quote_line(
                quote["id"],
                f.quote_line_payload(
                    model["id"],
                    fx.read_quote_version(api, quote["id"], channel),
                    quantity=1,
                    payment_module="CARD",
                ),
                channel["headers"],
            ),
            expected_status=201,
        )
        a.assert_cents(card_line["payment_surcharge_cents"], 12500)
        a.assert_cents(card_line["line_total_cents"], 792500)
        a.assert_cents(card_line["unit_price_cents"], 780000)

        rolled = validate_success(
            api.get_quote(quote["id"], channel["headers"]), expected_status=200
        )
        assert rolled["line_count"] == 4
        a.assert_cents(rolled["line_subtotal_cents"], 3934000)
        a.assert_cents(rolled["discount_cents"], 393400)
        a.assert_cents(rolled["freight_cents"], 125000)
        a.assert_cents(rolled["total_cents"], 3665600)
        a.assert_money_identity(rolled)


class TestWarrantyProRataSettlement:
    def test_01_the_month_ratio_governs_when_it_is_the_smaller_entitlement(self, api):
        """A part half-way through its warranty year settles on the month ratio.

        PRD: "Two ratios are formed — the cycle-remaining ratio, being `effective_rated_cycles` minus `failure_cycle_count` divided by `effective_rated_cycles`; and the month-remaining ratio, being `warranty_months` minus `in_service_months` divided by `warranty_months` — and `covered_amount_cents` is the part's `unit_price_cents` multiplied by the **lesser** of those two ratios, rounded half up once to a whole number of cents."
        Design: Corner/calculations/warranty_pro_rata_governed_by_month_ratio
        """
        env = fx.make_floor_environment(
            api,
            model_overrides={
                "model_code": "VND-40-C",
                "product_line": "VENDED",
                "capacity_rating_lb": 40,
                "rated_water_gal_per_cwt": 0.95,
                "rated_kwh_per_cwt": 0.38,
                "drum_alloy_grade": "AISI_316",
                "payment_module_options": ["COIN"],
                "list_price_cents": 780000,
            },
        )
        unit = fx.make_accepted_unit(api, env, serial_number="SN-2001")
        channel = fx.make_authorized_distributor(api)
        service_technician = fx.make_service_technician(api, channel)
        part = fx.make_stocked_part(api, 3)

        claim = fx.make_claim(
            api,
            unit["build"]["id"],
            part["id"],
            channel,
            service_technician["id"],
            failure_cycle_count=4000,
            in_service_months=18,
            duty_cycle_class="HEAVY",
            diagnostics_code="BRG-OVERHEAT",
        )
        assert claim["effective_rated_cycles"] == 17850
        assert claim["claim_state"] == "SUBMITTED"

        settled = validate_success(
            api.adjudicate_warranty_claim(
                claim["id"],
                f.adjudicate_payload(fx.read_part_version(api, part["id"]), "APPROVE"),
                WARRANTY_ANALYST,
            ),
            expected_status=200,
        )
        assert settled["claim_state"] == "APPROVED"
        assert settled["coverage_variant"] == "PRO_RATA"
        a.assert_cents(settled["covered_amount_cents"], 21000)
        assert settled["denial_reason"] == "NONE"
        assert settled["block_reason"] == "NONE"

        distributor = validate_success(
            api.get_distributor(channel["distributor"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        a.assert_cents(distributor["warranty_credit_cents"], 21000)
        assert distributor["open_claim_count"] == 0

        reserved = validate_success(
            api.get_service_part(part["id"], WARRANTY_ANALYST), expected_status=200
        )
        assert reserved["on_hand_qty"] == 2
        assert reserved["reserved_qty"] == 1
        assert reserved["stock_state"] == "LOW"
        a.assert_unit_conservation(reserved, 3)


class TestStationOccupationWindows:
    def test_01_a_start_at_the_instant_a_window_ends_conflicts_at_zero_buffer(self, api):
        """With no changeover buffer, the next unit must start a minute after the last.

        PRD: "Because both ends are closed, a new operation beginning at exactly the instant an existing occupation window ends still conflicts — with a thirty-minute changeover buffer on a one-hour operation ending at nine o'clock, the window runs to half past nine and a new operation at half past nine is refused, while one starting a minute later is accepted."
        Design: Corner/calculations/station_occupation_closed_intervals_touch_at_zero_buffer
        """
        env = fx.make_certified_model(api)
        station = fx.make_station(
            api,
            station_code="DRUM-01",
            station_type="DRUM_FAB",
            parallel_capacity=1,
            changeover_buffer_minutes=0,
            supported_product_lines=["ON_PREMISES"],
        )
        technician = fx.make_certified_technician(
            api, ["DRUM_FAB"], employee_code="T-100", full_name="Ann Ito"
        )
        headers = make_technician_headers(technician["id"])

        first = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
        fx.release_build(api, first["id"])
        second = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0002")
        fx.release_build(api, second["id"])

        opening_log = validate_success(
            api.create_station_log(
                first["id"],
                f.station_log_payload(
                    station["id"],
                    "DRUM_FAB",
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T09:00:00Z",
                    "PASS",
                ),
                headers,
            ),
            expected_status=201,
        )
        assert opening_log["occupation_from"][:19] == "2026-08-01T08:00:00"
        assert opening_log["occupation_to"][:19] == "2026-08-01T09:00:00"
        assert opening_log["labor_minutes"] == 60

        touching = api.create_station_log(
            second["id"],
            f.station_log_payload(
                station["id"],
                "DRUM_FAB",
                "2026-08-01T09:00:00Z",
                "2026-08-01T10:00:00Z",
                "PASS",
            ),
            headers,
        )
        validate_error(touching, E.ERR_STATION_CAPACITY_CONFLICT, expected_status=409)

        accepted_log = validate_success(
            api.create_station_log(
                second["id"],
                f.station_log_payload(
                    station["id"],
                    "DRUM_FAB",
                    "2026-08-01T09:01:00Z",
                    "2026-08-01T10:00:00Z",
                    "PASS",
                ),
                headers,
            ),
            expected_status=201,
        )
        assert accepted_log["occupation_from"][:19] == "2026-08-01T09:01:00"
        assert accepted_log["occupation_to"][:19] == "2026-08-01T10:00:00"
        assert accepted_log["labor_minutes"] == 59

        moved = validate_success(
            api.get_build_order(second["id"], PLANT_MANAGER), expected_status=200
        )
        assert moved["build_state"] == "DRUM_DONE"
        assert moved["station_pass_count"] == 1
        assert moved["labor_minutes_total"] == 59

        rows, meta = validate_paginated(
            api.list_station_logs(PLANT_MANAGER, station_id=station["id"])
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2
