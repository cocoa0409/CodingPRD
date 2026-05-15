"""Composite setup helpers — multi-step preambles tests can reuse.

PRD §3.2 test-only capabilities: POST /_clock/advance moves the logical
clock to a supplied `to` instant; POST /_sweep/run runs the downsampling
+ arrears scan. Both are PlatformAdmin-only.

PRD §2.1: All four roles carry opaque identities, so role headers are
shared constants. Per-instance builders are used when a test must
distinguish two actors (e.g., patrol SoD verifier != actor_id).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_advance_payload,
    complete_work_order_payload,
    create_alarm_code_map_payload,
    create_alarm_payload,
    create_array_payload,
    create_defect_payload,
    create_inverter_payload,
    create_investor_share_payload,
    create_metering_payload,
    create_module_payload,
    create_patrol_plan_payload,
    create_reading_payload,
    create_settlement_period_payload,
    create_spare_part_payload,
    create_station_payload,
    create_string_payload,
    create_subsidy_declaration_payload,
    create_subsidy_policy_payload,
    create_supplier_payload,
    create_transformer_payload,
    create_work_order_payload,
    iso_utc,
    log_zone_payload,
    random_suffix,
    schedule_patrol_payload,
    start_reconciliation_payload,
    update_supplier_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_operator_headers,
)


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------
def _admin() -> Dict[str, str]:
    return TEST_USERS["platform_admin_headers"]


def _om() -> Dict[str, str]:
    return TEST_USERS["om_engineer_headers"]


def _om_alt() -> Dict[str, str]:
    return TEST_USERS["om_engineer_headers_alt"]


def _field() -> Dict[str, str]:
    return TEST_USERS["field_operator_headers"]


def _finance() -> Dict[str, str]:
    return TEST_USERS["finance_officer_headers"]


def _ok(resp) -> Dict[str, Any]:
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Test-driver hooks (PRD §3.2)
# ---------------------------------------------------------------------------
def advance_clock_to(to_instant: str) -> Dict[str, Any]:
    """Advance the logical clock to a supplied `to` instant."""
    return _ok(api_client.clock_advance(
        clock_advance_payload(to_instant), _admin(),
    ))


def run_sweep() -> Dict[str, Any]:
    """Run downsampling + arrears scan (PRD §3.2)."""
    return _ok(api_client.sweep_run(_admin()))


# ---------------------------------------------------------------------------
# Tier 1 — primitive entity creators
# ---------------------------------------------------------------------------
def create_station(
    installed_capacity_kw: float = 100.000,
    ac_capacity_kw: float = 100.000,
    feed_in_tariff_cny_per_kwh: float = 0.5000,
    market_trading_enabled: bool = False,
    commissioning_date: str = "2025-06-01T00:00:00.000Z",
    name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create an ACTIVE station with default geometry."""
    payload = create_station_payload(
        name=name,
        installed_capacity_kw=installed_capacity_kw,
        ac_capacity_kw=ac_capacity_kw,
        feed_in_tariff_cny_per_kwh=feed_in_tariff_cny_per_kwh,
        market_trading_enabled=market_trading_enabled,
        commissioning_date=commissioning_date,
        **overrides,
    )
    return _ok(api_client.create_station(payload, _admin()))


