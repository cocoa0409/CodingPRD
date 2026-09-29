"""Corner behaviour of the money: the month-to-date tier window, the void that cheapens a later
ticket, the into-plane minimum, and the invoice's rebate boundary and capped administration fee."""
import pytest

from test_helpers import fixtures as fx

BIG_CREDIT = 100_000_000_000


class TestUpliftLineAmountCorners:
    def test_the_tier_window_restarts_at_the_first_instant_of_the_month(self, api):
        """PRD §3.6: "The **cumulative volume** driving the tier is the account's month-to-date net
        liters: the sum of `net_liters` over that airline account's uplift tickets whose `status` is
        `POSTED` or `BILLED` and whose `created_at` falls between the first instant of the calendar UTC
        month containing this ticket's `created_at` and this ticket's own `created_at` inclusive, and it
        **includes this ticket itself**."
        PRD §3.6: "From that cumulative a whole-line differential rate `volume_tier_diff_cents_per_liter`
        is selected — 1.60 cents per liter once the cumulative reaches 500,000 liters, otherwise 2.40
        cents per liter once it reaches 100,000 liters, otherwise 3.20 cents per liter — and the rate
        applies to the entire line, not marginally."
        PRD §3.6: "Five components are then computed, each rounded half up to a whole number of cents
        **before** anything is summed: `fuel_component_cents` is the ticket's net liters multiplied by the
        sum of the account's `base_price_cents_per_liter` and the selected differential; the into-plane
        fee is the larger of 2,500 cents and net liters multiplied by 0.45 cents per liter; the flowage
        fee is net liters multiplied by 0.12 cents per liter; the federal excise is net liters multiplied
        by 1.14 cents per liter; and the state sales tax is 7.25 percent of the sum of the fuel component
        and the into-plane fee."

        Design: Corner/calculations/month_to_date_resets_at_the_month_boundary
        """
        # Twice the requested volume plus the heel, because PRD §3.6 checks the tank's
        # available volume at assignment after the authorisation reservation removed it.
        env = fx.setup_sequential_uplifts_for_account(uplift_liters=(500_000.0,),
                                                      opening_volume_liters=2_000_000.0,
                                                      credit_limit_cents=BIG_CREDIT)
        august = env["uplifts"][0]
        assert august["net_liters"] == pytest.approx(500000.00, abs=0.005)
        assert august["volume_tier_diff_cents_per_liter"] == pytest.approx(1.60, abs=0.005), \
            "half a million liters reaches the deepest tier"

        fx.set_clock("2026-08-31T23:59:00Z")
        assert fx.read_uplift(august["id"])["volume_tier_diff_cents_per_liter"] == \
            pytest.approx(1.60, abs=0.005)

        fx.set_clock("2026-09-01T06:00:00Z")
        account_id, tank_id = env["account"]["id"], env["tank"]["id"]
        flight = fx.register_flight(account_id, stand_code="A31",
                                    scheduled_departure_utc="2026-09-01T08:00:00Z")
        auth = fx.issue_authorization(account_id, flight["id"],
                                      max_authorized_liters=20_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0,
                                window_start_utc="2026-09-01T06:00:00Z",
                                window_end_utc="2026-09-01T07:30:00Z")
        fx.authorize_order(order["id"])
        fx.assign_order(order["id"], env["truck"]["id"])
        fx.start_order(order["id"])
        september = fx.post_uplift(order["id"], meter_start_liters=500_000.0,
                                   meter_end_liters=520_000.0, temperature_c=15.0)

        assert september["net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert september["volume_tier_diff_cents_per_liter"] == pytest.approx(3.20, abs=0.005), \
            "September starts a fresh month-to-date window of 20,000.00 liters"
        assert september["fuel_component_cents"] == 1304000
        assert fx.read_uplift(august["id"])["volume_tier_diff_cents_per_liter"] == \
            pytest.approx(1.60, abs=0.005), "the August ticket is never repriced"

    def test_a_voided_ticket_stops_pushing_later_tickets_up_the_tiers(self, api):
        """PRD §3.6: "The **cumulative volume** driving the tier is the account's month-to-date net
        liters: the sum of `net_liters` over that airline account's uplift tickets whose `status` is
        `POSTED` or `BILLED` and whose `created_at` falls between the first instant of the calendar UTC
        month containing this ticket's `created_at` and this ticket's own `created_at` inclusive, and it
        **includes this ticket itself**."
        PRD §3.6: "**Abort**, `FUELING → ABORTED`, carries an `abort_reason` of `SPILL`, `QUALITY_HOLD`,
        `AIRCRAFT_RELEASE` or `EQUIPMENT_FAILURE`, and compensates everything: every `POSTED` ticket on
        the order becomes `VOIDED` with `voided_reason` `ORDER_ABORTED` and its `net_liters` are credited
        back to the tank's `book_volume_liters`; the requested volume is subtracted from the tank's
        `reserved_volume_liters`; for truck delivery the asset's `onboard_volume_liters` recomputes to
        0.0 as the voided tickets leave the posted set, so the sum of tank book volume and on-board volume
        returns to exactly its pre-fuelling value; the authorization is driven `ISSUED → VOIDED` with
        `voided_reason` `ORDER_CANCELLED`; pit occupancy ends; and the account's accrual exposure returns
        to its pre-authorization value."

        Design: Corner/calculations/voiding_a_ticket_can_cheapen_a_later_one
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=100_000.0, temperature_c=15.0,
            requested_uplift_liters=100_000.0, max_authorized_liters=100_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": BIG_CREDIT})
        big = fx.read_uplift(env["uplift"]["id"])
        assert big["volume_tier_diff_cents_per_liter"] == pytest.approx(2.40, abs=0.005)

        fx.abort_order(env["order"]["id"], abort_reason="AIRCRAFT_RELEASE")
        voided = fx.read_uplift(env["uplift"]["id"])
        assert voided["status"] == "VOIDED"
        assert voided["volume_tier_diff_cents_per_liter"] == pytest.approx(2.40, abs=0.005), \
            "the retired ticket keeps the rate it was priced at"

        account_id, tank_id = env["account"]["id"], env["tank"]["id"]
        flight = fx.register_flight(account_id, stand_code="B09",
                                    scheduled_departure_utc="2026-08-10T09:00:00Z")
        auth = fx.issue_authorization(account_id, flight["id"],
                                      max_authorized_liters=20_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0)
        fx.authorize_order(order["id"])
        fx.assign_order(order["id"], env["truck"]["id"])
        fx.start_order(order["id"])
        fresh = fx.post_uplift(order["id"], meter_start_liters=100_000.0,
                               meter_end_liters=120_000.0, temperature_c=15.0)

        assert fresh["volume_tier_diff_cents_per_liter"] == pytest.approx(3.20, abs=0.005), \
            "the voided 100,000.00 liters have left the cumulative"
        assert fresh["fuel_component_cents"] == 1304000

    def test_the_into_plane_minimum_swallows_a_small_ticket_and_the_tax_follows_it(self, api):
        """PRD §3.6: "Five components are then computed, each rounded half up to a whole number of cents
        **before** anything is summed: `fuel_component_cents` is the ticket's net liters multiplied by the
        sum of the account's `base_price_cents_per_liter` and the selected differential; the into-plane
        fee is the larger of 2,500 cents and net liters multiplied by 0.45 cents per liter; the flowage
        fee is net liters multiplied by 0.12 cents per liter; the federal excise is net liters multiplied
        by 1.14 cents per liter; and the state sales tax is 7.25 percent of the sum of the fuel component
        and the into-plane fee."
        PRD §3.6: "The `billed_line_cents` is the sum of those five already-rounded components."

        Design: Corner/calculations/into_plane_minimum_dominates_a_small_ticket
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=5_000.0, temperature_c=15.0, requested_uplift_liters=5_000.0,
            max_authorized_liters=5_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False})

        ticket = fx.read_uplift(env["uplift"]["id"])
        assert ticket["net_liters"] == pytest.approx(5000.00, abs=0.005)
        assert ticket["fuel_component_cents"] == 326000
        # PRD names only `fuel_component_cents` and `billed_line_cents` as ticket fields, so the
        # floored into-plane fee is verified through the total: 326000 + 2500 (the 2,500 floor
        # beating the 2,250 the volume earns) + 600 + 5700 + 23816, the tax being 7.25 percent
        # of 328,500 — the floored fee, not the 2,250 that lost.
        assert ticket["billed_line_cents"] == 358616


