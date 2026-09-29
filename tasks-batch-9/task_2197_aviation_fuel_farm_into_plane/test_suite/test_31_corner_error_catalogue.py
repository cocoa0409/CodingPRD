"""Corner behaviour of the error catalogue itself: one status per identifier, identifiers rather than message
text as the only contract, and exactly one identifier per failed request."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    make_airline_rep_headers, fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000
PIPELINE_PARCEL = dict(delivery_mode="PIPELINE", supplier_name="Refinery One",
                       meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
                       tank_closing_gauge_liters=29700.0, temperature_c=15.0,
                       certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)


class TestErrorIdToStatusPairing:
    def test_each_identifier_carries_its_own_single_http_status(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not exactly one of the seven role
        names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "When the headers are well formed but the named role is not among the roles authorised for
        the requested endpoint, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.1: "Concretely, an `AirlineRep` acting on a flight, a fuel authorization, a fuelling order or
        an invoice whose owning account is not the account named by `X-User-ID` is rejected with
        `ERR_ACCOUNT_OWNERSHIP_REQUIRED` (HTTP 403); for a fuelling order or an uplift ticket the owning
        account is reached through the order's flight."
        PRD §2.1: "**Segregation of duties.** Three workflow steps compare the acting `X-User-ID` against
        the identifier recorded at the preceding step of the same workflow, and reject a match with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): an inspector may not sign a receipt verdict when the acting
        identifier equals the receipt's `sampled_by_user_id`; an inspector may not release a tank on the
        quality dimension when the acting identifier equals the `drawn_by_user_id` of the governing periodic
        tank sample; and a billing clerk may not resolve a dispute on an invoice whose `issued_by_user_id`
        equals the acting identifier."
        PRD §2.9: "If `expected_fueling_order_version` does not equal the order's current `version`, the
        post is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), which is what prevents a ticket from
        being written against an out-of-date view of the order's posted volume and the tank reservation
        behind it."
        PRD §3.6: "The airline account's `status` must be `ACTIVE` and the accrual-basis exposure, including
        this order's freshly computed `reserved_amount_cents`, must not exceed the account's
        `credit_limit_cents`; failure either way is `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402), which is also how
        a `CREDIT_HOLD` account is refused."
        PRD §5: "The trigger condition for each identifier is specified in the §2 and §3 narratives where
        the rule it guards is described."

        Design: Corner/errors/every_error_id_maps_to_exactly_one_status
        """
        env = fx.setup_truck_order(target_state="FUELING",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id, tank_id = env["order"]["id"], env["tank"]["id"]
        version = fx.current_order_version(order_id)

        # 401 is reached exactly once, by a request whose headers do not identify a role
        validate_error(api.create_fuel_farm(F.create_fuel_farm_payload(),
                                            {"X-User-Role": "ConsortiumAdmin",
                                             "Content-Type": "application/json"}),
                       ApiErrorId.ERR_UNAUTHENTICATED, 401)

        # the three 403 identifiers: role membership, account ownership, segregation of duties
        validate_error(api.create_fuel_farm(F.create_fuel_farm_payload(), fx.OPERATOR),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        stranger = fx.open_account()
        validate_error(api.create_flight(F.create_flight_payload(
            env["account"]["id"], scheduled_departure_utc="2026-08-10T11:00:00Z",
            stand_code="K09"), make_airline_rep_headers(stranger["id"])),
                       ApiErrorId.ERR_ACCOUNT_OWNERSHIP_REQUIRED, 403)
        receipt, _sample = fx.make_tested_receipt(tank_id, **PIPELINE_PARCEL)
        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_A),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        # the two 404 identifiers: a path id and a body foreign key
        validate_error(api.get_fueling_order(NON_EXISTENT_UUID, fx.AGENT),
                       ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)
        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(NON_EXISTENT_UUID), fx.OPERATOR),
                       ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND, 404)

        # 400 for shape, 422 for a declared constraint, 409 for scoped uniqueness
        validate_error(api.create_uplift_record(order_id, F.create_uplift_record_payload(
            version, meter_start_liters=0.0, meter_end_liters="20000",
            temperature_c=15.0), fx.AGENT), ApiErrorId.ERR_INVALID_PAYLOAD, 400)
        validate_error(api.create_uplift_record(order_id, F.create_uplift_record_payload(
            version, meter_start_liters=5000.0, meter_end_liters=4000.0,
            temperature_c=15.0), fx.AGENT), ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)
        validate_error(api.create_fuel_farm(
            F.create_fuel_farm_payload(iata_code=env["farm"]["iata_code"]), fx.ADMIN),
                       ApiErrorId.ERR_DUPLICATE_KEY, 409)

        # 412 for the order-version guard
        validate_error(api.create_uplift_record(order_id, F.create_uplift_record_payload(
            1, meter_start_liters=0.0, meter_end_liters=20_000.0, temperature_c=15.0),
            fx.AGENT), ApiErrorId.ERR_STALE_ORDER_VERSION, 412)

        # 402 belongs to the credit check alone
        poor = fx.setup_truck_order(target_state="REQUESTED",
                                    account_overrides={"credit_limit_cents": 1000})
        validate_error(api.authorize_order(poor["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)


class TestOnlyTheIdentifierIsContractual:
    def test_two_near_duplicate_refusals_are_told_apart_by_id_alone(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
        PRD §3.3: "The destination tank's current `book_volume_liters` plus the receipt's
        `net_volume_liters` must not exceed the tank's `safe_fill_liters`, or the release is refused with
        `ERR_SAFE_FILL_EXCEEDED`."
        PRD §3.3: "The farm's `active_permit_throughput_used_liters` plus the receipt's net volume must not
        exceed the governing permit's `max_daily_throughput_liters`, or the release is refused with
        `ERR_PERMIT_THROUGHPUT_EXCEEDED`."

        Design: Corner/errors/message_text_is_never_asserted
        """
        tight_shell = fx.setup_fuel_farm(
            permit_overrides={"max_daily_throughput_liters": 5_000_000.0})
        small_tank = fx.make_released_tank(tight_shell["farm"]["id"],
                                          capacity_liters=5_000_000.0,
                                          safe_fill_liters=20_000.0,
                                          density_kg_per_m3=795.0,
                                          opening_volume_liters=0.0)
        shell_receipt, _s1 = fx.make_tested_receipt(small_tank["id"], **PIPELINE_PARCEL)
        shell_refusal = api.sign_receipt_verdict(shell_receipt["id"],
                                                 {"decision": "RELEASE"}, fx.INSPECTOR_B)

        tight_permit = fx.setup_fuel_farm(
            permit_overrides={"max_daily_throughput_liters": 10_000.0})
        big_tank = fx.make_released_tank(tight_permit["farm"]["id"],
                                        capacity_liters=5_000_000.0,
                                        safe_fill_liters=4_000_000.0,
                                        density_kg_per_m3=795.0,
                                        opening_volume_liters=0.0)
        permit_receipt, _s2 = fx.make_tested_receipt(big_tank["id"], **PIPELINE_PARCEL)
        permit_refusal = api.sign_receipt_verdict(permit_receipt["id"],
                                                  {"decision": "RELEASE"}, fx.INSPECTOR_B)

        validate_error(shell_refusal, ApiErrorId.ERR_SAFE_FILL_EXCEEDED, 409)
        validate_error(permit_refusal, ApiErrorId.ERR_PERMIT_THROUGHPUT_EXCEEDED, 409)

        shell_body, permit_body = shell_refusal.json()["data"], permit_refusal.json()["data"]
        assert shell_body["error_id"] != permit_body["error_id"], \
            "the same 29,700-liter parcel is refused for two reasons that only the id tells apart"
        for body in (shell_body, permit_body):
            assert isinstance(body["message"], str)
            assert body["message"] != "", \
                "a message must exist, but nothing about its wording is contractual"

    def test_a_request_that_breaks_several_rules_answers_with_one_identifier(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."
        PRD §2.10: "When several checks could reject the same request, the order in which they are evaluated
        is part of the contract, because it determines which error identifier the caller sees."
        PRD §2.10: "**Existence.** Path identifiers are resolved left to right (`ERR_RESOURCE_NOT_FOUND`)
        on every endpoint carrying a path parameter, then body foreign keys are resolved in the order the
        fields are listed in the endpoint's input (`ERR_REFERENCED_ENTITY_NOT_FOUND`), then aggregate
        agreement is checked (`ERR_CROSS_FARM_REFERENCE`) on fuelling order creation and order assignment —
        specifically that the quoted authorization's flight matches the order's flight, that the hydrant pit
        and the storage tank belong to the same farm, and that the fuelling asset and the storage tank belong
        to the same farm."
        PRD §2.10: "A request that is both unauthorised and fiscally impossible reports the authorisation
        failure."

        Design: Corner/errors/no_error_leaks_a_stack_trace_or_a_second_id
        """
        env = fx.setup_truck_order(target_state="REQUESTED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        # three separate failures in one payload: an unknown flight, a reversed window and a bad code
        broken = F.create_fueling_order_payload(
            NON_EXISTENT_UUID, env["auth"]["id"], env["tank"]["id"], "WRONGCODE0000",
            delivery_mode="TRUCK", requested_uplift_liters=20_000.0,
            window_start_utc="2026-08-10T07:30:00Z", window_end_utc="2026-08-10T06:00:00Z")

        response = api.create_fueling_order(broken, fx.AGENT)
        validate_error(response, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND, 404)

        body = response.json()
        assert set(body.keys()) == {"data", "meta", "response_type"}
        assert set(body["data"].keys()) == {"error_id", "message"}, \
            "no errors array and no field-level detail map, just the winning identifier"
        assert "Traceback" not in body["data"]["message"]
