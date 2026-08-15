"""Optimistic concurrency control on the three guarded write paths (PRD §2.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    create_active_contract,
    create_plant,
    create_route,
    create_vehicle,
    read_contract_version,
    read_route_version,
    setup_plant_with_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
PROC2 = TEST_USERS["procurement_manager_2_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
SM = TEST_USERS["sales_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestOrderCreateStaleContractVersion:
    def test_occ_order_create_stale_contract_version(self, api):
        """PRD §2.8: "Creating a sales order (capability: order creation against a contract)
        requires the request to carry `expected_contract_version`, the contract `version`
        the client last observed. If the contract's current `version` has advanced past that
        value, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than
        allowing the client to book against contract terms it has not observed. A successful
        creation itself increments the contract's `version` by one."

        Design: Corner/complexity_layers/occ_order_create_stale_contract_version
        """
        plant = create_plant()
        contract = create_active_contract(plant["id"])
        observed_version = contract["version"]

        # First creation succeeds on a fresh read...
        payload1 = {
            "contract_id": contract["id"],
            "plant_id": plant["id"],
            "quantity_lbs": 100,
            "requested_ship_date": "2026-08-20",
            "expected_contract_version": observed_version,
        }
        order1 = validate_success(api.create_sales_order(payload1, SM), 201)
        assert order1["status"] == "DRAFT"

        # ...and itself advanced the contract version by exactly one.
        contract_mid = validate_success(
            api.get_customer_contract(contract["id"], ANY), 200
        )
        assert contract_mid["version"] == observed_version + 1

        # A second creation replaying the stale version is rejected.
        payload2 = {**payload1, "quantity_lbs": 200, "requested_ship_date": "2026-08-21"}
        res = api.create_sales_order(payload2, SM)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Re-reading and retrying with the fresh version succeeds.
        payload3 = {**payload2,
                    "expected_contract_version": read_contract_version(contract["id"])}
        order2 = validate_success(api.create_sales_order(payload3, SM), 201)
        assert order2["status"] == "DRAFT"


class TestStopCreateStaleRouteVersion:
    def test_occ_stop_create_stale_route_version(self, api):
        """PRD §2.8: "Adding a route stop to a collection route requires
        `expected_route_version`, the route `version` the client last observed. A mismatch
        with the route's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
        A successful stop creation increments the route's `version` by one."

        Design: Corner/complexity_layers/occ_stop_create_stale_route_version
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        observed_version = route["version"]

        # The first stop succeeds and bumps the route version by one.
        stop1 = add_stop(route["id"], supplier["id"], agreement["id"], plant["id"],
                         sequence_no=1)
        assert stop1["status"] == "SCHEDULED"
        route_mid = validate_success(api.get_collection_route(route["id"], ANY), 200)
        assert route_mid["version"] == observed_version + 1

        # A second creation still carrying the pre-stop version is rejected, even though
        # the route is still PLANNED and would otherwise accept the stop.
        from test_helpers import create_stop_payload

        payload = create_stop_payload(
            route["id"], supplier["id"], agreement["id"], plant["id"], observed_version,
            sequence_no=2,
            scheduled_window_start="2026-08-10T10:00:00Z",
            scheduled_window_end="2026-08-10T11:00:00Z",
            estimated_weight_lbs=4000,
            estimated_distance_miles=5,
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        stops, meta = validate_paginated(
            api.list_route_stops(ANY, params={"route_id": route["id"]})
        )
        assert meta["total_count"] == 1


class TestAgreementAmendStaleVersion:
    def test_occ_agreement_amend_stale_version(self, api):
        """PRD §2.8: "Amending a supplier agreement's commercial terms requires
        `expected_agreement_version`, the agreement `version` the client last observed. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful amend
        increments the agreement's `version` by one."
        PRD §3.3: "A `ProcurementManager` amends in place — the agreement stays `ACTIVE` —
        passing `expected_agreement_version` per §2.8 together with any subset of the
        amendable fields: `pickup_base_fee_cents`, `per_lb_fee_cents`,
        `mileage_rate_cents`, `dead_stock_surcharge_cents`, `minimum_volume_lbs`,
        `volume_discount_pct`, and `effective_to`."

        Design: Corner/complexity_layers/occ_agreement_amend_stale_version
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        observed_version = agreement["version"]

        # First amend on the fresh version succeeds in place.
        amended = validate_success(
            api.amend_agreement(
                agreement["id"],
                {"expected_agreement_version": observed_version, "per_lb_fee_cents": 4},
                PROC,
            ),
            200,
        )
        assert amended["per_lb_fee_cents"] == 4
        assert amended["version"] == observed_version + 1
        assert amended["status"] == "ACTIVE"

        # Replaying the pre-amend version is rejected.
        res = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": observed_version, "per_lb_fee_cents": 5},
            PROC2,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = validate_success(api.get_supplier_agreement(agreement["id"], ANY), 200)
        assert after["per_lb_fee_cents"] == 4
        assert after["version"] == observed_version + 1
