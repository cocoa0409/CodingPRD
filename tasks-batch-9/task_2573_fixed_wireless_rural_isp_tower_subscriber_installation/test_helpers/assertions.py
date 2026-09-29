"""Entity shape assertions and domain invariant checkers.

Every check below is anchored on a rule PRD.md states directly: the audit trio of
PRD 2.5, the enum vocabularies of PRD 3, and the ledger identities of PRD 3.3.
"""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AssignmentStatus,
    CapacityPosture,
    CircuitState,
    CoordinationStatus,
    CreditStatus,
    HoldStatus,
    LicenseStatus,
    MountingType,
    OutageStatus,
    RequestStatus,
    SectorStatus,
    ServiceStatus,
    TowerStatus,
    UsagePriority,
    WorkOrderStatus,
)

_ENUM_VALUES = {
    "tower_status": [s.value for s in TowerStatus],
    "circuit_state": [s.value for s in CircuitState],
    "license_status": [s.value for s in LicenseStatus],
    "sector_status": [s.value for s in SectorStatus],
    "capacity_posture": [s.value for s in CapacityPosture],
    "coordination_status": [s.value for s in CoordinationStatus],
    "request_status": [s.value for s in RequestStatus],
    "hold_status": [s.value for s in HoldStatus],
    "service_status": [s.value for s in ServiceStatus],
    "usage_priority": [s.value for s in UsagePriority],
    "work_order_status": [s.value for s in WorkOrderStatus],
    "assignment_status": [s.value for s in AssignmentStatus],
    "outage_status": [s.value for s in OutageStatus],
    "credit_status": [s.value for s in CreditStatus],
    "mounting_type": [m.value for m in MountingType],
}


# --------------------------------------------------------------------------
# Shared field groups (PRD 2.5)
# --------------------------------------------------------------------------


