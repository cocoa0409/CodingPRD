"""Multi-hop cascades and compensating invariants: the no-show depth-3 chain
(fee -> strike -> suspension), the complete depth-2 chain (stop SERVICED ->
route CLOSED), money-conservation on settle, route-load conservation on void,
and the waive compensation that reverses both money and a strike.

Difficulty queue: transitive_cascade, compensating_invariant.
Corner queue: cross_cutting_complexity_layers (fee waive).
"""
from test_helpers import fixtures as fx


class TestNoShowCascade:
    def _world_two_prior_strikes(self, zip_code, clock):
        fx.set_clock(clock)
        world = fx.setup_world(zip_code=zip_code, tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start=f"{clock[:11]}09:00:00Z",
                               window_end=f"{clock[:11]}17:00:00Z",
                               service_date=f"{clock[:11]}00:00:00Z")
        fx.accrue_no_show_strikes(world, 2, first_slot=f"{clock[:11]}09:00:00Z")
        return world

    def test_third_no_show_suspends_account(self, api):
        """PRD §3.5: "registers a strike that recomputes the customer's
        no_show_strikes, suspending the account if the threshold is reached."
        PRD §3.9: "The customer's account_status is SUSPENDED when no_show_strikes
        is at least 3 and ACTIVE otherwise; the suspension boundary is inclusive at
        exactly 3."

        Design: Difficulty/transitive_cascade/no_show_cascade_fee_strike_suspend_depth3
        """
        clock = "2026-06-13T10:00:00Z"
        world = self._world_two_prior_strikes("90007", clock)
        third = fx.create_scheduled_appointment(world, "2026-06-13T13:00:00Z")
        fx.no_show(third["id"])
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["no_show_strikes"] == 3, cust
        assert cust["account_status"] == "SUSPENDED", cust

    def test_outstanding_fees_accumulate_across_three_no_shows(self, api):
        """PRD §3.5: "debits the customer's outstanding_fee_cents by the assessed
        amount and registers a strike."
        PRD §3.9: "it is debited when a fee is assessed and credited back when a fee
        is settled or waived, preserving the invariant that it always equals the
        total of the customer's pending fees."

        Design: Difficulty/transitive_cascade/no_show_cascade_fee_strike_suspend_depth3
        """
        clock = "2026-06-13T10:00:00Z"
        world = self._world_two_prior_strikes("90007", clock)
        third = fx.create_scheduled_appointment(world, "2026-06-13T13:00:00Z")
        fx.no_show(third["id"])
        cust = fx.get_customer(world["customer"]["id"])
        # 3000 + 3000 + 4500 (third escalated, strikes_before == 2) = 10500
        assert cust["outstanding_fee_cents"] == 10500, cust


class TestCompleteCascade:
    def test_complete_services_stop_and_closes_route(self, api):
        """PRD §3.5: "On completion the linked route stop transitions to SERVICED;
        if that makes every stop on the route day terminal, the route day bubbles up
        to CLOSED."
        PRD §3.7: "A route day transitions automatically from LOCKED to CLOSED as a
        bubble-up side effect the moment every stop on the day has reached a terminal
        status (SERVICED, NO_SHOW, or VOIDED)."

        Design: Difficulty/transitive_cascade/complete_cascade_stop_serviced_route_closed_depth2
        """
        fx.set_clock("2026-06-14T08:00:00Z")
        world = fx.setup_world(zip_code="90008", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-14T09:00:00Z",
                               window_end="2026-06-14T17:00:00Z",
                               service_date="2026-06-14T00:00:00Z")
        appt = fx.create_scheduled_appointment(world, "2026-06-14T09:30:00Z")
        stop_id = appt["route_stop_id"]
        fx.get_success_data(api.dispatch_route_day(world["route_day"]["id"], fx.DISPATCH))
        fx.complete(appt["id"], world["groomer"]["id"])
        stop = fx.get_success_data(api.get_route_stop(stop_id, fx.DISPATCH))
        assert stop["status"] == "SERVICED", stop
        rd = fx.get_success_data(api.get_route_day(world["route_day"]["id"], fx.DISPATCH))
        assert rd["status"] == "CLOSED", rd

    def test_complete_sets_route_stop_serviced(self, api):
        """PRD §3.5: "On completion the linked route stop transitions to SERVICED."

        Design: Difficulty/transitive_cascade/complete_cascade_stop_serviced_route_closed_depth2
        """
        fx.set_clock("2026-06-14T08:00:00Z")
        world = fx.setup_world(zip_code="90008", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-14T09:00:00Z",
                               window_end="2026-06-14T17:00:00Z",
                               service_date="2026-06-14T00:00:00Z")
        appt = fx.create_scheduled_appointment(world, "2026-06-14T09:30:00Z")
        completed = fx.complete(appt["id"], world["groomer"]["id"])
        assert completed["status"] == "COMPLETED", completed
        stop = fx.get_success_data(api.get_route_stop(appt["route_stop_id"], fx.DISPATCH))
        assert stop["status"] == "SERVICED", stop


