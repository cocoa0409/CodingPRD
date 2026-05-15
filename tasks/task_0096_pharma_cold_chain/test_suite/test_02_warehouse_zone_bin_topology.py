"""Warehouse, zone, bin, supplier, product master data + clock.

PRD §3.1 master data; §2.7 deterministic clock.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_bin,
    assert_product,
    assert_supplier,
    assert_warehouse,
    assert_zone,
    create_bin,
    create_bin_payload,
    create_product,
    create_supplier,
    create_warehouse,
    create_zone,
    create_zone_payload,
    advance_clock,
    get_warehouse,
    get_zone,
    validate_error,
    validate_success,
)


class TestWarehouseCreation:

    def test_create_warehouse_initial_clock_is_zero(self, api):
        """PRD §2.7: "Each warehouse carries its own logical clock —
        `clock_minutes`, a non-negative integer measured in minutes
        since a per-warehouse epoch and defaulting to 0 on warehouse
        creation."

        Claim: a freshly-created warehouse has clock_minutes == 0.
        """
        wh = create_warehouse()
        assert wh["clock_minutes"] == 0
        assert_warehouse(wh)

    def test_create_warehouse_initial_status_is_active(self, api):
        """PRD §3.1: "a `status` that defaults to `ACTIVE` (the
        alternative is `SUSPENDED`)".

        Claim: warehouse status default is ACTIVE.
        """
        wh = create_warehouse()
        assert wh["status"] == "ACTIVE"


class TestClockAdvance:

    def test_clock_advance_adds_minutes(self, api):
        """PRD §2.7: "The clock advances only through explicit
        operator action: the dedicated clock-advance capability
        accepts a positive `minutes` increment, adds it to
        `clock_minutes`".

        Claim: posting minutes=N to /_clock/advance raises
        clock_minutes by N.
        """
        wh = create_warehouse()
        advance_clock(wh["id"], 30)
        wh2 = get_warehouse(wh["id"])
        assert wh2["clock_minutes"] == 30


class TestZoneCreation:

    def test_create_zone_initial_posture_is_open(self, api):
        """PRD §3.1: "The zone's `current_posture` starts at `OPEN`,
        `last_sensor_reading_c` starts null, and `utilization_units`
        starts at 0".

        Claim: new zone has posture==OPEN, utilization==0,
        last_sensor_reading_c==null.
        """
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        assert z["current_posture"] == "OPEN"
        assert z["utilization_units"] == 0
        assert z.get("last_sensor_reading_c") is None
        assert_zone(z)

    def test_create_zone_persists_temperature_bands(self, api):
        wh = create_warehouse()
        z = create_zone(
            wh["id"], zone_type="REFRIGERATED",
            target_temp_low_c=2.0, target_temp_high_c=8.0,
            alarm_low_c=0.0, alarm_high_c=10.0,
            capacity_units=500,
        )
        assert z["target_temp_low_c"] == 2.0
        assert z["target_temp_high_c"] == 8.0
        assert z["alarm_low_c"] == 0.0
        assert z["alarm_high_c"] == 10.0
        assert z["capacity_units"] == 500


class TestBinCreation:

    def test_create_bin_initial_status_is_available(self, api):
        """PRD §3.1: "Initial state is empty and `AVAILABLE`."

        Claim: new bin has status==AVAILABLE, current_lot_id==null,
        occupied_volume==0.
        """
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        b = create_bin(z["id"], volume_units=100, weight_limit_kg=500.0)
        assert b["status"] == "AVAILABLE"
        assert b.get("current_lot_id") is None
        assert b["occupied_volume"] == 0
        assert_bin(b)

    def test_create_bin_default_special_storage_tag_is_none(self, api):
        """PRD §3.1: "an optional `special_storage_tag` defaulting to
        `NONE`".

        Claim: omitting special_storage_tag yields tag=='NONE'.
        """
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        b = create_bin(z["id"], volume_units=100, weight_limit_kg=500.0)
        assert b["special_storage_tag"] == "NONE"


class TestSupplierProductCreation:

    def test_create_supplier_qualified_defaults_true(self, api):
        """PRD §3.1: "a boolean `qualified` flag defaulting to true".

        Claim: omitting qualified yields qualified==true.
        """
        s = create_supplier(qualification_expiry_minutes=100_000)
        assert s["qualified"] is True
        assert_supplier(s)

    def test_create_product_default_special_storage_tag_none(self, api):
        """PRD §3.1: "an optional `special_storage_tag` defaulting to
        `NONE`".

        Claim: omitting special_storage_tag on product yields
        tag=='NONE'.
        """
        p = create_product(required_zone_type="REFRIGERATED")
        assert p["special_storage_tag"] == "NONE"
        assert p["qualified"] is True
        assert_product(p)

    @pytest.mark.parametrize("tag", [
        "NONE", "NARCOTIC", "PSYCHOTROPIC", "BIOLOGICAL", "VACCINE",
    ])
    def test_create_product_with_each_tag(self, api, tag):
        p = create_product(
            required_zone_type="REFRIGERATED", special_storage_tag=tag,
        )
        assert p["special_storage_tag"] == tag


# ===========================================================================
# RBAC negative tests — non-WarehouseAdmin roles cannot create
# WarehouseAdmin-exclusive resources (PRD §2.1 + §4 RBAC matrix).
# ===========================================================================
class TestRbacRestrictedOperations:

    @pytest.mark.parametrize("role_key", [
        "receiver_headers", "qa_officer_headers",
        "picker_headers", "recall_officer_headers",
    ])
    def test_non_admin_cannot_create_warehouse(self, api, role_key):
        """PRD §2.1: "A `WarehouseAdmin` is the configuration role: it
        creates warehouses, zones, and bins, registers suppliers and
        products".

        Claim: non-WarehouseAdmin roles attempting POST /warehouses
        yield ERR_FORBIDDEN / 403.
        """
        from test_helpers import create_warehouse_payload
        res = api.create_warehouse(
            create_warehouse_payload(), TEST_USERS[role_key],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_warehouse_admin_only_creates_zone(self, api):
        """Same rule applies to zone creation."""
        wh = create_warehouse()
        res = api.create_zone(
            wh["id"], create_zone_payload(),
            TEST_USERS["receiver_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