def create_supplier(
    name: Optional[str] = None,
    rating: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_supplier_payload(name=name, rating=rating, **overrides)
    return _ok(api_client.create_supplier(payload, _admin()))


def blacklist_supplier(supplier_id: str) -> Dict[str, Any]:
    return _ok(api_client.update_supplier(
        supplier_id,
        update_supplier_payload(lifecycle_state="BLACKLISTED"),
        _admin(),
    ))


def create_inverter(
    station_id: str,
    supplier_id: str,
    role: str = "INVERTER",
    vendor: str = "VendorAlpha",
    model: str = "MDL-100",
    rated_ac_power_kw: float = 50.0,
    serial_no: Optional[str] = None,
    array_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_inverter_payload(
        station_id=station_id,
        warranty_supplier_id=supplier_id,
        role=role,
        vendor=vendor,
        model=model,
        rated_ac_power_kw=rated_ac_power_kw,
        serial_no=serial_no,
        array_id=array_id,
    )
    return _ok(api_client.create_inverter(payload, _admin()))


def create_transformer(station_id: str, supplier_id: str,
                       **overrides: Any) -> Dict[str, Any]:
    payload = create_transformer_payload(
        warranty_supplier_id=supplier_id, **overrides,
    )
    return _ok(api_client.create_transformer(station_id, payload, _admin()))


def create_array(station_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = create_array_payload(**overrides)
    return _ok(api_client.create_array(station_id, payload, _admin()))


def create_pvstring(array_id: str, inverter_id: str,
                    **overrides: Any) -> Dict[str, Any]:
    payload = create_string_payload(inverter_id=inverter_id, **overrides)
    return _ok(api_client.create_string(array_id, payload, _admin()))


def create_module(string_id: str, supplier_id: str,
                  **overrides: Any) -> Dict[str, Any]:
    payload = create_module_payload(
        warranty_supplier_id=supplier_id, **overrides,
    )
    return _ok(api_client.create_module(string_id, payload, _admin()))


def create_spare_part(stock_on_hand: int = 100,
                      sku: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    payload = create_spare_part_payload(
        sku=sku, stock_on_hand=stock_on_hand, **overrides,
    )
    return _ok(api_client.create_spare_part(payload, _admin()))


# ---------------------------------------------------------------------------
# Tier 2 — station + supplier + inverter helpers
# ---------------------------------------------------------------------------
def setup_station_with_inverters(
    inverter_count: int = 1,
    installed_capacity_kw: float = 100.000,
    ac_capacity_kw: float = 100.000,
    feed_in_tariff_cny_per_kwh: float = 0.5000,
    market_trading_enabled: bool = False,
    commissioning_date: str = "2025-06-01T00:00:00.000Z",
    vendor: str = "VendorAlpha",
    model: str = "MDL-100",
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Station + supplier + N inverters under it.

    Returns (station, supplier, [inverter_1, ..., inverter_N]).
    """
    station = create_station(
        installed_capacity_kw=installed_capacity_kw,
        ac_capacity_kw=ac_capacity_kw,
        feed_in_tariff_cny_per_kwh=feed_in_tariff_cny_per_kwh,
        market_trading_enabled=market_trading_enabled,
        commissioning_date=commissioning_date,
    )
    supplier = create_supplier()
    inverters = [
        create_inverter(
            station_id=station["id"],
            supplier_id=supplier["id"],
            vendor=vendor,
            model=model,
        )
        for _ in range(inverter_count)
    ]
    return station, supplier, inverters


def register_alarm_code_map(
    vendor: str = "VendorAlpha",
    model: str = "MDL-100",
    vendor_code: str = "E1",
    canonical_code: str = "INV_OVERTEMP",
    severity: str = "MAJOR",
    root_cause_hint: str = "Inverter overtemperature",
) -> Dict[str, Any]:
    payload = create_alarm_code_map_payload(
        vendor=vendor, model=model, vendor_code=vendor_code,
        canonical_code=canonical_code, severity=severity,
        root_cause_hint=root_cause_hint,
    )
    return _ok(api_client.create_alarm_code_map(payload, _admin()))


# ---------------------------------------------------------------------------
# Tier 3 — alarm lifecycle scenarios
# ---------------------------------------------------------------------------
def ingest_alarm(
    inverter_id: str,
    vendor_code: str = "E1",
    first_seen_at: str = "2026-01-01T00:00:00.000Z",
) -> Dict[str, Any]:
    payload = create_alarm_payload(
        inverter_id=inverter_id,
        vendor_code=vendor_code,
        first_seen_at=first_seen_at,
    )
    return _ok(api_client.create_alarm(payload, _admin()))


def setup_acknowledged_alarm(
    severity: str = "MAJOR",
    canonical_code: str = "INV_OVERTEMP",
    inverter_count: int = 1,
    first_seen_at: str = "2026-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Station + N inverters + alarm-code-map + ingested alarm + ack.

    Returns (station, inverters, acknowledged_alarm).
    """
    station, _supplier, inverters = setup_station_with_inverters(
        inverter_count=inverter_count,
    )
    register_alarm_code_map(
        canonical_code=canonical_code, severity=severity,
    )
    alarm = ingest_alarm(
        inverter_id=inverters[0]["id"], first_seen_at=first_seen_at,
    )
    acked = _ok(api_client.ack_alarm(alarm["id"], _om()))
    return station, inverters, acked


# ---------------------------------------------------------------------------
# Tier 4 — defect / work-order lifecycle
# ---------------------------------------------------------------------------
def create_manual_defect(
    station_id: str,
    subject_type: str = "INVERTER",
    subject_id: Optional[str] = None,
    source: str = "EXTERNAL_INSPECTION",
    severity: str = "MINOR",
    source_ref_id: Optional[str] = None,
    parent_defect_id: Optional[str] = None,
) -> Dict[str, Any]:
    if subject_id is None:
        # Caller MUST pass an actual subject_id; we default to the
        # station_id only to make the schema valid for a smoke fixture.
        subject_id = station_id
    payload = create_defect_payload(
        station_id=station_id,
        subject_type=subject_type,
        subject_id=subject_id,
        source=source,
        severity=severity,
        source_ref_id=source_ref_id,
        parent_defect_id=parent_defect_id,
    )
    return _ok(api_client.create_defect(payload, _om()))


def dispatch_work_order(
    defect_id: str,
    supplier_id: str,
    spare_part_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = create_work_order_payload(
        assigned_supplier_id=supplier_id,
        spare_part_lines=spare_part_lines or [],
    )
    return _ok(api_client.create_work_order(defect_id, payload, _om()))


def start_work_order(work_order_id: str) -> Dict[str, Any]:
    return _ok(api_client.start_work_order(work_order_id, _field()))


def complete_work_order(work_order_id: str,
                        after_metrics: Optional[Dict[str, Any]] = None
                        ) -> Dict[str, Any]:
    payload = complete_work_order_payload(after_metrics=after_metrics)
    return _ok(api_client.complete_work_order(
        work_order_id, payload, _field(),
    ))


def cancel_work_order(work_order_id: str) -> Dict[str, Any]:
    return _ok(api_client.cancel_work_order(work_order_id, _om()))


def walk_defect_through_close(
    station_id: str,
    inverter_id: str,
    supplier_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Manually walk a defect OPEN→DISPATCHED→UNDER_REPAIR→RESOLVED→CLOSED.

    Returns (defect_after_close, latest_work_order).
    Useful as a parent_defect_id for recurrence-chain tests.
    """
    defect = create_manual_defect(
        station_id=station_id,
        subject_type="INVERTER",
        subject_id=inverter_id,
        severity="MINOR",
    )
    wo = dispatch_work_order(defect["id"], supplier_id, spare_part_lines=[])
    start_work_order(wo["id"])
    wo_done = complete_work_order(wo["id"])
    closed = _ok(api_client.close_defect(defect["id"], _om()))
    return closed, wo_done


# ---------------------------------------------------------------------------
# Tier 5 — settlement workflow
# ---------------------------------------------------------------------------
def create_settlement_period(
    station_id: str,
    period_start: str = "2026-02-01T00:00:00.000Z",
    period_end: str = "2026-03-01T00:00:00.000Z",
) -> Dict[str, Any]:
    payload = create_settlement_period_payload(
        period_start=period_start, period_end=period_end,
    )
    return _ok(api_client.create_settlement_period(
        station_id, payload, _finance(),
    ))


def add_metering_record(
    station_id: str,
    settlement_period_id: str,
    window_start: str,
    window_end: str,
    on_grid_kwh: float = 100.000,
    pricing_channel: str = "FEED_IN",
    market_price_cny_per_kwh: Optional[float] = None,
) -> Dict[str, Any]:
    payload = create_metering_payload(
        settlement_period_id=settlement_period_id,
        window_start=window_start,
        window_end=window_end,
        on_grid_kwh=on_grid_kwh,
        pricing_channel=pricing_channel,
        market_price_cny_per_kwh=market_price_cny_per_kwh,
    )
    return _ok(api_client.create_metering(station_id, payload, _finance()))


def create_investor_share(
    station_id: str,
    investor_name: str,
    share_basis_points: int,
    effective_from: str = "2025-01-01T00:00:00.000Z",
    effective_to: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_investor_share_payload(
        investor_name=investor_name,
        share_basis_points=share_basis_points,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    return _ok(api_client.create_investor_share(
        station_id, payload, _admin(),
    ))


def setup_confirmed_settlement(
    feed_in_tariff_cny_per_kwh: float = 0.5000,
    on_grid_kwh: float = 200.000,
    grid_company_confirmed_kwh: Optional[float] = None,
    period_start: str = "2026-02-01T00:00:00.000Z",
    period_end: str = "2026-03-01T00:00:00.000Z",
    period_end_clock: str = "2026-03-02T00:00:00.000Z",
    market_trading_enabled: bool = False,
    commissioning_date: str = "2025-06-01T00:00:00.000Z",
    investor_shares: Optional[List[Tuple[str, int]]] = None,
    confirm: bool = True,
) -> Dict[str, Any]:
    """Complete settlement walk: station → metering → reconcile → (confirm).

    Returns a dict {station, period (after confirm/reconcile), shares}.
    """
    station = create_station(
        feed_in_tariff_cny_per_kwh=feed_in_tariff_cny_per_kwh,
        market_trading_enabled=market_trading_enabled,
        commissioning_date=commissioning_date,
    )
    shares_input = investor_shares or [("OnlyInvestor", 10000)]
    shares = []
    for (name_, bp) in shares_input:
        shares.append(create_investor_share(
            station_id=station["id"],
            investor_name=name_,
            share_basis_points=bp,
            effective_from="2025-01-01T00:00:00.000Z",
        ))
    period = create_settlement_period(
        station["id"], period_start=period_start, period_end=period_end,
    )
    add_metering_record(
        station["id"], period["id"],
        window_start=period_start, window_end=period_end,
        on_grid_kwh=on_grid_kwh, pricing_channel="FEED_IN",
    )
    advance_clock_to(period_end_clock)
    grid_kwh = (
        grid_company_confirmed_kwh
        if grid_company_confirmed_kwh is not None
        else on_grid_kwh
    )
    period_recon = _ok(api_client.start_reconciliation(
        period["id"],
        start_reconciliation_payload(grid_kwh),
        _finance(),
    ))
    out_period = period_recon
    if confirm:
        out_period = _ok(api_client.confirm_settlement(
            period["id"], _finance(),
        ))
    return {
        "station": station,
        "period": out_period,
        "shares": shares,
    }


# ---------------------------------------------------------------------------
# Tier 6 — subsidy workflow
# ---------------------------------------------------------------------------
def create_subsidy_policy(
    rate_cny_per_kwh: float = 0.0500,
    eligible_from: str = "2026-01-01T00:00:00.000Z",
    eligible_to: str = "2027-01-01T00:00:00.000Z",
    required_documents: Optional[List[str]] = None,
    min_commissioning_date: Optional[str] = None,
    max_commissioning_date: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_subsidy_policy_payload(
        rate_cny_per_kwh=rate_cny_per_kwh,
        eligible_from=eligible_from,
        eligible_to=eligible_to,
        required_documents=required_documents,
        min_commissioning_date=min_commissioning_date,
        max_commissioning_date=max_commissioning_date,
    )
    return _ok(api_client.create_subsidy_policy(payload, _admin()))


def create_subsidy_declaration(
    station_id: str,
    subsidy_policy_id: str,
    settlement_period_id: str,
    documents: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    payload = create_subsidy_declaration_payload(
        subsidy_policy_id=subsidy_policy_id,
        settlement_period_id=settlement_period_id,
        documents=documents,
    )
    return _ok(api_client.create_subsidy_declaration(
        station_id, payload, _finance(),
    ))


# ---------------------------------------------------------------------------
# Tier 7 — patrol scenarios
# ---------------------------------------------------------------------------
def create_patrol_plan(
    station_id: str,
    zone_route: Optional[List[str]] = None,
    kind: str = "PERIODIC",
    cadence_days: int = 7,
    checklist: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    payload = create_patrol_plan_payload(
        zone_route=zone_route, kind=kind,
        cadence_days=cadence_days, checklist=checklist,
    )
    return _ok(api_client.create_patrol_plan(station_id, payload, _om()))


def schedule_patrol(plan_id: str,
                    scheduled_for: str = "2026-01-15T08:00:00.000Z"
                    ) -> Dict[str, Any]:
    payload = schedule_patrol_payload(scheduled_for=scheduled_for)
    return _ok(api_client.schedule_patrol(plan_id, payload, _om()))


def setup_submitted_patrol(
    operator_id: str = "field-op-alpha",
    zone_route: Optional[List[str]] = None,
    checklist: Optional[Dict[str, List[str]]] = None,
    findings_per_zone: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Station + plan + scheduled record + start + log each zone + submit.

    Returns (station, plan, record_after_submit). The PatrolRecord's
    `actor_id` will be `operator_id`, so the SoD verifier MUST use a
    different X-User-ID.
    """
    station, _supp, _invs = setup_station_with_inverters(inverter_count=1)
    zones = zone_route or ["Z1", "Z2"]
    ck = checklist or {"INVERTER": ["temp", "fan_noise"]}
    plan = create_patrol_plan(
        station["id"], zone_route=zones, kind="PERIODIC",
        cadence_days=7, checklist=ck,
    )
    record = schedule_patrol(plan["id"])
    operator_headers = make_field_operator_headers(operator_id)
    _ok(api_client.start_patrol(record["id"], operator_headers))
    findings = findings_per_zone or {"temp": "ok", "fan_noise": "ok"}
    for zone in zones:
        payload = log_zone_payload(checklist_findings=findings)
        _ok(api_client.log_patrol_zone(
            record["id"], zone, payload, operator_headers,
        ))
    submitted = _ok(api_client.submit_patrol(record["id"], operator_headers))
    return station, plan, submitted


# ---------------------------------------------------------------------------
# Tier 8 — performance-window targeting (difficulty design)
# ---------------------------------------------------------------------------
def setup_performance_window_with_alarm(
    minutes: int = 60,
    irradiance: float = 800.0,
    dc_power: float = 72.0,
    ac_power: float = 70.0,
    module_temp: float = 25.0,
    base_hour_start: str = "2026-01-01T00:00:00.000Z",
    installed_capacity_kw: float = 100.000,
    ac_capacity_kw: float = 100.000,
    alarm_severity: str = "MAJOR",
    alarm_first_seen_at: Optional[str] = None,
    alarm_clock_until_ack: Optional[str] = None,
    place_alarm: bool = True,
    alarm_bump_last_seen_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Setup for the expected/actual performance dual-variant test.

    Builds a station with one inverter, ingests `minutes` of RAW_1MIN
    readings at minute boundaries 00..(minutes-1), optionally registers
    an alarm code and ingests an alarm whose [first_seen_at, last_seen_at]
    window overlaps part of the data.

    Returns dict with: station, inverter, alarm (optional).
    """
    base_dt = datetime.fromisoformat(base_hour_start.replace("Z", "+00:00"))
    station, _supp, invs = setup_station_with_inverters(
        inverter_count=1,
        installed_capacity_kw=installed_capacity_kw,
        ac_capacity_kw=ac_capacity_kw,
    )
    inverter = invs[0]
    # Advance clock to the start of the readings window so ingestion
    # is past-of-clock — the readings themselves carry their own ts.
    advance_clock_to(base_hour_start)
    for m in range(minutes):
        ts_dt = base_dt + timedelta(minutes=m)
        payload = create_reading_payload(
            timestamp=iso_utc(ts_dt),
            dc_power_kw=dc_power,
            ac_power_kw=ac_power,
            irradiance_w_m2=irradiance,
            module_temp_c=module_temp,
        )
        _ok(api_client.create_reading(station["id"], payload, _admin()))
    alarm_payload = None
    if place_alarm:
        register_alarm_code_map(
            severity=alarm_severity, canonical_code="INV_OVERTEMP",
        )
        first_seen = alarm_first_seen_at or iso_utc(
            base_dt + timedelta(minutes=15),
        )
        ingested = ingest_alarm(
            inverter_id=inverter["id"],
            first_seen_at=first_seen,
        )
        # Optionally bump last_seen_at via chained dedup re-ingests
        # BEFORE the ack. PRD §3.3 only merges into an OPEN row, and
        # only when the new first_seen_at is within five minutes of
        # the existing last_seen_at. We therefore walk forward in
        # ≤5-minute hops until last_seen_at reaches the target.
        if alarm_bump_last_seen_to:
            target_dt = datetime.fromisoformat(
                alarm_bump_last_seen_to.replace("Z", "+00:00"),
            )
            current = datetime.fromisoformat(
                first_seen.replace("Z", "+00:00"),
            )
            while current < target_dt:
                step = min(timedelta(minutes=5), target_dt - current)
                current = current + step
                ingested = _ok(api_client.create_alarm(
                    create_alarm_payload(
                        inverter_id=inverter["id"],
                        first_seen_at=iso_utc(current),
                    ),
                    _admin(),
                ))
        # Acknowledge so its state is ACKNOWLEDGED (still inside the
        # "OPEN or ACKNOWLEDGED" filter PRD §3.2 requires for downtime).
        if alarm_clock_until_ack:
            advance_clock_to(alarm_clock_until_ack)
        alarm_payload = _ok(api_client.ack_alarm(ingested["id"], _om()))
    return {
        "station": station,
        "inverter": inverter,
        "alarm": alarm_payload,
    }


def ingest_readings_for_window(
    station_id: str,
    base_start: str,
    minutes: int,
    irradiance: float = 800.0,
    dc_power: float = 72.0,
    ac_power: float = 70.0,
    module_temp: float = 25.0,
) -> None:
    base_dt = datetime.fromisoformat(base_start.replace("Z", "+00:00"))
    for m in range(minutes):
        ts_dt = base_dt + timedelta(minutes=m)
        payload = create_reading_payload(
            timestamp=iso_utc(ts_dt),
            dc_power_kw=dc_power,
            ac_power_kw=ac_power,
            irradiance_w_m2=irradiance,
            module_temp_c=module_temp,
        )
        _ok(api_client.create_reading(station_id, payload, _admin()))


__all__ = [
    "advance_clock_to",
    "run_sweep",
    "create_station",
    "create_supplier",
    "blacklist_supplier",
    "create_inverter",
    "create_transformer",
    "create_array",
    "create_pvstring",
    "create_module",
    "create_spare_part",
    "setup_station_with_inverters",
    "register_alarm_code_map",
    "ingest_alarm",
    "setup_acknowledged_alarm",
    "create_manual_defect",
    "dispatch_work_order",
    "start_work_order",
    "complete_work_order",
    "cancel_work_order",
    "walk_defect_through_close",
    "create_settlement_period",
    "add_metering_record",
    "create_investor_share",
    "setup_confirmed_settlement",
    "create_subsidy_policy",
    "create_subsidy_declaration",
    "create_patrol_plan",
    "schedule_patrol",
    "setup_submitted_patrol",
    "setup_performance_window_with_alarm",
    "ingest_readings_for_window",
]
