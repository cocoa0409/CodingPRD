"""Warehouse, bin, and lot creation; CRUD/input validation; auth/role gates."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_warehouse, assert_bin, assert_lot,
    create_warehouse_payload, create_bin_payload, create_lot_payload,
    TEST_USERS, NON_EXISTENT_UUID, build_user_headers,
    create_warehouse, create_bin, create_lot,
    TEST_DEFAULTS, ABNORMAL_EVENT_WEIGHT, RECALL_WEIGHT,
)


# =============================================================================
# Warehouse creation
# =============================================================================

class TestWarehouseCreation:
    def test_create_warehouse_default_putaway_strategy(self, api, manager_headers):
        """PRD §3.1: "an optional putaway_strategy selector that defaults to
        DISTANCE_OPTIMIZED when the request omits it"

        Claim: omitting putaway_strategy on POST /warehouses → default DISTANCE_OPTIMIZED.
        """
        payload = create_warehouse_payload(name="Default-Strategy")
        # Make sure we're not passing the field
        payload.pop("putaway_strategy", None)
        wh = validate_success(api.create_warehouse(payload, manager_headers), 201)
        assert_warehouse(wh)
        assert wh["putaway_strategy"] == "DISTANCE_OPTIMIZED"

    def test_create_warehouse_explicit_capacity_optimized(self, api, manager_headers):
        """PRD §3.1: "the alternative value is CAPACITY_OPTIMIZED"

        Claim: explicit putaway_strategy=CAPACITY_OPTIMIZED is honored.
        """
        payload = create_warehouse_payload(name="Cap-Opt-WH",
                                          putaway_strategy="CAPACITY_OPTIMIZED")
        wh = validate_success(api.create_warehouse(payload, manager_headers), 201)
        assert wh["putaway_strategy"] == "CAPACITY_OPTIMIZED"

    def test_create_warehouse_seeds_initial_state(self, api, manager_headers):
        """PRD §3.1: "On creation the system also seeds the warehouse with
        ops_run_index set to 0, clock_now set to the fixed epoch
        1970-01-01T00:00:00.000Z, the rolling counters
        shrinkage_value_30d_cents, abnormal_event_count_24h, and
        recall_count_open set to 0, the risk_score set to 0, and the posture
        set to OPEN."

        Claim: every initial counter and posture is seeded as specified.
        """
        wh = validate_success(api.create_warehouse(
            create_warehouse_payload(name="Seed-Test"), manager_headers), 201)
        assert wh["ops_run_index"] == 0
        assert wh["clock_now"].startswith("1970-01-01T00:00:00")
        assert wh["shrinkage_value_30d_cents"] == 0
        assert wh["abnormal_event_count_24h"] == 0
        assert wh["recall_count_open"] == 0
        assert wh["risk_score"] == 0
        assert wh["posture"] == "OPEN"

    def test_get_warehouse_round_trip(self, api, manager_headers):
        """PRD §3.1: "Read-only retrieval of a warehouse exposes all of the
        fields above: identity, name, dock position, the putaway_strategy,
        the clock_now, ops_run_index, the rolling counters, the risk_score,
        and the posture."

        Claim: GET /warehouses/{id} returns the same resource that POST created.
        """
        wh = validate_success(api.create_warehouse(
            create_warehouse_payload(name="Round-Trip"), manager_headers), 201)
        retrieved = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert retrieved["id"] == wh["id"]
        assert retrieved["name"] == "Round-Trip"
        assert_warehouse(retrieved)


class TestWarehouseInputValidation:
    @pytest.mark.parametrize("missing_field",
        ["name", "dock_position_x", "dock_position_y"])
    def test_create_warehouse_missing_required(self, api, manager_headers, missing_field):
        """PRD §3.1: "Creating a warehouse takes a name, an inbound dock
        location given by dock_position_x and dock_position_y (the origin
        from which bin distances are measured), and an optional
        putaway_strategy selector"

        Claim: omitting any required field → ERR_INVALID_INPUT (422).
        """
        payload = create_warehouse_payload(name="With-Missing")
        del payload[missing_field]
        validate_error(api.create_warehouse(payload, manager_headers),
                      "ERR_INVALID_INPUT")

    def test_get_warehouse_not_found(self, api, manager_headers):
        """PRD §2.6 rule 3: "Every path-id must exist within its parent scope,
        otherwise ERR_NOT_FOUND."

        Claim: GET on a non-existent warehouse id → ERR_NOT_FOUND (404).
        """
        validate_error(api.get_warehouse(NON_EXISTENT_UUID, manager_headers),
                      "ERR_NOT_FOUND")


# =============================================================================
# Bin creation
# =============================================================================

class TestBinCreation:
    def test_create_bin_initial_state(self, api, manager_headers):
        """PRD §3.1: "Each new bin starts with used_volume_cm3 and
        used_weight_g at 0, status ACTIVE, and frozen_by_cycle_count_id null."

        Claim: a freshly-created bin has used capacities at 0, status ACTIVE.
        """
        wh = create_warehouse()
        payload = create_bin_payload(bin_code="BIN-INIT", zone="AMBIENT",
                                    position_x=3, position_y=4,
                                    capacity_volume_cm3=1000, capacity_weight_g=2000)
        b = validate_success(api.create_bin(wh["id"], payload, manager_headers), 201)
        assert_bin(b)
        assert b["used_volume_cm3"] == 0
        assert b["used_weight_g"] == 0
        assert b["status"] == "ACTIVE"
        assert b["frozen_by_cycle_count_id"] is None
        assert b["remaining_volume_cm3"] == 1000
        assert b["remaining_weight_g"] == 2000

    def test_bin_distance_from_dock_euclidean(self, api, manager_headers):
        """PRD §3.1: "The system computes distance_from_dock as the Euclidean
        distance from the bin position to the warehouse's dock position —
        that is, the square root of the sum of the squared differences
        between position_x and dock_position_x and between position_y and
        dock_position_y — rounded half-up to four decimal places."

        Claim: distance_from_dock = sqrt(dx^2 + dy^2), rounded to 4 decimals.
        """
        wh = create_warehouse(dock_position_x=0, dock_position_y=0)
        b = validate_success(api.create_bin(
            wh["id"],
            create_bin_payload(bin_code="DIST-3-4", position_x=3, position_y=4,
                              capacity_volume_cm3=1000, capacity_weight_g=1000),
            manager_headers), 201)
        # sqrt(9 + 16) = 5.0
        assert b["distance_from_dock"] == pytest.approx(5.0, abs=1e-4)

    def test_bin_distance_off_origin(self, api, manager_headers):
        """PRD §3.1: see distance_from_dock formula above.

        Claim: distance_from_dock measures from dock position, not origin.
        """
        wh = create_warehouse(dock_position_x=10, dock_position_y=10)
        b = validate_success(api.create_bin(
            wh["id"],
            create_bin_payload(bin_code="DIST-OFF", position_x=13, position_y=14,
                              capacity_volume_cm3=1000, capacity_weight_g=1000),
            manager_headers), 201)
        # sqrt(9 + 16) = 5.0
        assert b["distance_from_dock"] == pytest.approx(5.0, abs=1e-4)

    @pytest.mark.parametrize("zone", ["AMBIENT", "COLD", "HAZMAT", "RETURNS"])
    def test_create_bin_each_valid_zone(self, api, manager_headers, zone):
        """PRD §3.1: "a zone chosen from AMBIENT, COLD, HAZMAT, or RETURNS"

        Claim: every declared zone enum value is accepted.
        """
        wh = create_warehouse()
        b = validate_success(api.create_bin(
            wh["id"],
            create_bin_payload(bin_code=f"ZONE-{zone}", zone=zone,
                              capacity_volume_cm3=1000, capacity_weight_g=1000),
            manager_headers), 201)
        assert b["zone"] == zone


class TestBinInputValidation:
    @pytest.mark.parametrize("missing_field",
        ["bin_code", "zone", "position_x", "position_y",
         "capacity_volume_cm3", "capacity_weight_g"])
    def test_create_bin_missing_required(self, api, manager_headers, missing_field):
        """PRD §3.1: lists bin_code, zone, position_x, position_y,
        capacity_volume_cm3, and capacity_weight_g as the bin input fields.

        Claim: omitting any required field → ERR_INVALID_INPUT.
        """
        wh = create_warehouse()
        payload = create_bin_payload(bin_code="MISSING")
        del payload[missing_field]
        validate_error(api.create_bin(wh["id"], payload, manager_headers),
                      "ERR_INVALID_INPUT")

    def test_create_bin_in_nonexistent_warehouse(self, api, manager_headers):
        """PRD §2.6 rule 3: "Every path-id must exist within its parent scope,
        otherwise ERR_NOT_FOUND."

        Claim: creating a bin under a non-existent warehouse id → ERR_NOT_FOUND.
        """
        validate_error(
            api.create_bin(NON_EXISTENT_UUID, create_bin_payload(), manager_headers),
            "ERR_NOT_FOUND")


# =============================================================================
# Lot creation
# =============================================================================

class TestLotCreation:
    def test_create_lot_initial_state(self, api, manager_headers):
        """PRD §3.1: "Newly-created lots have status ACTIVE; the recalled_at
        and recall_reason fields are populated only when the lot transitions
        into RECALLED."

        Claim: a freshly-created lot starts in ACTIVE, with recalled_at null.
        """
        wh = create_warehouse()
        lot = validate_success(api.create_lot(
            wh["id"],
            create_lot_payload(lot_code="LOT-INIT", sku="WIDGET"),
            manager_headers), 201)
        assert_lot(lot)
        assert lot["status"] == "ACTIVE"
        assert lot.get("recalled_at") is None
        assert lot.get("recall_reason") is None

    def test_create_lot_received_at_initially_empty(self, api, manager_headers):
        """PRD §3.1: "The received_at timestamp on the lot is left empty at
        creation and is filled by the system the very first time the lot
        is putaway from an inbound shipment"

        Claim: received_at is null at creation time.
        """
        wh = create_warehouse()
        lot = validate_success(api.create_lot(
            wh["id"], create_lot_payload(lot_code="RECV-AT-NULL"),
            manager_headers), 201)
        assert lot.get("received_at") is None


class TestLotInputValidation:
    @pytest.mark.parametrize("missing_field", [
        "lot_code", "sku", "category", "unit_weight_g", "unit_volume_cm3",
        "unit_value_cents", "manufacture_date", "expiry_date", "supplier_lot_ref",
    ])
    def test_create_lot_missing_required(self, api, manager_headers, missing_field):
        """PRD §3.1: lists lot_code, sku, category, unit_weight_g, unit_volume_cm3,
        unit_value_cents, manufacture_date, expiry_date, supplier_lot_ref as
        the lot input fields.

        Claim: omitting any required field → ERR_INVALID_INPUT.
        """
        wh = create_warehouse()
        payload = create_lot_payload(lot_code="MISSING")
        del payload[missing_field]
        validate_error(api.create_lot(wh["id"], payload, manager_headers),
                      "ERR_INVALID_INPUT")


# =============================================================================
# Auth and role validation (PRD §2.1)
# =============================================================================

class TestAuth:
    def test_missing_user_id_header(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED and HTTP status 401."

        Claim: a request lacking X-User-ID → ERR_AUTH_REQUIRED (401).
        """
        headers = {"X-User-Role": "WarehouseManager"}
        validate_error(api.create_warehouse(create_warehouse_payload(), headers),
                      "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header(self, api):
        """PRD §2.1: same sentence as above.

        Claim: a request lacking X-User-Role → ERR_AUTH_REQUIRED (401).
        """
        headers = {"X-User-ID": "test"}
        validate_error(api.create_warehouse(create_warehouse_payload(), headers),
                      "ERR_AUTH_REQUIRED")

    def test_empty_user_id_header(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED and HTTP status 401."

        Claim: an empty X-User-ID header → ERR_AUTH_REQUIRED (401).
        """
        headers = {"X-User-ID": "", "X-User-Role": "WarehouseManager"}
        validate_error(api.create_warehouse(create_warehouse_payload(), headers),
                      "ERR_AUTH_REQUIRED")

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "If both headers are present but X-User-Role is not one
        of the three role names below, the request is rejected with
        ERR_FORBIDDEN and HTTP status 403."

        Claim: an unrecognised role name → ERR_FORBIDDEN (403).
        """
        headers = build_user_headers("test", "Hacker")
        validate_error(api.create_warehouse(create_warehouse_payload(), headers),
                      "ERR_FORBIDDEN")

    def test_role_unauthorized_for_endpoint(self, api):
        """PRD §2.1: "The same ERR_FORBIDDEN is returned when the caller's
        role is recognised but is not authorised for the specific endpoint
        per the role-permission matrix in §4."

        Claim: WarehouseStaff cannot create a warehouse (manager-only) → ERR_FORBIDDEN.
        """
        headers = TEST_USERS["staff_headers"]
        validate_error(api.create_warehouse(create_warehouse_payload(), headers),
                      "ERR_FORBIDDEN")

    def test_recall_lot_forbidden_for_staff(self, api):
        """PRD §3.9: "A WarehouseManager may recall an ACTIVE or NEAR_EXPIRY lot"

        Claim: WarehouseStaff cannot invoke /lots/{id}/recall → ERR_FORBIDDEN.
        """
        wh = create_warehouse()
        lot = validate_success(api.create_lot(
            wh["id"], create_lot_payload(), TEST_USERS["manager_headers"]), 201)
        from test_helpers import create_recall_payload
        validate_error(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            TEST_USERS["staff_headers"]), "ERR_FORBIDDEN")
