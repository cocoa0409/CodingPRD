"""Corner behaviour of the head of the validation ladder: authentication, role membership, account
ownership, existence, tenancy and payload shape, each proving which identifier the caller sees."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    build_user_headers, NON_EXISTENT_UUID, make_airline_rep_headers,
    fixtures as fx, factories as F,
)


class TestAuthenticationCorners:
    def test_an_invented_role_name_is_an_authentication_failure(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not exactly one of the seven role
        names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "When the headers are well formed but the named role is not among the roles authorised
        for the requested endpoint, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.1: "The seven roles are `ConsortiumAdmin`, `FarmOperator`, `QualityInspector`,
        `IntoPlaneAgent`, `AirlineRep`, `EnvironmentalOfficer`, and `BillingClerk`."

        Design: Corner/validations/unknown_role_string_is_unauthenticated_not_forbidden
        """
        fx.set_clock()
        driver = build_user_headers("someone", "TruckDriver")

        validate_error(api.create_fuel_farm(F.create_fuel_farm_payload(), driver),
                       ApiErrorId.ERR_UNAUTHENTICATED, 401)

        validate_error(api.create_fuel_farm(F.create_fuel_farm_payload(), fx.OPERATOR),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        admitted = validate_success(api.create_fuel_farm(F.create_fuel_farm_payload(),
                                                         fx.ADMIN), 201)
        assert admitted["posture"] == "FROZEN", \
            "an unresolvable role never reaches the endpoint's role list, while a real one does"

    def test_a_role_without_a_user_id_is_not_authenticated_either(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and
        `X-User-Role`, naming the role that user is acting in."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not exactly one of the seven role
        names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "For the other six roles — `ConsortiumAdmin`, `FarmOperator`, `QualityInspector`,
        `IntoPlaneAgent`, `EnvironmentalOfficer` and `BillingClerk` — `X-User-ID` is an opaque operator
        identifier not tied to any persisted entity."

        Design: Corner/validations/role_present_but_user_id_missing
        """
        env = fx.setup_fuel_farm()
        headerless = {"X-User-Role": "FarmOperator", "Content-Type": "application/json"}

        validate_error(api.get_fuel_farm(env["farm"]["id"], headerless),
                       ApiErrorId.ERR_UNAUTHENTICATED, 401)

        readable = validate_success(api.get_fuel_farm(env["farm"]["id"], fx.OPERATOR))
        assert readable["id"] == env["farm"]["id"], \
            "the same read with both headers present is perfectly ordinary"


class TestRoleMembershipCorners:
    def test_the_role_list_is_consulted_before_any_row_is_looked_up(self, api):
        """PRD §2.10: "**Authentication and authorisation.** Header presence and role validity
        (`ERR_UNAUTHENTICATED`) is checked first, then endpoint role membership
        (`ERR_ROLE_NOT_PERMITTED`), then — for the five operations an `AirlineRep` may reach, namely flight
        creation, fuel authorization creation, fuelling order creation, fuelling order cancellation and
        invoice dispute — account ownership (`ERR_ACCOUNT_OWNERSHIP_REQUIRED`)."
        PRD §2.10: "**Existence.** Path identifiers are resolved left to right
        (`ERR_RESOURCE_NOT_FOUND`) on every endpoint carrying a path parameter, then body foreign keys are
        resolved in the order the fields are listed in the endpoint's input
        (`ERR_REFERENCED_ENTITY_NOT_FOUND`), then aggregate agreement is checked
        (`ERR_CROSS_FARM_REFERENCE`) on fuelling order creation and order assignment — specifically that
        the quoted authorization's flight matches the order's flight, that the hydrant pit and the storage
        tank belong to the same farm, and that the fuelling asset and the storage tank belong to the same
        farm."
        PRD §2.10: "The practical reading is that structural problems always beat business problems,
        business-state problems beat safety problems, and safety problems beat money problems."

        Design: Corner/validations/role_check_precedes_resource_existence
        """
        validate_error(api.sign_receipt_verdict(NON_EXISTENT_UUID, {"decision": "RELEASE"},
                                                fx.BILLING),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        # Only a permitted role gets to learn that the id does not exist.
        validate_error(api.sign_receipt_verdict(NON_EXISTENT_UUID, {"decision": "RELEASE"},
                                                fx.INSPECTOR_B),
                       ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)


class TestOwnershipCorners:
    def test_staff_roles_act_across_every_airline_account(self, api):
        """PRD §2.1: "When `X-User-Role` is `AirlineRep`, `X-User-ID` is the `id` of the acting
        `AirlineAccount`; ownership checks on any resource that references an `AirlineAccount` compare the
        resource's airline-account reference to `X-User-ID`."
        PRD §3.6: "An into-plane order is the five-way join at the centre of ramp operations, and it may
        be raised by either an `IntoPlaneAgent` or the `AirlineRep` that owns the flight."
        PRD §2.1: "For the other six roles — `ConsortiumAdmin`, `FarmOperator`, `QualityInspector`,
        `IntoPlaneAgent`, `EnvironmentalOfficer` and `BillingClerk` — `X-User-ID` is an opaque operator
        identifier not tied to any persisted entity."

        Design: Corner/validations/non_airline_roles_bypass_the_ownership_check_entirely
        """
        env = fx.setup_farm_with_released_tank()
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        airline = fx.setup_airline(account_overrides={"credit_limit_cents": 100_000_000})

        created = validate_success(api.create_fueling_order(
            F.create_fueling_order_payload(
                airline["flight"]["id"], airline["auth"]["id"], env["tank"]["id"],
                airline["auth"]["authorization_code"], requested_uplift_liters=20_000.0,
                window_start_utc=fx.WINDOW_START, window_end_utc=fx.WINDOW_END),
            fx.AGENT), 201)

        assert created["status"] == "REQUESTED", \
            "the ownership rule is scoped to AirlineRep and no staff role is measured against it"
        assert created["flight_id"] == airline["flight"]["id"]

    def test_ownership_is_resolved_through_the_invoices_own_account(self, api):
        """PRD §2.1: "Concretely, an `AirlineRep` acting on a flight, a fuel authorization, a fuelling
        order or an invoice whose owning account is not the account named by `X-User-ID` is rejected with
        `ERR_ACCOUNT_OWNERSHIP_REQUIRED` (HTTP 403); for a fuelling order or an uplift ticket the owning
        account is reached through the order's flight."
        PRD §3.9: "An `AirlineRep` owning the account may dispute an issued invoice,
        `ISSUED → DISPUTED`, provided the acting identifier is the invoice's `airline_account_id`, the
        invoice's `amount_paid_cents` is zero, and its `dispute_round` is at most 1 — so an invoice may be
        disputed at most twice, and a third attempt on an invoice already at a `dispute_round` of 2 is
        rejected with `ERR_DISPUTE_LIMIT_REACHED`."
        PRD §2.10: "**Authentication and authorisation.** Header presence and role validity
        (`ERR_UNAUTHENTICATED`) is checked first, then endpoint role membership
        (`ERR_ROLE_NOT_PERMITTED`), then — for the five operations an `AirlineRep` may reach, namely flight
        creation, fuel authorization creation, fuelling order creation, fuelling order cancellation and
        invoice dispute — account ownership (`ERR_ACCOUNT_OWNERSHIP_REQUIRED`)."

        Design: Corner/validations/ownership_is_evaluated_through_the_parent_chain
        """
        env = fx.setup_issued_invoice(
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000})
        stranger = fx.open_account(credit_limit_cents=100_000_000)

        validate_error(api.dispute_invoice(env["invoice"]["id"],
                                           make_airline_rep_headers(stranger["id"])),
                       ApiErrorId.ERR_ACCOUNT_OWNERSHIP_REQUIRED, 403)
        assert fx.read_invoice(env["invoice"]["id"])["status"] == "ISSUED"

        owner = validate_success(api.dispute_invoice(
            env["invoice"]["id"], make_airline_rep_headers(env["account"]["id"])))
        assert owner["status"] == "DISPUTED", "the account named on the invoice is the one that may act"


class TestExistenceCorners:
    def test_a_missing_path_id_and_a_missing_body_reference_report_different_ids(self, api):
        """PRD §2.10: "**Existence.** Path identifiers are resolved left to right
        (`ERR_RESOURCE_NOT_FOUND`) on every endpoint carrying a path parameter, then body foreign keys are
        resolved in the order the fields are listed in the endpoint's input
        (`ERR_REFERENCED_ENTITY_NOT_FOUND`), then aggregate agreement is checked
        (`ERR_CROSS_FARM_REFERENCE`) on fuelling order creation and order assignment — specifically that
        the quoted authorization's flight matches the order's flight, that the hydrant pit and the storage
        tank belong to the same farm, and that the fuelling asset and the storage tank belong to the same
        farm."
        PRD §3.6: "The payload names the `flight_id` to be fuelled, the `fuel_authorization_id` being
        quoted, the `storage_tank_id` the product will be drawn from, a `delivery_mode` of either `HYDRANT`
        or `TRUCK`, a `requested_uplift_liters` strictly greater than zero expressing the net volume at 15
        degrees Celsius the airline wants, a `window_start_utc` and a `window_end_utc` strictly later than
        the start bounding the booked fuelling window, and a `quoted_authorization_code`."

        Design: Corner/validations/path_id_versus_body_fk_use_different_error_ids
        """
        env = fx.setup_farm_with_released_tank()
        airline = fx.setup_airline(account_overrides={"credit_limit_cents": 100_000_000})

        validate_error(api.create_fueling_order(
            F.create_fueling_order_payload(
                airline["flight"]["id"], airline["auth"]["id"], NON_EXISTENT_UUID,
                airline["auth"]["authorization_code"], requested_uplift_liters=20_000.0,
                window_start_utc=fx.WINDOW_START, window_end_utc=fx.WINDOW_END),
            fx.AGENT), ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND, 404)

        # The two 404s are never interchanged: a path id has its own identifier.
        validate_error(api.authorize_order(NON_EXISTENT_UUID, fx.AGENT),
                       ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)

    def test_a_well_formed_but_unissued_uuid_is_a_missing_row_not_a_bad_payload(self, api):
        """PRD §2.4: "Every resource carries a server-minted `id` that is a UUID string with no type
        prefix; clients never supply an `id`."
        PRD §2.10: "**Existence.** Path identifiers are resolved left to right
        (`ERR_RESOURCE_NOT_FOUND`) on every endpoint carrying a path parameter, then body foreign keys are
        resolved in the order the fields are listed in the endpoint's input
        (`ERR_REFERENCED_ENTITY_NOT_FOUND`), then aggregate agreement is checked
        (`ERR_CROSS_FARM_REFERENCE`) on fuelling order creation and order assignment — specifically that
        the quoted authorization's flight matches the order's flight, that the hydrant pit and the storage
        tank belong to the same farm, and that the fuelling asset and the storage tank belong to the same
        farm."
        PRD §2.10: "**Payload shape and static constraints.** Required-field presence and type
        correctness (`ERR_INVALID_PAYLOAD`) precede declared value constraints
        (`ERR_FIELD_OUT_OF_RANGE`), which cover every numeric range and enumeration membership declared in
        this document as well as the relational constraints — a receipt's closing gauge must exceed its
        opening gauge, an uplift's meter end reading must exceed its meter start reading, a fuelling
        window's end must be later than its start, a reconciliation or billing period's end must be later
        than its start, and a tank's safe fill volume must not exceed its shell capacity."

        Design: Corner/validations/syntactically_valid_but_unknown_uuid
        """
        fx.set_clock()

        # The id shape is never validated as a payload concern.
        validate_error(api.get_storage_tank(NON_EXISTENT_UUID, fx.OPERATOR),
                       ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)
        validate_error(api.get_fuel_farm(NON_EXISTENT_UUID, fx.ADMIN),
                       ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)


class TestTenancyCorners:
    def test_a_pit_from_another_farm_is_a_tenancy_failure_before_a_mode_failure(self, api):
        """PRD §2.10: "**Existence.** Path identifiers are resolved left to right
        (`ERR_RESOURCE_NOT_FOUND`) on every endpoint carrying a path parameter, then body foreign keys are
        resolved in the order the fields are listed in the endpoint's input
        (`ERR_REFERENCED_ENTITY_NOT_FOUND`), then aggregate agreement is checked
        (`ERR_CROSS_FARM_REFERENCE`) on fuelling order creation and order assignment — specifically that
        the quoted authorization's flight matches the order's flight, that the hydrant pit and the storage
        tank belong to the same farm, and that the fuelling asset and the storage tank belong to the same
        farm."
        PRD §2.10: "**Mode, temporal and capacity checks.** Delivery-mode coherence
        (`ERR_DELIVERY_MODE_MISMATCH`) is checked on order creation and order assignment."
        PRD §3.6: "Assignment stores the `fueling_asset_id` and, for hydrant work, the `hydrant_pit_id`,
        and records the order's pit occupancy for its window — note that the pit's own `status` is *not*
        changed to `LOCKED_OUT` by an assignment, because lockout means administrative unavailability, not
        momentary use."

        Design: Corner/validations/hydrant_pit_from_another_farm
        """
        env = fx.setup_hydrant_order(target_state="AUTHORIZED", stand_code="A12",
                                     account_overrides={"credit_limit_cents": 100_000_000})
        other = fx.setup_farm_with_released_tank(permit_overrides={"permit_number": "PN-OTHER-1"})
        foreign_pit = fx.register_pit(other["farm"]["id"], other["tank"]["id"],
                                      stand_code="A12")
        local_truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)

        validate_error(api.assign_order(env["order"]["id"],
                                        {"fueling_asset_id": local_truck["id"],
                                         "hydrant_pit_id": foreign_pit["id"]}, fx.AGENT),
                       ApiErrorId.ERR_CROSS_FARM_REFERENCE, 422)

        assert fx.read_order(env["order"]["id"])["status"] == "AUTHORIZED"
        assert fx.read_order(env["order"]["id"])["hydrant_pit_id"] is None, \
            "the tenancy check outranks the mode check and nothing was stored"


class TestPayloadShapeCorners:
    def test_a_wrongly_typed_number_is_diagnosed_before_its_value_is_judged(self, api):
        """PRD §2.10: "**Payload shape and static constraints.** Required-field presence and type
        correctness (`ERR_INVALID_PAYLOAD`) precede declared value constraints
        (`ERR_FIELD_OUT_OF_RANGE`), which cover every numeric range and enumeration membership declared in
        this document as well as the relational constraints — a receipt's closing gauge must exceed its
        opening gauge, an uplift's meter end reading must exceed its meter start reading, a fuelling
        window's end must be later than its start, a reconciliation or billing period's end must be later
        than its start, and a tank's safe fill volume must not exceed its shell capacity."
        PRD §3.2: "The payload names the destination tank with a `storage_tank_id`, declares how the
        parcel arrived through `delivery_mode` (either `PIPELINE` or `TRUCK`), and carries a
        `supplier_name`, a `meter_ticket_number` unique across all receipts, the `meter_ticket_gross_liters`
        printed on the supplier's ticket (greater than zero), the `tank_opening_gauge_liters` read before
        the parcel landed (zero or greater), the `tank_closing_gauge_liters` read afterwards (strictly
        greater than the opening reading), the observed `temperature_c` in Celsius (at least minus 20 and
        at most 60), and the `certificate_density_kg_per_m3` from the supplier's refinery certificate of
        quality (at least 750 and at most 850)."

        Design: Corner/validations/wrong_type_beats_out_of_range
        """
        env = fx.setup_farm_with_released_tank()
        tank_id = env["tank"]["id"]

        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, meter_ticket_gross_liters="-5"),
            fx.OPERATOR), ApiErrorId.ERR_INVALID_PAYLOAD, 400)

        # The same value typed correctly is a domain-range failure instead.
        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, meter_ticket_gross_liters=-5.0),
            fx.OPERATOR), ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

    def test_zero_is_refused_where_the_bound_is_strict_and_accepted_where_it_is_not(self, api):
        """PRD §3.5: "Issuing one is available to both an `AirlineRep` acting for its own account and to a
        `BillingClerk`, and the payload names the `airline_account_id` to be billed, the `flight_id` the
        authorization may be redeemed for — exactly one flight, never a bearer credit — and a
        `max_authorized_liters` strictly greater than zero that ceilings the total posted uplift volume
        redeemable under it."
        PRD §3.2: "An optional `measured_water_liters`, defaulting to 0.0 and required to be zero or
        greater, records the free water drained from the parcel before capping."
        PRD §2.10: "**Payload shape and static constraints.** Required-field presence and type
        correctness (`ERR_INVALID_PAYLOAD`) precede declared value constraints
        (`ERR_FIELD_OUT_OF_RANGE`), which cover every numeric range and enumeration membership declared in
        this document as well as the relational constraints — a receipt's closing gauge must exceed its
        opening gauge, an uplift's meter end reading must exceed its meter start reading, a fuelling
        window's end must be later than its start, a reconciliation or billing period's end must be later
        than its start, and a tank's safe fill volume must not exceed its shell capacity."

        Design: Corner/validations/zero_is_out_of_range_where_strictly_positive_is_required
        """
        env = fx.setup_farm_with_released_tank()
        account = fx.open_account(credit_limit_cents=100_000_000)
        flight = fx.register_flight(account["id"], stand_code="A12")

        validate_error(api.create_fuel_authorization(
            F.create_fuel_authorization_payload(account["id"], flight["id"],
                                                max_authorized_liters=0.0), fx.BILLING),
            ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

        receipt = validate_success(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(env["tank"]["id"], measured_water_liters=0.0),
            fx.OPERATOR), 201)
        assert receipt["measured_water_liters"] == pytest.approx(0.00, abs=0.005), \
            "the same zero is perfectly valid where the bound is zero-or-greater"

    def test_a_zero_length_fuelling_window_never_reaches_the_overlap_search(self, api):
        """PRD §2.10: "**Payload shape and static constraints.** Required-field presence and type
        correctness (`ERR_INVALID_PAYLOAD`) precede declared value constraints
        (`ERR_FIELD_OUT_OF_RANGE`), which cover every numeric range and enumeration membership declared in
        this document as well as the relational constraints — a receipt's closing gauge must exceed its
        opening gauge, an uplift's meter end reading must exceed its meter start reading, a fuelling
        window's end must be later than its start, a reconciliation or billing period's end must be later
        than its start, and a tank's safe fill volume must not exceed its shell capacity."
        PRD §3.6: "The payload names the `flight_id` to be fuelled, the `fuel_authorization_id` being
        quoted, the `storage_tank_id` the product will be drawn from, a `delivery_mode` of either `HYDRANT`
        or `TRUCK`, a `requested_uplift_liters` strictly greater than zero expressing the net volume at 15
        degrees Celsius the airline wants, a `window_start_utc` and a `window_end_utc` strictly later than
        the start bounding the booked fuelling window, and a `quoted_authorization_code`."

        Design: Corner/validations/window_end_not_after_window_start
        """
        env = fx.setup_farm_with_released_tank()
        airline = fx.setup_airline(account_overrides={"credit_limit_cents": 100_000_000})

        validate_error(api.create_fueling_order(
            F.create_fueling_order_payload(
                airline["flight"]["id"], airline["auth"]["id"], env["tank"]["id"],
                airline["auth"]["authorization_code"], requested_uplift_liters=20_000.0,
                window_start_utc="2026-08-10T06:00:00Z",
                window_end_utc="2026-08-10T06:00:00Z"), fx.AGENT),
            ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

        orders, _meta = validate_paginated(api.list_fueling_orders(fx.AGENT))
        assert orders == [], "a window that occupies no time is refused outright"


class TestDuplicateKeyCorners:
    def test_the_duplicate_ticket_number_only_surfaces_once_the_values_are_sound(self, api):
        """PRD §2.10: "Scoped uniqueness (`ERR_DUPLICATE_KEY`) is checked next, on farm creation, permit
        creation, tank creation, asset creation, pit creation, receipt creation, airline account creation
        and uplift ticket creation."
        PRD §3.2: "The payload names the destination tank with a `storage_tank_id`, declares how the
        parcel arrived through `delivery_mode` (either `PIPELINE` or `TRUCK`), and carries a
        `supplier_name`, a `meter_ticket_number` unique across all receipts, the `meter_ticket_gross_liters`
        printed on the supplier's ticket (greater than zero), the `tank_opening_gauge_liters` read before
        the parcel landed (zero or greater), the `tank_closing_gauge_liters` read afterwards (strictly
        greater than the opening reading), the observed `temperature_c` in Celsius (at least minus 20 and
        at most 60), and the `certificate_density_kg_per_m3` from the supplier's refinery certificate of
        quality (at least 750 and at most 850)."
        PRD §2.10: "**Payload shape and static constraints.** Required-field presence and type
        correctness (`ERR_INVALID_PAYLOAD`) precede declared value constraints
        (`ERR_FIELD_OUT_OF_RANGE`), which cover every numeric range and enumeration membership declared in
        this document as well as the relational constraints — a receipt's closing gauge must exceed its
        opening gauge, an uplift's meter end reading must exceed its meter start reading, a fuelling
        window's end must be later than its start, a reconciliation or billing period's end must be later
        than its start, and a tank's safe fill volume must not exceed its shell capacity."

        Design: Corner/validations/duplicate_check_runs_after_range_checks
        """
        env = fx.setup_farm_with_released_tank()
        tank_id = env["tank"]["id"]
        first = fx.record_receipt(tank_id, meter_ticket_number="MT-DUPLICATE-1")
        assert first["meter_ticket_number"] == "MT-DUPLICATE-1"

        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, meter_ticket_number="MT-DUPLICATE-1",
                                          temperature_c=-50.0), fx.OPERATOR),
            ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

        # The clash is only reported once the payload is otherwise sound.
        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, meter_ticket_number="MT-DUPLICATE-1",
                                          temperature_c=15.0), fx.OPERATOR),
            ApiErrorId.ERR_DUPLICATE_KEY, 409)
