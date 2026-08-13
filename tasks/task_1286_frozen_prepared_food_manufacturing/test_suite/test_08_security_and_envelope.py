"""Authentication, role matrix, customer scope, and response envelope (PRD §2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_component,
    create_approved_recipe,
    create_batch,
    create_copack_customer,
    create_freezer_cell,
    create_order,
    create_recipe,
    kit_batch,
    make_copack_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
QA_TECH = TEST_USERS["qa_technician_headers"]
QA_MGR = TEST_USERS["qa_manager_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request arriving without both headers, or carrying a role
        outside this declared list, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.4: "1. **Authentication.** Both headers are present and the role is
        one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api.list_recipes(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_role_forbidden_returns_403(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `PlantManager` administers master data: recipes and their
        approval cycle, component lines, co-pack customers, freezer cells,
        packaging lines, storage slots, film reception, and the logical clock."

        Design: Corner/validations/role_forbidden_returns_403
        """
        resp = api.create_recipe(
            {
                "name": "R-X", "product_style": "ENTREE",
                "base_batch_yield_units": 1000, "portion_weight_g": 340,
                "shelf_life_days": 365,
            },
            QA_TECH,  # recipe creation is a PlantManager-exclusive operation
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestPeerRoleBoundaries:
    def test_peer_role_cannot_cross_exclusive_boundaries(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `ProductionPlanner` plans production: orders, batches,
        freezing-cycle bookings and voids, line-run scheduling, and
        cancellations."
        PRD §2.1: "A `LineOperator` executes the physical steps: kitting, cooking,
        cycle starts and completions, run starts and completions."
        PRD §2.1: "A `QAManager` holds disposition authority: lot release,
        rejection, rework, and recall, complaint resolution, film de-quarantine,
        and sending held batches to rework."
        PRD §2.1: "A `WarehouseLead` performs cold-storage movements: put-away and
        withdrawal."

        Design: Corner/rbac/peer_role_cannot_cross_exclusive_boundaries
        """
        recipe = create_approved_recipe(name="R-Perm")
        draft = create_recipe(name="R-Perm2")
        add_component(draft["id"])
        order = create_order(recipe["id"], units_planned=6000)
        batch = create_batch(order["id"], units_planned=6000)
        kit_batch(batch["id"])

        # ProductionPlanner cannot approve recipes (PlantManager-exclusive).
        resp = api.approve_recipe(draft["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        # LineOperator cannot create production orders (ProductionPlanner-exclusive).
        resp = api.create_production_order(
            {"recipe_id": recipe["id"], "pack_format": "RETAIL", "units_planned": 100},
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        # WarehouseLead cannot receive film (PlantManager-exclusive).
        resp = api.create_film_lot(
            {"film_type": "TRAY_FILM", "rolls_received": 1, "meters_per_roll": 100},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        # QAManager cannot record CCP checks (QATechnician-exclusive).
        resp = api.create_ccp_check(
            batch["id"], {"check_type": "XRAY", "test_piece_detected": True}, QA_MGR
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestCustomerScope:
    def test_cross_customer_scope_returns_403(self, api):
        """PRD §2.1: "When `X-User-Role` is `CoPackCustomer`, `X-User-ID` is the
        `id` of the acting `CoPackCustomer` record; ownership checks on any
        resource that references a co-pack customer compare the resource's
        `copack_customer_id` field to `X-User-ID`, and any attempt by a
        customer-scoped caller to read or file against an order, lot, or complaint
        outside their own customer scope is rejected with
        `ERR_CROSS_CUSTOMER_ACCESS` (HTTP 403)."

        Design: Corner/validations/cross_customer_scope_returns_403
        """
        recipe = create_approved_recipe(name="R-Scope")
        cust_a = create_copack_customer(name="Cust A")
        cust_b = create_copack_customer(name="Cust B")
        order = create_order(
            recipe["id"], units_planned=6000, copack_customer_id=cust_a["id"]
        )

        resp = api.get_production_order(
            order["id"], make_copack_customer_headers(cust_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_CUSTOMER_ACCESS, expected_status=403)

        own = validate_success(
            api.get_production_order(order["id"], make_copack_customer_headers(cust_a["id"]))
        )
        assert own["id"] == order["id"], "a customer reads its own order"


class TestValidationPipelineOrder:
    def test_shape_error_beats_existence_error(self, api):
        """PRD §2.4: "When several checks could reject the same request, the
        earliest failing stage in the order below determines the error that is
        returned; later stages are never consulted for that request." — "5.
        **Request shape.**" is listed before "6. **Existence.**"
        PRD §2.4: "Required fields are present, types are correct, enum members
        are valid, and numeric ranges are respected (for example, unit counts must
        be positive and a component's `scale_exponent` must be greater than zero
        and no greater than 1.5); otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/shape_error_beats_existence_error
        """
        # Missing required units_planned (shape, stage 5) AND a nonexistent
        # recipe_id (existence, stage 6): the shape error must surface.
        resp = api.create_production_order(
            {"recipe_id": NON_EXISTENT_UUID, "pack_format": "RETAIL"},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestNotFound:
    def test_entity_get_unknown_id_returns_404(self, api):
        """PRD §2.9: "the server resolves each identifier in sequence and rejects
        the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
        does not correspond to an existing resource"
        PRD §2.4: "6. **Existence.** Path identifiers are resolved left to right,
        then foreign keys in the request body; the first missing reference yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_get_unknown_id_returns_404
        """
        resp = api.get_lot(NON_EXISTENT_UUID, QA_MGR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        resp = api.get_batch(NON_EXISTENT_UUID, PLANNER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestPaginationEnvelope:
    def test_list_endpoint_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; when not provided it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/list_endpoint_pagination_envelope
        """
        for code, cap, rate, san in (("FC-1", 2000, 400, 30), ("FC-2", 2000, 400, 30), ("FC-3", 3000, 500, 45)):
            create_freezer_cell(
                cell_code=code, capacity_kg=cap, pull_down_kg_per_hour=rate,
                sanitation_minutes=san,
            )
        resp = api.list_freezer_cells(PLANNER)
        body = resp.json()
        assert body.get("response_type") == "array", (
            f"list endpoints answer with response_type=array, got {body.get('response_type')}"
        )
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, f"default limit is 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset is 0, got {meta['offset']}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
