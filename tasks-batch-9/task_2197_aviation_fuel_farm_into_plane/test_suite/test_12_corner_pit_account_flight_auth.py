"""Corner behaviour of the commercial side and the ramp's scarce plumbing: pit lockout on tank
retirement, the two contract collapses in the pricing formula, flight ownership, and the
deterministic authorization code with its never-reused day sequence."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F, make_airline_rep_headers,
)


class TestHydrantPitCorners:
    def test_retiring_the_source_tank_locks_out_only_the_pits_it_feeds(self, api):
        """PRD §3.4: "Retirement additionally locks out every hydrant pit whose
        `source_storage_tank_id` names this tank, setting each pit's `status` to `LOCKED_OUT`, then
        recomputes posture and raises both versions."
        PRD §3.4: "Retiring a tank, `ISOLATED → OUT_OF_SERVICE`, is a `ConsortiumAdmin` action
        permitted only once the tank has been drained down to its unpumpable heel: the tank's
        `book_volume_liters` must not exceed the farm's `unpumpable_bottom_liters`."
        PRD §3.1: "A pit's `status` starts `AVAILABLE`; the only other value, `LOCKED_OUT`, is
        reserved for administrative lockout when the pit's source tank is taken out of service, and is
        never used to represent momentary occupancy by an order."

        Design: Corner/entities/pit_locked_out_when_source_tank_goes_out_of_service
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0,
                                               hydrant_system_available=True)
        farm_id, doomed = env["farm"]["id"], env["tank"]["id"]
        spare = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                 safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                 opening_volume_liters=0.0)
        fed_a = fx.register_pit(farm_id, doomed, stand_code="A12")
        fed_b = fx.register_pit(farm_id, doomed, stand_code="A13")
        untouched = fx.register_pit(farm_id, spare["id"], stand_code="A14")
        assert [p["status"] for p in (fed_a, fed_b, untouched)] == ["AVAILABLE"] * 3

        fx.isolate_tank(doomed, "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        retired = validate_success(api.change_tank_service_status(
            doomed, {"to_status": "OUT_OF_SERVICE"}, fx.ADMIN))
        assert retired["service_status"] == "OUT_OF_SERVICE"

        assert fx.read_pit(fed_a["id"])["status"] == "LOCKED_OUT"
        assert fx.read_pit(fed_b["id"])["status"] == "LOCKED_OUT"
        assert fx.read_pit(untouched["id"])["status"] == "AVAILABLE", \
            "lockout follows the source tank, not the farm"


