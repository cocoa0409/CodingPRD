"""Operator accounts, catalog administration, authentication, and RBAC."""
from test_helpers import (
    ADMIN,
    PLANNER,
    TELEMETRY,
    WAREHOUSE,
    ADJUSTER,
    ApiErrorId,
    create_location,
    create_operator,
    create_product,
    create_route,
    get_operator,
    make_operator_manager_headers,
    validate_error,
    validate_success,
)

BOGUS_UUID_1 = "11111111-1111-1111-1111-111111111111"
BOGUS_UUID_2 = "22222222-2222-2222-2222-222222222222"
BOGUS_UUID_3 = "33333333-3333-3333-3333-333333333333"
BOGUS_UUID_4 = "44444444-4444-4444-4444-444444444444"
BOGUS_UUID_5 = "55555555-5555-5555-5555-555555555555"
BOGUS_UUID_6 = "66666666-6666-6666-6666-666666666666"
BOGUS_UUID_7 = "77777777-7777-7777-7777-777777777777"
BOGUS_UUID_8 = "88888888-8888-8888-8888-888888888888"
BOGUS_UUID_9 = "99999999-9999-9999-9999-999999999999"


class TestOperatorDefaults:
    def test_operator_creation_applies_defaults(self, api):
        """PRD §3.1: "A `WholesaleAdmin` opens an operator account by supplying
        the company `name` and, optionally, a `default_tender` of `CASH` or
        `CASHLESS`; when omitted, the tender defaults to `CASH`. New accounts
        start `ACTIVE` with `credit_balance_cents` at zero."
        PRD §2.4: "All primary resources — operators, delivery routes, products,
        locations, planograms, replenishment orders, promotions, credit claims,
        and service tickets — carry a standard set of system-managed fields"

        Design: Corner/entities/operator_creation_applies_defaults
        """
        resp = api.create_operator({"name": "Op Defaults"}, ADMIN)
        created = validate_success(resp, 201)
        assert created["default_tender"] == "CASH"
        assert created["credit_balance_cents"] == 0
        assert created["status"] == "ACTIVE"
        # System-managed fields are server-stamped on creation.
        assert isinstance(created["id"], str) and created["id"]
        assert isinstance(created["created_at"], str)
        assert isinstance(created["updated_at"], str)
        assert isinstance(created["version"], int)

        fetched = validate_success(api.get_operator(created["id"], ADMIN), 200)
        assert fetched["default_tender"] == "CASH"
        assert fetched["credit_balance_cents"] == 0
        assert fetched["status"] == "ACTIVE"


