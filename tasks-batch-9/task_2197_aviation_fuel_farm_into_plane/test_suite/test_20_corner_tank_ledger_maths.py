"""Corner behaviour of the tank ledger: the availability floor, the receipt that contributes nothing
until the instant it contributes everything, and the void/repost cycle that leaves no drift."""
import pytest

from test_helpers import fixtures as fx

PARCEL = dict(delivery_mode="PIPELINE", supplier_name="Refinery One",
              meter_ticket_gross_liters=10_100.0, tank_opening_gauge_liters=0.0,
              tank_closing_gauge_liters=10_000.0, temperature_c=15.0,
              certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)


class TestTankBookInventoryCorners:
    def test_availability_floors_at_zero_while_the_book_stays_large(self, api):
        """PRD §3.4: "The `available_volume_liters` is the book volume less the reserved volume less the
        farm's `unpumpable_bottom_liters`, rounded half up to two decimals and then floored at 0.0 so it
        can never go negative."
        PRD §3.4: "The `reserved_volume_liters` is the sum of `requested_uplift_liters` over every order
        on this tank whose `status` is `AUTHORIZED`, `ASSIGNED` or `FUELING`, rounded half up to two
        decimals."
        PRD §3.4: "The tank ledger is never maintained incrementally."

        Design: Corner/calculations/available_volume_floors_at_zero_and_never_goes_negative
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=21_000.0,
                                               density_kg_per_m3=795.0)
        farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]
        first_truck = fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        fx.register_truck(farm_id, tank_capacity_liters=40_000.0)
        account = fx.open_account(base_price_cents_per_liter=62.00,
                                  credit_limit_cents=100_000_000)

        def raise_order(stand, departure):
            flight = fx.register_flight(account["id"], stand_code=stand,
                                        scheduled_departure_utc=departure)
            auth = fx.issue_authorization(account["id"], flight["id"],
                                          max_authorized_liters=10_000.0)
            order = fx.create_order(flight["id"], auth["id"], tank_id,
                                    auth["authorization_code"], delivery_mode="TRUCK",
                                    requested_uplift_liters=10_000.0)
            fx.authorize_order(order["id"])
            return order

        # The first order is assigned before the second reservation lands, because PRD §3.6
        # gates TRUCK assignment on the tank's available volume being at least the requested
        # volume and the second reservation would take availability below that.
        first_order = raise_order("A12", "2026-08-10T08:00:00Z")
        fx.assign_order(first_order["id"], first_truck["id"])
        raise_order("A13", "2026-08-10T09:00:00Z")

        reserved = fx.read_tank(tank_id)
        assert reserved["reserved_volume_liters"] == pytest.approx(20000.00, abs=0.005)
        assert reserved["available_volume_liters"] == pytest.approx(500.00, abs=0.005), \
            "21,000.00 book less 20,000.00 reserved less the 500.0 unpumpable heel"

        fx.start_order(first_order["id"])
        fx.post_uplift(first_order["id"], meter_start_liters=0.0, meter_end_liters=10_000.0,
                       temperature_c=15.0)

        tank = fx.read_tank(tank_id)
        assert tank["book_volume_liters"] == pytest.approx(11000.00, abs=0.005), \
            "the book is still substantial"
        assert tank["reserved_volume_liters"] == pytest.approx(20000.00, abs=0.005), \
            "the fuelling order keeps its reservation until it completes"
        assert tank["available_volume_liters"] == pytest.approx(0.00, abs=0.005), \
            "the raw arithmetic would be minus 9,500.00, and the floor catches it"

    def test_a_quarantined_parcel_contributes_nothing_and_then_everything(self, api):
        """PRD §3.4: "The `book_volume_liters` is the tank's `opening_volume_liters`, plus the sum of
        `net_volume_liters` over every receipt destined for this tank whose `status` is `RELEASED`, minus
        the sum of `net_liters` over every uplift ticket drawn from this tank whose `status` is `POSTED`
        or `BILLED`, plus the sum of `adjustment_liters` written for this tank by every reconciliation
        run whose `status` is `POSTED`, the whole rounded half up to two decimals."
        PRD §3.4: "Receipts in `RECORDED`, `SAMPLED`, `UNDER_TEST`, `QUARANTINED` or `REJECTED`
        contribute nothing; `VOIDED` uplift tickets contribute nothing."
        PRD §3.3: "The revision cycle is therefore
        `QUARANTINED → SAMPLED → UNDER_TEST → RELEASED` or back to `QUARANTINED`."

        Design: Corner/calculations/quarantined_receipt_contributes_nothing_then_everything
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0,
                                               density_kg_per_m3=795.0)
        tank_id = env["tank"]["id"]

        receipt = fx.record_receipt(tank_id, **PARCEL)
        assert receipt["net_volume_liters"] == pytest.approx(10000.00, abs=0.005)
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(0.00, abs=0.005)

        first_sample = fx.draw_receipt_sample(receipt["id"])
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(0.00, abs=0.005)
        fx.post_results(first_sample["id"], fx.INSPECTOR_A, flash_point_c=30.0)
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(0.00, abs=0.005)

        held = fx.sign_verdict(receipt["id"], "QUARANTINE", fx.INSPECTOR_B)
        assert held["status"] == "QUARANTINED"
        assert fx.read_tank(tank_id)["quality_status"] == "QUARANTINED"
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(0.00, abs=0.005), \
            "four states have passed and not one litre has entered the ledger"

        retest = fx.draw_receipt_sample(receipt["id"])
        fx.post_results(retest["id"], fx.INSPECTOR_A)
        released = fx.sign_verdict(receipt["id"], "RELEASE", fx.INSPECTOR_B)

        assert released["status"] == "RELEASED"
        assert released["retest_round"] == 1
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(10000.00, abs=0.005), \
            "the whole parcel arrives on the single hop into RELEASED"

    def test_a_void_and_an_identical_repost_leave_the_ledger_where_it_started(self, api):
        """PRD §3.4: "The tank ledger is never maintained incrementally. On each of its triggers — a
        receipt release, an uplift ticket being posted, an uplift ticket being voided, an order abort,
        and a reconciliation run being posted — the tank's figures are recomputed in full from the source
        rows."
        PRD §3.6: "**Abort**, `FUELING → ABORTED`, carries an `abort_reason` of `SPILL`, `QUALITY_HOLD`,
        `AIRCRAFT_RELEASE` or `EQUIPMENT_FAILURE`, and compensates everything: every `POSTED` ticket on
        the order becomes `VOIDED` with `voided_reason` `ORDER_ABORTED` and its `net_liters` are credited
        back to the tank's `book_volume_liters`; the requested volume is subtracted from the tank's
        `reserved_volume_liters`; for truck delivery the asset's `onboard_volume_liters` recomputes to
        0.0 as the voided tickets leave the posted set, so the sum of tank book volume and on-board
        volume returns to exactly its pre-fuelling value; the authorization is driven `ISSUED → VOIDED`
        with `voided_reason` `ORDER_CANCELLED`; pit occupancy ends; and the account's accrual exposure
        returns to its pre-authorization value."
        PRD §3.4: "Receipts in `RECORDED`, `SAMPLED`, `UNDER_TEST`, `QUARANTINED` or `REJECTED`
        contribute nothing; `VOIDED` uplift tickets contribute nothing."

        Design: Corner/calculations/full_recompute_survives_a_void_and_repost
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, temperature_c=15.0, requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000})
        tank_id, account_id = env["tank"]["id"], env["account"]["id"]
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(980000.00, abs=0.005)

        fx.abort_order(env["order"]["id"], abort_reason="EQUIPMENT_FAILURE")
        assert fx.read_uplift(env["uplift"]["id"])["status"] == "VOIDED"
        restored = fx.read_tank(tank_id)
        assert restored["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005)
        assert restored["reserved_volume_liters"] == pytest.approx(0.00, abs=0.005)

        flight = fx.register_flight(account_id, stand_code="B07",
                                    scheduled_departure_utc="2026-08-10T09:00:00Z")
        auth = fx.issue_authorization(account_id, flight["id"],
                                      max_authorized_liters=20_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0)
        fx.authorize_order(order["id"])
        fx.assign_order(order["id"], env["truck"]["id"])
        fx.start_order(order["id"])
        replacement = fx.post_uplift(order["id"], meter_start_liters=0.0,
                                     meter_end_liters=20_000.0, temperature_c=15.0)

        assert replacement["net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(980000.00,
                                                                           abs=0.005), \
            "a full recompute over the source rows cannot drift"
