"""Response envelope, creation defaults, existence checks, and pagination
(PRD §2.2, §2.3, §2.4, §2.6, §3.1)."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, create_customer, create_site,
    create_vehicles, create_wash_order, is_iso8601_timestamp, is_valid_uuid,
    setup_customer_site_vehicles, validate_error, validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestCustomerCreationDefaults:
    def test_minimal_customer_gets_defaults(self, api):
        """PRD §3.1: "A customer is created with a display `name`, a contact `email`
        that must be unique across customers, and an optional `customer_type` of
        `RETAIL` or `FLEET` (defaulting to `RETAIL`). New customers start with
        `status` `ACTIVE`."
        PRD §2.4: "`version` (integer): starts at 1 when the resource is created and
        increments by one on every mutation."

        Design: Corner/entities/customer_creation_defaults
        """
        resp = api.create_customer({"name": "Acme", "email": "acme@example.com"},
                                   ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["customer_type"] == "RETAIL"
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestVehicleInvalidClassRejected:
    def test_unknown_vehicle_class_rejected(self, api):
        """PRD §2.6: "Body shape — required fields are present, and types, enum
        members, and ranges are valid (dates parse, a window's end is strictly after
        its start, gallons are positive, audit scores lie between 0 and 20
        inclusive), else `ERR_VALIDATION`."
        PRD §3.1: "a `vehicle_class` of `SEDAN`, `SUV_PICKUP`, `VAN_BOXTRUCK`, or
        `HEAVY_FLEET`"

        Design: Corner/entities/vehicle_invalid_class_rejected
        """
        ctx = setup_customer_site_vehicles(num_vehicles=0, vehicle_class="SEDAN")
        resp = api.create_vehicle(
            {"customer_id": ctx["customer"]["id"], "site_id": ctx["site"]["id"],
             "plate": "E2X", "vehicle_class": "MOTORCYCLE"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _, meta = validate_paginated(api.list_vehicles(DISPATCHER))
        assert meta["total_count"] == 0


class TestVehicleUnknownCustomerReturnsNotFound:
    def test_body_fk_to_missing_customer_rejected(self, api):
        """PRD §2.6: "Existence — path identifiers and body foreign-key references
        exist, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/vehicle_unknown_customer_returns_not_found
        """
        customer = create_customer()
        site = create_site(customer["id"], name="E5S")
        resp = api.create_vehicle(
            {"customer_id": NON_EXISTENT_UUID, "site_id": site["id"],
             "plate": "E5X", "vehicle_class": "SEDAN"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestGetUnknownWashOrderReturnsNotFound:
    def test_missing_order_id_returns_404(self, api):
        """PRD §2.6: "Existence — path identifiers and body foreign-key references
        exist, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/endpoints/get_unknown_wash_order_returns_not_found
        """
        resp = api.get_wash_order(NON_EXISTENT_UUID, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestErrorEnvelopeShapeOnNotFound:
    def test_error_response_uses_fixed_envelope(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.get_site(NON_EXISTENT_UUID, DISPATCHER)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestWashOrdersPaginationDefaults:
    def test_default_limit_and_offset_paging(self, api):
        """PRD §2.3: "When omitted, `limit` defaults to 10, with a minimum of 1 and a
        maximum of 100; `offset` defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/wash_orders_pagination_defaults
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        for hour in range(8, 20):  # 12 DRAFT orders
            create_wash_order(
                ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
                scheduled_window_start=f"2026-08-06T{hour:02d}:00:00Z",
                scheduled_window_end=f"2026-08-06T{hour:02d}:30:00Z",
            )
        page1, meta1 = validate_paginated(api.list_wash_orders(DISPATCHER))
        assert len(page1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_wash_orders(
            DISPATCHER, params={"limit": 10, "offset": 10},
        ))
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
