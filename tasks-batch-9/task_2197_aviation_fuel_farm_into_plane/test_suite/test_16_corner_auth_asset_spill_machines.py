"""Corner behaviour of three more machines: the authorization's three absorbing exits, the asset
cycle that has no terminal state at all, and the spill's two roads into containment."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures as fx,
)


class TestFuelAuthorizationMachineCorners:
    def test_a_redeemed_code_still_matches_but_no_longer_authorises(self, api):
        """PRD §3.6: "That quoted code must equal the authorization's minted `authorization_code`
        character for character, and any discrepancy is rejected with `ERR_AUTH_CODE_MISMATCH` — checked
        both when the order is raised and again when it is authorised."
        PRD §3.6: "The quoted authorization must be `ISSUED` and the logical clock must be strictly
        before its `expires_at_utc`, or the request fails with `ERR_AUTHORIZATION_NOT_REDEEMABLE`."
        PRD §3.5: "It is `REDEEMED` by the system when an order completes against it, subject to that
        order's `posted_net_liters` not exceeding the authorization's `max_authorized_liters`."

        Design: Corner/state_machines/redeemed_authorization_cannot_be_reused_by_a_second_order
        """
        env = fx.setup_completed_order(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        auth = fx.read_authorization(env["auth"]["id"])
        assert auth["status"] == "REDEEMED"

        second = fx.create_order(env["flight"]["id"], auth["id"], env["tank"]["id"],
                                 auth["authorization_code"], delivery_mode="TRUCK",
                                 requested_uplift_liters=5_000.0)
        assert second["status"] == "REQUESTED", "the quoted code matched character for character"

        validate_error(api.authorize_order(second["id"], fx.AGENT),
                       ApiErrorId.ERR_AUTHORIZATION_NOT_REDEEMABLE, 409)

        assert fx.read_order(second["id"])["status"] == "REQUESTED"
        assert fx.read_tank(env["tank"]["id"])["reserved_volume_liters"] == \
            pytest.approx(0.00, abs=0.005)

    def test_neither_a_voided_nor_an_expired_authorization_can_be_voided_again(self, api):
        """PRD §3.5: "An authorization leaves `ISSUED` by one of three doors, all terminal."
        PRD §3.5: "It becomes `EXPIRED` by the system once the logical clock has reached or passed its
        `expires_at_utc`; this is evaluated lazily whenever the authorization is read or referenced
        after a clock advance, and an expired authorization can no longer authorise an order."
        PRD §2.10: "the terminal-state guard (`ERR_ALREADY_TERMINAL`), which applies to every
        state-transition endpoint and fires when the target row already sits in a terminal state for its
        machine: a fuel receipt in `RELEASED` or `REJECTED`, a fuelling order in `COMPLETED`,
        `CANCELLED` or `ABORTED`, a fuel authorization in `REDEEMED`, `VOIDED` or `EXPIRED`, a spill
        incident in `CLOSED`, an invoice in `PAID` or `VOIDED`, or a reconciliation run in `POSTED`."

        Design: Corner/state_machines/all_three_exits_are_terminal
        """
        fx.set_clock()
        account = fx.open_account()
        early = fx.register_flight(account["id"], stand_code="A12",
                                   scheduled_departure_utc="2026-08-10T08:00:00Z")
        later = fx.register_flight(account["id"], stand_code="A13",
                                   scheduled_departure_utc="2026-08-10T20:00:00Z")
        voided_auth = fx.issue_authorization(account["id"], early["id"],
                                             max_authorized_liters=10_000.0)
        expiring_auth = fx.issue_authorization(account["id"], later["id"],
                                               max_authorized_liters=10_000.0)

        validate_success(api.void_fuel_authorization(voided_auth["id"], fx.BILLING))
        validate_error(api.void_fuel_authorization(voided_auth["id"], fx.BILLING),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)

        fx.set_clock("2026-08-10T22:00:00Z")
        assert fx.read_authorization(expiring_auth["id"])["status"] == "EXPIRED"

        validate_error(api.void_fuel_authorization(expiring_auth["id"], fx.BILLING),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        assert fx.read_authorization(expiring_auth["id"])["voided_reason"] is None


class TestFuelingAssetMachineCorners:
    def test_the_whole_asset_cycle_runs_without_a_terminal_state(self, api):
        """PRD §3.7: "Reaching 100.0 percent element life moves the asset `IN_SERVICE → FILTER_DUE`
        automatically — the comparison is inclusive, so exactly 100.0 triggers it — provided the
        differential pressure leg has not itself passed the 103.0 kilopascal threshold."
        PRD §3.7: "Returning `DOWN_MAINTENANCE → IN_SERVICE` is reserved to a `ConsortiumAdmin` and
        requires that the `reliability_score` has recovered to at least 60, that `element_life_pct` is
        strictly below 100.0, and that the farm is not `FROZEN`."
        PRD §3.7: "Finally the farm's in-service asset count and posture are recomputed and the asset's
        and farm's `version` each rise by one, closing the cycle
        `IN_SERVICE → FILTER_DUE → DOWN_FOR_FILTER → IN_SERVICE`."

        Design: Corner/state_machines/no_terminal_state_means_every_asset_is_recoverable
        """
        env = fx.setup_fuel_farm(
            clock="2025-08-10T06:00:00Z",
            permit_overrides={"valid_from_utc": "2025-01-01T00:00:00Z",
                              "valid_until_utc": "2028-01-01T00:00:00Z"})
        asset = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  differential_pressure_kpa=10.0)
        asset_id = asset["id"]
        assert asset["status"] == "IN_SERVICE"

        parked = validate_success(api.change_asset_status(
            asset_id, {"to_status": "DOWN_MAINTENANCE"}, fx.OPERATOR))
        assert parked["status"] == "DOWN_MAINTENANCE"
        recovered = validate_success(api.change_asset_status(
            asset_id, {"to_status": "IN_SERVICE"}, fx.ADMIN))
        assert recovered["status"] == "IN_SERVICE"

        fx.set_clock("2026-08-10T06:00:00Z")
        aged = fx.read_asset(asset_id)
        assert aged["element_life_pct"] == pytest.approx(100.0, abs=0.00005)
        assert aged["status"] == "FILTER_DUE", "365 whole days is exactly one nominal element life"

        pulled = validate_success(api.change_asset_status(
            asset_id, {"to_status": "DOWN_FOR_FILTER"}, fx.OPERATOR))
        assert pulled["status"] == "DOWN_FOR_FILTER"

        # PRD §4: "Endpoints that create a new resource respond with HTTP 201".
        validate_success(api.create_filter_change(
            asset_id, {"element_lot_number": "LOT-7001", "element_count": 6,
                       "post_change_differential_pressure_kpa": 10.0}, fx.INSPECTOR_A), 201)

        closed = fx.read_asset(asset_id)
        assert closed["status"] == "IN_SERVICE", "no hop in the cycle is one-way"
        assert closed["element_life_pct"] == pytest.approx(9.7087, abs=0.00005)
        assert closed["reliability_score"] == 100

    def test_filter_due_finishes_the_job_in_hand_but_takes_no_new_one(self, api):
        """PRD §3.7: "`FILTER_DUE` blocks any further assignment of that asset to an order, recomputes
        the farm's `in_service_asset_count`, and recomputes posture, which becomes `RESTRICTED` if the
        count has fallen to zero."
        PRD §3.7: "Element life is recomputed whenever a ticket is posted, whenever an order completes,
        whenever a filter change is recorded, and whenever the logical clock advances."
        PRD §3.6: "Completion drives the authorization `ISSUED → REDEEMED`; releases the reservation by
        subtracting `requested_uplift_liters` from the tank's `reserved_volume_liters` and recomputing
        `available_volume_liters`, the posted tickets having already debited book volume; ends the
        order's pit occupancy as the order leaves the assigned-or-fuelling set; leaves a truck asset
        `IN_SERVICE` unless its element life has reached 100.0, in which case the asset moves
        `IN_SERVICE → FILTER_DUE`; and recomputes the account's accrual exposure, where the reservation
        term drops out and the uncollected-ticket term enters."

        Design: Corner/state_machines/filter_due_cannot_be_assigned_but_can_finish_its_order
        """
        env = fx.setup_farm_with_released_tank(
            clock="2025-08-10T06:00:00Z", opening_volume_liters=1_000_000.0,
            permit_overrides={"valid_from_utc": "2025-01-01T00:00:00Z",
                              "valid_until_utc": "2028-01-01T00:00:00Z",
                              "max_daily_throughput_liters": 400000.0})
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  differential_pressure_kpa=10.0)
        truck_id, tank_id = truck["id"], env["tank"]["id"]

        fx.set_clock("2026-08-10T05:00:00Z")
        assert fx.read_asset(truck_id)["status"] == "IN_SERVICE"

        account = fx.open_account(base_price_cents_per_liter=62.00,
                                  credit_limit_cents=100_000_000)
        flight = fx.register_flight(account["id"], stand_code="C01",
                                    scheduled_departure_utc="2026-08-10T08:00:00Z")
        auth = fx.issue_authorization(account["id"], flight["id"],
                                      max_authorized_liters=20_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0,
                                window_start_utc="2026-08-10T04:00:00Z",
                                window_end_utc="2026-08-10T07:30:00Z")
        fx.authorize_order(order["id"])
        fx.assign_order(order["id"], truck_id)
        fx.start_order(order["id"])
        fx.post_uplift(order["id"], meter_start_liters=0.0, meter_end_liters=20_000.0,
                       temperature_c=15.0)

        fx.set_clock("2026-08-10T07:00:00Z")
        assert fx.read_asset(truck_id)["status"] == "FILTER_DUE"
        assert fx.read_order(order["id"])["status"] == "FUELING"

        completed = validate_success(api.complete_order(order["id"], fx.AGENT))
        assert completed["status"] == "COMPLETED"
        assert fx.read_asset(truck_id)["status"] == "FILTER_DUE"

        next_flight = fx.register_flight(account["id"], stand_code="C02",
                                         scheduled_departure_utc="2026-08-10T12:00:00Z")
        next_auth = fx.issue_authorization(account["id"], next_flight["id"],
                                          max_authorized_liters=10_000.0)
        next_order = fx.create_order(next_flight["id"], next_auth["id"], tank_id,
                                     next_auth["authorization_code"], delivery_mode="TRUCK",
                                     requested_uplift_liters=10_000.0,
                                     window_start_utc="2026-08-10T09:00:00Z",
                                     window_end_utc="2026-08-10T10:00:00Z")
        fx.authorize_order(next_order["id"])

        validate_error(api.assign_order(next_order["id"], {"fueling_asset_id": truck_id},
                                        fx.AGENT),
                       ApiErrorId.ERR_ASSET_NOT_SERVICEABLE, 409)
        assert fx.read_order(next_order["id"])["status"] == "AUTHORIZED"


class TestSpillIncidentMachineCorners:
    def test_containment_arrives_from_both_predecessors_with_different_footprints(self, api):
        """PRD §3.8: "Escalation and containment are sibling branches out of `REPORTED` with genuinely
        disjoint effects, and which branch is lawful depends on the volume."
        PRD §3.8: "An escalated incident reaches containment by the same action from a different
        origin: `ESCALATED → CONTAINED` requires only a `contained_volume_liters` no greater than the
        spilled volume, applies the same reliability penalty, and recomputes the open spill count and
        posture."
        PRD §3.8: "Reporting alone recomputes the farm's `open_spill_count` and posture, and an open
        incident makes the farm `RESTRICTED` — never `FROZEN`. Only escalation freezes a farm."

        Design: Corner/state_machines/contain_reachable_from_two_predecessors
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 20.0})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        farm_id = env["farm"]["id"]

        minor = fx.report_spill(farm_id, spilled_volume_liters=15.0, surface="APRON")
        assert fx.read_farm(farm_id)["posture"] == "RESTRICTED"
        contained_minor = fx.contain_spill(minor["id"], 15.0)
        assert contained_minor["status"] == "CONTAINED"
        assert contained_minor["regulator_reference"] is None
        assert fx.read_farm(farm_id)["posture"] == "OPEN", \
            "the unescalated road needs no regulator and leaves no residue"

        major = fx.report_spill(farm_id, spilled_volume_liters=25.0, surface="APRON")
        fx.escalate_spill(major["id"], regulator_reference="REG-2026-0021")
        assert fx.read_farm(farm_id)["posture"] == "FROZEN"

        contained_major = fx.contain_spill(major["id"], 25.0)
        assert contained_major["status"] == "CONTAINED"
        assert contained_major["regulator_reference"] == "REG-2026-0021"
        assert fx.read_farm(farm_id)["posture"] == "RESTRICTED", \
            "the freeze cascade left the farm without an in-service asset"

    def test_a_contained_incident_can_never_be_escalated_back(self, api):
        """PRD §3.8: "**Escalation, `REPORTED → ESCALATED`,** is lawful only when the spilled volume has
        reached the governing permit's `max_reportable_spill_liters` — the comparison is inclusive, so a
        spill of exactly the reportable volume must be escalated — and only when a non-empty
        `regulator_reference` is supplied."
        PRD §2.10: "`ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close"

        Design: Corner/state_machines/escalate_after_containment
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 20.0})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        spill = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0, surface="APRON")
        fx.escalate_spill(spill["id"], regulator_reference="REG-2026-0031")
        fx.contain_spill(spill["id"], 25.0)

        validate_error(api.escalate_spill(spill["id"],
                                          {"regulator_reference": "REG-2026-0032"}, fx.ENVIRO),
                       ApiErrorId.ERR_INVALID_SPILL_STATE, 409)

        after = fx.read_spill(spill["id"])
        assert after["status"] == "CONTAINED"
        assert after["regulator_reference"] == "REG-2026-0031"
        assert fx.read_farm(env["farm"]["id"])["posture"] != "FROZEN", \
            "cleanup cannot be undone by a second escalation"

    def test_closing_the_file_does_not_give_the_asset_its_points_back(self, api):
        """PRD §3.8: "`CONTAINED → REMEDIATED` requires only that the incident is `CONTAINED` and raises
        the incident's `version` by one; it touches nothing else."
        PRD §3.8: "Closure recomputes the farm's posture and raises the incident's and farm's `version`
        by one each. `CLOSED` is terminal."
        PRD §3.7: "The product of severity and multiplier is capped at 40 again **after** the
        multiplication, and that capped figure is the penalty. The new score is the previous score less
        the penalty, floored at zero."

        Design: Corner/state_machines/closed_incident_still_carries_its_reliability_penalty
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 40.0})
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        spill = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0,
                                surface="APRON", fueling_asset_id=truck["id"])
        fx.contain_spill(spill["id"], 25.0)
        assert fx.read_asset(truck["id"])["reliability_score"] == 85

        remediated = validate_success(api.remediate_spill(spill["id"], fx.ENVIRO))
        assert remediated["status"] == "REMEDIATED"
        closed = validate_success(api.close_spill(spill["id"], fx.ENVIRO))
        assert closed["status"] == "CLOSED"

        asset = fx.read_asset(truck["id"])
        assert asset["reliability_score"] == 85, "closing is paperwork, not repair"
        assert asset["status"] == "IN_SERVICE"
        farm = fx.read_farm(env["farm"]["id"])
        assert farm["open_spill_count"] == 0
        assert farm["posture"] == "OPEN"
