"""Equipment ledger CRUD and Station operational_status cascade
(PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_inverter,
    assert_station,
    assert_supplier,
    create_inverter,
    create_inverter_payload,
    create_station,
    create_station_payload,
    create_supplier,
    create_supplier_payload,
    setup_station_with_inverters,
    update_supplier_payload,
    validate_error,
    validate_success,
)


class TestStationCreation:
    """PRD §3.1 station fields, status defaulting, computed values."""

    def test_create_station_initial_state(self, api, admin_headers):
        """PRD §3.1: "Two enumerated postures live on the station: a
        lifecycle_state that is ACTIVE on creation and may later be
        moved to DECOMMISSIONED by administrative process, and an
        operational_status that the platform itself computes — never
        accepted from the client."

        Claim: a freshly created station has lifecycle_state=ACTIVE
        and the platform supplies operational_status.
        """
        resp = api.create_station(create_station_payload(), admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["lifecycle_state"] == "ACTIVE"
        assert "operational_status" in data
        assert_station(data)

    def test_create_station_with_no_inverters_is_operational(
        self, api, admin_headers,
    ):
        """PRD §3.1: "If the denominator is zero (the station has no
        active inverters), the status is set to OPERATIONAL."

        Claim: a station with zero inverters has operational_status
        OPERATIONAL.
        """
        station = create_station()
        resp = api.get_station(station["id"], admin_headers)
        data = validate_success(resp)
        assert data["operational_status"] == "OPERATIONAL"

    def test_market_trading_disabled_by_default(self, api, admin_headers):
        """PRD §3.1: "a market_trading_enabled boolean that defaults
        to false."

        Claim: omitting market_trading_enabled persists as false.
        """
        payload = create_station_payload(market_trading_enabled=None)
        # Strip the key entirely so we test "omitted" behaviour.
        payload.pop("market_trading_enabled", None)
        resp = api.create_station(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["market_trading_enabled"] is False


class TestStationOperationalStatusThreshold:
    """PRD §3.1: station operational_status thresholds 0.20 / 0.50,
    both closed at the boundary."""

    def _setup_inverters_then_alarm_critical(
        self, total: int, under_repair_target: int,
    ):
        """Build station with `total` inverters; drive
        `under_repair_target` of them into UNDER_REPAIR via the
        alarm-ack cascade (CRITICAL severity)."""
        from test_helpers import (
            ingest_alarm,
            register_alarm_code_map,
            api_client,
            TEST_USERS,
        )
        station, _supp, inverters = setup_station_with_inverters(
            inverter_count=total,
        )
        register_alarm_code_map(
            severity="CRITICAL", canonical_code="INV_FAIL",
        )
        for i in range(under_repair_target):
            alarm = ingest_alarm(
                inverter_id=inverters[i]["id"],
                first_seen_at="2026-01-01T00:00:00.000Z",
            )
            api_client.ack_alarm(
                alarm["id"], TEST_USERS["om_engineer_headers"],
            )
        return station, inverters

    def test_ratio_below_degraded_threshold_stays_operational(
        self, api, admin_headers,
    ):
        """PRD §3.1: "if it is at least one fifth, the status becomes
        DEGRADED; otherwise it is OPERATIONAL." PRD §3.1: "Both
        thresholds are closed at the boundary — a ratio of exactly
        0.20 is DEGRADED, and a ratio of exactly 0.50 is OUT_OF_SERVICE."

        Claim: 1 UNDER_REPAIR of 10 inverters = ratio 0.10 → OPERATIONAL.
        """
        station, _ = self._setup_inverters_then_alarm_critical(
            total=10, under_repair_target=1,
        )
        resp = api.get_station(station["id"], admin_headers)
        data = validate_success(resp)
        assert data["operational_status"] == "OPERATIONAL"

    def test_ratio_exactly_degraded_threshold_is_degraded(
        self, api, admin_headers,
    ):
        """PRD §3.1: "Both thresholds are closed at the boundary — a
        ratio of exactly 0.20 is DEGRADED, and a ratio of exactly 0.50
        is OUT_OF_SERVICE."

        Claim: 1 UNDER_REPAIR of 5 inverters = ratio 0.20 → DEGRADED.
        """
        station, _ = self._setup_inverters_then_alarm_critical(
            total=5, under_repair_target=1,
        )
        resp = api.get_station(station["id"], admin_headers)
        data = validate_success(resp)
        assert data["operational_status"] == "DEGRADED"

    def test_ratio_exactly_out_of_service_threshold(
        self, api, admin_headers,
    ):
        """PRD §3.1: "a ratio of exactly 0.50 is OUT_OF_SERVICE."

        Claim: 2 UNDER_REPAIR of 4 inverters = ratio 0.50 → OUT_OF_SERVICE.
        """
        station, _ = self._setup_inverters_then_alarm_critical(
            total=4, under_repair_target=2,
        )
        resp = api.get_station(station["id"], admin_headers)
        data = validate_success(resp)
        assert data["operational_status"] == "OUT_OF_SERVICE"


class TestSupplierUpdate:
    """PRD §3.1 + §2.5: supplier patch + OCC."""

    def test_blacklist_supplier_via_patch(self, api, admin_headers):
        """PRD §3.1: "The administrator may patch any of contact,
        rating, lifecycle_state, or supply a version for OCC checking;
        a blacklisted supplier cannot subsequently be assigned to a
        new work order."

        Claim: PATCH /pv-ops/suppliers/{id} can transition
        lifecycle_state to BLACKLISTED.
        """
        supplier = create_supplier()
        resp = api.update_supplier(
            supplier["id"],
            update_supplier_payload(lifecycle_state="BLACKLISTED"),
            admin_headers,
        )
        data = validate_success(resp)
        assert data["lifecycle_state"] == "BLACKLISTED"

    def test_supplier_version_conflict_on_patch(self, api, admin_headers):
        """PRD §2.5: "When version is supplied, the server compares it
        to the current version of the target row before applying any
        state change; on mismatch the request is rejected with
        ERR_VERSION_CONFLICT (HTTP 409)."

        Claim: patching with a stale version yields ERR_VERSION_CONFLICT.
        """
        supplier = create_supplier()
        # Make one successful mutation to bump version → mismatch.
        api.update_supplier(
            supplier["id"], update_supplier_payload(rating="A"),
            admin_headers,
        )
        # Now patch with the original (stale) version.
        resp = api.update_supplier(
            supplier["id"],
            update_supplier_payload(rating="C", version=supplier["version"]),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestInverterCreation:
    """PRD §3.1 inverter registration."""

    def test_create_inverter_initial_state(self, api, admin_headers):
        """PRD §3.1: "an asset lifecycle_state that begins at
        OPERATING and may move through UNDER_REPAIR and ultimately
        RETIRED."

        Claim: a freshly created inverter is OPERATING.
        """
        station = create_station()
        supplier = create_supplier()
        payload = create_inverter_payload(
            station_id=station["id"],
            warranty_supplier_id=supplier["id"],
        )
        resp = api.create_inverter(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["lifecycle_state"] == "OPERATING"
        assert_inverter(data)