class TestAirlineAccountCorners:
    def test_an_exemption_certificate_zeroes_the_excise_and_the_sales_tax(self, api):
        """PRD §3.6: "Five components are then computed, each rounded half up to a whole number of
        cents **before** anything is summed: `fuel_component_cents` is the ticket's net liters
        multiplied by the sum of the account's `base_price_cents_per_liter` and the selected
        differential; the into-plane fee is the larger of 2,500 cents and net liters multiplied by 0.45
        cents per liter; the flowage fee is net liters multiplied by 0.12 cents per liter; the federal
        excise is net liters multiplied by 1.14 cents per liter; and the state sales tax is 7.25 percent
        of the sum of the fuel component and the into-plane fee."
        PRD §3.6: "When the account's `tax_exempt` flag is true both the excise and the sales tax are
        zero."
        PRD §3.1: "The optional `tax_exempt` flag, defaulting to false, records that a valid federal
        excise and state sales tax exemption certificate is on file."

        Design: Corner/entities/tax_exempt_account_zeroes_both_tax_components
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, temperature_c=15.0,
            requested_uplift_liters=20_000.0, max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": True},
            permit_overrides={"max_daily_throughput_liters": 400000.0})

        ticket = fx.read_uplift(env["uplift"]["id"])
        assert ticket["net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert ticket["volume_tier_diff_cents_per_liter"] == pytest.approx(3.20, abs=0.005)
        assert ticket["fuel_component_cents"] == 1304000
        # PRD names only `fuel_component_cents` and `billed_line_cents` as ticket fields; the
        # other four components appear in the formula alone, so the exempt line is verified
        # through the total: 1304000 + 9000 + 2400 with both tax components at zero.
        assert ticket["billed_line_cents"] == 1315400, \
            "1304000 + 9000 + 2400, where a taxed line would have reached 1433393"

    def test_an_into_plane_only_line_is_handling_charges_only(self, api):
        """PRD §3.6: "For an `INTO_PLANE_ONLY` account the picture collapses: the account's base price
        is zero, no differential is applied, `fuel_component_cents` is zero, and `billed_line_cents` is
        just the into-plane fee plus the flowage fee."
        PRD §3.1: "A `CONTRACT_FUEL` airline buys product at the consortium contract price; an
        `INTO_PLANE_ONLY` airline supplies its own fuel and pays handling only, so its
        `base_price_cents_per_liter` is zero."

        Design: Corner/entities/into_plane_only_contract_drops_the_fuel_component
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, temperature_c=15.0,
            requested_uplift_liters=20_000.0, max_authorized_liters=20_000.0,
            account_overrides={"contract_type": "INTO_PLANE_ONLY",
                               "base_price_cents_per_liter": 0.0,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False},
            permit_overrides={"max_daily_throughput_liters": 400000.0})

        ticket = fx.read_uplift(env["uplift"]["id"])
        assert ticket["net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert ticket["fuel_component_cents"] == 0
        assert ticket["billed_line_cents"] == 11400, \
            "handling only: 9000 + 2400, with no fuel and no tier differential"


class TestFlightCorners:
    def test_a_rep_may_not_register_a_flight_for_a_neighbouring_airline(self, api):
        """PRD §2.1: "Concretely, an `AirlineRep` acting on a flight, a fuel authorization, a fuelling
        order or an invoice whose owning account is not the account named by `X-User-ID` is rejected
        with `ERR_ACCOUNT_OWNERSHIP_REQUIRED` (HTTP 403); for a fuelling order or an uplift ticket the
        owning account is reached through the order's flight."
        PRD §2.10: "Header presence and role validity (`ERR_UNAUTHENTICATED`) is checked first, then
        endpoint role membership (`ERR_ROLE_NOT_PERMITTED`), then — for the five operations an
        `AirlineRep` may reach, namely flight creation, fuel authorization creation, fuelling order
        creation, fuelling order cancellation and invoice dispute — account ownership
        (`ERR_ACCOUNT_OWNERSHIP_REQUIRED`)."

        Design: Corner/entities/flight_created_by_a_rep_of_another_account
        """
        first = fx.open_account()
        second = fx.open_account()
        intruder = make_airline_rep_headers(second["id"])

        validate_error(api.create_flight(
            F.create_flight_payload(first["id"], stand_code="A12",
                                    scheduled_departure_utc="2026-08-10T08:00:00Z"), intruder),
            ApiErrorId.ERR_ACCOUNT_OWNERSHIP_REQUIRED, 403)

        flights, _meta = validate_paginated(api.list_flights(
            fx.ADMIN, {"airline_account_id": first["id"]}))
        assert flights == []

    def test_a_flight_that_already_departed_yields_an_unredeemable_authorization(self, api):
        """PRD §3.5: "The `expires_at_utc` is set to the flight's scheduled departure plus 2 hours, and
        the authorization opens in `ISSUED` with `voided_reason` null."
        PRD §3.6: "The quoted authorization must be `ISSUED` and the logical clock must be strictly
        before its `expires_at_utc`, or the request fails with `ERR_AUTHORIZATION_NOT_REDEEMABLE`."
        PRD §3.1: "A flight begins `SCHEDULED` and may later be `DEPARTED` or `CANCELLED`."

        Design: Corner/entities/departure_in_the_past_relative_to_the_logical_clock
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        account = fx.open_account(base_price_cents_per_liter=62.00,
                                  credit_limit_cents=100_000_000)

        flight = fx.register_flight(account["id"], stand_code="A12",
                                    scheduled_departure_utc="2026-08-10T03:00:00Z")
        assert flight["status"] == "SCHEDULED", "creation carries no temporal guard"

        auth = fx.issue_authorization(account["id"], flight["id"],
                                      max_authorized_liters=20_000.0)
        assert auth["expires_at_utc"][:19] == "2026-08-10T05:00:00", \
            "departure plus two hours already lies behind the 06:00Z clock"

        order = fx.create_order(flight["id"], auth["id"], env["tank"]["id"],
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0,
                                window_start_utc="2026-08-10T06:00:00Z",
                                window_end_utc="2026-08-10T07:00:00Z")

        validate_error(api.authorize_order(order["id"], fx.AGENT),
                       ApiErrorId.ERR_AUTHORIZATION_NOT_REDEEMABLE, 409)

        assert fx.read_order(order["id"])["status"] == "REQUESTED"
        assert fx.read_tank(env["tank"]["id"])["reserved_volume_liters"] == \
            pytest.approx(0.00, abs=0.005)


class TestFuelAuthorizationCorners:
    def test_a_voided_authorization_still_consumes_its_day_sequence(self, api):
        """PRD §3.5: "The next four are the `day_sequence` zero-padded to four digits, where the day
        sequence is one more than the number of authorizations already existing for the same airline
        account whose flight departs on the same UTC calendar day, counted in `created_at` ascending
        order and counted regardless of status — voided and expired authorizations still consume their
        sequence number, so a number is never reused."
        PRD §3.5: "It is `VOIDED` — manually by a `BillingClerk`, or by the system when the order that
        quoted it is cancelled or aborted, or by the freeze cascade — and the `voided_reason` records
        which: `MANUAL` for the clerk's own action, `ORDER_CANCELLED` when an order cancellation or
        abort drove it, and `FARM_FROZEN` when the farm freeze cascade drove it."

        Design: Corner/entities/day_sequence_counts_voided_and_expired_siblings
        """
        fx.set_clock()
        account = fx.open_account(airline_iata_code="AA")
        morning = fx.register_flight(account["id"], stand_code="A12",
                                     scheduled_departure_utc="2026-08-10T08:00:00Z")
        evening = fx.register_flight(account["id"], stand_code="A13",
                                     scheduled_departure_utc="2026-08-10T20:00:00Z")

        first = fx.issue_authorization(account["id"], morning["id"],
                                       max_authorized_liters=10_000.0)
        assert first["day_sequence"] == 1

        voided = validate_success(api.void_fuel_authorization(first["id"], fx.BILLING))
        assert voided["status"] == "VOIDED"
        assert voided["voided_reason"] == "MANUAL"

        second = fx.issue_authorization(account["id"], evening["id"],
                                        max_authorized_liters=10_000.0)
        assert second["day_sequence"] == 2, \
            "the retired sibling keeps its number out of circulation"
        assert second["authorization_code"] != first["authorization_code"]
        assert second["authorization_code"][2:12] == "2608100002"

    def test_the_code_is_a_reproducible_twelve_character_body_plus_a_mod_97_check(self, api):
        """PRD §3.5: "It is assembled as fourteen characters in three parts plus a check. The first two
        characters are the account's `airline_iata_code`. The next six are the flight's
        `scheduled_departure_utc` rendered in UTC as a two-digit year, then a two-digit month, then a
        two-digit day."
        PRD §3.5: "The final two characters are a check value: the ASCII code points of the twelve body
        characters are summed, the remainder of that sum on division by 97 is taken, and that remainder
        is zero-padded to two digits."
        PRD §3.5: "The `authorization_code` is minted deterministically, with no random component, so
        it is fully reproducible from the account, the flight and the issuance order."

        Design: Corner/entities/authorization_code_is_fourteen_characters_with_a_mod_97_check
        """
        fx.set_clock()
        account = fx.open_account(airline_iata_code="AA")
        flight = fx.register_flight(account["id"], stand_code="A12",
                                    scheduled_departure_utc="2026-08-10T08:00:00Z")

        auth = fx.issue_authorization(account["id"], flight["id"],
                                      max_authorized_liters=10_000.0)

        body = "AA" + "260810" + "0001"
        check = "{:02d}".format(sum(ord(char) for char in body) % 97)
        code = auth["authorization_code"]
        assert len(code) == 14
        assert code[:12] == body
        assert code[12:] == check
        assert code == body + check
        assert auth["status"] == "ISSUED"
        assert auth["voided_reason"] is None
