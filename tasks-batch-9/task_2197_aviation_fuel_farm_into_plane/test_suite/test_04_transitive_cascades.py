"""Depth-three cascades: a receipt quarantine verdict walking tank -> orders -> tickets, and a
spill escalation freezing the farm and sweeping every order, asset and authorization."""
import pytest

from test_helpers import validate_success, fixtures as fx

ORDER_A_WINDOW = ("2026-08-10T08:00:00Z", "2026-08-10T08:30:00Z")
ORDER_B_WINDOW = ("2026-08-10T06:00:00Z", "2026-08-10T07:30:00Z")


def _two_order_farm(assign_order_a):
    """One tank, two trucks, one account: order A at 10,000 L and order B fuelling 20,000 L."""
    env = fx.setup_farm_with_released_tank(
        opening_volume_liters=1_000_000.0,
        permit_overrides={"max_daily_throughput_liters": 400000.0,
                          "max_reportable_spill_liters": 20.0})
    farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]
    env["truck1"] = fx.register_truck(farm_id, tank_capacity_liters=40_000.0,
                                      turnaround_buffer_minutes=15,
                                      differential_pressure_kpa=10.0)
    env["truck2"] = fx.register_truck(farm_id, tank_capacity_liters=40_000.0,
                                      turnaround_buffer_minutes=15,
                                      differential_pressure_kpa=10.0)
    env["account"] = fx.open_account(base_price_cents_per_liter=62.00,
                                     credit_limit_cents=100_000_000, tax_exempt=False)
    account_id = env["account"]["id"]

    env["flight_a"] = fx.register_flight(account_id, stand_code="A12",
                                         scheduled_departure_utc="2026-08-10T09:00:00Z")
    env["flight_b"] = fx.register_flight(account_id, stand_code="A13",
                                         scheduled_departure_utc="2026-08-10T08:00:00Z")
    env["auth_a"] = fx.issue_authorization(account_id, env["flight_a"]["id"],
                                           max_authorized_liters=10_000.0)
    env["auth_b"] = fx.issue_authorization(account_id, env["flight_b"]["id"],
                                           max_authorized_liters=20_000.0)

    env["order_a"] = fx.create_order(
        env["flight_a"]["id"], env["auth_a"]["id"], tank_id,
        env["auth_a"]["authorization_code"], delivery_mode="TRUCK",
        requested_uplift_liters=10_000.0,
        window_start_utc=ORDER_A_WINDOW[0], window_end_utc=ORDER_A_WINDOW[1])
    fx.authorize_order(env["order_a"]["id"])
    if assign_order_a:
        fx.assign_order(env["order_a"]["id"], env["truck2"]["id"])

    env["order_b"] = fx.create_order(
        env["flight_b"]["id"], env["auth_b"]["id"], tank_id,
        env["auth_b"]["authorization_code"], delivery_mode="TRUCK",
        requested_uplift_liters=20_000.0,
        window_start_utc=ORDER_B_WINDOW[0], window_end_utc=ORDER_B_WINDOW[1])
    fx.authorize_order(env["order_b"]["id"])
    fx.assign_order(env["order_b"]["id"], env["truck1"]["id"])
    started = fx.start_order(env["order_b"]["id"])
    env["uplift_b"] = fx.post_uplift(env["order_b"]["id"], started["version"],
                                     meter_start_liters=0.0, meter_end_liters=20_000.0,
                                     temperature_c=15.0)
    return env


FAIL_METRICS = {"water_reaction_rating": 3, "particulate_mg_per_l": 2.5,
                "conductivity_ps_per_m": 40.0, "flash_point_c": 41.0}


