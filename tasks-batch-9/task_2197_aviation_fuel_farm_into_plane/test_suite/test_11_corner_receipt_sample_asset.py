"""Corner behaviour of the parcel and fitness records: receipt payload edges, the partial metric
set, the three element-life legs and the immutable filter-change document."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)


class TestFuelReceiptCorners:
    def test_a_closing_gauge_equal_to_the_opening_gauge_is_out_of_range(self, api):
        """PRD §3.2: "The payload names the destination tank with a `storage_tank_id`, declares how
        the parcel arrived through `delivery_mode` (either `PIPELINE` or `TRUCK`), and carries a
        `supplier_name`, a `meter_ticket_number` unique across all receipts, the
        `meter_ticket_gross_liters` printed on the supplier's ticket (greater than zero), the
        `tank_opening_gauge_liters` read before the parcel landed (zero or greater), the
        `tank_closing_gauge_liters` read afterwards (strictly greater than the opening reading), the
        observed `temperature_c` in Celsius (at least minus 20 and at most 60), and the
        `certificate_density_kg_per_m3` from the supplier's refinery certificate of quality (at least
        750 and at most 850)."
        PRD §2.10: "Required-field presence and type correctness (`ERR_INVALID_PAYLOAD`) precede
        declared value constraints (`ERR_FIELD_OUT_OF_RANGE`), which cover every numeric range and
        enumeration membership declared in this document as well as the relational constraints — a
        receipt's closing gauge must exceed its opening gauge, an uplift's meter end reading must
        exceed its meter start reading, a fuelling window's end must be later than its start, a
        reconciliation or billing period's end must be later than its start, and a tank's safe fill
        volume must not exceed its shell capacity."

        Design: Corner/entities/closing_gauge_not_greater_than_opening_gauge
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        payload = F.create_fuel_receipt_payload(
            env["tank"]["id"], delivery_mode="TRUCK", meter_ticket_gross_liters=30120.0,
            tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=100.0,
            temperature_c=25.0, certificate_density_kg_per_m3=795.0)

        validate_error(api.create_fuel_receipt(payload, fx.OPERATOR),
                       ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

        receipts, _meta = validate_paginated(api.list_fuel_receipts(
            fx.OPERATOR, {"storage_tank_id": env["tank"]["id"]}))
        assert receipts == []

    def test_a_meter_ticket_number_may_not_be_reused_on_another_tank(self, api):
        """PRD §3.2: "The payload names the destination tank with a `storage_tank_id`, declares how the
        parcel arrived through `delivery_mode` (either `PIPELINE` or `TRUCK`), and carries a
        `supplier_name`, a `meter_ticket_number` unique across all receipts, the
        `meter_ticket_gross_liters` printed on the supplier's ticket (greater than zero), the
        `tank_opening_gauge_liters` read before the parcel landed (zero or greater), the
        `tank_closing_gauge_liters` read afterwards (strictly greater than the opening reading), the
        observed `temperature_c` in Celsius (at least minus 20 and at most 60), and the
        `certificate_density_kg_per_m3` from the supplier's refinery certificate of quality (at least
        750 and at most 850)."

        Design: Corner/entities/duplicate_meter_ticket_number
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        other = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                 safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                 opening_volume_liters=0.0)
        first = fx.record_receipt(
            env["tank"]["id"], delivery_mode="TRUCK", meter_ticket_number="MT-8001",
            meter_ticket_gross_liters=30120.0, tank_opening_gauge_liters=100.0,
            tank_closing_gauge_liters=30100.0, temperature_c=25.0,
            certificate_density_kg_per_m3=795.0)
        assert first["meter_ticket_number"] == "MT-8001"

        duplicate = F.create_fuel_receipt_payload(
            other["id"], delivery_mode="TRUCK", meter_ticket_number="MT-8001",
            meter_ticket_gross_liters=30120.0, tank_opening_gauge_liters=0.0,
            tank_closing_gauge_liters=30000.0, temperature_c=25.0,
            certificate_density_kg_per_m3=795.0)
        validate_error(api.create_fuel_receipt(duplicate, fx.OPERATOR),
                       ApiErrorId.ERR_DUPLICATE_KEY, 409)

    def test_an_omitted_water_figure_defaults_to_zero_and_deducts_nothing(self, api):
        """PRD §3.2: "An optional `measured_water_liters`, defaulting to 0.0 and required to be zero or
        greater, records the free water drained from the parcel before capping."
        PRD §3.2: "**Sixth**, `net_volume_liters` is the corrected volume less the applied deduction,
        rounded half up to two decimals again."

        Design: Corner/entities/water_deduction_cap_when_water_is_zero
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        receipt = fx.record_receipt(
            env["tank"]["id"], delivery_mode="TRUCK", supplier_name="Refinery One",
            meter_ticket_gross_liters=30000.0, tank_opening_gauge_liters=100.0,
            tank_closing_gauge_liters=30100.0, temperature_c=25.0,
            certificate_density_kg_per_m3=795.0)

        assert receipt["measured_water_liters"] == pytest.approx(0.0, abs=0.005)
        assert receipt["governing_gross_liters"] == pytest.approx(30000.00, abs=0.005)
        assert receipt["net_volume_liters"] == pytest.approx(29730.00, abs=0.005), \
            "with no water the net volume is the corrected gross exactly"
        assert receipt["advisory_gross_liters"] == pytest.approx(30000.00, abs=0.005)
        assert receipt["advisory_net_volume_liters"] == pytest.approx(29730.00, abs=0.005)


class TestQualitySampleCorners:
    def test_a_result_payload_with_every_metric_omitted_is_refused(self, api):
        """PRD §3.2: "Five metrics may be posted, each optional individually but with at least one
        required overall — a payload in which every metric is null is rejected with
        `ERR_EMPTY_TEST_RESULT_SET`."

        Design: Corner/entities/all_metrics_null_is_rejected
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        receipt = fx.record_receipt(
            env["tank"]["id"], delivery_mode="TRUCK", meter_ticket_gross_liters=30120.0,
            tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=30100.0,
            temperature_c=25.0, certificate_density_kg_per_m3=795.0)
        sample = fx.draw_receipt_sample(receipt["id"], fx.INSPECTOR_A)

        validate_error(api.post_test_results(sample["id"], {}, fx.INSPECTOR_A),
                       ApiErrorId.ERR_EMPTY_TEST_RESULT_SET, 422)

        assert validate_success(api.get_quality_sample(
            sample["id"], fx.INSPECTOR_A))["status"] == "DRAWN"
        assert validate_success(api.get_fuel_receipt(
            receipt["id"], fx.OPERATOR))["status"] == "SAMPLED"

    def test_a_tank_sample_populates_exactly_one_parent_slot(self, api):
        """PRD §3.2: "A sample's own lifecycle has just two values, `DRAWN` and `TESTED`, and its
        polymorphic parentage is expressed by exactly one of `fuel_receipt_id`, `storage_tank_id` or
        `fueling_asset_id` being set, with `drawn_by_user_id` always recording who took it."

        Design: Corner/entities/exactly_one_polymorphic_parent_is_set
        """
        env = fx.setup_fuel_farm()
        tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=0.0)
        sample = fx.draw_tank_sample(tank["id"], fx.INSPECTOR_A)

        assert sample["sample_purpose"] == "PERIODIC_TANK_QA"
        assert sample["storage_tank_id"] == tank["id"]
        assert sample["fuel_receipt_id"] is None
        assert sample["fueling_asset_id"] is None
        assert sample["status"] == "DRAWN"

    def test_a_single_failing_metric_is_judged_without_the_absent_ones(self, api):
        """PRD §3.2: "The verdict computation is a strict all-pass gate over the metrics that were
        actually posted; a null metric is skipped entirely and cannot fail."
        PRD §3.2: "The flash point fails when it is below 38.0 degrees Celsius, so exactly 38.0
        passes."

        Design: Corner/entities/partial_metric_set_still_yields_a_verdict
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        receipt = fx.record_receipt(
            env["tank"]["id"], delivery_mode="TRUCK", meter_ticket_gross_liters=30120.0,
            tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=30100.0,
            temperature_c=25.0, certificate_density_kg_per_m3=795.0)
        sample = fx.draw_receipt_sample(receipt["id"], fx.INSPECTOR_A)

        tested = validate_success(api.post_test_results(
            sample["id"], {"flash_point_c": 37.9}, fx.INSPECTOR_A))
        reread = validate_success(api.get_quality_sample(sample["id"], fx.INSPECTOR_A))

        assert reread["status"] == "TESTED"
        assert reread["verdict"] == "FAIL"
        assert reread["failed_metrics"] == ["flash_point_c"], \
            "absent metrics are neither passed nor failed"


class TestFuelingAssetCorners:
    def test_a_differential_pressure_of_exactly_the_maximum_exhausts_element_life(self, api):
        """PRD §3.7: "The **pressure leg** compares the asset's `differential_pressure_kpa` against a
        maximum permitted differential of 103.0 kilopascals and expresses that as a percentage rounded
        half up to four decimals. The asset's `element_life_pct` is the largest of those three
        percentages."
        PRD §3.6: "The asset must be `IN_SERVICE` with its `element_life_pct` strictly below 100.0."

        Design: Corner/entities/differential_pressure_at_103_kpa_downs_the_asset_immediately
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED", requested_uplift_liters=10_000.0,
                                   max_authorized_liters=10_000.0,
                                   account_overrides={"credit_limit_cents": 100_000_000})
        maxed = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  turnaround_buffer_minutes=15,
                                  differential_pressure_kpa=103.0)
        just_below = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                       turnaround_buffer_minutes=15,
                                       differential_pressure_kpa=102.99)
        assert maxed["element_life_pct"] == pytest.approx(100.0, abs=0.00005)
        assert just_below["element_life_pct"] == pytest.approx(99.9903, abs=0.00005)

        validate_error(api.assign_order(env["order"]["id"],
                                        {"fueling_asset_id": maxed["id"]}, fx.AGENT),
                       ApiErrorId.ERR_ASSET_NOT_SERVICEABLE, 409)

        clean = validate_success(api.assign_order(
            env["order"]["id"], {"fueling_asset_id": just_below["id"]}, fx.AGENT))
        assert clean["status"] == "ASSIGNED"

    def test_onboard_volume_counts_only_posted_tickets_of_a_fuelling_truck_order(self, api):
        """PRD §3.7: "The `onboard_volume_liters` of an asset is the sum of `net_liters` over the
        uplift tickets whose `status` is `POSTED`, whose parent order is currently `FUELING`, whose
        parent order's `delivery_mode` is `TRUCK`, and whose parent order names this asset."
        PRD §3.9: "Issuance flips every swept ticket from `POSTED` to `BILLED` and freezes its
        `billed_line_cents`, recomputing the invoice totals one final time in the same four steps;
        stamps `issued_by_user_id` from the acting identifier; and recomputes both of the account's
        exposure figures, where the uncollected-ticket term is replaced by the invoiced-invoice term,
        which additionally carries the admin fee and the rebate."

        Design: Corner/entities/onboard_volume_counts_only_posted_tickets_of_fueling_truck_orders
        """
        env = fx.setup_issued_invoice(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        truck_id = env["truck"]["id"]
        assert fx.read_uplift(env["uplift"]["id"])["status"] == "BILLED"
        assert fx.read_asset(truck_id)["onboard_volume_liters"] == pytest.approx(0.0, abs=0.005)

        # The second order is booked for a window on the 11th, and PRD §3.6 gates the start of
        # fuelling on the logical clock sitting inside that window, so the clock has to be moved
        # into it before the order is raised.
        fx.set_clock("2026-08-11T01:00:00Z")
        flight = fx.register_flight(env["account"]["id"], stand_code="A13",
                                    scheduled_departure_utc="2026-08-11T04:00:00Z")
        auth = fx.issue_authorization(env["account"]["id"], flight["id"],
                                      max_authorized_liters=10_000.0)
        order = fx.create_order(flight["id"], auth["id"], env["tank"]["id"],
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=10_000.0,
                                window_start_utc="2026-08-11T00:30:00Z",
                                window_end_utc="2026-08-11T02:00:00Z")
        fx.authorize_order(order["id"])
        fx.assign_order(order["id"], truck_id)
        started = fx.start_order(order["id"])
        fx.post_uplift(order["id"], started["version"], meter_start_liters=0.0,
                       meter_end_liters=10_000.0, temperature_c=15.0)

        assert fx.read_asset(truck_id)["onboard_volume_liters"] == \
            pytest.approx(10000.00, abs=0.005), \
            "the billed ticket of the completed order has already left the truck"


class TestFilterChangeCorners:
    def test_the_filter_change_record_is_an_immutable_audit_document(self, api):
        """PRD §3.7: "As an immutable audit document a filter change record carries no `updated_at`
        and no `version`."
        PRD §3.7: "The change record captures the pre-change state for audit: `liters_at_change` is
        the value of the asset's `liters_since_filter_change` immediately before it was reset, and
        `differential_pressure_before_kpa` is the value of the asset's `differential_pressure_kpa`
        immediately before it was overwritten."
        PRD §3.7: "When the differential pressure has reached 103.0 kilopascals the asset skips the
        advisory state and goes straight to `DOWN_FOR_FILTER`, regardless of what the other two legs
        say."

        Design: Corner/entities/filter_change_row_has_no_common_fields
        """
        env = fx.setup_fuel_farm()
        asset = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  differential_pressure_kpa=103.0)
        # A pressure that has reached 103.0 kPa skips the advisory state altogether, so this
        # asset is already `DOWN_FOR_FILTER` and needs no explicit status change to get there.
        assert fx.read_asset(asset["id"])["status"] == "DOWN_FOR_FILTER"

        # PRD §4: "Endpoints that create a new resource respond with HTTP 201".
        record = validate_success(api.create_filter_change(
            asset["id"], {"element_lot_number": "LOT-9001", "element_count": 6,
                          "post_change_differential_pressure_kpa": 10.0}, fx.INSPECTOR_A), 201)

        assert record["fueling_asset_id"] == asset["id"]
        assert record["liters_at_change"] == pytest.approx(0.0, abs=0.005)
        assert record["differential_pressure_before_kpa"] == pytest.approx(103.0, abs=0.005)
        assert "version" not in record
        assert "updated_at" not in record

        after = fx.read_asset(asset["id"])
        assert after["status"] == "IN_SERVICE"
        assert after["differential_pressure_kpa"] == pytest.approx(10.0, abs=0.005)

    def test_an_in_service_asset_does_not_accept_a_filter_change(self, api):
        """PRD §3.7: "Recording a filter change is a `QualityInspector` action, permitted when the
        asset's `status` is either `DOWN_FOR_FILTER` or `FILTER_DUE` and the farm is not `FROZEN`, and
        it is what returns the asset to `IN_SERVICE`."

        Design: Corner/entities/filter_change_on_an_in_service_asset
        """
        env = fx.setup_fuel_farm()
        asset = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  differential_pressure_kpa=10.0)
        assert fx.read_asset(asset["id"])["status"] == "IN_SERVICE"

        validate_error(api.create_filter_change(
            asset["id"], {"element_lot_number": "LOT-9002", "element_count": 6,
                          "post_change_differential_pressure_kpa": 9.0}, fx.INSPECTOR_A),
            ApiErrorId.ERR_INVALID_ASSET_STATE, 409)

        changes, _meta = validate_paginated(api.list_filter_changes(asset["id"], fx.INSPECTOR_A))
        assert changes == []
