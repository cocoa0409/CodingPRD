"""Corner behaviour of the deterministic authorization code: the zero-padded check group, the
departure-day sequence counter, the byte-exact quotation, and the departure-plus-two-hours expiry."""
import pytest

from test_helpers import (
    assert_same_instant,
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)


class TestAuthorizationCodeCorners:
    def test_a_small_check_remainder_is_padded_to_two_characters(self, api):
        """PRD §3.5: "The final two characters are a check value: the ASCII code points of the twelve body
        characters are summed, the remainder of that sum on division by 97 is taken, and that remainder is
        zero-padded to two digits."
        PRD §3.5: "It is assembled as fourteen characters in three parts plus a check."
        PRD §3.5: "The first two characters are the account's `airline_iata_code`. The next six are the
        flight's `scheduled_departure_utc` rendered in UTC as a two-digit year, then a two-digit month,
        then a two-digit day. The next four are the `day_sequence` zero-padded to four digits, where the
        day sequence is one more than the number of authorizations already existing for the same airline
        account whose flight departs on the same UTC calendar day, counted in `created_at` ascending order
        and counted regardless of status — voided and expired authorizations still consume their sequence
        number, so a number is never reused."

        Design: Corner/calculations/check_digits_are_zero_padded_to_two_characters
        """
        fx.set_clock()
        account = fx.open_account(airline_iata_code="ZZ")
        flight = fx.register_flight(account["id"], stand_code="A12",
                                    scheduled_departure_utc="2026-08-18T08:00:00Z")

        auth = fx.issue_authorization(account["id"], flight["id"],
                                      max_authorized_liters=20_000.0)

        assert auth["day_sequence"] == 1
        assert auth["authorization_code"] == "ZZ260818000107", \
            "the twelve body characters sum to a remainder of 7, which is rendered as 07"
        assert len(auth["authorization_code"]) == 14
        assert auth["authorization_code"][-2:] == "07"

    def test_the_sequence_counter_is_keyed_on_the_departure_day(self, api):
        """PRD §3.5: "The next four are the `day_sequence` zero-padded to four digits, where the day
        sequence is one more than the number of authorizations already existing for the same airline
        account whose flight departs on the same UTC calendar day, counted in `created_at` ascending order
        and counted regardless of status — voided and expired authorizations still consume their sequence
        number, so a number is never reused."
        PRD §3.5: "The next six are the flight's `scheduled_departure_utc` rendered in UTC as a two-digit
        year, then a two-digit month, then a two-digit day."
        PRD §3.5: "The `authorization_code` is minted deterministically, with no random component, so it
        is fully reproducible from the account, the flight and the issuance order."

        Design: Corner/calculations/day_sequence_is_keyed_on_the_departure_day_not_the_creation_day
        """
        fx.set_clock("2026-08-10T06:00:00Z")
        account = fx.open_account(airline_iata_code="QQ")
        today = fx.register_flight(account["id"], stand_code="A12",
                                   scheduled_departure_utc="2026-08-10T08:00:00Z")
        tomorrow = fx.register_flight(account["id"], stand_code="A13",
                                      scheduled_departure_utc="2026-08-11T08:00:00Z")

        first = fx.issue_authorization(account["id"], today["id"],
                                       max_authorized_liters=20_000.0)
        second = fx.issue_authorization(account["id"], tomorrow["id"],
                                        max_authorized_liters=20_000.0)

        assert first["day_sequence"] == 1
        assert second["day_sequence"] == 1, \
            "both were minted on the 10th, but they depart on different days"
        assert first["authorization_code"] == "QQ260810000178"
        assert second["authorization_code"] == "QQ260811000179"

        third = fx.issue_authorization(account["id"], today["id"],
                                       max_authorized_liters=20_000.0)
        assert third["day_sequence"] == 2, "the 10th's counter, and only the 10th's, moved on"
        assert third["authorization_code"] == "QQ260810000279"

    def test_the_quoted_code_is_compared_byte_for_byte(self, api):
        """PRD §3.6: "That quoted code must equal the authorization's minted `authorization_code`
        character for character, and any discrepancy is rejected with `ERR_AUTH_CODE_MISMATCH` — checked
        both when the order is raised and again when it is authorised."
        PRD §2.10: "**Referential business checks.** The quoted authorization code must match character
        for character (`ERR_AUTH_CODE_MISMATCH`) — checked on both fuelling order creation and order
        authorization — and then the authorization must still be redeemable
        (`ERR_AUTHORIZATION_NOT_REDEEMABLE`) on order authorization."
        PRD §3.5: "The first two characters are the account's `airline_iata_code`."

        Design: Corner/calculations/quoted_code_is_compared_exactly
        """
        env = fx.setup_farm_with_released_tank()
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        account = fx.open_account(airline_iata_code="ZZ",
                                  base_price_cents_per_liter=62.00,
                                  credit_limit_cents=100_000_000)
        flight = fx.register_flight(account["id"], stand_code="A12")
        auth = fx.issue_authorization(account["id"], flight["id"],
                                      max_authorized_liters=20_000.0)
        code = auth["authorization_code"]
        assert code.startswith("ZZ")

        lowercased = code[:2].lower() + code[2:]
        validate_error(api.create_fueling_order(
            F.create_fueling_order_payload(flight["id"], auth["id"], env["tank"]["id"],
                                           lowercased, requested_uplift_liters=20_000.0,
                                           window_start_utc=fx.WINDOW_START,
                                           window_end_utc=fx.WINDOW_END), fx.AGENT),
            ApiErrorId.ERR_AUTH_CODE_MISMATCH, 422)

        orders, _meta = validate_paginated(api.list_fueling_orders(fx.AGENT))
        assert orders == [], "no normalisation, no order"

        accepted = fx.create_order(flight["id"], auth["id"], env["tank"]["id"], code,
                                   delivery_mode="TRUCK", requested_uplift_liters=20_000.0)
        assert accepted["quoted_authorization_code"] == code, \
            "the very same string is accepted the moment its case is right"

    def test_the_authorization_dies_exactly_two_hours_after_departure(self, api):
        """PRD §3.5: "The `expires_at_utc` is set to the flight's scheduled departure plus 2 hours, and
        the authorization opens in `ISSUED` with `voided_reason` null."
        PRD §3.5: "It becomes `EXPIRED` by the system once the logical clock has reached or passed its
        `expires_at_utc`; this is evaluated lazily whenever the authorization is read or referenced after a
        clock advance, and an expired authorization can no longer authorise an order."
        PRD §3.6: "The quoted authorization must be `ISSUED` and the logical clock must be strictly before
        its `expires_at_utc`, or the request fails with `ERR_AUTHORIZATION_NOT_REDEEMABLE`."

        Design: Corner/calculations/expiry_is_departure_plus_two_hours
        """
        env = fx.setup_truck_order(
            target_state="REQUESTED", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            flight_overrides={"scheduled_departure_utc": "2026-08-10T08:00:00Z"},
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000})
        auth_id = env["auth"]["id"]
        assert_same_instant(env["auth"]["expires_at_utc"], "2026-08-10T10:00:00Z",
                            "expires_at_utc")

        fx.set_clock("2026-08-10T09:59:59Z")
        alive = fx.read_authorization(auth_id)
        assert alive["status"] == "ISSUED", "one second short of the expiry is still one second short"

        authorized = validate_success(api.authorize_order(env["order"]["id"], fx.AGENT))
        assert authorized["status"] == "AUTHORIZED", "and it is still redeemable"

        fx.set_clock("2026-08-10T10:00:00Z")
        assert fx.read_authorization(auth_id)["status"] == "EXPIRED", \
            "the comparison is inclusive, so the stroke of the second hour kills it"
        assert fx.read_order(env["order"]["id"])["reserved_amount_cents"] == 1313000
