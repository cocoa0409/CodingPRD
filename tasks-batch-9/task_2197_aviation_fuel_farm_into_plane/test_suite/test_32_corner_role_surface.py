"""Corner behaviour of the role surface: each of the seven roles owns something no other role can do, role
separation and per-user segregation are separate mechanisms, the airline role is entity-backed, and the admin
role is not a superuser."""
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


class TestRoleCoverage:
    def test_each_of_the_seven_roles_owns_a_surface_no_other_role_reaches(self, api):
        """PRD §2.1: "The seven roles are `ConsortiumAdmin`, `FarmOperator`, `QualityInspector`,
        `IntoPlaneAgent`, `AirlineRep`, `EnvironmentalOfficer`, and `BillingClerk`."
        PRD §2.1: "A `FarmOperator` runs the farm floor: recording incoming fuel receipts, taking gauge
        measurements, isolating and returning tanks to service, rejecting quarantined parcels back to the
        supplier, opening reconciliation runs and posting their measurements."
        PRD §2.1: "A `QualityInspector` owns the product-quality chain: drawing samples from receipts, tanks
        and post-filter-change membranes, posting laboratory results, signing receipt release and quarantine
        verdicts, releasing and quarantining tanks on the quality dimension, and performing filter element
        changes."
        PRD §2.1: "An `IntoPlaneAgent` works the ramp: authorising, assigning, unassigning, starting,
        aborting and completing fuelling orders, posting uplift tickets, and reporting spills observed during
        fuelling."
        PRD §2.1: "An `EnvironmentalOfficer` is the compliance authority: suspending and reinstating
        environmental permits, and driving the spill response chain through escalation, containment,
        remediation and closure."
        PRD §2.1: "A `BillingClerk` handles the money: issuing fuel authorizations (shared with
        `AirlineRep`), voiding authorizations, sweeping uplift tickets into draft invoices, issuing,
        disputing-resolution, voiding and settling invoices, and recording payments."
        PRD §2.1: "When the headers are well formed but the named role is not among the roles authorised for
        the requested endpoint, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/every_role_owns_at_least_one_exclusive_operation
        """
        ramp = fx.setup_truck_order(target_state="AUTHORIZED",
                                    account_overrides={"credit_limit_cents": BIG_CREDIT})
        money = fx.setup_issued_invoice(meter_end_liters=20_000.0,
                                       account_overrides={"credit_limit_cents": BIG_CREDIT})
        farm_id, tank_id = ramp["farm"]["id"], ramp["tank"]["id"]

        # ConsortiumAdmin: static registration
        validate_error(api.create_storage_tank(farm_id, F.create_storage_tank_payload(),
                                               fx.OPERATOR),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_success(api.create_storage_tank(farm_id, F.create_storage_tank_payload(),
                                                 fx.ADMIN), 201)

        # FarmOperator: the farm floor
        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, **PIPELINE_PARCEL), fx.ADMIN),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        receipt = validate_success(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, **PIPELINE_PARCEL), fx.OPERATOR), 201)

        # QualityInspector: the product-quality chain
        validate_error(api.create_receipt_sample(receipt["id"], fx.OPERATOR),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_success(api.create_receipt_sample(receipt["id"], fx.INSPECTOR_A), 201)

        # IntoPlaneAgent: the ramp
        assign = {"fueling_asset_id": ramp["truck"]["id"]}
        validate_error(api.assign_order(ramp["order"]["id"], assign, fx.ADMIN),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_success(api.assign_order(ramp["order"]["id"], assign, fx.AGENT), 200)

        # AirlineRep: disputing an invoice is the one action nobody else may take
        owner = make_airline_rep_headers(money["account"]["id"])
        validate_error(api.dispute_invoice(money["invoice"]["id"], fx.BILLING),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        assert validate_success(api.dispute_invoice(money["invoice"]["id"], owner),
                                200)["status"] == "DISPUTED"

        # BillingClerk: the money side, including voiding an unredeemed authorization
        spare_flight = fx.register_flight(ramp["account"]["id"], stand_code="M01",
                                          scheduled_departure_utc="2026-08-10T12:00:00Z")
        spare_auth = validate_success(api.create_fuel_authorization(
            F.create_fuel_authorization_payload(ramp["account"]["id"], spare_flight["id"]),
            fx.BILLING), 201)
        validate_error(api.void_fuel_authorization(spare_auth["id"], fx.AGENT),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        assert validate_success(api.void_fuel_authorization(spare_auth["id"], fx.BILLING),
                                200)["status"] == "VOIDED"

        # EnvironmentalOfficer: the spill response chain
        # PRD §3.8 makes escalation "lawful only when the spilled volume has reached the governing
        # permit's `max_reportable_spill_liters`", which defaults to 20.0 liters, so the release
        # this role check escalates has to be a reportable one.
        spill = fx.report_spill(money["farm"]["id"], spilled_volume_liters=25.0)
        escalation = {"regulator_reference": "REG-2026-0007"}
        validate_error(api.escalate_spill(spill["id"], escalation, fx.OPERATOR),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        assert validate_success(api.escalate_spill(spill["id"], escalation, fx.ENVIRO),
                                200)["status"] == "ESCALATED"

    def test_role_separation_and_user_segregation_are_two_different_walls(self, api):
        """PRD §2.1: "A `FarmOperator` runs the farm floor: recording incoming fuel receipts, taking gauge
        measurements, isolating and returning tanks to service, rejecting quarantined parcels back to the
        supplier, opening reconciliation runs and posting their measurements."
        PRD §2.1: "**Segregation of duties.** Three workflow steps compare the acting `X-User-ID` against
        the identifier recorded at the preceding step of the same workflow, and reject a match with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): an inspector may not sign a receipt verdict when the acting
        identifier equals the receipt's `sampled_by_user_id`; an inspector may not release a tank on the
        quality dimension when the acting identifier equals the `drawn_by_user_id` of the governing periodic
        tank sample; and a billing clerk may not resolve a dispute on an invoice whose `issued_by_user_id`
        equals the acting identifier."
        PRD §3.3: "Both branches are `QualityInspector` actions and both refuse a signer whose identifier
        equals the receipt's `sampled_by_user_id` — the inspector who drew the sample may not sign its
        verdict, and an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/no_role_can_perform_both_halves_of_a_segregated_pair
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        tank_id = env["tank"]["id"]

        # the inspector cannot even record the parcel: recording is a FarmOperator operation
        validate_error(api.create_fuel_receipt(
            F.create_fuel_receipt_payload(tank_id, **PIPELINE_PARCEL), fx.INSPECTOR_A),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        receipt, _sample = fx.make_tested_receipt(tank_id, **PIPELINE_PARCEL)
        assert fx.read_receipt(receipt["id"])["sampled_by_user_id"] == "qi-alice"

        # the same identifier is now blocked by the second, user-level wall
        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_A),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        released = validate_success(api.sign_receipt_verdict(
            receipt["id"], {"decision": "RELEASE"}, fx.INSPECTOR_B), 200)
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "qi-bob"

    def test_the_airline_role_must_resolve_to_a_real_account_row(self, api):
        """PRD §2.1: "When `X-User-Role` is `AirlineRep`, `X-User-ID` is the `id` of the acting
        `AirlineAccount`; ownership checks on any resource that references an `AirlineAccount` compare the
        resource's airline-account reference to `X-User-ID`."
        PRD §2.1: "Concretely, an `AirlineRep` acting on a flight, a fuel authorization, a fuelling order or
        an invoice whose owning account is not the account named by `X-User-ID` is rejected with
        `ERR_ACCOUNT_OWNERSHIP_REQUIRED` (HTTP 403); for a fuelling order or an uplift ticket the owning
        account is reached through the order's flight."
        PRD §2.10: "**Authentication and authorisation.** Header presence and role validity
        (`ERR_UNAUTHENTICATED`) is checked first, then endpoint role membership (`ERR_ROLE_NOT_PERMITTED`),
        then — for the five operations an `AirlineRep` may reach, namely flight creation, fuel authorization
        creation, fuelling order creation, fuelling order cancellation and invoice dispute — account
        ownership (`ERR_ACCOUNT_OWNERSHIP_REQUIRED`)."

        Design: Corner/rbac/airline_rep_is_entity_backed
        """
        env = fx.setup_truck_order(target_state="REQUESTED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        nobody = make_airline_rep_headers(NON_EXISTENT_UUID)

        validate_error(api.cancel_order(env["order"]["id"], nobody),
                       ApiErrorId.ERR_ACCOUNT_OWNERSHIP_REQUIRED, 403)
        payload = F.create_fueling_order_payload(
            env["flight"]["id"], env["auth"]["id"], env["tank"]["id"],
            env["auth"]["authorization_code"], delivery_mode="TRUCK",
            requested_uplift_liters=5_000.0, window_start_utc="2026-08-10T09:00:00Z",
            window_end_utc="2026-08-10T09:30:00Z")
        validate_error(api.create_fueling_order(payload, nobody),
                       ApiErrorId.ERR_ACCOUNT_OWNERSHIP_REQUIRED, 403)

        assert fx.read_order(env["order"]["id"])["status"] == "REQUESTED", \
            "an unresolvable airline identity cannot act as an anonymous customer"

    def test_the_admin_role_cannot_shortcut_the_operational_flows(self, api):
        """PRD §2.1: "A `ConsortiumAdmin` is the consortium's operations manager. This role registers fuel
        farms, environmental permits, storage tanks, fuelling assets, hydrant pits and airline accounts,
        posts reconciliation runs, and drives the system's logical clock."
        PRD §2.1: "It shares tank service-status changes and asset status changes with `FarmOperator`,
        shares flight creation with `AirlineRep`, and may read every collection in the system."
        PRD §2.1: "When the headers are well formed but the named role is not among the roles authorised for
        the requested endpoint, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/consortium_admin_is_not_an_operational_override
        """
        env = fx.setup_truck_order(target_state="FUELING",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id, tank_id = env["order"]["id"], env["tank"]["id"]
        ticket = F.create_uplift_record_payload(fx.current_order_version(order_id),
                                                meter_start_liters=0.0,
                                                meter_end_liters=20_000.0,
                                                temperature_c=15.0)

        validate_error(api.create_uplift_record(order_id, ticket, fx.ADMIN),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        receipt, _sample = fx.make_tested_receipt(tank_id, **PIPELINE_PARCEL)
        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.ADMIN),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        # the admin may still read everything it is refused permission to write
        assert validate_success(api.get_fueling_order(order_id, fx.ADMIN))["status"] == "FUELING"
        assert fx.read_receipt(receipt["id"])["status"] == "UNDER_TEST"