class TestInvoiceTotalCorners:
    def test_the_rebate_band_opens_at_exactly_one_hundred_thousand_liters(self, api):
        """PRD §3.9: "**Step two** computes the volume rebate, which is keyed on liters and applied to
        the fuel component only: the rate is 1.5 percent once the swept volume reaches 250,000 liters,
        otherwise 0.75 percent once it reaches 100,000 liters, otherwise nothing at all, and
        `volume_rebate_cents` is the fuel component multiplied by that rate, rounded half up to whole
        cents."
        PRD §3.9: "**Step one** sums the swept figures: `swept_net_liters` is the sum of the tickets'
        `net_liters` rounded half up to two decimals, `fuel_component_cents` is the sum of the tickets'
        own `fuel_component_cents`, and `subtotal_cents` is the sum of the tickets' `billed_line_cents`,
        each of which was already rounded to whole cents when the ticket was posted."
        PRD §3.9: "**Step four** sets `total_cents` to the subtotal, less the rebate, plus the admin
        fee."

        Design: Corner/calculations/rebate_boundary_at_exactly_one_hundred_thousand_liters
        """
        env = fx.setup_sequential_uplifts_for_account(
            uplift_liters=(30_000.0, 30_000.0, 40_000.0), credit_limit_cents=BIG_CREDIT)
        lines = [fx.read_uplift(u["id"])["billed_line_cents"] for u in env["uplifts"]]
        assert lines == [2150089, 2150089, 2832465]

        invoice = fx.create_draft_invoice(env["account"]["id"])

        assert invoice["swept_net_liters"] == pytest.approx(100000.00, abs=0.005)
        assert invoice["fuel_component_cents"] == 6488000
        assert invoice["subtotal_cents"] == 7132643
        assert invoice["volume_rebate_cents"] == 48660, \
            "exactly 100,000.00 liters reaches the 0.75 percent band, which is inclusive"
        assert invoice["admin_fee_cents"] == 28336
        assert invoice["total_cents"] == 7112319, \
            "7,132,643 less the 48,660 rebate plus the 28,336 fee"

    def test_the_administration_fee_stops_dead_at_five_hundred_dollars(self, api):
        """PRD §3.9: "**Step three** computes the consortium administration fee on the post-rebate
        subtotal: `admin_fee_cents` is the smaller of 50,000 cents and four tenths of one percent of the
        subtotal less the rebate, rounded half up to whole cents."
        PRD §3.9: "**Step two** computes the volume rebate, which is keyed on liters and applied to the
        fuel component only: the rate is 1.5 percent once the swept volume reaches 250,000 liters,
        otherwise 0.75 percent once it reaches 100,000 liters, otherwise nothing at all, and
        `volume_rebate_cents` is the fuel component multiplied by that rate, rounded half up to whole
        cents."
        PRD §3.9: "The draft's totals are then computed in four strictly ordered steps, and the order
        matters because the rebate is keyed on volume while the admin fee is keyed on the post-rebate
        money total, which makes the two look mutually dependent when they are not."

        Design: Corner/calculations/admin_fee_cap_binds_at_a_large_subtotal
        """
        env = fx.setup_sequential_uplifts_for_account(
            uplift_liters=(100_000.0, 100_000.0, 100_000.0, 100_000.0),
            credit_limit_cents=BIG_CREDIT)

        invoice = fx.create_draft_invoice(env["account"]["id"])

        assert invoice["swept_net_liters"] == pytest.approx(400000.00, abs=0.005)
        assert invoice["fuel_component_cents"] == 25760000
        assert invoice["subtotal_cents"] == 28324652
        assert invoice["volume_rebate_cents"] == 386400, "1.5 percent of the fuel component"
        assert invoice["admin_fee_cents"] == 50000, \
            "four tenths of a percent of 27,938,252 would have been 111,753, so the cap binds"
        assert invoice["total_cents"] == 27988252

    def test_a_one_ticket_invoice_is_its_line_plus_the_fee_and_nothing_else(self, api):
        """PRD §3.9: "**Step one** sums the swept figures: `swept_net_liters` is the sum of the tickets'
        `net_liters` rounded half up to two decimals, `fuel_component_cents` is the sum of the tickets'
        own `fuel_component_cents`, and `subtotal_cents` is the sum of the tickets' `billed_line_cents`,
        each of which was already rounded to whole cents when the ticket was posted."
        PRD §3.9: "**Step three** computes the consortium administration fee on the post-rebate subtotal:
        `admin_fee_cents` is the smaller of 50,000 cents and four tenths of one percent of the subtotal
        less the rebate, rounded half up to whole cents."
        PRD §3.9: "**Step four** sets `total_cents` to the subtotal, less the rebate, plus the admin
        fee."

        Design: Corner/calculations/single_ticket_invoice_equals_its_line_plus_fees
        """
        env = fx.setup_issued_invoice(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False})
        ticket = fx.read_uplift(env["uplift"]["id"])
        invoice = fx.read_invoice(env["invoice"]["id"])

        assert invoice["swept_net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert invoice["subtotal_cents"] == ticket["billed_line_cents"] == 1433393
        assert invoice["volume_rebate_cents"] == 0, "20,000 liters is far short of 100,000"
        assert invoice["admin_fee_cents"] == 5734, "four tenths of a percent of 1,433,393"
        assert invoice["total_cents"] == 1439127
        assert invoice["total_cents"] == invoice["subtotal_cents"] + invoice["admin_fee_cents"]