class TestOperatorCycleGuards:
    def test_operator_suspend_reinstate_cycle_guards(self, api):
        """PRD §3.1: "Suspension by a `WholesaleAdmin` moves an operator
        `ACTIVE` → `SUSPENDED` and requires the account to currently be
        `ACTIVE`; anything else is rejected with `ERR_OPERATOR_NOT_ACTIVE`."
        PRD §3.1: "Reinstatement moves `SUSPENDED` → `ACTIVE` under the same
        guard, and the cycle may loop indefinitely."

        Design: Corner/state_machines/operator_suspend_reinstate_cycle_guards
        """
        op = create_operator("Op Cyc")
        validate_success(api.suspend_operator(op["id"], ADMIN), 200)

        err = api.suspend_operator(op["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_OPERATOR_NOT_ACTIVE)

        validate_success(api.reinstate_operator(op["id"], ADMIN), 200)
        err2 = api.reinstate_operator(op["id"], ADMIN)
        validate_error(err2, ApiErrorId.ERR_OPERATOR_NOT_ACTIVE)

        assert get_operator(op["id"])["status"] == "ACTIVE"


class TestCatalogUniqueness:
    def test_product_create_duplicate_sku_rejected(self, api):
        """PRD §3.2: "Creating a product requires a catalog-unique `sku` — a
        duplicate rejects with `ERR_DUPLICATE_SKU`"

        Design: Corner/entities/product_create_duplicate_sku_rejected
        """
        first = create_product(sku="DUP-1", name="First")
        err = api.create_product(
            {
                "sku": "DUP-1",
                "name": "Second",
                "category": "CANDY",
                "eligible_location_types": ["GYM"],
                "case_pack_qty": 5,
                "base_price_cents": 500,
                "cost_cents": 300,
                "shelf_life_days": 60,
            },
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_DUPLICATE_SKU)

        reread = validate_success(api.get_product(first["id"], ADMIN), 200)
        assert reread["name"] == "First", "first product must be untouched"

    def test_product_rediscontinue_rejected(self, api):
        """PRD §3.2: "Repeating the operation on an already-`DISCONTINUED`
        product is a from-state rejection carrying `ERR_PRODUCT_DISCONTINUED`
        at the 409 tier."

        Design: Corner/state_machines/product_rediscontinue_rejected
        """
        product = create_product(sku="DSC-1", name="Disc item", category="CANDY",
                                 eligible_location_types=["GYM"], case_pack_qty=10,
                                 base_price_cents=500, cost_cents=300,
                                 shelf_life_days=120)
        validate_success(api.discontinue_product(product["id"], ADMIN), 200)

        # PRD §5 pins 409 for the repeated discontinuation specifically; the
        # registered map carries the common 422, so pass 409 explicitly.
        err = api.discontinue_product(product["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_PRODUCT_DISCONTINUED, 409)

        reread = validate_success(api.get_product(product["id"], ADMIN), 200)
        assert reread["status"] == "DISCONTINUED"


class TestLocationCreationValidation:
    def test_location_create_bogus_operator_fk_returns_not_found(self, api):
        """PRD §2.8: "Identifiers carried in the request body must exist:
        `location_id`, `route_id`, `operator_id`, `product_id`, `order_id`,
        `telemetry_event_id`, and the `product_id` members inside `lines` and
        `slots`. A missing reference rejects with its matching not-found error"

        Design: Corner/entities/location_create_bogus_operator_fk_returns_not_found
        """
        route = create_route("R-FK", ("MON",), 50, 0)
        err = api.create_location(
            {
                "operator_id": BOGUS_UUID_1,
                "name": "L-Bogus",
                "location_type": "OFFICE",
                "route_id": route["id"],
            },
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_OPERATOR_NOT_FOUND)

    def test_location_create_invalid_enum_rejected(self, api):
        """PRD §2.8: "Required fields must be present, enum members valid,
        types correct, and integer quantities greater than zero, else
        `ERR_INVALID_REQUEST`"
        PRD §3.3: "the `location_type` — one of `OFFICE`, `SCHOOL`, `HOSPITAL`,
        or `GYM`, which gates which products may be vended there"

        Design: Corner/entities/location_create_invalid_enum_rejected
        """
        op = create_operator("Op Enum")
        route = create_route("R-EN", ("TUE",), 50, 0)
        err = api.create_location(
            {
                "operator_id": op["id"],
                "name": "L-BadEnum",
                "location_type": "MALL",
                "route_id": route["id"],
            },
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_INVALID_REQUEST)


class TestPathExistence:
    def test_entity_not_found_gets(self, api):
        """PRD §2.8: "Identifiers in a parameterized path are validated
        sequentially from left to right; the first identifier that does not
        resolve rejects the request with its matching not-found error —
        `ERR_OPERATOR_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
        `ERR_LOCATION_NOT_FOUND`, `ERR_PLANOGRAM_NOT_FOUND`,
        `ERR_PROMOTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_CREDIT_CLAIM_NOT_FOUND`, or `ERR_SERVICE_TICKET_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/entity_not_found_gets
        """
        cases = [
            (api.get_operator(BOGUS_UUID_1, ADMIN), ApiErrorId.ERR_OPERATOR_NOT_FOUND),
            (api.get_location(BOGUS_UUID_2, ADMIN), ApiErrorId.ERR_LOCATION_NOT_FOUND),
            (api.get_route(BOGUS_UUID_3, ADMIN), ApiErrorId.ERR_ROUTE_NOT_FOUND),
            (api.get_product(BOGUS_UUID_4, ADMIN), ApiErrorId.ERR_PRODUCT_NOT_FOUND),
            (api.get_promotion(BOGUS_UUID_5, ADMIN), ApiErrorId.ERR_PROMOTION_NOT_FOUND),
            (api.get_planogram(BOGUS_UUID_6, ADMIN), ApiErrorId.ERR_PLANOGRAM_NOT_FOUND),
            (api.get_order(BOGUS_UUID_7, ADMIN), ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api.get_credit_claim(BOGUS_UUID_8, ADMIN), ApiErrorId.ERR_CREDIT_CLAIM_NOT_FOUND),
            (api.get_service_ticket(BOGUS_UUID_9, ADMIN), ApiErrorId.ERR_SERVICE_TICKET_NOT_FOUND),
        ]
        for resp, error_id in cases:
            validate_error(resp, error_id)


class TestAuthenticationContext:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or naming a role the
        system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        # No X-User-ID / X-User-Role headers at all.
        resp = api.list_operators(None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_missing_auth_beats_not_found(self, api):
        """PRD §2.8: "the cascade below is evaluated in order, the first
        failing tier determines the response, and later tiers are never reached
        for that request." (tier 1 authentication precedes tier 4 existence.)

        Design: Corner/validations/missing_auth_beats_not_found
        """
        # Headerless GET on a non-existent order: auth fires before existence.
        resp = api.get_order(BOGUS_UUID_7, None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRbac:
    def test_rbac_exclusive_operation_denials(self, api):
        """PRD §2.1: "Beyond authentication, every write operation restricts
        which roles may invoke it; a caller whose role is not on the
        operation's authorization list is rejected with `ERR_FORBIDDEN`."
        PRD §4: the authorization list for `/wholesale/telemetry-events` is
        "TelemetryGateway" alone, so WholesaleAdmin is denied ingestion too.

        Design: Corner/roles/rbac_exclusive_operation_denials
        """
        om_headers = make_operator_manager_headers(BOGUS_UUID_1)

        # OperatorManager creating products (WholesaleAdmin-only).
        e1 = api.create_product(
            {
                "sku": "RB-1", "name": "Denied", "category": "SNACK",
                "eligible_location_types": ["OFFICE"], "case_pack_qty": 10,
                "base_price_cents": 100, "cost_cents": 50, "shelf_life_days": 30,
            },
            om_headers,
        )
        validate_error(e1, ApiErrorId.ERR_FORBIDDEN)

        # CreditAdjuster filing claims (OperatorManager-only).
        e2 = api.create_credit_claim(
            {"order_id": BOGUS_UUID_2, "lines": []},
            ADJUSTER,
        )
        validate_error(e2, ApiErrorId.ERR_FORBIDDEN)

        # RoutePlanner marking delivered (WarehouseOps-only).
        e3 = api.mark_order_delivered(BOGUS_UUID_3, PLANNER)
        validate_error(e3, ApiErrorId.ERR_FORBIDDEN)

        # WarehouseOps settling (WholesaleAdmin-only).
        e4 = api.settle_order(
            BOGUS_UUID_4,
            {"tender_type": "CASH", "telemetry_event_id": BOGUS_UUID_5},
            WAREHOUSE,
        )
        validate_error(e4, ApiErrorId.ERR_FORBIDDEN)

        # TelemetryGateway creating routes (WholesaleAdmin-only).
        e5 = api.create_route(
            {"route_code": "R-RB", "delivery_weekdays": ["MON"],
             "daily_case_capacity": 10, "min_order_cents": 0},
            TELEMETRY,
        )
        validate_error(e5, ApiErrorId.ERR_FORBIDDEN)

        # WholesaleAdmin ingesting telemetry (TelemetryGateway-only — the role
        # model has no superset role).
        e6 = api.create_telemetry_event(
            {"location_id": BOGUS_UUID_6, "recorded_at": "2026-08-01T00:00:00Z",
             "cash_collected_cents": 0, "cashless_sales_cents": 0, "items": []},
            ADMIN,
        )
        validate_error(e6, ApiErrorId.ERR_FORBIDDEN)

    def test_rbac_operator_manager_positive_own_resource(self, api):
        """PRD §3.3: "An `OperatorManager` may create locations only for its own
        operator, while a `WholesaleAdmin` may create for any."
        PRD §3.3: "its `on_hand_projection` starts as an empty array"

        Design: Corner/roles/rbac_operator_manager_positive_own_resource
        """
        op = create_operator("Op Allow")
        route = create_route("R-ALW", ("WED",), 50, 0)
        resp = api.create_location(
            {
                "operator_id": op["id"],
                "name": "L-Allow",
                "location_type": "HOSPITAL",
                "route_id": route["id"],
            },
            make_operator_manager_headers(op["id"]),
        )
        loc = validate_success(resp, 201)
        assert loc["operator_id"] == op["id"]
        assert loc["on_hand_projection"] == []

    def test_operator_manager_cannot_touch_other_operators_order(self, api):
        """PRD §2.1: "ownership checks on any resource that references an
        operator — replenishment orders, credit claims, service tickets, and
        planograms via their location's owning operator — compare the
        resource's operator foreign key to `X-User-ID`, and a mismatch is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/validations/operator_manager_cannot_touch_other_operators_order
        """
        op_a = create_operator("Op A-own")
        op_b = create_operator("Op B-own")
        route = create_route("R-OWN", ("MON",), 50, 0)
        product = create_product(sku="OWN-1", name="Own item")
        loc = create_location(op_a["id"], route["id"], "L-A")
        order_resp = api.create_order(
            {
                "location_id": loc["id"],
                "requested_delivery_date": "2026-08-03",
                "lines": [{"product_id": product["id"], "quantity_cases": 1}],
            },
            make_operator_manager_headers(op_a["id"]),
        )
        order = validate_success(order_resp, 201)

        err = api.submit_order(order["id"], make_operator_manager_headers(op_b["id"]))
        validate_error(err, ApiErrorId.ERR_FORBIDDEN)

        reread = validate_success(api.get_order(order["id"], ADMIN), 200)
        assert reread["fulfillment_status"] == "DRAFT"
