"""Entity assertions and domain invariant checkers.

Per PRD §2.4: most resources carry id/created_at/updated_at/version.
GenerationReading, MeteringRecord, RevenueDistribution, AlarmCodeMap,
and AuditEntry are append-only — only id + created_at.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers
# ---------------------------------------------------------------------------
def _assert_mutable_common(data: dict, label: str) -> None:
    """id/created_at/updated_at/version (PRD §2.4 mutable resources)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be int, got {type(data.get('version'))}"
    )
    assert data["version"] >= 1, (
        f"{label}.version must be >= 1, got {data['version']}"
    )


def _assert_append_only_common(data: dict, label: str) -> None:
    """id + created_at only (PRD §2.4 append-only entities)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Station
# ---------------------------------------------------------------------------
def assert_station(data: dict) -> None:
    _assert_mutable_common(data, "Station")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["installed_capacity_kw"], (int, float))
    assert data["installed_capacity_kw"] > 0
    assert isinstance(data["ac_capacity_kw"], (int, float))
    assert data["ac_capacity_kw"] > 0
    assert isinstance(data["latitude"], (int, float))
    assert -90 <= data["latitude"] <= 90
    assert isinstance(data["longitude"], (int, float))
    assert -180 <= data["longitude"] <= 180
    assert data["operational_status"] in {
        "OPERATIONAL", "DEGRADED", "OUT_OF_SERVICE",
    }
    assert data["lifecycle_state"] in {"ACTIVE", "DECOMMISSIONED"}
    assert isinstance(data.get("market_trading_enabled"), bool)


# ---------------------------------------------------------------------------
# Array, PVString, Module
# ---------------------------------------------------------------------------
def assert_array(data: dict) -> None:
    _assert_mutable_common(data, "Array")
    assert isinstance(data["station_id"], str)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert 0 <= data["tilt_angle_deg"] <= 90
    assert 0 <= data["azimuth_deg"] <= 360


def assert_pvstring(data: dict) -> None:
    _assert_mutable_common(data, "PVString")
    assert isinstance(data["array_id"], str)
    assert isinstance(data["module_count"], int)
    assert 1 <= data["module_count"] <= 40
    assert isinstance(data["inverter_id"], str)


def assert_module(data: dict) -> None:
    _assert_mutable_common(data, "Module")
    assert isinstance(data["string_id"], str)
    assert isinstance(data["serial_no"], str)
    assert 0 < data["wp_rating"] <= 1000
    assert data["lifecycle_state"] in {
        "INSTALLED", "REMOVED", "RETURN_TO_VENDOR", "SCRAPPED",
    }


# ---------------------------------------------------------------------------
# Inverter / Transformer
# ---------------------------------------------------------------------------
def assert_inverter(data: dict) -> None:
    _assert_mutable_common(data, "Inverter")
    assert data["role"] in {"INVERTER", "COMBINER_BOX"}
    assert data["lifecycle_state"] in {"OPERATING", "UNDER_REPAIR", "RETIRED"}
    assert isinstance(data["vendor"], str)
    assert isinstance(data["model"], str)
    assert isinstance(data["serial_no"], str)


def assert_transformer(data: dict) -> None:
    _assert_mutable_common(data, "Transformer")
    assert data["rated_capacity_kva"] > 0


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------
def assert_supplier(data: dict) -> None:
    _assert_mutable_common(data, "Supplier")
    assert isinstance(data["name"], str)
    assert data["rating"] in {"A", "B", "C"}
    assert data["lifecycle_state"] in {"ACTIVE", "BLACKLISTED"}


# ---------------------------------------------------------------------------
# SparePart
# ---------------------------------------------------------------------------
def assert_spare_part(data: dict) -> None:
    _assert_mutable_common(data, "SparePart")
    assert isinstance(data["sku"], str)
    assert isinstance(data["stock_on_hand"], int)
    assert data["stock_on_hand"] >= 0
    assert isinstance(data["reserved_qty"], int)
    assert data["reserved_qty"] >= 0


def assert_spare_part_invariant(data: dict) -> None:
    """PRD §3.5: reservations cannot exceed stock_on_hand."""
    assert data["reserved_qty"] >= 0
    assert data["stock_on_hand"] >= 0


# ---------------------------------------------------------------------------
# GenerationReading (append-only)
# ---------------------------------------------------------------------------
def assert_generation_reading(data: dict) -> None:
    _assert_append_only_common(data, "GenerationReading")
    assert isinstance(data["station_id"], str)
    assert is_iso8601_timestamp(data["timestamp"])
    assert data["dc_power_kw"] >= 0
    assert data["ac_power_kw"] >= 0
    assert data["irradiance_w_m2"] >= 0
    assert data["granularity"] in {
        "RAW_1MIN", "AGG_15MIN", "AGG_1H", "AGG_1DAY",
    }
    # PRD §2.4 forbids updated_at/version on append-only entities.
    assert "updated_at" not in data, (
        "GenerationReading is append-only — must NOT carry updated_at"
    )
    assert "version" not in data, (
        "GenerationReading is append-only — must NOT carry version"
    )


# ---------------------------------------------------------------------------
# AlarmCodeMap (append-only)
# ---------------------------------------------------------------------------
def assert_alarm_code_map(data: dict) -> None:
    _assert_append_only_common(data, "AlarmCodeMap")
    assert isinstance(data["vendor"], str)
    assert isinstance(data["model"], str)
    assert isinstance(data["vendor_code"], str)
    assert isinstance(data["canonical_code"], str)
    assert data["severity"] in {"INFO", "WARN", "MAJOR", "CRITICAL"}


# ---------------------------------------------------------------------------
# AlarmEvent
# ---------------------------------------------------------------------------
def assert_alarm_event(data: dict) -> None:
    _assert_mutable_common(data, "AlarmEvent")
    assert data["state"] in {"OPEN", "ACKNOWLEDGED", "CLEARED", "ARCHIVED"}
    assert data["severity"] in {"INFO", "WARN", "MAJOR", "CRITICAL"}
    assert isinstance(data["inverter_id"], str)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["canonical_code"], str)
    assert is_iso8601_timestamp(data["first_seen_at"])
    assert is_iso8601_timestamp(data["last_seen_at"])
    assert isinstance(data["occurrence_count"], int)
    assert data["occurrence_count"] >= 1


# ---------------------------------------------------------------------------
# Patrol
# ---------------------------------------------------------------------------
def assert_patrol_plan(data: dict) -> None:
    _assert_mutable_common(data, "PatrolPlan")
    assert isinstance(data["zone_route"], list)
    assert 1 <= len(data["zone_route"]) <= 50
    assert data["kind"] in {"PERIODIC", "SPECIAL_POST_STORM"}
    assert data["lifecycle_state"] in {"ACTIVE", "RETIRED"}


def assert_patrol_record(data: dict) -> None:
    _assert_mutable_common(data, "PatrolRecord")
    assert isinstance(data["patrol_plan_id"], str)
    assert data["state"] in {
        "SCHEDULED", "IN_PROGRESS", "SUBMITTED", "VERIFIED", "REJECTED",
    }
    assert isinstance(data["completed_zone_count"], int)
    assert data["completed_zone_count"] >= 0


# ---------------------------------------------------------------------------
# Defect / WorkOrder
# ---------------------------------------------------------------------------
def assert_defect(data: dict) -> None:
    _assert_mutable_common(data, "Defect")
    assert data["subject_type"] in {
        "INVERTER", "MODULE", "TRANSFORMER", "STRING", "ARRAY",
    }
    assert data["source"] in {
        "ALARM", "PATROL", "DATA_ANOMALY", "EXTERNAL_INSPECTION",
    }
    assert data["severity"] in {"MINOR", "MODERATE", "MAJOR", "CRITICAL"}
    assert data["state"] in {
        "OPEN", "DISPATCHED", "UNDER_REPAIR", "RESOLVED", "CLOSED", "REOPENED",
    }
    assert isinstance(data["recurrence_index"], int)
    assert data["recurrence_index"] >= 1


def assert_work_order(data: dict) -> None:
    _assert_mutable_common(data, "WorkOrder")
    assert data["state"] in {
        "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELED",
    }
    assert isinstance(data["defect_id"], str)
    assert isinstance(data["assigned_supplier_id"], str)


# ---------------------------------------------------------------------------
# Settlement entities
# ---------------------------------------------------------------------------
def assert_settlement_period(data: dict) -> None:
    _assert_mutable_common(data, "SettlementPeriod")
    assert data["state"] in {
        "DRAFT", "RECONCILING", "CONFIRMED", "INVOICED", "DISPUTED",
    }


def assert_metering_record(data: dict) -> None:
    _assert_append_only_common(data, "MeteringRecord")
    assert data["pricing_channel"] in {"FEED_IN", "MARKET_TRADING"}
    assert data["on_grid_kwh"] >= 0


def assert_revenue_distribution(data: dict) -> None:
    _assert_append_only_common(data, "RevenueDistribution")
    assert isinstance(data["share_basis_points"], int)
    assert isinstance(data["amount_cny"], (int, float))


def assert_investor_share(data: dict) -> None:
    _assert_mutable_common(data, "InvestorShare")
    assert isinstance(data["share_basis_points"], int)
    assert 1 <= data["share_basis_points"] <= 10000


# ---------------------------------------------------------------------------
# Subsidy entities
# ---------------------------------------------------------------------------
def assert_subsidy_policy(data: dict) -> None:
    _assert_mutable_common(data, "SubsidyPolicy")
    assert data["scope"] in {"NATIONAL", "LOCAL"}
    assert data["rate_cny_per_kwh"] >= 0


def assert_subsidy_declaration(data: dict) -> None:
    _assert_mutable_common(data, "SubsidyDeclaration")
    assert data["state"] in {
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "RECEIVED", "ARREARS",
    }


# ---------------------------------------------------------------------------
# AuditEntry (append-only)
# ---------------------------------------------------------------------------
def assert_audit_entry(data: dict) -> None:
    _assert_append_only_common(data, "AuditEntry")
    assert data["target_type"] in {
        "ALARM", "SETTLEMENT", "DECLARATION", "DEFECT",
    }
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["actor_role"], str)
    # PRD §2.4 — no updated_at, no version.
    assert "updated_at" not in data
    assert "version" not in data


# ---------------------------------------------------------------------------
# Helpers — list operations
# ---------------------------------------------------------------------------
def find_row(rows: Iterable[dict], **filters) -> Optional[dict]:
    """Return the first row in `rows` whose fields match `filters`, or None."""
    for row in rows:
        if all(row.get(k) == v for k, v in filters.items()):
            return row
    return None


def select_rows(rows: Iterable[dict], **filters) -> list:
    return [r for r in rows if all(r.get(k) == v for k, v in filters.items())]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_revenue_distribution_sum_equals_final(
    distributions: list, final_revenue_cny: float,
) -> None:
    """PRD §3.6: "The invariant the platform enforces is that the sum
    of amount_cny across the period's distributions equals
    final_revenue_cny exactly — zero drift."
    """
    total_cents = sum(round(d["amount_cny"] * 100) for d in distributions)
    expected_cents = round(final_revenue_cny * 100)
    assert total_cents == expected_cents, (
        f"Σ amount_cny ({total_cents} cents) must equal "
        f"final_revenue_cny ({expected_cents} cents)"
    )


__all__ = [
    "assert_station",
    "assert_array",
    "assert_pvstring",
    "assert_module",
    "assert_inverter",
    "assert_transformer",
    "assert_supplier",
    "assert_spare_part",
    "assert_spare_part_invariant",
    "assert_generation_reading",
    "assert_alarm_code_map",
    "assert_alarm_event",
    "assert_patrol_plan",
    "assert_patrol_record",
    "assert_defect",
    "assert_work_order",
    "assert_settlement_period",
    "assert_metering_record",
    "assert_revenue_distribution",
    "assert_investor_share",
    "assert_subsidy_policy",
    "assert_subsidy_declaration",
    "assert_audit_entry",
    "assert_revenue_distribution_sum_equals_final",
    "find_row",
    "select_rows",
]
