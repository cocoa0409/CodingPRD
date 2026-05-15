"""Payload factories — one per endpoint that accepts a request body.

Each factory emits the exact schema PRD §3.1–§3.7 declares for the
request body. Tests pass overrides for the values they want to control.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_alpha = string.ascii_lowercase + string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(_alpha, k=n))


def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits
    (PRD §2.4 timestamp format)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ---------------------------------------------------------------------------
# Station (PRD §3.1)
# ---------------------------------------------------------------------------
def create_station_payload(
    name: Optional[str] = None,
    installed_capacity_kw: float = 100.000,
    ac_capacity_kw: float = 100.000,
    commissioning_date: Optional[str] = None,
    latitude: float = 31.230,
    longitude: float = 121.473,
    grid_company: str = "Test Grid Co.",
    feed_in_tariff_cny_per_kwh: float = 0.5000,
    market_trading_enabled: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Station-{random_suffix(6)}",
        "installed_capacity_kw": installed_capacity_kw,
        "ac_capacity_kw": ac_capacity_kw,
        "commissioning_date": commissioning_date or "2025-06-01T00:00:00.000Z",
        "latitude": latitude,
        "longitude": longitude,
        "grid_company": grid_company,
        "feed_in_tariff_cny_per_kwh": feed_in_tariff_cny_per_kwh,
    }
    if market_trading_enabled is not None:
        payload["market_trading_enabled"] = market_trading_enabled
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Array / String / Module (PRD §3.1)
# ---------------------------------------------------------------------------
def create_array_payload(
    code: Optional[str] = None,
    tilt_angle_deg: float = 30.0,
    azimuth_deg: float = 180.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or f"ARR-{random_suffix(4).upper()}",
        "tilt_angle_deg": tilt_angle_deg,
        "azimuth_deg": azimuth_deg,
    }
    payload.update(overrides)
    return payload


def create_string_payload(
    inverter_id: str,
    code: Optional[str] = None,
    module_count: int = 20,
    combiner_box_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or f"STR-{random_suffix(4).upper()}",
        "module_count": module_count,
        "inverter_id": inverter_id,
    }
    if combiner_box_id is not None:
        payload["combiner_box_id"] = combiner_box_id
    payload.update(overrides)
    return payload


def create_module_payload(
    warranty_supplier_id: str,
    serial_no: Optional[str] = None,
    wp_rating: float = 540.0,
    manufacturer: str = "TestCo",
    warranty_until: str = "2035-01-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "serial_no": serial_no or f"MOD-{random_suffix(8).upper()}",
        "wp_rating": wp_rating,
        "manufacturer": manufacturer,
        "warranty_supplier_id": warranty_supplier_id,
        "warranty_until": warranty_until,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inverter / Transformer (PRD §3.1)
# ---------------------------------------------------------------------------
def create_inverter_payload(
    station_id: str,
    warranty_supplier_id: str,
    role: str = "INVERTER",
    model: str = "MDL-100",
    vendor: str = "VendorAlpha",
    serial_no: Optional[str] = None,
    rated_ac_power_kw: float = 50.0,
    warranty_until: str = "2035-01-01T00:00:00.000Z",
    array_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "role": role,
        "model": model,
        "vendor": vendor,
        "serial_no": serial_no or f"INV-{random_suffix(8).upper()}",
        "rated_ac_power_kw": rated_ac_power_kw,
        "warranty_supplier_id": warranty_supplier_id,
        "warranty_until": warranty_until,
    }
    if array_id is not None:
        payload["array_id"] = array_id
    payload.update(overrides)
    return payload


def create_transformer_payload(
    warranty_supplier_id: str,
    code: Optional[str] = None,
    rated_capacity_kva: float = 1000.0,
    primary_voltage_kv: float = 35.0,
    secondary_voltage_kv: float = 0.4,
    grid_connection_point_no: Optional[str] = None,
    warranty_until: str = "2035-01-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or f"TR-{random_suffix(4).upper()}",
        "rated_capacity_kva": rated_capacity_kva,
        "primary_voltage_kv": primary_voltage_kv,
        "secondary_voltage_kv": secondary_voltage_kv,
        "grid_connection_point_no": (
            grid_connection_point_no or f"GCP-{random_suffix(8).upper()}"
        ),
        "warranty_supplier_id": warranty_supplier_id,
        "warranty_until": warranty_until,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Supplier (PRD §3.1)
# ---------------------------------------------------------------------------
def create_supplier_payload(
    name: Optional[str] = None,
    contact: str = "ops@supplier.example",
    rating: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Supplier-{random_suffix(6)}",
        "contact": contact,
    }
    if rating is not None:
        payload["rating"] = rating
    payload.update(overrides)
    return payload


def update_supplier_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# ---------------------------------------------------------------------------
# GenerationReading (PRD §3.2)
# ---------------------------------------------------------------------------
def create_reading_payload(
    timestamp: str,
    dc_power_kw: float = 72.0,
    ac_power_kw: float = 70.0,
    irradiance_w_m2: float = 800.0,
    module_temp_c: float = 25.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "timestamp": timestamp,
        "dc_power_kw": dc_power_kw,
        "ac_power_kw": ac_power_kw,
        "irradiance_w_m2": irradiance_w_m2,
        "module_temp_c": module_temp_c,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driver hooks (PRD §3.2)
# ---------------------------------------------------------------------------
def clock_advance_payload(to: str) -> Dict[str, Any]:
    """PRD §3.2: '...advances the logical clock to a supplied to instant.'"""
    return {"to": to}


def events_emit_payload(source: str, payload: Optional[Dict[str, Any]] = None
                        ) -> Dict[str, Any]:
    return {"source": source, "payload": payload or {}}


# ---------------------------------------------------------------------------
# AlarmCodeMap / AlarmEvent (PRD §3.3)
# ---------------------------------------------------------------------------
def create_alarm_code_map_payload(
    vendor: str = "VendorAlpha",
    model: str = "MDL-100",
    vendor_code: str = "E1",
    canonical_code: str = "INV_OVERTEMP",
    severity: str = "MAJOR",
    root_cause_hint: str = "Inverter overtemperature",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor": vendor,
        "model": model,
        "vendor_code": vendor_code,
        "canonical_code": canonical_code,
        "severity": severity,
        "root_cause_hint": root_cause_hint,
    }
    payload.update(overrides)
    return payload


def create_alarm_payload(
    inverter_id: str,
    vendor_code: str = "E1",
    first_seen_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inverter_id": inverter_id,
        "vendor_code": vendor_code,
        "first_seen_at": first_seen_at or "2026-01-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Patrol (PRD §3.4)
# ---------------------------------------------------------------------------
def create_patrol_plan_payload(
    name: Optional[str] = None,
    zone_route: Optional[List[str]] = None,
    kind: str = "PERIODIC",
    cadence_days: Optional[int] = 7,
    checklist: Optional[Dict[str, List[str]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Plan-{random_suffix(6)}",
        "zone_route": zone_route or ["Z1", "Z2"],
        "kind": kind,
        "checklist": checklist or {"INVERTER": ["temp", "fan_noise"]},
    }
    if kind == "PERIODIC":
        payload["cadence_days"] = cadence_days if cadence_days is not None else 7
    else:
        # PRD §3.4: cadence_days "must be null when kind is SPECIAL_POST_STORM"
        payload["cadence_days"] = None
    payload.update(overrides)
    return payload


def schedule_patrol_payload(scheduled_for: Optional[str] = None,
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_for": scheduled_for or "2026-01-15T08:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def log_zone_payload(
    photo_url: str = "https://photos.example/test.jpg",
    gps: Optional[Dict[str, float]] = None,
    checklist_findings: Optional[Any] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "photo_url": photo_url,
        "gps": gps or {"lat": 31.230, "lng": 121.473},
        "checklist_findings": (
            checklist_findings
            if checklist_findings is not None
            else {"temp": "ok", "fan_noise": "ok"}
        ),
    }
    payload.update(overrides)
    return payload


def reject_patrol_payload(notes: str = "Needs rework",
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"notes": notes}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Defects / WorkOrder (PRD §3.5)
# ---------------------------------------------------------------------------
def create_defect_payload(
    station_id: str,
    subject_type: str,
    subject_id: str,
    source: str = "EXTERNAL_INSPECTION",
    severity: str = "MINOR",
    source_ref_id: Optional[str] = None,
    parent_defect_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "source": source,
        "severity": severity,
    }
    if source_ref_id is not None:
        payload["source_ref_id"] = source_ref_id
    if parent_defect_id is not None:
        payload["parent_defect_id"] = parent_defect_id
    payload.update(overrides)
    return payload


def create_work_order_payload(
    assigned_supplier_id: str,
    spare_part_lines: Optional[List[Dict[str, Any]]] = None,
    assigned_technician_id: str = "tech-001",
    scheduled_start: Optional[str] = None,
    scheduled_end: Optional[str] = None,
    before_metrics: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "assigned_supplier_id": assigned_supplier_id,
        "assigned_technician_id": assigned_technician_id,
        "scheduled_start": (
            scheduled_start or "2026-02-01T08:00:00.000Z"
        ),
        "scheduled_end": (
            scheduled_end or "2026-02-01T12:00:00.000Z"
        ),
        "spare_part_lines": spare_part_lines or [],
        "before_metrics": (
            before_metrics if before_metrics is not None
            else {"dc_power_kw": 10.0}
        ),
    }
    payload.update(overrides)
    return payload


def complete_work_order_payload(
    after_metrics: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "after_metrics": (
            after_metrics if after_metrics is not None
            else {"dc_power_kw": 40.0}
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Spare parts (PRD §3.5)
# ---------------------------------------------------------------------------
def create_spare_part_payload(
    sku: Optional[str] = None,
    name: str = "Test Spare",
    stock_on_hand: int = 100,
    unit_cost_cny: float = 50.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sku": sku or f"SKU-{random_suffix(6).upper()}",
        "name": name,
        "stock_on_hand": stock_on_hand,
        "unit_cost_cny": unit_cost_cny,
    }
    payload.update(overrides)
    return payload


def update_spare_part_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# ---------------------------------------------------------------------------
# Settlement (PRD §3.6)
# ---------------------------------------------------------------------------
def create_settlement_period_payload(
    period_start: str = "2026-02-01T00:00:00.000Z",
    period_end: str = "2026-03-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_metering_payload(
    settlement_period_id: str,
    window_start: str,
    window_end: str,
    on_grid_kwh: float = 100.000,
    pricing_channel: str = "FEED_IN",
    market_price_cny_per_kwh: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "settlement_period_id": settlement_period_id,
        "window_start": window_start,
        "window_end": window_end,
        "on_grid_kwh": on_grid_kwh,
        "pricing_channel": pricing_channel,
    }
    if market_price_cny_per_kwh is not None:
        payload["market_price_cny_per_kwh"] = market_price_cny_per_kwh
    payload.update(overrides)
    return payload


def start_reconciliation_payload(grid_company_confirmed_kwh: float
                                 ) -> Dict[str, Any]:
    return {"grid_company_confirmed_kwh": grid_company_confirmed_kwh}


def issue_invoice_payload(invoice_no: Optional[str] = None) -> Dict[str, Any]:
    return {"invoice_no": invoice_no or f"INV-{random_suffix(8).upper()}"}


def revenue_adjust_payload(reason: str = "operator correction") -> Dict[str, Any]:
    return {"reason": reason}


def create_investor_share_payload(
    investor_name: str,
    share_basis_points: int,
    effective_from: str = "2025-01-01T00:00:00.000Z",
    effective_to: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "investor_name": investor_name,
        "share_basis_points": share_basis_points,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Subsidies (PRD §3.7)
# ---------------------------------------------------------------------------
def create_subsidy_policy_payload(
    code: Optional[str] = None,
    scope: str = "NATIONAL",
    rate_cny_per_kwh: float = 0.0500,
    eligible_from: str = "2026-01-01T00:00:00.000Z",
    eligible_to: str = "2027-01-01T00:00:00.000Z",
    min_commissioning_date: Optional[str] = None,
    max_commissioning_date: Optional[str] = None,
    required_documents: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or f"POL-{random_suffix(6).upper()}",
        "scope": scope,
        "rate_cny_per_kwh": rate_cny_per_kwh,
        "eligible_from": eligible_from,
        "eligible_to": eligible_to,
        "required_documents": required_documents
        if required_documents is not None
        else ["GRID_CONNECTION_CERT", "METER_REPORT"],
    }
    if min_commissioning_date is not None:
        payload["min_commissioning_date"] = min_commissioning_date
    if max_commissioning_date is not None:
        payload["max_commissioning_date"] = max_commissioning_date
    payload.update(overrides)
    return payload


def create_subsidy_declaration_payload(
    subsidy_policy_id: str,
    settlement_period_id: str,
    documents: Optional[List[Dict[str, str]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subsidy_policy_id": subsidy_policy_id,
        "settlement_period_id": settlement_period_id,
        "documents": documents if documents is not None else [
            {"key": "GRID_CONNECTION_CERT",
             "ref_url": "https://docs.example/cert.pdf"},
            {"key": "METER_REPORT",
             "ref_url": "https://docs.example/meter.pdf"},
        ],
    }
    payload.update(overrides)
    return payload


def reject_subsidy_payload(reason: str = "Documentation issue"
                           ) -> Dict[str, Any]:
    return {"reason": reason}


__all__ = [
    "random_suffix",
    "iso_utc",
    "create_station_payload",
    "create_array_payload",
    "create_string_payload",
    "create_module_payload",
    "create_inverter_payload",
    "create_transformer_payload",
    "create_supplier_payload",
    "update_supplier_payload",
    "create_reading_payload",
    "clock_advance_payload",
    "events_emit_payload",
    "create_alarm_code_map_payload",
    "create_alarm_payload",
    "create_patrol_plan_payload",
    "schedule_patrol_payload",
    "log_zone_payload",
    "reject_patrol_payload",
    "create_defect_payload",
    "create_work_order_payload",
    "complete_work_order_payload",
    "create_spare_part_payload",
    "update_spare_part_payload",
    "create_settlement_period_payload",
    "create_metering_payload",
    "start_reconciliation_payload",
    "issue_invoice_payload",
    "revenue_adjust_payload",
    "create_investor_share_payload",
    "create_subsidy_policy_payload",
    "create_subsidy_declaration_payload",
    "reject_subsidy_payload",
]
