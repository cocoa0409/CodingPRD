"""Supplier onboarding and supply-agreement lifecycle (PRD §2.3, §2.4, §2.9, §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    assert_agreement,
    assert_stop,
    assert_supplier,
    create_active_agreement,
    create_draft_agreement,
    create_plant,
    create_route,
    create_supplier,
    create_vehicle,
    is_valid_uuid,
    read_route_version,
    setup_plant_with_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


class TestSupplierCreation:
    def test_supplier_create_missing_required_name_rejected(self, api):
        """PRD §2.9: "Required fields must be present, types must be correct, enum values
        must belong to their declared domains, integer quantities must be at least 1 where
        so declared, ... Violations return `ERR_INVALID_REQUEST` (400)."
        PRD §3.3: "A `ProcurementManager` onboards each supplier with its `plant_id`, a
        `supplier_name`, and a `supplier_type` of `FARM`, `SLAUGHTERHOUSE`, `BUTCHER_SHOP`,
        or `GROCERY`."

        Design: Corner/entities/supplier_create_missing_required_name_rejected
        """
        plant = create_plant()
        res = api.create_supplier(
            {"plant_id": plant["id"], "supplier_type": "FARM"}, PROC
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        data, meta = validate_paginated(
            api.list_suppliers(ANY, params={"plant_id": plant["id"]})
        )
        assert data == []
        assert meta["total_count"] == 0

    def test_supplier_create_invalid_enum_rejected(self, api):
        """PRD §2.9: "Required fields must be present, types must be correct, enum values
        must belong to their declared domains, integer quantities must be at least 1 where
        so declared, ... Violations return `ERR_INVALID_REQUEST` (400)."
        PRD §3.3: "A `ProcurementManager` onboards each supplier with its `plant_id`, a
        `supplier_name`, and a `supplier_type` of `FARM`, `SLAUGHTERHOUSE`, `BUTCHER_SHOP`,
        or `GROCERY`."

        Design: Corner/entities/supplier_create_invalid_enum_rejected
        """
        plant = create_plant()
        res = api.create_supplier(
            {"plant_id": plant["id"], "supplier_name": "Sup X", "supplier_type": "RANCH"},
            PROC,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_supplier_create_client_id_input_ignored(self, api):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a UUID,
        with no type prefix."
        PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
        digits recording when the resource was created."

        Design: Corner/entities/supplier_create_client_id_input_ignored
        """
        plant = create_plant()
        res = api.create_supplier(
            {
                "id": "client-supplied",
                "plant_id": plant["id"],
                "supplier_name": "Sup A",
                "supplier_type": "FARM",
            },
            PROC,
        )
        supplier = validate_success(res, 201)
        assert_supplier(supplier)
        assert supplier["id"] != "client-supplied"
        assert is_valid_uuid(supplier["id"])
        assert supplier["status"] == "ACTIVE"

    def test_supplier_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it defaults
        to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that
        many items from the start of the result set and defaults to 0."
        PRD §2.3: "Unless otherwise stated, every list endpoint returns resources sorted by
        `created_at` in ascending order, and the `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/supplier_list_pagination_envelope
        """
        plant = create_plant()
        for name, stype in [("S1", "FARM"), ("S2", "GROCERY"), ("S3", "BUTCHER_SHOP")]:
            create_supplier(plant["id"], supplier_name=name, supplier_type=stype)

        page1, meta1 = validate_paginated(
            api.list_suppliers(ANY, params={"plant_id": plant["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_suppliers(ANY, params={"plant_id": plant["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestAgreementSuspendReinstateCycle:
    def test_agreement_suspend_blocks_stop_creation(self, api):
        """PRD §3.4: "Cross-entity checks then apply: the supplier must be `ACTIVE`
        (`ERR_SUPPLIER_NOT_ACTIVE`), the agreement must be `ACTIVE` and belong to the named
        supplier (`ERR_AGREEMENT_NOT_ACTIVE`), ..."
        PRD §3.3: "An `ACTIVE` agreement can be suspended — manually by a `PlantManager`, or
        automatically by the supplier strike cascade — which cancels every stop referencing
        it that is still `SCHEDULED` or `ARRIVED`; manual suspension of a non-`ACTIVE`
        agreement returns `ERR_AGREEMENT_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])

        suspended = validate_success(api.suspend_agreement(agreement["id"], PM), 200)
        assert suspended["status"] == "SUSPENDED"

        payload = {
            "route_id": route["id"],
            "supplier_id": supplier["id"],
            "agreement_id": agreement["id"],
            "plant_id": plant["id"],
            "sequence_no": 1,
            "scheduled_window_start": "2026-08-10T08:00:00Z",
            "scheduled_window_end": "2026-08-10T09:00:00Z",
            "estimated_weight_lbs": 5000,
            "estimated_distance_miles": 10,
            "species_tag": "BOVINE",
            "is_dead_stock": False,
            "expected_route_version": route["version"],
        }
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)

    def test_agreement_reinstate_reenables_stop_creation(self, api):
        """PRD §3.3: "Reinstatement requires the agreement `SUSPENDED`
        (`ERR_AGREEMENT_INVALID_STATE`) and its supplier currently `ACTIVE`
        (`ERR_SUPPLIER_NOT_ACTIVE`), and returns it to `ACTIVE`."
        PRD §3.4: "its creation increments the route's `version` by one"

        Design: Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        route_version_before = route["version"]

        validate_success(api.suspend_agreement(agreement["id"], PM), 200)
        reinstated = validate_success(api.reinstate_agreement(agreement["id"], PM), 200)
        assert reinstated["status"] == "ACTIVE"

        stop = add_stop(route["id"], supplier["id"], agreement["id"], plant["id"])
        assert_stop(stop)
        assert stop["status"] == "SCHEDULED"

        # The rejected-then-successful cycle advanced the route version exactly once.
        route_after = validate_success(api.get_collection_route(route["id"], ANY), 200)
        assert route_after["version"] == route_version_before + 1


class TestStopCreationAgreementDependency:
    def test_stop_create_blocked_while_agreement_suspended(self, api):
        """PRD §3.4: "Cross-entity checks then apply: the supplier must be `ACTIVE`
        (`ERR_SUPPLIER_NOT_ACTIVE`), the agreement must be `ACTIVE` and belong to the named
        supplier (`ERR_AGREEMENT_NOT_ACTIVE`), ..."

        Design: Difficulty/cross_entity_state_dependency/stop_create_blocked_by_suspended_agreement
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        validate_success(api.suspend_agreement(agreement["id"], PM), 200)

        payload = {
            "route_id": route["id"],
            "supplier_id": supplier["id"],
            "agreement_id": agreement["id"],
            "plant_id": plant["id"],
            "sequence_no": 1,
            "scheduled_window_start": "2026-08-10T08:00:00Z",
            "scheduled_window_end": "2026-08-10T09:00:00Z",
            "estimated_weight_lbs": 5000,
            "estimated_distance_miles": 10,
            "species_tag": "BOVINE",
            "is_dead_stock": False,
            "expected_route_version": route["version"],
        }
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)

        route_after = validate_success(api.get_collection_route(route["id"], ANY), 200)
        assert route_after["status"] == "PLANNED"
        stops, meta = validate_paginated(
            api.list_route_stops(ANY, params={"route_id": route["id"]})
        )
        assert stops == []
        assert meta["total_count"] == 0
        agreement_after = validate_success(
            api.get_supplier_agreement(agreement["id"], ANY), 200
        )
        assert agreement_after["status"] == "SUSPENDED"

    def test_agreement_suspension_cancels_open_stops(self, api):
        """PRD §3.3: "An `ACTIVE` agreement can be suspended — manually by a `PlantManager`,
        or automatically by the supplier strike cascade — which cancels every stop
        referencing it that is still `SCHEDULED` or `ARRIVED`; manual suspension of a
        non-`ACTIVE` agreement returns `ERR_AGREEMENT_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/stop_create_blocked_by_suspended_agreement
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        stop = add_stop(route["id"], supplier["id"], agreement["id"], plant["id"])
        assert stop["status"] == "SCHEDULED"

        validate_success(api.suspend_agreement(agreement["id"], PM), 200)

        stop_after = validate_success(api.get_route_stop(stop["id"], ANY), 200)
        assert stop_after["status"] == "CANCELLED"

        # And while suspended, further stop creation is refused.
        payload = {
            "route_id": route["id"],
            "supplier_id": supplier["id"],
            "agreement_id": agreement["id"],
            "plant_id": plant["id"],
            "sequence_no": 2,
            "scheduled_window_start": "2026-08-10T10:00:00Z",
            "scheduled_window_end": "2026-08-10T11:00:00Z",
            "estimated_weight_lbs": 1000,
            "estimated_distance_miles": 5,
            "species_tag": "BOVINE",
            "is_dead_stock": False,
            "expected_route_version": read_route_version(route["id"]),
        }
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)
