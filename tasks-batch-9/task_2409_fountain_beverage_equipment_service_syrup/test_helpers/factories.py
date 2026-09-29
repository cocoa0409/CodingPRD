"""Payload factories — one per write endpoint, carrying only client-supplied fields."""

import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so codes that the PRD requires to be unique stay unique."""
    return f"{next(_counter):05d}"


# ─── Clock ────────────────────────────────────────────────────────────────


def set_clock_payload(to_iso8601: str = "2026-08-01T00:00:00Z", **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ─── Outlet ───────────────────────────────────────────────────────────────


def create_outlet_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "name": f"Fountain Outlet {suffix}",
        "account_code": f"ACCT-{suffix}",
        "region_code": "R-WEST",
    }
    payload.update(overrides)
    return payload


def outlet_status_change_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def compliance_hold_payload(action: str, hold_reason_code: str = "HEALTH_INSPECTION",
                            **overrides) -> dict:
    payload = {"action": action, "hold_reason_code": hold_reason_code}
    payload.update(overrides)
    return payload


# ─── PlacementAgreement ───────────────────────────────────────────────────


def create_agreement_payload(outlet_id: str, expected_outlet_version: int,
                             **overrides) -> dict:
    payload = {
        "outlet_id": outlet_id,
        "term_start_date": "2026-01-01T00:00:00Z",
        "term_end_date": "2027-01-01T00:00:00Z",
        "annual_commitment_gallons": 4000,
        "equipment_value_cents": 300000,
        "expected_outlet_version": expected_outlet_version,
    }
    payload.update(overrides)
    return payload


def assess_shortfall_payload(period_start_date: str = "2026-01-01T00:00:00Z",
                             period_end_date: str = "2026-10-01T00:00:00Z",
                             **overrides) -> dict:
    payload = {
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload


def recall_decision_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ─── DispenserUnit ────────────────────────────────────────────────────────


def create_dispenser_unit_payload(outlet_id: str, agreement_id: str, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "outlet_id": outlet_id,
        "agreement_id": agreement_id,
        "serial_number": f"SN-{suffix}",
        "model_code": "FREESTYLE_9100",
        "installed_at": "2026-02-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def service_hold_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ─── SupplyItem ───────────────────────────────────────────────────────────


def create_supply_item_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "sku_code": f"SKU-{suffix}",
        "brand_name": "Coca-Cola",
        "supply_form": "CARTRIDGE",
        "case_pack_units": 4,
        "ounces_per_unit": 350,
    }
    payload.update(overrides)
    return payload


def patch_supply_item_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


# ─── TelemetryReading ─────────────────────────────────────────────────────


def create_telemetry_payload(dispenser_unit_id: str, supply_item_id: str,
                             dispensed_ounces: float,
                             reading_at: str = "2026-07-31T00:00:00Z",
                             **overrides) -> dict:
    payload = {
        "dispenser_unit_id": dispenser_unit_id,
        "supply_item_id": supply_item_id,
        "dispensed_ounces": dispensed_ounces,
        "reading_at": reading_at,
    }
    payload.update(overrides)
    return payload


# ─── OutletSupplyPosition ─────────────────────────────────────────────────


def create_supply_position_payload(outlet_id: str, supply_item_id: str, **overrides) -> dict:
    payload = {"outlet_id": outlet_id, "supply_item_id": supply_item_id}
    payload.update(overrides)
    return payload


def forecast_payload(variant: str = "TRAILING_ACTUAL", window_days: int = 7,
                     **overrides) -> dict:
    payload = {"variant": variant, "window_days": window_days}
    payload.update(overrides)
    return payload


# ─── ReplenishmentRoute / RouteStop ───────────────────────────────────────


def create_route_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "route_code": f"RT-{suffix}",
        "depot_region_code": "R-WEST",
        "service_date": "2026-08-02T00:00:00Z",
        "van_code": f"V-{suffix}",
        "capacity_units": 500,
    }
    payload.update(overrides)
    return payload


def create_route_stop_payload(outlet_id: str, expected_route_version: int,
                              sequence_index: int = 1,
                              window_start: str = "2026-08-02T08:00:00Z",
                              window_end: str = "2026-08-02T10:00:00Z",
                              **overrides) -> dict:
    payload = {
        "outlet_id": outlet_id,
        "sequence_index": sequence_index,
        "window_start": window_start,
        "window_end": window_end,
        "expected_route_version": expected_route_version,
    }
    payload.update(overrides)
    return payload


def dispatch_route_payload(expected_route_version: int, **overrides) -> dict:
    payload = {"expected_route_version": expected_route_version}
    payload.update(overrides)
    return payload


def cancel_route_payload(expected_route_version: int, **overrides) -> dict:
    payload = {"expected_route_version": expected_route_version}
    payload.update(overrides)
    return payload


def allocation_payload(supply_position_ids: list, **overrides) -> dict:
    payload = {"supply_position_ids": list(supply_position_ids)}
    payload.update(overrides)
    return payload


def skip_stop_payload(skip_reason_code: str = "ACCESS_DENIED", **overrides) -> dict:
    payload = {"skip_reason_code": skip_reason_code}
    payload.update(overrides)
    return payload


# ─── MaintenanceTask ──────────────────────────────────────────────────────


def create_maintenance_task_payload(dispenser_unit_id: str,
                                    task_type: str = "PREVENTIVE",
                                    due_at: str = "2026-08-10T00:00:00Z",
                                    **overrides) -> dict:
    payload = {
        "dispenser_unit_id": dispenser_unit_id,
        "task_type": task_type,
        "due_at": due_at,
    }
    payload.update(overrides)
    return payload


def complete_task_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def waive_task_payload(waiver_reason: str = "OPERATOR_REQUEST", **overrides) -> dict:
    payload = {"waiver_reason": waiver_reason}
    payload.update(overrides)
    return payload


# ─── ServiceCall ──────────────────────────────────────────────────────────


def create_service_call_payload(dispenser_unit_id: str,
                                symptom_code: str = "NO_POUR",
                                reported_at: str = "2026-08-01T00:00:00Z",
                                **overrides) -> dict:
    payload = {
        "dispenser_unit_id": dispenser_unit_id,
        "reported_at": reported_at,
        "symptom_code": symptom_code,
    }
    payload.update(overrides)
    return payload


def dispatch_call_payload(van_code: str,
                          scheduled_window_start: str = "2026-08-01T09:00:00Z",
                          scheduled_window_end: str = "2026-08-01T11:00:00Z",
                          **overrides) -> dict:
    payload = {
        "van_code": van_code,
        "scheduled_window_start": scheduled_window_start,
        "scheduled_window_end": scheduled_window_end,
    }
    payload.update(overrides)
    return payload


def resolve_call_payload(resolution_code: str = "NO_FAULT_FOUND", **overrides) -> dict:
    payload = {"resolution_code": resolution_code}
    payload.update(overrides)
    return payload


def escalate_call_payload(escalation_reason_code: str = "WRONG_PART", **overrides) -> dict:
    payload = {"escalation_reason_code": escalation_reason_code}
    payload.update(overrides)
    return payload


# ─── VanPartStock ─────────────────────────────────────────────────────────


def create_van_part_stock_payload(van_code: str, part_sku: str = "PUMP_ASSY_12",
                                  on_van_units: int = 5, **overrides) -> dict:
    payload = {
        "van_code": van_code,
        "part_sku": part_sku,
        "on_van_units": on_van_units,
    }
    payload.update(overrides)
    return payload


def restock_payload(units: int, **overrides) -> dict:
    payload = {"units": units}
    payload.update(overrides)
    return payload