class TestReceiptQuarantineCascade:
    @staticmethod
    def _tested_failing_receipt(env):
        receipt, _sample = fx.make_tested_receipt(
            env["tank"]["id"], metrics=dict(FAIL_METRICS),
            delivery_mode="TRUCK", supplier_name="Refinery One",
            meter_ticket_gross_liters=30120.0, tank_opening_gauge_liters=100.0,
            tank_closing_gauge_liters=30100.0, temperature_c=25.0,
            certificate_density_kg_per_m3=795.0, measured_water_liters=200.0)
        return receipt

    def test_quarantine_verdict_moves_the_tank_and_then_the_orders_on_it(self, api):
        """PRD §3.3: "**Hop one** sets the destination tank's `quality_status` to `QUARANTINED`,
        which is the tank's own quality-dimension move from either `RELEASED` or `ON_TEST` into
        `QUARANTINED`."
        PRD §3.3: "**Hop two**, caused by hop one, reaches every fuelling order drawing on that
        tank: each order in `ASSIGNED` is driven `ASSIGNED → AUTHORIZED`, releasing its
        `fueling_asset_id` and `hydrant_pit_id` and raising its `unassign_count` by one, and each
        order in `FUELING` is driven `FUELING → ABORTED` with `abort_reason` set to `QUALITY_HOLD`."
        PRD §2.11: "Cascades run to completion within the request that triggered them; there is no
        deferred or eventual settlement."

        Design: Difficulty/transitive_cascade/receipt_quarantine_verdict_depth3_quality_cascade
        """
        env = _two_order_farm(assign_order_a=True)
        receipt = self._tested_failing_receipt(env)

        before_tank = fx.read_tank(env["tank"]["id"])
        assert before_tank["book_volume_liters"] == pytest.approx(980000.00, abs=0.005)
        assert fx.read_account(env["account"]["id"])["accrual_exposure_cents"] == 3402893

        signed = fx.sign_verdict(receipt["id"], "QUARANTINE", fx.INSPECTOR_B)
        assert signed["status"] == "QUARANTINED"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["quality_status"] == "QUARANTINED"
        assert tank["service_status"] == "IN_SERVICE", \
            "the quality cascade never touches the mechanical dimension"

        order_a = fx.read_order(env["order_a"]["id"])
        assert order_a["status"] == "AUTHORIZED"
        assert order_a["unassign_count"] == 1
        assert order_a["fueling_asset_id"] is None

        order_b = fx.read_order(env["order_b"]["id"])
        assert order_b["status"] == "ABORTED"
        assert order_b["abort_reason"] == "QUALITY_HOLD"

    def test_third_hop_voids_the_ticket_credits_the_ledger_and_drops_exposure(self, api):
        """PRD §3.3: "**Hop three**, caused by hop two, settles the consequences: each unassigned or
        aborted order's hydrant pit occupancy ends; every `POSTED` uplift ticket on an aborted order
        becomes `VOIDED` with `voided_reason` `ORDER_ABORTED` and its `net_liters` are credited back
        to the tank's `book_volume_liters`; each affected fuel authorization is driven to `VOIDED`;
        and the farm's posture is recomputed to `RESTRICTED`."
        PRD §3.4: "The `available_volume_liters` is the book volume less the reserved volume less the
        farm's `unpumpable_bottom_liters`, rounded half up to two decimals and then floored at 0.0 so
        it can never go negative."
        PRD §3.6: "for truck delivery the asset's `onboard_volume_liters` recomputes to 0.0 as the
        voided tickets leave the posted set, so the sum of tank book volume and on-board volume
        returns to exactly its pre-fuelling value"

        Design: Difficulty/transitive_cascade/receipt_quarantine_verdict_depth3_quality_cascade
        """
        env = _two_order_farm(assign_order_a=True)
        receipt = self._tested_failing_receipt(env)
        fx.sign_verdict(receipt["id"], "QUARANTINE", fx.INSPECTOR_B)

        uplift = fx.read_uplift(env["uplift_b"]["id"])
        assert uplift["status"] == "VOIDED"
        assert uplift["voided_reason"] == "ORDER_ABORTED"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005), \
            "the voided ticket's net liters are credited back to the ledger"
        assert tank["reserved_volume_liters"] == pytest.approx(10000.00, abs=0.005), \
            "order A survives as AUTHORIZED and keeps its reservation"
        assert tank["available_volume_liters"] == pytest.approx(989500.00, abs=0.005)

        assert fx.read_authorization(env["auth_b"]["id"])["status"] == "VOIDED"
        assert fx.read_authorization(env["auth_b"]["id"])["voided_reason"] == "ORDER_CANCELLED"
        assert fx.read_authorization(env["auth_a"]["id"])["status"] == "ISSUED"

        assert fx.read_asset(env["truck1"]["id"])["onboard_volume_liters"] == \
            pytest.approx(0.0, abs=0.005)

        account = fx.read_account(env["account"]["id"])
        assert account["accrual_exposure_cents"] == 656500, \
            "only order A's reservation remains on the accrual basis"
        assert account["invoiced_exposure_cents"] == 0
        assert fx.read_farm(env["farm"]["id"])["posture"] == "RESTRICTED"


