"""CRUD plumbing and input-validation tests.

Covers the basic create/read/list paths for every PRD §3.1-§3.4
resource, pagination per PRD §2.3, the response envelope per PRD §2.2,
and the fiscal range checks per PRD §3.3 / §5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assert_address,
    assert_customer,
    assert_driver,
    assert_parcel,
    assert_route,
    assert_transit_center,
    create_address,
    create_address_payload,
    create_customer,
    create_customer_payload,
    create_customer_with_default_address,
    create_driver,
    create_driver_payload,
    create_parcel,
    create_parcel_payload,
    create_route,
    create_route_payload,
    create_transit_center,
    create_transit_center_payload,
    iso_utc,
    make_customer_headers,
    PAGINATION_DEFAULT_LIMIT,
    PARCEL_DECLARED_VALUE_MAX_INCLUSIVE,
    PARCEL_WEIGHT_MAX_INCLUSIVE,
    TEST_USERS,
    add_hours,
    setup_baseline,
    utcnow,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
class TestCustomerCrud:

    def test_create_customer_returns_201_and_shape(self, api):
        """PRD §4: 'Operations that create a brand-new stand-alone
        resource (a customer, a parcel, an address, a transit center,
        a driver, a route, a route stop, an appointment, or a delivery
        attempt) return 201 Created.'"""
        payload = create_customer_payload()
        res = api.create_customer(payload, TEST_USERS["dispatcher_headers"])
        cust = validate_success(res, 201)
        assert_customer(cust)
        assert cust["email"] == payload["email"]
        # PRD §3.1: 'an optional driver_release_authorized flag —
        # defaulting to false.'
        assert cust["driver_release_authorized"] is False
        # PRD §3.1: 'A new customer's default_address_id is unset
        # until at least one address has been added.'
        assert cust.get("default_address_id") in (None,)

    def test_get_nonexistent_customer_returns_404(self, api):
        """PRD §2.9: 'Path-id existence (left-to-right) — a missing row
        yields ERR_NOT_FOUND.'"""
        res = api.get_customer(
            NON_EXISTENT_UUID, TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_patch_customer_toggles_driver_release(self, api):
        """PRD §3.1: 'toggle of driver_release_authorized flow through
        the same controlled customer update path.'"""
        cust = create_customer(driver_release_authorized=False)
        res = api.patch_customer(
            cust["id"], {"driver_release_authorized": True},
            make_customer_headers(cust["id"]),
        )
        updated = validate_success(res, 200)
        assert updated["driver_release_authorized"] is True

    def test_add_address_then_set_default(self, api):
        """PRD §3.1: 'Once an address exists, the customer's
        default_address_id may be updated to point at it.'"""
        cust, addr = create_customer_with_default_address()
        assert cust["default_address_id"] == addr["id"]
        assert_address(addr)


# ---------------------------------------------------------------------------
# Transit center / driver
# ---------------------------------------------------------------------------
class TestTransitCenterAndDriverCrud:

    def test_create_transit_center_201(self, api):
        """PRD §3.2: 'Each TransitCenter is registered by a Dispatcher
        with a three-letter code consisting of exactly three uppercase
        letters'."""
        res = api.create_transit_center(
            create_transit_center_payload(code="LAX"),
            TEST_USERS["dispatcher_headers"],
        )
        center = validate_success(res, 201)
        assert_transit_center(center)
        assert center["code"] == "LAX"
        # PRD §3.2: 'an optional hazmat_certified flag — defaulting to false.'
        assert center["hazmat_certified"] is False
        # PRD §3.2: 'The parcels_on_belt counter is system-maintained ...
        # initialized to zero.'
        assert center["parcels_on_belt"] == 0

    def test_create_driver_starts_off_duty(self, api):
        """PRD §3.2: 'A driver's status field is system-computed and
        traverses a four-state cycle: starting OFF_DUTY'."""
        center = create_transit_center()
        res = api.create_driver(
            create_driver_payload(home_center_id=center["id"]),
            TEST_USERS["dispatcher_headers"],
        )
        driver = validate_success(res, 201)
        assert_driver(driver)
        assert driver["status"] == "OFF_DUTY"
        # PRD §3.2: 'an optional hazmat_endorsement flag (default false).'
        assert driver["hazmat_endorsement"] is False


# ---------------------------------------------------------------------------
# Parcel — base creation and fiscal range checks
# ---------------------------------------------------------------------------
class TestParcelInductionAndRanges:

    def test_induct_parcel_starts_in_inducted_and_mints_tracking(self, api):
        """PRD §3.3: 'The server mints a 12-character alphanumeric
        tracking_number composed of uppercase letters and digits,
        places the parcel into the initial state INDUCTED'."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        parcel = validate_success(res, 201)
        assert_parcel(parcel)
        assert parcel["status"] == "INDUCTED"
        # PRD §3.3: 'initializes redelivery_attempts to zero, sets
        # last_attempt_outcome to NONE, leaves final_fee unset'.
        assert parcel["redelivery_attempts"] == 0
        assert parcel["last_attempt_outcome"] == "NONE"
        assert parcel.get("final_fee") is None

    def test_weight_at_upper_boundary_70_accepted(self, api):
        """PRD §3.3: 'The declared weight_kg is rejected with
        ERR_PARCEL_WEIGHT_OUT_OF_RANGE if it is not strictly greater
        than zero and at most 70.0 kilograms (70.0 inclusive is
        accepted; 70.01 is rejected)'."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=PARCEL_WEIGHT_MAX_INCLUSIVE,
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        parcel = validate_success(res, 201)
        assert parcel["weight_kg"] == PARCEL_WEIGHT_MAX_INCLUSIVE

    def test_weight_just_above_70_rejected(self, api):
        """PRD §3.3: '70.01 is rejected' with
        ERR_PARCEL_WEIGHT_OUT_OF_RANGE."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=70.01,
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        validate_error(res, "ERR_PARCEL_WEIGHT_OUT_OF_RANGE")

    def test_weight_zero_rejected(self, api):
        """PRD §3.3: 'not strictly greater than zero ... is rejected
        with ERR_PARCEL_WEIGHT_OUT_OF_RANGE'."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=0.0,
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        validate_error(res, "ERR_PARCEL_WEIGHT_OUT_OF_RANGE")

    def test_declared_value_above_max_rejected(self, api):
        """PRD §3.3: 'the declared_value is rejected with
        ERR_DECLARED_VALUE_OUT_OF_RANGE if it is below zero or above
        50000.00.'"""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
            declared_value=PARCEL_DECLARED_VALUE_MAX_INCLUSIVE + 0.01,
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        validate_error(res, "ERR_DECLARED_VALUE_OUT_OF_RANGE")

    def test_declared_value_below_zero_rejected(self, api):
        """PRD §3.3: 'below zero ... is rejected with
        ERR_DECLARED_VALUE_OUT_OF_RANGE'."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
            declared_value=-0.01,
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        validate_error(res, "ERR_DECLARED_VALUE_OUT_OF_RANGE")

    def test_declared_value_zero_accepted(self, api):
        """PRD §3.3: range is '[0, 50000.00]'. Zero is the lower
        bound and is accepted."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
            declared_value=0.0,
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        parcel = validate_success(res, 201)
        assert parcel["declared_value"] == 0.0

    def test_destination_defaults_to_customer_default_address(self, api):
        """PRD §3.3: 'an optional destination_address_id (which, when
        omitted, defaults to the customer's default_address_id)'."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
        )
        # No destination_address_id supplied.
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        parcel = validate_success(res, 201)
        assert parcel["destination_address_id"] == base["address"]["id"]


# ---------------------------------------------------------------------------
# 404 / reference-not-found paths
# ---------------------------------------------------------------------------
class TestPathAndReferenceExistence:

    def test_get_nonexistent_parcel_returns_404(self, api):
        """PRD §2.5: 'The first identifier that does not resolve to an
        existing row yields ERR_NOT_FOUND'."""
        res = api.get_parcel(
            NON_EXISTENT_UUID, TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_nonexistent_route_returns_404(self, api):
        res = api.get_route(
            NON_EXISTENT_UUID, TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_parcel_with_unknown_customer_id_returns_reference_not_found(self, api):
        """PRD §2.5: 'Body-level foreign-key references ... a body-level
        reference to a non-existent row produces ERR_REFERENCE_NOT_FOUND.'"""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=NON_EXISTENT_UUID,
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_create_parcel_with_unknown_origin_center_returns_reference_not_found(self, api):
        """PRD §2.5: 'a body-level reference to a non-existent row
        produces ERR_REFERENCE_NOT_FOUND'."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=NON_EXISTENT_UUID,
            destination_address_id=base["address"]["id"],
        )
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_create_route_with_unknown_driver_returns_reference_not_found(self, api):
        """PRD §2.5: same rule for /routes; driver_id is a body-level FK."""
        base = setup_baseline()
        payload = create_route_payload(
            center_id=base["center"]["id"], driver_id=NON_EXISTENT_UUID,
        )
        res = api.create_route(payload, TEST_USERS["dispatcher_headers"])
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ---------------------------------------------------------------------------
# Pagination + list
# ---------------------------------------------------------------------------
class TestParcelListPagination:

    def test_list_parcels_returns_pagination_meta(self, api):
        """PRD §2.3: 'Every paginated list response includes limit,
        offset, total_count, and has_more inside the meta object'."""
        base = setup_baseline()
        for _ in range(3):
            create_parcel(
                base["customer"]["id"], base["center"]["id"],
                destination_address_id=base["address"]["id"],
            )
        data, meta = validate_paginated(
            api.list_parcels(TEST_USERS["dispatcher_headers"]),
        )
        assert "total_count" in meta and meta["total_count"] >= 3
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta
        assert len(data) >= 1

    def test_list_parcels_limit_one(self, api):
        """PRD §2.3: 'The limit parameter specifies the maximum number
        of items returned'."""
        base = setup_baseline()
        for _ in range(2):
            create_parcel(
                base["customer"]["id"], base["center"]["id"],
                destination_address_id=base["address"]["id"],
            )
        data, meta = validate_paginated(api.list_parcels(
            TEST_USERS["dispatcher_headers"], params={"limit": 1},
        ))
        assert len(data) == 1
        assert meta["limit"] == 1

    def test_list_parcels_default_limit_is_10(self, api):
        """PRD §2.3: 'defaults to 10'."""
        # Don't need to verify there's >10 items — just that limit=10 is the meta.
        data, meta = validate_paginated(
            api.list_parcels(TEST_USERS["dispatcher_headers"]),
        )
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT

    def test_list_parcels_filter_by_status(self, api):
        """PRD §4: 'Filters available on the parcel list endpoint are
        passed as query parameters: status, customer_id,
        origin_center_id, hazmat_class'."""
        base = setup_baseline()
        p1 = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        # Filter by INDUCTED — p1 should appear.
        data, _ = validate_paginated(api.list_parcels(
            TEST_USERS["dispatcher_headers"],
            params={"status": "INDUCTED"},
        ))
        ids = {item["id"] for item in data}
        assert p1["id"] in ids
        # Filter by DELIVERED — p1 must not appear.
        data, _ = validate_paginated(api.list_parcels(
            TEST_USERS["dispatcher_headers"],
            params={"status": "DELIVERED"},
        ))
        ids = {item["id"] for item in data}
        assert p1["id"] not in ids
