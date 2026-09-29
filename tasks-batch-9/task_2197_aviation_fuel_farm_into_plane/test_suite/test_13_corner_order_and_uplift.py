"""Corner behaviour of the order's five-way join and of the ticket that moves the product: payload
agreement, the reversible assignment cycle, the FUELING exit doors and the two authorization
ceilings with their different tolerances."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)


class TestFuelingOrderCorners:
    def test_an_authorization_minted_for_another_flight_is_an_agreement_failure(self, api):
        """PRD §2.4: "A payload whose identifiers each resolve but do not agree — a tank, asset, pit,
        flight and authorization that are not all anchored to the same farm, or an authorization that
        does not belong to the flight named on the same order — yields `ERR_CROSS_FARM_REFERENCE`."
        PRD §2.10: "then aggregate agreement is checked (`ERR_CROSS_FARM_REFERENCE`) on fuelling order
        creation and order assignment — specifically that the quoted authorization's flight matches the
        order's flight, that the hydrant pit and the storage tank belong to the same farm, and that the
        fuelling asset and the storage tank belong to the same farm."
        PRD §3.5: "Issuing one is available to both an `AirlineRep` acting for its own account and to a
        `BillingClerk`, and the payload names the `airline_account_id` to be billed, the `flight_id` the
        authorization may be redeemed for — exactly one flight, never a bearer credit — and a
        `max_authorized_liters` strictly greater than zero that ceilings the total posted uplift volume
        redeemable under it."

        Design: Corner/entities/cross_farm_reference_between_tank_and_flight_stand
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        account = fx.open_account(base_price_cents_per_liter=62.00,
                                  credit_limit_cents=100_000_000)
        booked = fx.register_flight(account["id"], stand_code="A12")
        other = fx.register_flight(account["id"], stand_code="A13",
                                   scheduled_departure_utc="2026-08-10T09:00:00Z")
        auth = fx.issue_authorization(account["id"], booked["id"],
                                      max_authorized_liters=20_000.0)

        payload = F.create_fueling_order_payload(
            other["id"], auth["id"], env["tank"]["id"], auth["authorization_code"],
            delivery_mode="TRUCK", requested_uplift_liters=20_000.0,
            window_start_utc="2026-08-10T06:00:00Z", window_end_utc="2026-08-10T07:30:00Z")
        validate_error(api.create_fueling_order(payload, fx.AGENT),
                       ApiErrorId.ERR_CROSS_FARM_REFERENCE, 422)

        orders, _meta = validate_paginated(api.list_fueling_orders(fx.AGENT))
        assert orders == []
        assert fx.read_authorization(auth["id"])["status"] == "ISSUED"

    def test_the_assignment_cycle_may_repeat_and_only_the_counter_records_it(self, api):
        """PRD §3.6: "Assignment is reversible. Unassigning, `ASSIGNED → AUTHORIZED`, clears both the
        `fueling_asset_id` and the `hydrant_pit_id` to null, raises `unassign_count` by one, and ends
        the order's pit occupancy for its window — but it deliberately leaves the tank's
        `reserved_volume_liters` untouched, because the volume reservation belongs to the authorised
        state, not to the assignment."
        PRD §3.6: "The order's and asset's `version` each rise by one, and the order may then be
        re-assigned to a different asset, so the cycle `AUTHORIZED → ASSIGNED → AUTHORIZED` may
        repeat."

        Design: Corner/entities/repeated_unassign_reassign_accumulates_unassign_count
        """
        env = fx.setup_truck_order(target_state="ASSIGNED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": 100_000_000})
        order_id, tank_id = env["order"]["id"], env["tank"]["id"]
        spare = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  turnaround_buffer_minutes=15, differential_pressure_kpa=10.0)
        assert fx.read_tank(tank_id)["reserved_volume_liters"] == pytest.approx(20000.00,
                                                                              abs=0.005)

        first_release = validate_success(api.unassign_order(order_id, fx.AGENT))
        assert first_release["status"] == "AUTHORIZED"
        assert first_release["fueling_asset_id"] is None
        assert first_release["unassign_count"] == 1
        assert fx.read_tank(tank_id)["reserved_volume_liters"] == pytest.approx(20000.00,
                                                                               abs=0.005)

        again = fx.assign_order(order_id, spare["id"])
        assert again["fueling_asset_id"] == spare["id"]
        second_release = validate_success(api.unassign_order(order_id, fx.AGENT))

        assert second_release["status"] == "AUTHORIZED"
        assert second_release["unassign_count"] == 2, "the cycle is legal and merely counted"
        assert second_release["hydrant_pit_id"] is None
        tank = fx.read_tank(tank_id)
        assert tank["reserved_volume_liters"] == pytest.approx(20000.00, abs=0.005)
        assert tank["available_volume_liters"] == pytest.approx(979500.00, abs=0.005)

    def test_a_fuelling_order_can_only_be_aborted_never_cancelled(self, api):
        """PRD §3.6: "**Cancellation** is available from three states and its effects grow with how far
        the order had progressed."
        PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection;
        `ERR_INVALID_ORDER_STATE` on order authorize, assign, unassign, start, uplift posting,
        complete, abort and cancel; `ERR_INVALID_TANK_STATE` on tank service-status changes, quality
        release, quarantine and tank sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and
        filter changes; `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment;
        and `ERR_INVALID_RUN_STATE` on reconciliation measure and post."
        PRD §3.6: "**Abort**, `FUELING → ABORTED`, carries an `abort_reason` of `SPILL`,
        `QUALITY_HOLD`, `AIRCRAFT_RELEASE` or `EQUIPMENT_FAILURE`, and compensates everything: every
        `POSTED` ticket on the order becomes `VOIDED` with `voided_reason` `ORDER_ABORTED` and its
        `net_liters` are credited back to the tank's `book_volume_liters`; the requested volume is
        subtracted from the tank's `reserved_volume_liters`; for truck delivery the asset's
        `onboard_volume_liters` recomputes to 0.0 as the voided tickets leave the posted set, so the sum
        of tank book volume and on-board volume returns to exactly its pre-fuelling value; the
        authorization is driven `ISSUED → VOIDED` with `voided_reason` `ORDER_CANCELLED`; pit occupancy
        ends; and the account's accrual exposure returns to its pre-authorization value."

        Design: Corner/entities/cancel_is_not_available_from_fueling
        """
        env = fx.setup_truck_order(target_state="FUELING", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": 100_000_000})
        order_id = env["order"]["id"]

        validate_error(api.cancel_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)
        assert fx.read_order(order_id)["status"] == "FUELING"
        assert fx.read_authorization(env["auth"]["id"])["status"] == "ISSUED"

        aborted = validate_success(api.abort_order(order_id, {"abort_reason": "SPILL"}, fx.AGENT))
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "SPILL"


class TestUpliftRecordCorners:
    def test_a_top_up_ticket_is_priced_from_the_cumulative_including_both_tickets(self, api):
        """PRD §3.6: "The **cumulative volume** driving the tier is the account's month-to-date net
        liters: the sum of `net_liters` over that airline account's uplift tickets whose `status` is
        `POSTED` or `BILLED` and whose `created_at` falls between the first instant of the calendar UTC
        month containing this ticket's `created_at` and this ticket's own `created_at` inclusive, and it
        **includes this ticket itself**."
        PRD §3.6: "From that cumulative a whole-line differential rate
        `volume_tier_diff_cents_per_liter` is selected — 1.60 cents per liter once the cumulative
        reaches 500,000 liters, otherwise 2.40 cents per liter once it reaches 100,000 liters,
        otherwise 3.20 cents per liter — and the rate applies to the entire line, not marginally."
        PRD §3.6: "The ticket's `gross_liters` is the end reading less the start reading, rounded half
        up to two decimals."

        Design: Corner/entities/second_ticket_on_the_same_order_is_legitimate
        """
        env = fx.setup_truck_order(
            target_state="FUELING", requested_uplift_liters=110_000.0,
            max_authorized_liters=120_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": True},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        order_id = env["order"]["id"]

        first = fx.post_uplift(order_id, meter_start_liters=0.0, meter_end_liters=90_000.0,
                               temperature_c=15.0)
        assert first["net_liters"] == pytest.approx(90000.00, abs=0.005)
        assert first["volume_tier_diff_cents_per_liter"] == pytest.approx(3.20, abs=0.005)

        second = fx.post_uplift(order_id, meter_start_liters=90_000.0,
                                meter_end_liters=110_000.0, temperature_c=15.0)
        assert second["status"] == "POSTED"
        assert second["net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert second["volume_tier_diff_cents_per_liter"] == pytest.approx(2.40, abs=0.005), \
            "the cumulative 110000.00 liters includes this ticket and crosses 100,000"
        assert second["fuel_component_cents"] == 1288000

        assert fx.read_uplift(first["id"])["status"] == "POSTED"
        assert fx.read_order(order_id)["posted_net_liters"] == pytest.approx(110000.00,
                                                                            abs=0.005)

    def test_the_posting_tolerance_is_wider_than_the_completion_ceiling(self, api):
        """PRD §3.6: "Posting is gated on the fuelling window, on the source tank still being
        `RELEASED`, on the asset still being serviceable, on the farm not being `FROZEN` and having an
        active permit, on the tank's `book_volume_liters` less the farm's `unpumpable_bottom_liters`
        being at least the ticket's `net_liters` (`ERR_INSUFFICIENT_TANK_VOLUME`), on the farm's
        permit-day throughput including this volume staying within `max_daily_throughput_liters`
        (`ERR_PERMIT_THROUGHPUT_EXCEEDED`), and on the order's `posted_net_liters` after this ticket not
        exceeding **105 percent** of the authorization's `max_authorized_liters` — a deliberate five
        percent posting tolerance, breach of which is `ERR_UPLIFT_EXCEEDS_AUTHORIZATION`."
        PRD §3.6: "**Completion**, `FUELING → COMPLETED`, requires at least one `POSTED` ticket on the
        order (otherwise `ERR_NO_UPLIFT_RECORDED`) and requires the order's `posted_net_liters` to be at
        most the authorization's `max_authorized_liters` — with **no tolerance at all** at this gate, in
        contrast to the five percent allowed when posting."

        Design: Corner/entities/uplift_five_percent_authorization_tolerance
        """
        env = fx.setup_truck_order(
            target_state="FUELING", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        order_id = env["order"]["id"]

        ticket = fx.post_uplift(order_id, meter_start_liters=0.0, meter_end_liters=21_000.0,
                                temperature_c=15.0)
        assert ticket["status"] == "POSTED"
        assert ticket["net_liters"] == pytest.approx(21000.00, abs=0.005), \
            "exactly 105 percent of 20000.0 clears the posting guard"
        assert fx.read_order(order_id)["posted_net_liters"] == pytest.approx(21000.00,
                                                                            abs=0.005)

        # PRD §5 maps `ERR_UPLIFT_EXCEEDS_AUTHORIZATION` to HTTP 409, not 422.
        validate_error(api.complete_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_UPLIFT_EXCEEDS_AUTHORIZATION, 409)

        assert fx.read_order(order_id)["status"] == "FUELING"
        assert fx.read_authorization(env["auth"]["id"])["status"] == "ISSUED"

    def test_a_totaliser_that_runs_backwards_is_out_of_range(self, api):
        """PRD §3.6: "The payload carries a `ticket_number` unique across all uplift tickets, a
        `meter_start_liters` totaliser reading zero or greater, a `meter_end_liters` reading strictly
        greater than the start, the product `temperature_c` at the wing (at least minus 20 and at most
        60), and the mandatory `expected_fueling_order_version` described in §2.9."
        PRD §2.10: "Required-field presence and type correctness (`ERR_INVALID_PAYLOAD`) precede
        declared value constraints (`ERR_FIELD_OUT_OF_RANGE`), which cover every numeric range and
        enumeration membership declared in this document as well as the relational constraints — a
        receipt's closing gauge must exceed its opening gauge, an uplift's meter end reading must exceed
        its meter start reading, a fuelling window's end must be later than its start, a reconciliation
        or billing period's end must be later than its start, and a tank's safe fill volume must not
        exceed its shell capacity."

        Design: Corner/entities/meter_rollback_is_rejected
        """
        env = fx.setup_truck_order(
            target_state="FUELING", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        order_id = env["order"]["id"]
        version_before = fx.read_order(order_id)["version"]

        payload = F.create_uplift_record_payload(
            version_before, meter_start_liters=20_000.0, meter_end_liters=19_000.0,
            temperature_c=15.0)
        validate_error(api.create_uplift_record(order_id, payload, fx.AGENT),
                       ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

        order = fx.read_order(order_id)
        assert order["version"] == version_before
        assert order["posted_net_liters"] == pytest.approx(0.0, abs=0.005)
        tickets, _meta = validate_paginated(api.list_uplift_records(
            fx.AGENT, {"fueling_order_id": order_id}))
        assert tickets == []
        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(1000000.00, abs=0.005)