class TestSettleConservesMoney:
    def _customer_with_pending_no_show_fee(self, zip_code, clock):
        fx.set_clock(clock)
        world = fx.setup_world(zip_code=zip_code, tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start=f"{clock[:11]}09:00:00Z",
                               window_end=f"{clock[:11]}17:00:00Z",
                               service_date=f"{clock[:11]}00:00:00Z")
        appt = fx.create_scheduled_appointment(world, f"{clock[:11]}09:30:00Z")
        fx.no_show(appt["id"])
        return world

    def test_outstanding_balance_before_settle(self, api):
        """PRD §3.9: "The customer's outstanding_fee_cents is maintained as the sum
        of amount_cents over that customer's PENDING fee charges."

        Design: Difficulty/compensating_invariant/fee_settle_conserves_outstanding_balance
        """
        world = self._customer_with_pending_no_show_fee("90017", "2026-06-23T10:00:00Z")
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["outstanding_fee_cents"] == 3000, cust

    def test_settle_restores_balance_to_zero(self, api):
        """PRD §3.9: "Settling a PENDING fee credits the customer's
        outstanding_fee_cents by the fee's amount_cents and bumps the fee's version."

        Design: Difficulty/compensating_invariant/fee_settle_conserves_outstanding_balance
        """
        world = self._customer_with_pending_no_show_fee("90017", "2026-06-23T10:00:00Z")
        fee = fx.first_fee_for_customer(world["customer"]["id"])
        settled = fx.get_success_data(api.settle_fee_charge(
            fee["id"], fx.make_customer_headers(world["customer"]["id"])))
        assert settled["settlement_status"] == "SETTLED", settled
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["outstanding_fee_cents"] == 0, cust


class TestCancelConservesRouteLoad:
    def _scheduled_far_out(self, zip_code, clock):
        fx.set_clock(clock)
        # BATH_ONLY base 50 min -> stop load 65. Slot far in the future so cancel
        # is well over 24h out (no late fee).
        world = fx.setup_world(zip_code=zip_code, tier_code="BATH_ONLY",
                               base_price_cents=3000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=20,
                               window_start="2026-06-28T09:00:00Z",
                               window_end="2026-06-28T17:00:00Z",
                               service_date="2026-06-28T00:00:00Z")
        appt = fx.create_scheduled_appointment(world, "2026-06-28T09:00:00Z")
        return world, appt

    def test_booked_minutes_before_cancel(self, api):
        """PRD §3.4: "The persisted booked_minutes on the route day denormalizes
        that existing load (service minutes plus a 15-minute buffer for each
        non-voided stop) and is reconciled on every stop addition or cancellation."

        Design: Difficulty/compensating_invariant/cancel_void_conserves_route_booked_minutes
        """
        world, appt = self._scheduled_far_out("90018", "2026-06-24T08:00:00Z")
        rd = fx.get_success_data(api.get_route_day(world["route_day"]["id"], fx.DISPATCH))
        assert rd["booked_minutes"] == 65, rd

    def test_cancel_voids_stop_and_frees_load(self, api):
        """PRD §3.5: "Cancelling a SCHEDULED appointment moves it to CANCELLED, sets
        the linked route stop to VOIDED (which frees the slot and its travel buffer),
        and recomputes the route day's booked_minutes."
        PRD §3.5: "If that gap is at least 24 hours the cancellation is not late and
        there is no fee and no strike."

        Design: Difficulty/compensating_invariant/cancel_void_conserves_route_booked_minutes
        """
        world, appt = self._scheduled_far_out("90018", "2026-06-24T08:00:00Z")
        stop_id = appt["route_stop_id"]
        fx.cancel(appt["id"], world["customer"]["id"])
        stop = fx.get_success_data(api.get_route_stop(stop_id, fx.DISPATCH))
        assert stop["status"] == "VOIDED", stop
        rd = fx.get_success_data(api.get_route_day(world["route_day"]["id"], fx.DISPATCH))
        assert rd["booked_minutes"] == 0, rd
        # cancel was >24h out: no fee created
        fees = fx.list_customer_fee_charges(world["customer"]["id"])
        assert fees == [], fees


class TestWaiveReversesStrikeAndMoney:
    def test_waive_credits_money_and_drops_strike(self, api):
        """PRD §3.9: "Waiving a PENDING fee likewise credits outstanding_fee_cents
        by amount_cents, and additionally reverses the strike the fee represented: it
        decrements the customer's no_show_strikes by one and recomputes
        account_status accordingly, then bumps the fee's version."

        Design: Corner/cross_cutting_complexity_layers/fee_waive_reverses_strike_compensation
        """
        fx.set_clock("2026-07-15T10:00:00Z")
        world = fx.setup_world(zip_code="10028", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=90,
                               window_start="2026-07-15T09:00:00Z",
                               window_end="2026-07-15T17:00:00Z",
                               service_date="2026-07-15T00:00:00Z")
        appt = fx.create_scheduled_appointment(world, "2026-07-15T09:30:00Z")
        fx.no_show(appt["id"])
        before = fx.get_customer(world["customer"]["id"])
        assert before["no_show_strikes"] == 1, before
        fee = fx.first_fee_for_customer(world["customer"]["id"])
        waived = fx.get_success_data(api.waive_fee_charge(fee["id"], fx.ADMIN))
        assert waived["settlement_status"] == "WAIVED", waived
        after = fx.get_customer(world["customer"]["id"])
        assert after["no_show_strikes"] == 0, after
        assert after["outstanding_fee_cents"] == 0, after
