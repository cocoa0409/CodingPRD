"""Per-entity assertions for the Shared Bicycle API.

PRD §2.4 splits entities into three field-shapes:
- Versioned (id + created_at + updated_at + version):
  Region, Bike, Rider, Ride, WorkOrder, TransferOrder.
- Geofence-shape (id + created_at + revision; NO updated_at, NO version).
- Append-only (id + created_at only; NO updated_at, NO version,
  NO revision): LossRecord, AuditLog.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared shape checkers
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 versioned shape: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_geofence_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: Geofence carries id + created_at + revision."""
    assert "id" in data and is_valid_uuid(data["id"]), (
        f"Geofence.id must be UUID, got {data.get('id')!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), "Geofence.created_at must be ISO 8601 UTC"
    assert "revision" in data, "Geofence missing revision"
    assert isinstance(data["revision"], int) and data["revision"] >= 1, (
        f"Geofence.revision must be >= 1, got {data.get('revision')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: 'Geofence, LossRecord, and the append-only entity
    AuditLog carry only id and created_at; both updated_at and version
    are absent on those three.'"""
    assert "id" in data and is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data.get('id')!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Allowed enum sets (mirrors PRD prose)
# ---------------------------------------------------------------------------
BIKE_MODELS = {"STANDARD", "E_BIKE"}
BIKE_SHELF_STATES = {"OFF_SHELF", "ON_SHELF", "SCRAPPED"}
BIKE_STATUSES = {"AVAILABLE", "IN_USE", "FAULT", "RECALL"}
BIKE_LOCK_STATES = {"LOCKED", "UNLOCKED", "UNKNOWN"}
DENSITY_POSTURES = {"LOW", "NORMAL", "HIGH"}
GEOFENCE_KINDS = {"ALLOWED_PARKING", "RESTRICTED", "FORBIDDEN"}
RIDER_STATES = {"ACTIVE", "SUSPENDED"}
RIDE_STATES = {"ACTIVE", "SETTLED", "VOIDED", "DISPUTED"}
SETTLEMENT_VARIANTS = {"PER_MINUTE", "DAILY_CAP"}
END_FENCE_KINDS = {"ALLOWED_PARKING", "RESTRICTED", "NONE"}
WORKORDER_STATES = {"OPEN", "ASSIGNED", "RESOLVED", "CANCELLED"}
WORKORDER_CAUSES = {
    "USER_REPORT", "LONG_STATIONARY", "LOCK_ABNORMAL",
    "LOW_BATTERY", "RECALL",
}
FAULT_CATEGORIES = {
    "FLAT_TIRE", "BRAKE", "LOCK_FAILURE",
    "BATTERY_SWAP", "CHARGING", "OTHER",
}
TRANSFER_STATES = {"PLANNED", "IN_TRANSIT", "COMPLETED", "CANCELLED"}
TRANSFER_KINDS = {"REPLENISH", "CLEARANCE"}
LOSS_CAUSES = {"THEFT", "DAMAGE", "ABANDONED"}
LOSS_RESPONSIBILITIES = {"RIDER", "OPERATOR", "UNKNOWN"}
AUDIT_EVENT_KINDS = {"BILLING_ADJUSTMENT", "OPS_ACTION", "EXTERNAL_SYNC"}


# ---------------------------------------------------------------------------
# Region (PRD §2.7, §3.1)
# ---------------------------------------------------------------------------
def assert_region(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Region")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("deployment_quota"), int)
    assert data["deployment_quota"] > 0, (
        f"Region.deployment_quota must be > 0, got {data['deployment_quota']}"
    )
    assert isinstance(data.get("low_density_threshold"), int)
    assert data["low_density_threshold"] >= 0, (
        "Region.low_density_threshold must be >= 0"
    )
    assert isinstance(data.get("high_density_threshold"), int)
    assert data["high_density_threshold"] > data["low_density_threshold"], (
        "Region.high_density_threshold must be strictly greater than "
        "low_density_threshold"
    )
    assert isinstance(data.get("in_zone_return_reward_cents"), int)
    assert isinstance(data.get("out_of_zone_penalty_cents"), int)
    assert isinstance(data.get("deployed_count"), int)
    assert data["deployed_count"] >= 0
    assert isinstance(data.get("available_count"), int)
    assert data["available_count"] >= 0
    assert data.get("density_posture") in DENSITY_POSTURES, (
        f"Region.density_posture must be one of {DENSITY_POSTURES}, "
        f"got {data.get('density_posture')!r}"
    )
    assert isinstance(data.get("clock_minutes"), int)
    assert data["clock_minutes"] >= 0


# ---------------------------------------------------------------------------
# Geofence (PRD §2.4, §3.1)
# ---------------------------------------------------------------------------
def assert_geofence(data: Dict[str, Any]) -> None:
    _check_geofence_fields(data)
    assert is_valid_uuid(data.get("region_id", "")), (
        f"Geofence.region_id must be UUID, got {data.get('region_id')!r}"
    )
    assert isinstance(data.get("label"), str) and data["label"]
    assert data.get("kind") in GEOFENCE_KINDS
    polygon = data.get("polygon")
    assert isinstance(polygon, list) and 3 <= len(polygon) <= 32, (
        "Geofence.polygon must have between 3 and 32 vertices, "
        f"got {len(polygon) if isinstance(polygon, list) else 'non-list'}"
    )
    for v in polygon:
        assert isinstance(v, dict) and "lat" in v and "lng" in v, (
            f"Geofence polygon vertex malformed: {v!r}"
        )
    assert isinstance(data.get("active"), bool)


# ---------------------------------------------------------------------------
# Bike (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_bike(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Bike")
    rid = data.get("region_id")
    if rid is not None:
        assert is_valid_uuid(rid), (
            f"Bike.region_id must be UUID or null, got {rid!r}"
        )
    assert data.get("model") in BIKE_MODELS
    assert isinstance(data.get("lock_id"), str) and data["lock_id"]
    assert data.get("shelf_state") in BIKE_SHELF_STATES
    assert data.get("status") in BIKE_STATUSES
    bp = data.get("battery_pct")
    assert isinstance(bp, int) and 0 <= bp <= 100, (
        f"Bike.battery_pct must be 0..100, got {bp!r}"
    )
    assert data.get("lock_state") in BIKE_LOCK_STATES
    assert isinstance(data.get("fault_categories"), list), (
        "Bike.fault_categories must be a list"
    )


# ---------------------------------------------------------------------------
# Rider (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_rider(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Rider")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("wallet_balance_cents"), int)
    assert data["wallet_balance_cents"] >= 0, (
        f"Rider.wallet_balance_cents must be >= 0, "
        f"got {data['wallet_balance_cents']}"
    )
    assert isinstance(data.get("monthly_pass_expires_minute"), int)
    assert data["monthly_pass_expires_minute"] >= 0
    assert isinstance(data.get("free_minutes_remaining"), int)
    assert data["free_minutes_remaining"] >= 0
    assert data.get("status") in RIDER_STATES


# ---------------------------------------------------------------------------
# Ride (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_ride(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Ride")
    assert is_valid_uuid(data.get("rider_id", "")), "Ride.rider_id must be UUID"
    assert is_valid_uuid(data.get("bike_id", "")), "Ride.bike_id must be UUID"
    assert is_valid_uuid(data.get("region_id", "")), "Ride.region_id must be UUID"
    assert data.get("status") in RIDE_STATES
    assert isinstance(data.get("start_minute"), int)
    assert data["start_minute"] >= 0
    if data["status"] in {"SETTLED", "DISPUTED", "VOIDED"}:
        em = data.get("end_minute")
        if data["status"] == "VOIDED":
            # VOID does not require end_minute to be set per PRD §3.10.
            pass
        else:
            assert isinstance(em, int) and em >= data["start_minute"], (
                f"Ride.end_minute should be >= start_minute, got {em!r}"
            )


def assert_ride_settled_invariants(data: Dict[str, Any]) -> None:
    """PRD §3.4 settlement invariants on a SETTLED ride."""
    assert data["status"] in {"SETTLED", "DISPUTED"}, (
        f"Expected SETTLED/DISPUTED, got {data['status']}"
    )
    for fld in (
        "applied_free_minutes", "pass_covered_minutes",
        "chargeable_minutes", "base_fare_cents",
        "penalty_cents", "reward_cents", "final_fare_cents",
    ):
        assert isinstance(data.get(fld), int), f"Ride.{fld} must be int"
        assert data[fld] >= 0, f"Ride.{fld} must be >= 0"
    assert data.get("settlement_variant") in SETTLEMENT_VARIANTS, (
        "Ride.settlement_variant must be PER_MINUTE or DAILY_CAP"
    )
    # final_fare_cents = base_fare_cents (capped) + penalty_cents
    # We cannot reconstruct the cap from the response alone, but penalty
    # must be additive on top of base_fare_cents (which is the capped
    # value on DAILY_CAP variant per PRD §3.4).
    expected_final = data["base_fare_cents"] + data["penalty_cents"]
    assert data["final_fare_cents"] == expected_final, (
        "PRD §3.4: 'final_fare_cents is the (possibly capped) "
        "base_fare_cents plus penalty_cents — the reward is not netted "
        f"in.' Expected {expected_final}, got {data['final_fare_cents']}"
    )


# ---------------------------------------------------------------------------
# WorkOrder (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_workorder(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "WorkOrder")
    assert is_valid_uuid(data.get("bike_id", ""))
    assert is_valid_uuid(data.get("region_id", ""))
    assert data.get("cause") in WORKORDER_CAUSES
    assert data.get("category") in FAULT_CATEGORIES
    assert data.get("status") in WORKORDER_STATES
    assert isinstance(data.get("sla_minutes"), int)
    assert data["sla_minutes"] > 0
    assert isinstance(data.get("opened_minute"), int)
    assert data["opened_minute"] >= 0
    assert isinstance(data.get("sla_breached"), bool)


# ---------------------------------------------------------------------------
# TransferOrder (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_transfer_order(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "TransferOrder")
    assert is_valid_uuid(data.get("from_region_id", ""))
    assert is_valid_uuid(data.get("to_region_id", ""))
    assert isinstance(data.get("bike_ids"), list) and data["bike_ids"], (
        "TransferOrder.bike_ids must be a non-empty list"
    )
    for b in data["bike_ids"]:
        assert is_valid_uuid(b), f"TransferOrder.bike_ids entry not UUID: {b!r}"
    assert data.get("status") in TRANSFER_STATES
    assert data.get("kind") in TRANSFER_KINDS


# ---------------------------------------------------------------------------
# LossRecord (PRD §3.11)
# ---------------------------------------------------------------------------
def assert_loss_record(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "LossRecord")
    assert is_valid_uuid(data.get("bike_id", ""))
    assert data.get("cause") in LOSS_CAUSES
    assert data.get("responsibility") in LOSS_RESPONSIBILITIES
    assert isinstance(data.get("financial_impact_cents"), int)
    assert data["financial_impact_cents"] > 0, (
        "PRD §3.11: financial_impact_cents must be strictly positive"
    )
    assert isinstance(data.get("scrapped"), bool)


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.9)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditLog")
    assert data.get("event_kind") in AUDIT_EVENT_KINDS
    assert isinstance(data.get("action"), str) and data["action"]
    assert isinstance(data.get("subject_type"), str) and data["subject_type"]
    assert isinstance(data.get("subject_id"), str) and data["subject_id"]
    assert isinstance(data.get("before"), dict)
    assert isinstance(data.get("after"), dict)
    assert isinstance(data.get("clock_minute"), int)


# ---------------------------------------------------------------------------
# Cross-cutting helpers
# ---------------------------------------------------------------------------
def find_audit_logs(
    audit_logs: Iterable[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    event_kind: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return audit log entries matching the given filters."""
    out: List[Dict[str, Any]] = []
    for row in audit_logs:
        if subject_type is not None and row.get("subject_type") != subject_type:
            continue
        if subject_id is not None and row.get("subject_id") != subject_id:
            continue
        if event_kind is not None and row.get("event_kind") != event_kind:
            continue
        if action is not None and row.get("action") != action:
            continue
        out.append(row)
    return out


def assert_density_posture_matches(
    region: Dict[str, Any],
    expected: str,
) -> None:
    """PRD §2.7: 'LOW when available_count <= low_density_threshold,
    HIGH when available_count >= high_density_threshold, NORMAL
    otherwise.'"""
    assert region["density_posture"] == expected, (
        f"Expected density_posture={expected}, got "
        f"{region['density_posture']} "
        f"(available_count={region['available_count']}, "
        f"low={region['low_density_threshold']}, "
        f"high={region['high_density_threshold']})"
    )


__all__ = [
    "BIKE_MODELS", "BIKE_SHELF_STATES", "BIKE_STATUSES", "BIKE_LOCK_STATES",
    "DENSITY_POSTURES", "GEOFENCE_KINDS", "RIDER_STATES", "RIDE_STATES",
    "SETTLEMENT_VARIANTS", "END_FENCE_KINDS", "WORKORDER_STATES",
    "WORKORDER_CAUSES", "FAULT_CATEGORIES", "TRANSFER_STATES",
    "TRANSFER_KINDS", "LOSS_CAUSES", "LOSS_RESPONSIBILITIES",
    "AUDIT_EVENT_KINDS",
    "assert_region", "assert_geofence", "assert_bike", "assert_rider",
    "assert_ride", "assert_ride_settled_invariants",
    "assert_workorder", "assert_transfer_order",
    "assert_loss_record", "assert_audit_log",
    "find_audit_logs", "assert_density_posture_matches",
]