def assert_audit_fields(data: dict, entity: str = "record"):
    """id + created_at + updated_at + version, per PRD 2.5."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_immutable_record_fields(data: dict, entity: str = "usage record"):
    """An immutable metered day carries only id and created_at (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not report updated_at"
    assert "version" not in data, f"{entity} must not report version"


def _assert_enum(data: dict, field: str, vocabulary: str, entity: str):
    assert data.get(field) in _ENUM_VALUES[vocabulary], (
        f"{entity}.{field} must be one of {_ENUM_VALUES[vocabulary]}, got {data.get(field)!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_tower(data: dict):
    assert_audit_fields(data, "tower")
    _assert_enum(data, "status", "tower_status", "tower")
    assert isinstance(data["site_code"], str) and 4 <= len(data["site_code"]) <= 32
    assert isinstance(data["latitude"], (int, float))
    assert isinstance(data["longitude"], (int, float))
    assert isinstance(data["ground_elevation_m"], (int, float))
    assert isinstance(data["antenna_agl_m"], (int, float))
    assert isinstance(data["lease_landowner_name"], str)
    assert isinstance(data["lease_monthly_base_rent_cents"], int)
    assert isinstance(data["lease_escalator_pct"], (int, float))
    assert isinstance(data["lease_start_date"], str)
    assert isinstance(data["lease_term_months"], int)
    assert isinstance(data["current_monthly_rent_cents"], int), (
        "current_monthly_rent_cents is an integer count of cents"
    )
    assert isinstance(data["active_sector_count"], int) and data["active_sector_count"] >= 0
    assert isinstance(data["backhaul_accepted_mbps"], int) and data["backhaul_accepted_mbps"] >= 0


def assert_backhaul_circuit(data: dict):
    assert_audit_fields(data, "backhaul circuit")
    _assert_enum(data, "state", "circuit_state", "backhaul circuit")
    assert is_valid_uuid(data["tower_id"])
    assert isinstance(data["carrier_name"], str)
    assert isinstance(data["circuit_ref"], str)
    assert isinstance(data["committed_mbps"], int) and data["committed_mbps"] >= 1
    assert isinstance(data["monthly_cost_cents"], int) and data["monthly_cost_cents"] >= 0


def assert_spectrum_license(data: dict):
    assert_audit_fields(data, "spectrum licence")
    _assert_enum(data, "status", "license_status", "spectrum licence")
    assert isinstance(data["license_ref"], str)
    assert isinstance(data["channel_center_mhz"], (int, float))
    assert isinstance(data["channel_width_mhz"], (int, float))
    assert isinstance(data["max_eirp_dbm"], (int, float))
    assert data["lower_edge_mhz"] == data["channel_center_mhz"] - data["channel_width_mhz"] / 2, (
        "lower_edge_mhz is channel_center_mhz less half of channel_width_mhz"
    )
    assert data["upper_edge_mhz"] == data["channel_center_mhz"] + data["channel_width_mhz"] / 2, (
        "upper_edge_mhz is channel_center_mhz plus half of channel_width_mhz"
    )


def assert_sector(data: dict):
    assert_audit_fields(data, "sector")
    _assert_enum(data, "status", "sector_status", "sector")
    _assert_enum(data, "capacity_posture", "capacity_posture", "sector")
    assert is_valid_uuid(data["tower_id"])
    assert is_valid_uuid(data["spectrum_license_id"])
    assert isinstance(data["capacity_mbps"], int) and data["capacity_mbps"] >= 1
    assert isinstance(data["max_oversubscription_ratio"], (int, float))
    for field in ("sold_mbps", "held_mbps", "committed_mbps", "remaining_allowance_mbps"):
        assert isinstance(data[field], int), f"sector.{field} is a whole number of Mbps"
        assert data[field] >= 0, f"sector.{field} is never negative, got {data[field]}"
    assert_sector_ledger_invariants(data)


def assert_sector_ledger_invariants(data: dict):
    """committed = sold + held, and the ratio is committed / capacity (PRD 3.3)."""
    assert data["committed_mbps"] == data["sold_mbps"] + data["held_mbps"], (
        "committed_mbps is sold_mbps plus held_mbps, got "
        f"{data['committed_mbps']} vs {data['sold_mbps']} + {data['held_mbps']}"
    )
    expected_ratio = float(
        (Decimal(data["committed_mbps"]) / Decimal(data["capacity_mbps"])).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
    )
    assert abs(data["oversubscription_ratio"] - expected_ratio) < 0.0005, (
        "oversubscription_ratio is committed_mbps divided by capacity_mbps to three decimals, "
        f"expected {expected_ratio}, got {data['oversubscription_ratio']}"
    )
    ceiling = int(
        (Decimal(data["capacity_mbps"]) * Decimal(str(data["max_oversubscription_ratio"]))).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    expected_allowance = max(0, ceiling - data["committed_mbps"])
    assert data["remaining_allowance_mbps"] == expected_allowance, (
        "remaining_allowance_mbps is floor(capacity_mbps * max_oversubscription_ratio) "
        f"less committed_mbps, expected {expected_allowance}, got {data['remaining_allowance_mbps']}"
    )


def assert_interference_coordination(data: dict):
    assert_audit_fields(data, "coordination")
    _assert_enum(data, "status", "coordination_status", "coordination")
    assert is_valid_uuid(data["requesting_sector_id"])
    assert is_valid_uuid(data["neighbor_sector_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["proposed_channel_center_mhz"], (int, float))
    assert isinstance(data["proposed_channel_width_mhz"], (int, float))
    assert isinstance(data["proposed_eirp_dbm"], (int, float))
    assert isinstance(data["guard_band_mhz"], (int, float))


def assert_service_plan(data: dict):
    assert_audit_fields(data, "service plan")
    assert isinstance(data["tier_code"], str)
    assert isinstance(data["downstream_mbps"], int) and data["downstream_mbps"] >= 1
    assert isinstance(data["upstream_mbps"], int) and data["upstream_mbps"] >= 1
    assert isinstance(data["monthly_price_cents"], int) and data["monthly_price_cents"] >= 0
    assert isinstance(data["soft_cap_gb"], (int, float)) and data["soft_cap_gb"] > 0
    assert 0.05 <= data["deprioritization_factor"] <= 1.0
    assert 90.0 <= data["sla_uptime_pct"] <= 100.0
    assert data["sla_credit_method"] in ("SLA_SHORTFALL", "PER_INCIDENT")
    assert data["equipment_policy"] in ("RENTAL_ONLY", "PURCHASE_ONLY", "RENTAL_OR_PURCHASE")


def assert_serviceability_request(data: dict):
    assert_audit_fields(data, "qualification")
    _assert_enum(data, "status", "request_status", "qualification")
    assert is_valid_uuid(data["candidate_tower_id"])
    assert is_valid_uuid(data["requested_plan_id"])
    assert isinstance(data["intake_sequence"], int) and data["intake_sequence"] >= 1
    assert data["status"] != "EVALUATING", (
        "the enquiry is always returned already in QUALIFIED, CAPACITY_DEFERRED or DENIED"
    )
    if data.get("desktop_mounting_type") is not None:
        _assert_enum(data, "desktop_mounting_type", "mounting_type", "qualification")


def assert_capacity_hold(data: dict):
    assert_audit_fields(data, "capacity reservation")
    _assert_enum(data, "status", "hold_status", "capacity reservation")
    assert is_valid_uuid(data["serviceability_request_id"])
    assert is_valid_uuid(data["sector_id"])
    assert isinstance(data["held_mbps"], int) and data["held_mbps"] >= 0
    assert isinstance(data["hold_days"], int) and 1 <= data["hold_days"] <= 30
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["origin"] in ("DIRECT", "AUTO_PROMOTION")


def assert_subscriber(data: dict):
    assert_audit_fields(data, "account")
    _assert_enum(data, "service_status", "service_status", "account")
    _assert_enum(data, "usage_priority", "usage_priority", "account")
    assert is_valid_uuid(data["serviceability_request_id"])
    assert is_valid_uuid(data["service_plan_id"])
    assert is_valid_uuid(data["sector_id"])
    assert isinstance(data["account_number"], str) and data["account_number"].startswith("RB-"), (
        f"account_number follows the RB-000001 series, got {data.get('account_number')!r}"
    )
    assert data["equipment_mode"] in ("RENTAL", "PURCHASE")
    assert isinstance(data["cycle_usage_gb"], (int, float)) and data["cycle_usage_gb"] >= 0
    assert isinstance(data["effective_downstream_mbps"], (int, float))
    assert isinstance(data["consecutive_breach_cycles"], int)
    assert isinstance(data["sticky_deprioritization_active"], bool)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["settlement_balance_cents"], int)
    assert isinstance(data["equipment_monthly_charge_cents"], int)


def assert_install_work_order(data: dict):
    assert_audit_fields(data, "work order")
    _assert_enum(data, "status", "work_order_status", "work order")
    assert is_valid_uuid(data["subscriber_id"])
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["resurvey_count"], int) and data["resurvey_count"] >= 0
    for field in ("recommended_mounting_type", "approved_mounting_type"):
        if data.get(field) is not None:
            _assert_enum(data, field, "mounting_type", "work order")


def assert_equipment_assignment(data: dict):
    assert_audit_fields(data, "equipment assignment")
    _assert_enum(data, "status", "assignment_status", "equipment assignment")
    assert is_valid_uuid(data["subscriber_id"])
    assert data["acquisition_mode"] in ("RENTAL", "PURCHASE")
    assert isinstance(data["monthly_rental_cents"], int)
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["replacement_cost_cents"], int)
    assert isinstance(data["settlement_cents"], int), "settlement_cents is an integer count of cents"
    if data.get("return_condition") is not None:
        assert data["return_condition"] in ("GOOD", "DAMAGED")
    if data.get("settlement_basis") is not None:
        assert data["settlement_basis"] in (
            "NONE",
            "RENTAL_CREDIT_OFFSET",
            "RENTAL_DAMAGE",
            "DEPRECIATED_REFUND",
        )


def assert_usage_record(data: dict):
    assert_immutable_record_fields(data, "usage record")
    assert is_valid_uuid(data["subscriber_id"])
    assert isinstance(data["usage_date"], str)
    assert isinstance(data["downstream_gb"], (int, float)) and data["downstream_gb"] >= 0
    assert isinstance(data["upstream_gb"], (int, float)) and data["upstream_gb"] >= 0
    assert isinstance(data["total_gb"], (int, float))
    assert isinstance(data["ingest_sequence"], int) and data["ingest_sequence"] >= 1
    assert isinstance(data["in_current_cycle"], bool)


def assert_outage_event(data: dict):
    assert_audit_fields(data, "outage")
    _assert_enum(data, "status", "outage_status", "outage")
    assert is_valid_uuid(data["tower_id"])
    assert is_iso8601_timestamp(data["started_at"])
    assert isinstance(data["sla_excluded"], bool)
    assert isinstance(data["total_credited_cents"], int)
    assert data["cause"] in (
        "WEATHER_WIND",
        "WEATHER_ICE",
        "WEATHER_FLOOD",
        "POWER",
        "BACKHAUL",
        "EQUIPMENT",
        "PLANNED_MAINTENANCE",
    )


def assert_outage_credit(data: dict):
    assert_audit_fields(data, "credit")
    _assert_enum(data, "status", "credit_status", "credit")
    assert is_valid_uuid(data["outage_event_id"])
    assert is_valid_uuid(data["subscriber_id"])
    assert data["method"] in ("SLA_SHORTFALL", "PER_INCIDENT")
    assert isinstance(data["cycle_outage_minutes"], int)
    assert isinstance(data["credit_cents"], int), "credit_cents is an integer count of cents"
    assert isinstance(data["prior_cycle_credited_cents"], int)
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    if data.get("denial_reason") is not None:
        assert data["denial_reason"] in (
            "SLA_EXCLUDED",
            "BELOW_MINIMUM_DURATION",
            "NO_SHORTFALL",
        )


# --------------------------------------------------------------------------
# Cross-record invariants
# --------------------------------------------------------------------------


def assert_version_advanced_by(before: dict, after: dict, steps: int = 1, entity: str = "record"):
    """version increments by exactly `steps` mutations (PRD 2.5)."""
    assert after["version"] == before["version"] + steps, (
        f"{entity}.version must advance by {steps} from {before['version']}, got {after['version']}"
    )


def assert_no_mutation(before: dict, after: dict, entity: str = "record"):
    """A record left untouched keeps its version and updated_at."""
    assert after["version"] == before["version"], (
        f"{entity} must not be mutated: version moved {before['version']} -> {after['version']}"
    )
    assert after["updated_at"] == before["updated_at"], (
        f"{entity} must not be mutated: updated_at moved"
    )
