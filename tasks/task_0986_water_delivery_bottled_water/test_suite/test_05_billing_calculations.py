"""Billing calculations: water charges, shortage charges, deposit refunds,
pricing-config tiling, and pricing-config validation."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer_payload,
    setup_customer, setup_zone, set_clock, create_standard_pricing_config,
    create_route, plan_stop, publish_route, start_route, arrive_and_deliver,
    deliver_via_work_order, create_and_issue_invoice, create_draft_invoice,
    issue_invoice, create_pricing_config_payload, current_route_version,
    arrive_stop, get_customer, get_invoice, get_stop,
    OPS_ADMIN, DISPATCHER, DRIVER, BILLING_ADMIN,
)


class TestWaterCharge:
    def test_water_charge_gold_tier_rate(self, api):
        """PRD §3.4: "When a stop lands in `DELIVERED` or `PARTIAL`, the water
        charge is the per-bottle rate for the customer's `pricing_tier` — drawn
        from the pricing configuration in effect on the route's `service_date`,
        so `STANDARD` accounts pay `standard_per_bottle_cents`, `SILVER`
        accounts pay `silver_per_bottle_cents`, and `GOLD` accounts pay
        `gold_per_bottle_cents` — multiplied by `actual_bottles_delivered`."
        PRD §3.8: "The `subtotal_water_cents` aggregates the per-stop water
        charges (per §3.4) for the customer's stops in the period that reached
        `DELIVERED` or `PARTIAL`."

        Design: Corner/calculations/water_charge_gold_tier_rate
        """
        world = setup_customer(account_type="OFFICE", business_name="GoldCo",
                               billing_email="g@x.example", service_address="1 G",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="GOLD")
        zone, customer = world["zone"], world["customer"]
        deliver_via_work_order(customer["id"], zone["id"], "2026-05-10", 10)
        invoice = create_and_issue_invoice(customer["id"], "2026-05-01",
                                           "2026-06-01", "2026-06-15")
        assert invoice["subtotal_water_cents"] == 6000, (
            f"GOLD rate 600c * 10 bottles must yield 6000c, "
            f"got {invoice['subtotal_water_cents']}"
        )

    def test_provisional_plan_differs_from_final_on_partial(self, api):
        """PRD §3.4: "A clean exchange — actuals exactly equal to plan, both
        bottles delivered and empties collected — moves the stop `ARRIVED` to
        `DELIVERED`. When either actual falls short of plan, the stop instead
        lands in `PARTIAL`: the recorded `shortage_count` is the number of
        empties owed but not returned, computed as `planned_empties_pickup`
        minus `actual_empties_collected` and floored at zero."
        PRD §3.3: "For an `AUTO` customer, `planned_bottles` is the gap between
        target and reality: the customer's `par_level_bottles` minus their
        current `bottles_on_site`, floored at zero, measured at plan time."

        A stop planned for 4 bottles (par 4, none on site) but delivered with 3
        must land in PARTIAL with the plan and the actuals both recorded.

        Design: Difficulty/dual_variant_calc/water_charge_provisional_vs_final
        """
        world = setup_customer(account_type="OFFICE", business_name="Acme Co",
                               billing_email="billing@acme.example",
                               service_address="100 Main St",
                               service_mode="AUTO", par_level_bottles=4,
                               pricing_tier="STANDARD")
        zone, customer = world["zone"], world["customer"]
        route = create_route(zone["id"], "2026-06-01")
        stop = plan_stop(route["id"], customer["id"], sequence_index=1)
        assert stop["planned_bottles"] == 4, "plan: 4 - 0 on site = 4"

        publish_route(route["id"])
        start_route(route["id"], "2026-06-01T08:00:00Z")
        delivered = arrive_and_deliver(stop["id"], route["id"], 3, 0)
        assert delivered["stop_status"] == "PARTIAL", \
            f"actual 3 vs plan 4 must land PARTIAL, got {delivered['stop_status']}"
        assert delivered["planned_bottles"] == 4
        assert delivered["actual_bottles_delivered"] == 3

    def test_invoice_water_charge_uses_actuals_not_plan(self, api):
        """PRD §3.4: "Planning shows a provisional figure computed the same way
        but against `planned_bottles`; that projection lives only in a
        projected-charges cache, is never persisted to an invoice, and is
        discarded the moment the actuals-based charge is written."
        PRD §3.8: "The `subtotal_water_cents` aggregates the per-stop water
        charges (per §3.4) for the customer's stops in the period that reached
        `DELIVERED` or `PARTIAL`."

        Planned 4 bottles (provisional 4*700=2800) but delivered 3, so the
        persisted invoice charge must be 3*700=2100.

        Design: Difficulty/dual_variant_calc/water_charge_provisional_vs_final
        """
        world = setup_customer(account_type="OFFICE", business_name="Acme Co",
                               billing_email="billing@acme.example",
                               service_address="100 Main St",
                               service_mode="AUTO", par_level_bottles=4,
                               pricing_tier="STANDARD")
        zone, customer = world["zone"], world["customer"]
        route = create_route(zone["id"], "2026-06-01")
        stop = plan_stop(route["id"], customer["id"], sequence_index=1)
        publish_route(route["id"])
        start_route(route["id"], "2026-06-01T08:00:00Z")
        arrive_and_deliver(stop["id"], route["id"], 3, 0)

        invoice = create_and_issue_invoice(customer["id"], "2026-06-01",
                                           "2026-07-01", "2026-07-15")
        assert invoice["subtotal_water_cents"] == 2100, (
            f"invoice must persist the actuals-based charge 3*700=2100, not the "
            f"provisional 4*700=2800; got {invoice['subtotal_water_cents']}"
        )


class TestShortageCharge:
    def test_shortage_charge_calculation(self, api):
        """PRD §3.4: "When either actual falls short of plan, the stop instead
        lands in `PARTIAL`: the recorded `shortage_count` is the number of
        empties owed but not returned, computed as `planned_empties_pickup`
        minus `actual_empties_collected` and floored at zero."
        PRD §3.8: "The `shortage_charge_cents` totals shortage events: for every
        stop in the period that finished `PARTIAL` with a positive
        `shortage_count`, the count is multiplied by the
        `bottle_shortage_fee_cents` from the configuration in effect on the
        stop's service date, and because the shortage fee is never less than the
        deposit, a shortage always costs at least the deposit refund that was
        forfeited."

        Plan 3 bottles, collect only 1 empty: shortage 2, charge 2*2000=4000.

        Design: Corner/calculations/shortage_charge_calculation
        """
        world = setup_customer(account_type="OFFICE", business_name="ShortCo",
                               billing_email="s@x.example", service_address="1 S",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        zone, customer = world["zone"], world["customer"]
        delivery = deliver_via_work_order(customer["id"], zone["id"], "2026-05-10", 3,
                                          actual_bottles_delivered=3,
                                          actual_empties_collected=1)
        stop = delivery["delivered_stop"]
        assert stop["stop_status"] == "PARTIAL"
        assert stop["shortage_count"] == 2, \
            f"shortage = 3 planned empties - 1 collected = 2, got {stop['shortage_count']}"

        invoice = create_and_issue_invoice(customer["id"], "2026-05-01",
                                           "2026-06-01", "2026-06-15")
        assert invoice["shortage_charge_cents"] == 4000, (
            f"shortage charge must be 2 * 2000 = 4000, "
            f"got {invoice['shortage_charge_cents']}"
        )


class TestDepositRefundNetMovement:
    def _exchange_parity_scenario(self, api):
        """Two WILL_CALL deliveries in June, each a clean 2-for-2 exchange:
        two DELIVER_FULL and two PICKUP_EMPTY events in the period, net
        movement zero."""
        world = setup_customer(account_type="HOME", business_name="Smith Household",
                               billing_email="smith@example.com",
                               service_address="12 Oak Ln",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        zone, customer = world["zone"], world["customer"]
        deliver_via_work_order(customer["id"], zone["id"], "2026-06-10", 2,
                               actual_bottles_delivered=2, actual_empties_collected=2)
        deliver_via_work_order(customer["id"], zone["id"], "2026-06-20", 2,
                               actual_bottles_delivered=2, actual_empties_collected=2)
        return world

    def test_deposit_refund_is_zero_under_exchange_parity(self, api):
        """PRD §3.8: "The net returned count is the opening count minus the
        closing count, floored at zero, and the `deposit_credit_cents` is that
        net count multiplied by the `bottle_deposit_cents` from the
        configuration in effect at period end."
        PRD §3.8: "Refunding at each individual pickup event is explicitly not
        the rule: under exchange parity a customer's count often stays flat
        while empties flow back, and per-event refunding would pay out deposits
        that were never truly returned, double-refunding against full-bottle
        deliveries in the same period."

        Two pickups in the period would refund 2*1500=3000 under the rejected
        per-event reading; the net-movement rule yields zero.

        Design: Difficulty/dual_variant_calc/deposit_refund_chronological_vs_per_event
        """
        world = self._exchange_parity_scenario(api)
        customer = world["customer"]
        invoice = create_and_issue_invoice(customer["id"], "2026-06-01",
                                           "2026-07-01", "2026-07-15")
        assert invoice["deposit_credit_cents"] == 0, (
            f"net movement is zero under exchange parity, so no deposit refund; "
            f"got {invoice['deposit_credit_cents']}"
        )

    def test_bottles_on_site_preserved_under_exchange_parity(self, api):
        """PRD §2.10: "The `bottles_on_site` count reflects how many full or
        owed bottles currently sit with the customer and is recomputed on every
        delivery, every exchange pickup, and every shortage marking. The
        `deposit_liability_cents` figure is purely derived, never independently
        stored: it is the customer's current `bottles_on_site` multiplied by the
        per-bottle deposit in the active pricing configuration."

        Delivering two full bottles and collecting two empties leaves the
        customer's custody flat, so the derived deposit liability stays zero.

        Design: Difficulty/dual_variant_calc/deposit_refund_chronological_vs_per_event
        """
        world = self._exchange_parity_scenario(api)
        customer = get_customer(world["customer"]["id"])
        assert customer["bottles_on_site"] == 0, (
            f"2 full delivered and 2 empties collected per stop must net to "
            f"zero custody, got {customer['bottles_on_site']}"
        )
        assert customer["deposit_liability_cents"] == 0


class TestPricingConfigTiling:
    def _deliver_and_invoice(self, api, customer, zone, date, bottles,
                             period_start, period_end):
        deliver_via_work_order(customer["id"], zone["id"], date, bottles,
                               actual_bottles_delivered=bottles,
                               actual_empties_collected=bottles)
        return create_and_issue_invoice(customer["id"], period_start, period_end,
                                        "2026-07-15")

    def _two_configs(self):
        zone = setup_zone(with_pricing=False)
        create_standard_pricing_config(effective_from="2026-01-01")
        create_standard_pricing_config(
            effective_from="2026-06-01",
            standard_per_bottle_cents=800, silver_per_bottle_cents=750,
            gold_per_bottle_cents=700,
        )
        return zone

    def test_delivery_on_new_config_boundary_uses_new_rate(self, api):
        """PRD §3.1: "Configurations tile time as half-open intervals: a config
        governs from its `effective_from` up to, but not including, the
        `effective_from` of the next one."
        PRD §3.4: "When a stop lands in `DELIVERED` or `PARTIAL`, the water
        charge is the per-bottle rate for the customer's `pricing_tier` — drawn
        from the pricing configuration in effect on the route's `service_date`,
        so `STANDARD` accounts pay `standard_per_bottle_cents`, `SILVER`
        accounts pay `silver_per_bottle_cents`, and `GOLD` accounts pay
        `gold_per_bottle_cents` — multiplied by `actual_bottles_delivered`."

        A delivery on 2026-06-01 — exactly the second config's effective_from —
        belongs to the new config (800c/bottle).

        Design: Difficulty/resource_temporal_overlap/pricing_config_period_no_overlap
        """
        zone = self._two_configs()
        customer = get_success_data(api_client.create_customer(
            create_customer_payload(zone["id"], account_type="OFFICE",
                                    business_name="BoundaryCo",
                                    billing_email="b@x.example",
                                    service_address="5 B",
                                    service_mode="WILL_CALL", par_level_bottles=0,
                                    pricing_tier="STANDARD"),
            OPS_ADMIN))
        invoice = self._deliver_and_invoice(api, customer, zone, "2026-06-01", 2,
                                            "2026-06-01", "2026-07-01")
        assert invoice["subtotal_water_cents"] == 1600, (
            f"boundary date belongs to the new config: 2*800=1600, "
            f"got {invoice['subtotal_water_cents']}"
        )

    def test_delivery_day_before_boundary_uses_old_rate(self, api):
        """PRD §3.1: "Configurations tile time as half-open intervals: a config
        governs from its `effective_from` up to, but not including, the
        `effective_from` of the next one."

        A delivery on 2026-05-31 falls before the second config's
        effective_from, so the original 700c rate governs.

        Design: Difficulty/resource_temporal_overlap/pricing_config_period_no_overlap
        """
        zone = self._two_configs()
        customer = get_success_data(api_client.create_customer(
            create_customer_payload(zone["id"], account_type="OFFICE",
                                    business_name="BoundaryCo",
                                    billing_email="b@x.example",
                                    service_address="5 B",
                                    service_mode="WILL_CALL", par_level_bottles=0,
                                    pricing_tier="STANDARD"),
            OPS_ADMIN))
        invoice = self._deliver_and_invoice(api, customer, zone, "2026-05-31", 2,
                                            "2026-05-01", "2026-06-01")
        assert invoice["subtotal_water_cents"] == 1400, (
            f"the day before the boundary still belongs to the old config: "
            f"2*700=1400, got {invoice['subtotal_water_cents']}"
        )


class TestPricingConfigValidation:
    def test_pricing_config_invalid_thresholds(self, api):
        """PRD §3.1: "Because `SILVER` must trigger before `GOLD`, the gold
        threshold must be strictly greater than the silver threshold; a
        configuration violating that ordering, or carrying non-positive amounts,
        is rejected with `ERR_INVALID_PRICING_CONFIG`."

        Design: Corner/validations/pricing_config_invalid_thresholds
        """
        set_clock("2026-05-01T00:00:00Z")
        res = api.create_pricing_config(
            create_pricing_config_payload(silver_volume_threshold=50,
                                          gold_volume_threshold=20),
            OPS_ADMIN,
        )
        validate_error(res, "ERR_INVALID_PRICING_CONFIG")