class TestSpillEscalationCascade:
    @staticmethod
    def _reported_spill(env):
        spill = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0,
                                surface="APRON", fueling_asset_id=env["truck1"]["id"])
        assert spill["status"] == "REPORTED"
        return spill

    def test_escalation_freezes_the_farm_then_sweeps_orders_and_assets(self, api):
        """PRD §3.8: "Reporting alone recomputes the farm's `open_spill_count` and posture, and an
        open incident makes the farm `RESTRICTED` — never `FROZEN`. Only escalation freezes a farm."
        PRD §3.8: "**Hop one** recomputes the farm's posture, which becomes `FROZEN` because an
        escalated incident now exists at the farm."
        PRD §3.8: "**Hop two**, caused by hop one, sweeps the farm: every fuelling order at the farm
        in `AUTHORIZED` is driven `AUTHORIZED → CANCELLED`, every order in `FUELING` is driven
        `FUELING → ABORTED` with `abort_reason` `SPILL`, and every fuelling asset at the farm whose
        `status` is `IN_SERVICE` or `FILTER_DUE` is driven to `DOWN_MAINTENANCE`."

        Design: Difficulty/transitive_cascade/spill_escalation_depth3_environmental_cascade
        """
        env = _two_order_farm(assign_order_a=False)
        spill = self._reported_spill(env)

        assert fx.read_farm(env["farm"]["id"])["posture"] == "RESTRICTED"
        before = fx.read_tank(env["tank"]["id"])
        assert before["book_volume_liters"] == pytest.approx(980000.00, abs=0.005)
        assert before["reserved_volume_liters"] == pytest.approx(30000.00, abs=0.005)

        escalated = fx.escalate_spill(spill["id"], "EPA-2026-08-10-001")
        assert escalated["status"] == "ESCALATED"

        farm = fx.read_farm(env["farm"]["id"])
        assert farm["posture"] == "FROZEN"
        assert farm["open_spill_count"] == 1
        assert farm["in_service_asset_count"] == 0

        assert fx.read_order(env["order_a"]["id"])["status"] == "CANCELLED"
        order_b = fx.read_order(env["order_b"]["id"])
        assert order_b["status"] == "ABORTED"
        assert order_b["abort_reason"] == "SPILL"

        assert fx.read_asset(env["truck1"]["id"])["status"] == "DOWN_MAINTENANCE"
        assert fx.read_asset(env["truck2"]["id"])["status"] == "DOWN_MAINTENANCE", \
            "the sweep downs every in-service asset at the farm, attributed or not"

    def test_freeze_cascade_voids_authorizations_with_the_farm_frozen_reason(self, api):
        """PRD §3.8: "**Hop three**, caused by hop two, settles each affected order: its
        authorization is driven `ISSUED → VOIDED` with `voided_reason` `FARM_FROZEN`, its tank
        reservation is released, and the owning account's `accrual_exposure_cents` is recomputed;
        aborted orders additionally void their `POSTED` uplift tickets and credit those tickets'
        `net_liters` back to the source tank's `book_volume_liters`."
        PRD §3.7: "Incidents are applied in `reported_at_utc` ascending order, with ties broken by
        `created_at` ascending, and only incidents that have actually reached `CONTAINED` are applied
        — an incident still in `REPORTED` or `ESCALATED` has had no effect on the score yet."

        Design: Difficulty/transitive_cascade/spill_escalation_depth3_environmental_cascade
        """
        env = _two_order_farm(assign_order_a=False)
        spill = self._reported_spill(env)
        fx.escalate_spill(spill["id"], "EPA-2026-08-10-001")

        auth_a = fx.read_authorization(env["auth_a"]["id"])
        auth_b = fx.read_authorization(env["auth_b"]["id"])
        assert auth_a["status"] == "VOIDED"
        assert auth_a["voided_reason"] == "FARM_FROZEN", \
            "the freeze cascade records FARM_FROZEN, not ORDER_CANCELLED"
        assert auth_b["status"] == "VOIDED"
        assert auth_b["voided_reason"] == "FARM_FROZEN"

        uplift = fx.read_uplift(env["uplift_b"]["id"])
        assert uplift["status"] == "VOIDED"
        assert uplift["voided_reason"] == "ORDER_ABORTED"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005)
        assert tank["reserved_volume_liters"] == pytest.approx(0.00, abs=0.005)
        assert tank["available_volume_liters"] == pytest.approx(999500.00, abs=0.005)

        assert fx.read_account(env["account"]["id"])["accrual_exposure_cents"] == 0
        assert fx.read_asset(env["truck1"]["id"])["reliability_score"] == 100, \
            "an escalated incident has not yet reached containment, so no penalty applies"
