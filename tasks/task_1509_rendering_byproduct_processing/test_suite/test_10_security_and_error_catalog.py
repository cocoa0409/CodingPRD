"""Caller-context enforcement, cross-role denials, and the 404 catalogue (PRD §2.1, §2.9)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_active_contract,
    create_plant,
    make_headers,
    validate_error,
    validate_paginated,
)

PM = TEST_USERS["plant_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestCallerContext:
    def test_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
        the acting operator, and `X-User-Role`, naming the operator's role. If either header
        is missing, or if `X-User-Role` does not name one of the declared roles, the request
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        res = api.create_plant(
            {"plant_name": "Plant A", "location": "Dallas TX", "cooker_capacity": 2,
             "standard_cost_cents_per_lb": 38},
            headers={},  # no X-User-ID / X-User-Role at all
        )
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )
        plants, meta = validate_paginated(api.list_plants(ANY))
        assert plants == []
        assert meta["total_count"] == 0


class TestCrossRoleDenials:
    def test_cross_role_exclusive_operations_denied(self, api):
        """PRD §2.1: "If the role is declared but not authorized for the target endpoint,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.9: "3. **Role authorization.** The caller's role must be listed for the
        endpoint; otherwise `ERR_INSUFFICIENT_PERMISSIONS` (403)."
        PRD §4 endpoint table: cook runs are ProductionSupervisor-only; collection routes
        RouteDispatcher-only; lot grading QualityLabTech-only; supplier onboarding
        ProcurementManager-only; odor-event intake ComplianceOfficer-only; order creation
        SalesManager-only.

        Design: Corner/rbac/cross_role_exclusive_operations_denied
        """
        from test_helpers import create_draft_contract

        plant = create_plant()
        contract = create_draft_contract(plant["id"])

        sh = make_headers("sh-1", "ScalehouseOperator")
        ql = make_headers("ql-1", "QualityLabTech")
        fa = make_headers("fa-1", "FinanceAnalyst")
        reg = make_headers("reg-1", "Regulator")
        rd = make_headers("rd-1", "RouteDispatcher")
        co = make_headers("co-1", "ComplianceOfficer")

        # d1: ScalehouseOperator staging a cook run (ProductionSupervisor-only).
        d1 = api.create_cook_run(
            {"plant_id": plant["id"], "cooker_line": 1, "recipe": "RUMINANT_RENDER",
             "planned_inputs": [{"batch_id": NON_EXISTENT_UUID, "weight_lbs": 100}],
             "cook_start": "2026-08-05T06:00:00Z", "cook_end": "2026-08-05T10:00:00Z"},
            sh,
        )
        # d2: QualityLabTech creating a collection route (RouteDispatcher-only).
        d2 = api.create_collection_route(
            {"plant_id": plant["id"], "vehicle_id": NON_EXISTENT_UUID, "route_code": "R1",
             "service_date": "2026-08-10", "scheduled_departure": "2026-08-10T06:00:00Z",
             "scheduled_return": "2026-08-10T12:00:00Z"},
            ql,
        )
        # d3: FinanceAnalyst grading a lot (QualityLabTech-only); the role check precedes
        # existence, so the bogus lot id still draws the permission error.
        d3 = api.grade_lot(
            NON_EXISTENT_UUID,
            {"lab_moisture_pct": 0.2, "lab_ffa_pct": 1.0, "lab_protein_pct": 0},
            fa,
        )
        # d4: Regulator onboarding a supplier (ProcurementManager-only).
        d4 = api.create_supplier(
            {"plant_id": plant["id"], "supplier_name": "S", "supplier_type": "FARM"}, reg
        )
        # d5: RouteDispatcher logging an odor event (ComplianceOfficer-only).
        d5 = api.create_odor_event(
            {"plant_id": plant["id"], "reported_at": "2026-08-05T09:00:00Z",
             "location_description": "G", "severity": "LOW"},
            rd,
        )
        # d6: ComplianceOfficer creating a sales order (SalesManager-only); the payload is
        # fully valid against a real contract and is still denied.
        d6 = api.create_sales_order(
            {"contract_id": contract["id"], "plant_id": plant["id"], "quantity_lbs": 100,
             "requested_ship_date": "2026-08-20",
             "expected_contract_version": contract["version"]},
            co,
        )

        for name, res in [("d1", d1), ("d2", d2), ("d3", d3), ("d4", d4), ("d5", d5), ("d6", d6)]:
            validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                           expected_status=403)

        # Nothing was persisted by any denied call.
        cooks, _ = validate_paginated(api.list_cook_runs(ANY, params={"plant_id": plant["id"]}))
        routes, _ = validate_paginated(api.list_collection_routes(ANY, params={"plant_id": plant["id"]}))
        suppliers, _ = validate_paginated(api.list_suppliers(ANY, params={"plant_id": plant["id"]}))
        events, _ = validate_paginated(api.list_odor_events(ANY, params={"plant_id": plant["id"]}))
        orders, _ = validate_paginated(api.list_sales_orders(ANY, params={"plant_id": plant["id"]}))
        assert cooks == [] and routes == [] and suppliers == []
        assert events == [] and orders == []


class TestNotFoundCatalogue:
    def test_not_found_read_paths_return_404s(self, api):
        """PRD §2.9: "4. **Existence.** Every identifier in the path must exist, then every
        foreign-key identifier in the body must exist, validated left-to-right — path first,
        then body fields in their declared order. The first missing resource yields its
        specific 404: `ERR_PLANT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_WASH_TICKET_NOT_FOUND`,
        `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
        `ERR_COOK_RUN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_INDEX_ENTRY_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, or
        `ERR_ODOR_EVENT_NOT_FOUND`."

        Design: Corner/errors/not_found_read_paths_return_404s
        """
        cases = [
            (lambda: api.get_permit(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_PERMIT_NOT_FOUND),
            (lambda: api.get_supplier(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
            (lambda: api.get_supplier_agreement(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (lambda: api.get_vehicle(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_VEHICLE_NOT_FOUND),
            (lambda: api.get_wash_ticket(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_WASH_TICKET_NOT_FOUND),
            (lambda: api.get_collection_route(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_ROUTE_NOT_FOUND),
            (lambda: api.get_route_stop(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_STOP_NOT_FOUND),
            (lambda: api.get_inbound_batch(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_BATCH_NOT_FOUND),
            (lambda: api.get_cook_run(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_COOK_RUN_NOT_FOUND),
            (lambda: api.get_product_lot(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_LOT_NOT_FOUND),
            (lambda: api.get_customer_contract(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_CONTRACT_NOT_FOUND),
            (lambda: api.get_sales_order(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_ORDER_NOT_FOUND),
            (lambda: api.get_price_index_entry(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_INDEX_ENTRY_NOT_FOUND),
            (lambda: api.get_period_settlement(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
            (lambda: api.get_odor_event(NON_EXISTENT_UUID, ANY), ApiErrorId.ERR_ODOR_EVENT_NOT_FOUND),
        ]
        for call, expected in cases:
            res = call()
            validate_error(res, expected, expected_status=404)
