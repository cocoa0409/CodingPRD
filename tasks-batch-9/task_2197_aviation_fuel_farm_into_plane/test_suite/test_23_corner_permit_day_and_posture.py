"""Corner behaviour of the permit-day throughput counter — which timestamp decides the day, where the
day boundary sits, and what a breach leaves behind — and of the three posture causes that only
restrict."""
import pytest

from test_helpers import (
    assert_same_instant,
    validate_success, validate_error, ApiErrorId,
    fixtures as fx, factories as F,
)

PARCEL = dict(delivery_mode="PIPELINE", supplier_name="Refinery One", temperature_c=15.0,
              certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)


def _parcel(gross, opening_gauge, closing_gauge):
    return dict(PARCEL, meter_ticket_gross_liters=gross,
                tank_opening_gauge_liters=opening_gauge,
                tank_closing_gauge_liters=closing_gauge)


def _tested_receipt(tank_id, **parcel):
    receipt = fx.record_receipt(tank_id, **parcel)
    sample = fx.draw_receipt_sample(receipt["id"])
    fx.post_results(sample["id"], fx.INSPECTOR_A)
    return receipt


class TestPermitDayThroughputCorners:
    def test_the_release_instant_and_not_the_recording_instant_picks_the_day(self, api):
        """PRD §3.1: "Issuing one requires a regulator-issued `permit_number` unique across all permits,
        an inclusive `valid_from_utc`, an exclusive `valid_until_utc`, and a `max_daily_throughput_liters`
        strictly greater than zero expressing the permitted net movement — released receipt volume plus
        posted uplift volume — for a single UTC day."
        PRD §3.3: "On success the receipt's `released_at_utc` is stamped from the logical clock and its
        `released_by_user_id` from the acting identifier; the receipt's net volume enters the tank ledger,
        which recomputes the tank's `book_volume_liters`, `reserved_volume_liters` and
        `available_volume_liters`; the farm's permit-day throughput counter is recomputed; and the farm's
        posture is recomputed, which may land on `RESTRICTED` the moment permit utilisation reaches the 90
        percent boundary."
        PRD §2.11: "**Permit throughput conservation**: a rejected parcel never touched the ledger, so
        rejecting a quarantined receipt leaves the farm's `active_permit_throughput_used_liters` exactly as
        it was — only receipts that reach `RELEASED` and uplift tickets that are `POSTED` or `BILLED` count
        toward the permit day."

        Design: Corner/calculations/released_at_utc_not_created_at_decides_the_day
        """
        env = fx.setup_farm_with_released_tank(
            clock="2026-08-10T23:50:00Z", opening_volume_liters=0.0, density_kg_per_m3=795.0,
            permit_overrides={"max_daily_throughput_liters": 400_000.0})
        farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]

        receipt = _tested_receipt(tank_id, **_parcel(10_100.0, 0.0, 10_000.0))
        assert receipt["net_volume_liters"] == pytest.approx(10000.00, abs=0.005)
        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(0.00, abs=0.005), "a merely recorded parcel counts against no day at all"

        fx.set_clock("2026-08-11T00:10:00Z")
        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(0.00, abs=0.005)

        released = fx.sign_verdict(receipt["id"], "RELEASE", fx.INSPECTOR_B)
        assert released["status"] == "RELEASED"
        assert_same_instant(released["released_at_utc"], "2026-08-11T00:10:00Z",
                            "released_at_utc")

        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(10000.00, abs=0.005), \
            "the 11th carries the movement; the parcel's creation on the 10th is irrelevant"
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(10000.00, abs=0.005)

    def test_the_permit_day_runs_from_midnight_inclusive_to_midnight_exclusive(self, api):
        """PRD §2.2: "A reconciliation period, a billing period, and the permit-day throughput window all
        follow the same convention."
        PRD §2.2: "Time windows in this domain are consistently **half-open** — start inclusive, end
        exclusive — with exactly one deliberate exception."
        PRD §3.6: "Posting debits the tank's book volume, raises the asset's `liters_since_filter_change`
        and recomputes its `element_life_pct`, recomputes the farm's permit-day throughput and posture,
        recomputes the account's accrual exposure, and raises the order's `version` by one."

        Design: Corner/calculations/day_window_is_half_open_at_midnight
        """
        env = fx.setup_truck_order(
            target_state="FUELING", clock="2026-08-11T00:00:00Z",
            requested_uplift_liters=20_000.0, max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000_000},
            flight_overrides={"scheduled_departure_utc": "2026-08-12T00:00:00Z"},
            order_overrides={"window_start_utc": "2026-08-11T00:00:00Z",
                             "window_end_utc": "2026-08-12T00:00:00Z"})
        farm_id, order_id = env["farm"]["id"], env["order"]["id"]

        fx.post_uplift(order_id, meter_start_liters=0.0, meter_end_liters=10_000.0,
                       temperature_c=15.0)
        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(10000.00, abs=0.005), "a ticket at exactly 00:00:00Z belongs to that day"

        fx.set_clock("2026-08-11T23:59:59Z")
        fx.post_uplift(order_id, meter_start_liters=10_000.0, meter_end_liters=20_000.0,
                       temperature_c=15.0)
        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(20000.00, abs=0.005), "the last second of the day is still inside it"

        fx.complete_order(order_id)
        fx.set_clock("2026-08-12T00:00:00Z")
        rolled = fx.read_farm(farm_id)
        assert rolled["active_permit_throughput_used_liters"] == pytest.approx(0.00, abs=0.005), \
            "midnight is exclusive of the day that just ended, so the counter starts again"

        account_id, tank_id = env["account"]["id"], env["tank"]["id"]
        flight = fx.register_flight(account_id, stand_code="D04",
                                    scheduled_departure_utc="2026-08-12T04:00:00Z")
        auth = fx.issue_authorization(account_id, flight["id"],
                                      max_authorized_liters=5_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=5_000.0,
                                window_start_utc="2026-08-12T00:00:00Z",
                                window_end_utc="2026-08-12T01:00:00Z")
        fx.authorize_order(order["id"])
        fx.assign_order(order["id"], env["truck"]["id"])
        fx.start_order(order["id"])
        fx.post_uplift(order["id"], meter_start_liters=20_000.0, meter_end_liters=25_000.0,
                       temperature_c=15.0)

        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(5000.00, abs=0.005), \
            "the new day carries its own 5,000.00 and none of the previous day's 20,000.00"

    def test_a_cap_breach_leaves_the_ledger_and_the_parcel_exactly_where_they_were(self, api):
        """PRD §3.3: "The farm's `active_permit_throughput_used_liters` plus the receipt's net volume must
        not exceed the governing permit's `max_daily_throughput_liters`, or the release is refused with
        `ERR_PERMIT_THROUGHPUT_EXCEEDED`."
        PRD §2.10: "**Fiscal and ledger checks, evaluated last.** Safe fill
        (`ERR_SAFE_FILL_EXCEEDED`) on the receipt verdict; then permit daily throughput
        (`ERR_PERMIT_THROUGHPUT_EXCEEDED`) on the receipt verdict and on uplift posting; then tank volume
        sufficiency (`ERR_INSUFFICIENT_TANK_VOLUME`) on order authorization and uplift posting; then the
        credit check (`ERR_CREDIT_LIMIT_EXCEEDED`) on order authorization; then the authorization ceiling
        (`ERR_UPLIFT_EXCEEDS_AUTHORIZATION`) on uplift posting and order completion; and finally the
        payment bounds check (`ERR_PAYMENT_EXCEEDS_BALANCE`) on recording a payment."
        PRD §3.3: "The `UNDER_TEST → RELEASED` branch is the only path by which product enters the
        ledger, and it carries the heaviest set of preconditions."

        Design: Corner/calculations/throughput_cap_breach_is_evaluated_before_the_ledger_moves
        """
        env = fx.setup_farm_with_released_tank(
            opening_volume_liters=0.0, density_kg_per_m3=795.0,
            permit_overrides={"max_daily_throughput_liters": 20_000.0})
        farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]

        first = fx.make_released_receipt(tank_id, **_parcel(10_100.0, 0.0, 10_000.0))
        assert first["status"] == "RELEASED"
        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(10000.00, abs=0.005)

        second = _tested_receipt(tank_id, **_parcel(12_100.0, 10_000.0, 22_000.0))
        assert second["net_volume_liters"] == pytest.approx(12000.00, abs=0.005)

        validate_error(api.sign_receipt_verdict(second["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_B),
                       ApiErrorId.ERR_PERMIT_THROUGHPUT_EXCEEDED, 409)

        held = validate_success(api.get_fuel_receipt(second["id"], fx.OPERATOR))
        assert held["status"] == "UNDER_TEST", "the refused parcel keeps its place in the chain"
        assert held["released_at_utc"] is None
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(10000.00, abs=0.005), \
            "the ledger never moved"
        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(10000.00, abs=0.005)

        fx.set_clock("2026-08-11T06:00:00Z")
        released = fx.sign_verdict(second["id"], "RELEASE", fx.INSPECTOR_B)

        assert released["status"] == "RELEASED", "a fresh day has a fresh 20,000.00 of headroom"
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(22000.00, abs=0.005)
        assert fx.read_farm(farm_id)["active_permit_throughput_used_liters"] == \
            pytest.approx(12000.00, abs=0.005)


class TestFarmPostureRestrictedCauses:
    def test_a_farm_with_no_permit_at_all_is_frozen_from_the_first_read(self, api):
        """PRD §3.1: "A newly registered farm's `posture` is `FROZEN`, because a farm with no active
        permit covering the logical clock is frozen by definition, and its
        `active_permit_throughput_used_liters`, `in_service_asset_count` and `open_spill_count` all start
        at zero."
        PRD §2.7: "The permit is considered satisfactory when it exists, its `status` is `ACTIVE`, and
        the logical clock is at or after its `valid_from_utc` and strictly before its `valid_until_utc`."
        PRD §2.7: "Operations that a `FROZEN` posture blocks are rejected with `ERR_FARM_FROZEN`, and
        when the block is specifically the absence of a satisfactory permit the rejection is
        `ERR_PERMIT_NOT_ACTIVE`."

        Design: Corner/calculations/no_permit_at_all_freezes_a_brand_new_farm
        """
        fx.set_clock()
        farm = fx.create_farm()

        assert farm["posture"] == "FROZEN"
        assert farm["active_permit_throughput_used_liters"] == pytest.approx(0.00, abs=0.005)
        assert farm["in_service_asset_count"] == 0
        assert farm["open_spill_count"] == 0
        assert fx.read_farm(farm["id"])["posture"] == "FROZEN", \
            "nothing about a later read thaws a farm that has no permit"

        tank = fx.register_tank(farm["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=0.0)
        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank["id"], **_parcel(10_100.0, 0.0, 10_000.0)),
            fx.OPERATOR), ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)

    def test_a_reported_spill_restricts_the_farm_and_leaves_the_work_standing(self, api):
        """PRD §2.7: "Third, the farm is **restricted** if any of four conditions holds: at least one
        storage tank at the farm has `quality_status` `QUARANTINED`; at least one spill incident at the
        farm has `status` `REPORTED`; the farm's `active_permit_throughput_used_liters` has reached or
        exceeded 90 percent of the governing permit's `max_daily_throughput_liters`; or the farm's
        `in_service_asset_count` is zero."
        PRD §2.7: "A `RESTRICTED` farm is narrower: it blocks the assignment of an asset to an order and
        the start of fuelling for those orders that draw on a tank whose `quality_status` is
        `QUARANTINED`, while leaving orders on clean tanks to proceed normally."
        PRD §2.7: "Alongside the posture the same pass refreshes two counters on the farm:
        `open_spill_count`, the number of spill incidents at the farm whose `status` is `REPORTED` or
        `ESCALATED`, and `in_service_asset_count`, the number of fuelling assets at the farm whose
        `status` is `IN_SERVICE`."

        Design: Corner/calculations/reported_spill_restricts_but_does_not_freeze
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED",
                                   account_overrides={"credit_limit_cents": 100_000_000_000})
        farm_id, order_id = env["farm"]["id"], env["order"]["id"]
        assert fx.read_farm(farm_id)["posture"] == "OPEN"

        spill = fx.report_spill(farm_id, spilled_volume_liters=5.0, surface="APRON")
        assert spill["status"] == "REPORTED"

        farm = fx.read_farm(farm_id)
        assert farm["posture"] == "RESTRICTED", "a reported spill restricts; only escalation freezes"
        assert farm["open_spill_count"] == 1
        assert farm["in_service_asset_count"] == 1

        assert fx.read_order(order_id)["status"] == "AUTHORIZED", \
            "the restricted cascade cancels nothing"
        assert fx.read_authorization(env["auth"]["id"])["status"] == "ISSUED"

        fx.assign_order(order_id, env["truck"]["id"])
        started = fx.start_order(order_id)
        assert started["status"] == "FUELING", "a restricted farm still fuels from a clean tank"

    def test_putting_the_last_truck_down_restricts_the_farm_until_it_returns(self, api):
        """PRD §2.7: "Third, the farm is **restricted** if any of four conditions holds: at least one
        storage tank at the farm has `quality_status` `QUARANTINED`; at least one spill incident at the
        farm has `status` `REPORTED`; the farm's `active_permit_throughput_used_liters` has reached or
        exceeded 90 percent of the governing permit's `max_daily_throughput_liters`; or the farm's
        `in_service_asset_count` is zero."
        PRD §3.7: "Every one of these moves recomputes the farm's in-service asset count and posture and
        raises the asset's and farm's `version` by one each."
        PRD §3.7: "Returning `DOWN_MAINTENANCE → IN_SERVICE` is reserved to a `ConsortiumAdmin` and
        requires that the `reliability_score` has recovered to at least 60, that `element_life_pct` is
        strictly below 100.0, and that the farm is not `FROZEN`."

        Design: Corner/calculations/last_in_service_asset_going_down_restricts_the_farm
        """
        env = fx.setup_fuel_farm()
        farm_id = env["farm"]["id"]
        truck = fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        opening = fx.read_farm(farm_id)
        assert opening["in_service_asset_count"] == 1
        assert opening["posture"] == "OPEN"

        down = validate_success(api.change_asset_status(
            truck["id"], {"to_status": "DOWN_MAINTENANCE"}, fx.OPERATOR))
        assert down["status"] == "DOWN_MAINTENANCE"
        assert down["reliability_score"] == 100, "nothing here touches reliability"

        restricted = fx.read_farm(farm_id)
        assert restricted["in_service_asset_count"] == 0
        assert restricted["posture"] == "RESTRICTED", "an empty ramp restricts rather than freezes"

        back = validate_success(api.change_asset_status(
            truck["id"], {"to_status": "IN_SERVICE"}, fx.ADMIN))
        assert back["status"] == "IN_SERVICE"

        healed = fx.read_farm(farm_id)
        assert healed["in_service_asset_count"] == 1
        assert healed["posture"] == "OPEN", "the same recompute that counted it out counts it back in"
