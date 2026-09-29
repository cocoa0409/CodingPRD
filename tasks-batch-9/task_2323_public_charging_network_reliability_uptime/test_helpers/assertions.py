"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    ClaimState,
    ComplaintState,
    DispatchState,
    FaultClass,
    OutageState,
    PartClass,
    ParkingEnforcementMode,
    PortMaintenanceState,
    PortServiceState,
    PowerClass,
    PowerUpgradeStatus,
    RefundState,
    ReservationState,
    StationStatus,
    SuspensionSource,
    TerminalCertificationStatus,
    UptimeReportState,
)


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """Every persisted resource type carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must start at 1, got {data['version']}"


def assert_host_site(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "HostSite")
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["host_org_name"], str) and data["host_org_name"]
    assert float(data["committed_service_capacity_kw"]) > 0
    assert data["agreement_status"] in _enum_values(AgreementStatus)
    assert data["power_upgrade_status"] in _enum_values(PowerUpgradeStatus)
    assert data["access_hours_mode"] in ("TWENTY_FOUR_SEVEN", "RESTRICTED")
    assert 0 <= int(data["access_open_minute"]) <= 1439
    assert 1 <= int(data["access_close_minute"]) <= 1440
    assert data["parking_enforcement_mode"] in _enum_values(ParkingEnforcementMode)
    assert int(data["station_count"]) >= 0


def assert_station(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Station")
    assert is_valid_uuid(data["host_site_id"])
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert data["power_class"] in _enum_values(PowerClass)
    assert int(data["declared_port_count"]) >= 1
    assert isinstance(data["corridor_designated"], bool)
    assert data["status"] in _enum_values(StationStatus)
    assert data["suspension_source"] in _enum_values(SuspensionSource)
    if data.get("commissioned_at") is not None:
        assert is_iso8601_timestamp(data["commissioned_at"])
    assert_station_ledger_consistent(data)


def assert_station_ledger_consistent(data: Dict[str, Any]) -> None:
    """billable_downtime_minutes_lifetime is the gross figure less the excluded figure."""
    gross = int(data["gross_downtime_minutes_lifetime"])
    excluded = int(data["excluded_downtime_minutes_lifetime"])
    billable = int(data["billable_downtime_minutes_lifetime"])
    assert gross >= 0 and excluded >= 0 and billable >= 0
    assert billable == gross - excluded, (
        "billable_downtime_minutes_lifetime must equal gross less excluded, got "
        f"{billable} != {gross} - {excluded}"
    )


def assert_charging_port(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ChargingPort")
    assert is_valid_uuid(data["station_id"])
    assert data["connector_type"] in ("CCS1", "NACS", "CHADEMO", "J1772")
    assert float(data["rated_power_kw"]) > 0
    assert isinstance(data["dispenser_serial"], str) and data["dispenser_serial"]
    assert isinstance(data["terminal_model"], str) and data["terminal_model"]
    assert isinstance(data["contactless_enabled"], bool)
    assert isinstance(data["plug_and_charge_enabled"], bool)
    assert isinstance(data["price_display_verified"], bool)
    assert data["roaming_ocpi_version"] in ("NONE", "V2_1_1", "V2_2_1", "V2_3_0")
    assert data["terminal_certification_status"] in _enum_values(TerminalCertificationStatus)
    assert data["service_state"] in _enum_values(PortServiceState)
    assert data["maintenance_state"] in _enum_values(PortMaintenanceState)
    if data.get("retired_at") is not None:
        assert is_iso8601_timestamp(data["retired_at"])


def assert_outage_event(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "OutageEvent")
    assert is_valid_uuid(data["port_id"])
    assert isinstance(data["fault_code"], str) and data["fault_code"]
    assert data["fault_class"] in _enum_values(FaultClass)
    assert is_iso8601_timestamp(data["detected_at"])
    assert data["state"] in _enum_values(OutageState)
    assert isinstance(data["is_system_generated"], bool)
    if data.get("cleared_at") is not None:
        assert is_iso8601_timestamp(data["cleared_at"])
    if data.get("excluded_at") is not None:
        assert is_iso8601_timestamp(data["excluded_at"])
    if data.get("pre_exclusion_state") is not None:
        assert data["pre_exclusion_state"] in ("CLASSIFIED", "RESOLVED")


def assert_maintenance_dispatch(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "MaintenanceDispatch")
    assert is_valid_uuid(data["outage_event_id"])
    assert is_valid_uuid(data["port_id"])
    assert isinstance(data["technician_user_id"], str) and data["technician_user_id"]
    assert data["technician_certification_class"] in ("L2", "DCFC_BASIC", "DCFC_HV")
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert data["window_end_at"] > data["window_start_at"]
    assert data["state"] in _enum_values(DispatchState)
    assert is_iso8601_timestamp(data["response_deadline_at"])
    if data.get("arrived_at") is None:
        assert data.get("response_met") is None, (
            "response_met stays null until arrival is posted, got " f"{data.get('response_met')!r}"
        )
    else:
        assert is_iso8601_timestamp(data["arrived_at"])
        assert isinstance(data["response_met"], bool)


def assert_spare_part(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "SparePart")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["part_class"] in _enum_values(PartClass)
    assert int(data["lead_time_days"]) >= 0
    for field in (
        "on_hand_qty",
        "reserved_qty",
        "backordered_qty",
        "consumed_qty_lifetime",
        "unencumbered_qty",
    ):
        assert int(data[field]) >= 0, f"SparePart.{field} must never be negative"
    assert_spare_part_unit_conservation(data)


def assert_spare_part_unit_conservation(data: Dict[str, Any]) -> None:
    """unencumbered_qty is on_hand_qty less reserved_qty."""
    on_hand = int(data["on_hand_qty"])
    reserved = int(data["reserved_qty"])
    unencumbered = int(data["unencumbered_qty"])
    assert unencumbered == on_hand - reserved, (
        "unencumbered_qty must equal on_hand_qty less reserved_qty, got "
        f"{unencumbered} != {on_hand} - {reserved}"
    )


def assert_part_reservation(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "PartReservation")
    assert is_valid_uuid(data["dispatch_id"])
    assert is_valid_uuid(data["spare_part_id"])
    assert int(data["qty"]) >= 1
    assert data["state"] in _enum_values(ReservationState)
    if data.get("expected_available_at") is not None:
        assert is_iso8601_timestamp(data["expected_available_at"])


def assert_uptime_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "UptimeReport")
    assert is_valid_uuid(data["station_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["period_end"] > data["period_start"]
    assert data["state"] in _enum_values(UptimeReportState)
    if data.get("methodology") is not None:
        assert data["methodology"] in ("PROVISIONAL", "FINAL")
    assert int(data["claim_count"]) >= 0
    assert int(data["returned_count"]) >= 0


def assert_uptime_report_draft_fields_null(data: Dict[str, Any]) -> None:
    """A fresh report opens with its computed figures null."""
    for field in (
        "methodology",
        "eligible_port_count",
        "total_port_minutes",
        "excluded_minutes",
        "billable_downtime_minutes",
        "uptime_pct",
    ):
        assert data[field] is None, f"UptimeReport.{field} must be null in DRAFT, got {data[field]!r}"


def assert_reimbursement_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ReimbursementClaim")
    assert is_valid_uuid(data["uptime_report_id"])
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    for item in data["line_items"]:
        assert is_valid_uuid(item["port_id"])
        assert item["category"] in ("OANDM", "NETWORK_FEES", "PARTS")
        assert int(item["amount_cents"]) >= 0
    assert int(data["requested_amount_cents"]) == sum(
        int(item["amount_cents"]) for item in data["line_items"]
    ), "requested_amount_cents must be the exact integer sum of the line-item amounts"
    assert data["state"] in _enum_values(ClaimState)


def assert_customer_complaint(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CustomerComplaint")
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["port_id"])
    assert data["complaint_type"] in (
        "PAYMENT_DECLINED",
        "PRICE_MISMATCH",
        "SESSION_FAILED",
        "CHARGER_OFFLINE",
        "BLOCKED_STALL",
    )
    assert is_iso8601_timestamp(data["session_started_at"])
    assert is_iso8601_timestamp(data["session_ended_at"])
    assert data["session_ended_at"] > data["session_started_at"]
    assert float(data["session_energy_kwh"]) >= 0
    assert int(data["session_price_per_kwh_cents"]) >= 0
    assert int(data["session_charged_cents"]) >= 0
    assert int(data["session_idle_fee_cents"]) >= 0
    assert data["state"] in _enum_values(ComplaintState)
    assert data["refund_state"] in _enum_values(RefundState)
    if data.get("refund_basis") is not None:
        assert data["refund_basis"] in ("ENERGY_PRORATED", "FULL_SESSION_GOODWILL")
    if data.get("refund_settled_at") is not None:
        assert is_iso8601_timestamp(data["refund_settled_at"])


def assert_session_money_conservation(data: Dict[str, Any]) -> None:
    """The refund and the retained amount always sum to what the driver was charged."""
    refund = data.get("refund_amount_cents")
    retained = data.get("retained_amount_cents")
    if refund is None and retained is None:
        return
    charged = int(data["session_charged_cents"])
    assert int(refund) + int(retained) == charged, (
        "refund_amount_cents + retained_amount_cents must equal session_charged_cents, got "
        f"{refund} + {retained} != {charged}"
    )


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """Error responses carry response_type 'error' and a meta with an api_request_id."""
    assert body.get("response_type") == "error", (
        f"error responses must carry response_type 'error', got {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must be a server-generated id starting with req_, got {meta.get('api_request_id')!r}"
    assert isinstance(body.get("data", {}).get("error_id"), str)


def assert_version_advanced_by(
    new_data: Dict[str, Any], old_version: int, increment: int = 1, label: str = "resource"
) -> None:
    """version increments by one on every mutation of the resource."""
    assert int(new_data["version"]) == old_version + increment, (
        f"{label}.version must move from {old_version} to {old_version + increment}, got "
        f"{new_data['version']}"
    )


def assert_version_unchanged(
    data: Dict[str, Any], expected_version: int, label: str = "resource"
) -> None:
    assert int(data["version"]) == expected_version, (
        f"{label}.version must stay at {expected_version} after a rejected write, got "
        f"{data['version']}"
    )


def parse_instant(value: str) -> datetime:
    """Read an ISO 8601 UTC instant, with or without fractional seconds."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two UTC instants by value, tolerating fractional-second notation."""
    assert actual is not None, f"{label} must be present, expected {expected}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} expected {expected}, got {actual}"
    )


def assert_two_decimals(value: Any, label: str = "value") -> None:
    """Percentages and power figures carry exactly two decimal places."""
    assert value is not None, f"{label} must be present"
    quantised = round(float(value) + 1e-12, 2)
    assert abs(float(value) - quantised) < 1e-9, f"{label} must carry two decimal places, got {value}"


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """Every list response carries limit, offset, total_count and has_more in meta."""
    assert meta.get("limit") == limit, f"meta.limit expected {limit}, got {meta.get('limit')}"
    assert meta.get("offset") == offset, f"meta.offset expected {offset}, got {meta.get('offset')}"
    assert (
        meta.get("total_count") == total_count
    ), f"meta.total_count expected {total_count}, got {meta.get('total_count')}"
    assert (
        meta.get("has_more") is has_more
    ), f"meta.has_more expected {has_more}, got {meta.get('has_more')}"
