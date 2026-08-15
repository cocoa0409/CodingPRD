"""Customer registration, aircraft registration, response envelope, and pagination."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_aircraft,
    assert_customer,
    assert_error_envelope,
    create_aircraft,
    create_customer,
    create_work_order,
    make_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestCustomerDefaults:
    def test_customer_create_applies_default_kind(self, api):
        """PRD §3.1: "A `ShopManager` registers a customer with a `name` and a `contact_email` — the address downtime updates flow to — and an optional `customer_kind` of `INDIVIDUAL`, `FLIGHT_SCHOOL`, or `FLEET_OPERATOR`, which defaults to `INDIVIDUAL` when omitted."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/customer_create_applies_defaults
        """
        response = api.create_customer(
            {"name": "Default Dana", "contact_email": "dana@x.com"}, MANAGER)
        data = validate_success(response, 201)
        assert response.json()["response_type"] == "object"
        assert response.json()["meta"]["api_request_id"].startswith("req_")
        assert_customer(data)
        assert data["customer_kind"] == "INDIVIDUAL", (
            f"omitted customer_kind must default to INDIVIDUAL, "
            f"got {data['customer_kind']!r}")


class TestAircraftRegistration:
    def test_aircraft_create_missing_tail_number_rejected(self, api):
        """PRD §3.1: "Registering an aircraft requires the owning `customer_id`, a `tail_number`, the `make_model`, and a baseline weight-and-balance datum: `baseline_empty_weight_lb` to one decimal, `baseline_arm_in` to two decimals, and the forward and aft CG limits `cg_min_arm_in` and `cg_max_arm_in`."
        PRD §2.11: "Third come request-body schema checks: required fields present, types valid, enum values in range, `quantity` at least 1, `unit_price_cents` greater than 0, `estimated_hours` greater than 0, `lead_time_days` zero or more, every time window ending after it begins, `removed_arm_in` present exactly when `removed_weight_lb` is greater than zero, and `stc_number` present exactly when `approval_path` is `STC`; the `stc_number` condition carries `ERR_STC_NUMBER_REQUIRED`, and the rest carry `ERR_VALIDATION`."

        Design: Corner/entities/aircraft_create_missing_required_tail_number
        """
        customer = create_customer(name="Req Ruth", contact_email="r@x.com")
        payload = {
            "customer_id": customer["id"],
            "make_model": "Cessna 182T",
            "baseline_empty_weight_lb": 1800.0,
            "baseline_arm_in": 40.0,
            "cg_min_arm_in": 35.0,
            "cg_max_arm_in": 41.5,
        }
        response = api.create_aircraft(payload, MANAGER)
        validate_error(response, ApiErrorId.ERR_VALIDATION)

    def test_aircraft_duplicate_tail_number_rejected(self, api):
        """PRD §3.1: "Tail numbers are unique across all registered aircraft; a duplicate `tail_number` is refused with `ERR_DUPLICATE_TAIL_NUMBER`."

        Design: Corner/entities/aircraft_duplicate_tail_number_rejected
        """
        customer = create_customer(name="Dup Dan", contact_email="d@x.com")
        first = create_aircraft(customer["id"], tail_number="N600DP",
                                make_model="Cessna 182T")
        response = api.create_aircraft(
            {
                "customer_id": customer["id"],
                "tail_number": "N600DP",
                "make_model": "Cirrus SR22",
                "baseline_empty_weight_lb": 1700.0,
                "baseline_arm_in": 40.0,
                "cg_min_arm_in": 35.0,
                "cg_max_arm_in": 41.5,
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_TAIL_NUMBER)
        reread = validate_success(api.get_aircraft(first["id"], MANAGER))
        assert reread["make_model"] == "Cessna 182T", (
            "rejected duplicate registration must not disturb the original "
            f"aircraft, got make_model {reread['make_model']!r}")
        assert reread["tail_number"] == "N600DP"


class TestExistenceAndEnvelope:
    def test_work_order_get_not_found_returns_404(self, api):
        """PRD §2.10: "Path identifiers are validated left to right: the first id in the path that does not correspond to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404) before any later id is examined."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/work_order_get_not_found_returns_404
        """
        response = api.get_work_order(NON_EXISTENT_UUID, MANAGER)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)
        assert_error_envelope(response)


class TestWorkOrderPagination:
    def test_work_order_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps how many items come back; it defaults to 10, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/work_order_list_pagination
        """
        customer = create_customer(name="Page Pam", contact_email="p@x.com")
        aircraft_a = create_aircraft(customer["id"], tail_number="N630PG")
        aircraft_b = create_aircraft(customer["id"], tail_number="N631PH",
                                     baseline_empty_weight_lb=1700.0)
        create_work_order(aircraft_a["id"], scope_description="one",
                          estimated_downtime_days=5, quoted_labor_hours=2,
                          bay_code="BAY-1",
                          bay_window_start="2026-08-01T00:00:00Z",
                          bay_window_end="2026-08-10T00:00:00Z")
        create_work_order(aircraft_b["id"], scope_description="two",
                          estimated_downtime_days=5, quoted_labor_hours=2,
                          bay_code="BAY-2",
                          bay_window_start="2026-08-01T00:00:00Z",
                          bay_window_end="2026-08-10T00:00:00Z")

        page1, meta1 = validate_paginated(
            api.list_work_orders(MANAGER, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1, f"page 1 must hold exactly 1 row, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_work_orders(MANAGER, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1, f"page 2 must hold exactly 1 row, got {len(page2)}"
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"]


class TestImmediateConsistency:
    def test_aircraft_create_read_after_write(self, api):
        """PRD §3.1: "From these the server derives `baseline_moment_lb_in` as the product of the baseline empty weight and the baseline arm, rounded half-up to one decimal."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/read_after_write_immediate_consistency
        """
        customer = create_customer(name="Cons Connie", contact_email="c5@x.com")
        created = validate_success(api.create_aircraft(
            {
                "customer_id": customer["id"],
                "tail_number": "N970IM",
                "make_model": "Cessna 182T",
                "baseline_empty_weight_lb": 1800.0,
                "baseline_arm_in": 40.0,
                "cg_min_arm_in": 35.0,
                "cg_max_arm_in": 41.5,
            },
            MANAGER,
        ), 201)
        assert_aircraft(created)
        assert created["baseline_moment_lb_in"] == pytest.approx(72000.0, abs=0.05), (
            f"1800.0 lb at arm 40.0 in yields moment 72000.0, "
            f"got {created['baseline_moment_lb_in']}")
        assert created["status"] == "AVAILABLE"

        fetched = validate_success(
            api.get_aircraft(created["id"], make_inspector_headers("insp-1")))
        assert_aircraft(fetched)
        assert fetched["baseline_moment_lb_in"] == pytest.approx(
            created["baseline_moment_lb_in"], abs=0.0001), (
            "GET must expose the same stored computed field as the POST response")
        assert fetched["version"] == created["version"], (
            "no mutation between write and read, so version must match")
        assert fetched["status"] == "AVAILABLE"
