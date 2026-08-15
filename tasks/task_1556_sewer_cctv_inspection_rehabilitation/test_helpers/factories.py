"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_district_payload(name=None, ii_reduction_target_pct=25, budget_cents=1_000_000,
                            notice_lead_hours=None, warranty_months=None) -> dict:
    """notice_lead_hours / warranty_months are optional policy knobs (PRD §3.1):
    included only when explicitly supplied so default-application tests can omit them."""
    payload = {
        "name": name or _uniq("District"),
        "ii_reduction_target_pct": ii_reduction_target_pct,
        "budget_cents": budget_cents,
    }
    if notice_lead_hours is not None:
        payload["notice_lead_hours"] = notice_lead_hours
    if warranty_months is not None:
        payload["warranty_months"] = warranty_months
    return payload


def create_technician_payload(full_name=None, nassco_cert_number=None,
                              nassco_cert_expires_at="2027-01-01T00:00:00Z",
                              capabilities=None, active=None) -> dict:
    payload = {
        "full_name": full_name or _uniq("Tech"),
        "nassco_cert_number": nassco_cert_number or _uniq("PACP"),
        "nassco_cert_expires_at": nassco_cert_expires_at,
        "capabilities": list(capabilities) if capabilities else ["CODER"],
    }
    if active is not None:
        payload["active"] = active
    return payload


def create_cycle_payload(label=None, window_start="2026-08-01T00:00:00Z",
                         window_end="2026-09-01T00:00:00Z") -> dict:
    return {
        "label": label or _uniq("CY"),
        "window_start": window_start,
        "window_end": window_end,
    }


def create_segment_payload(segment_ref=None, diameter_mm=200, material="VCP",
                           length_m=100, install_year=1980) -> dict:
    return {
        "segment_ref": segment_ref or f"{_uniq('MH-A')}-> {_uniq('MH-B')}".replace(" ", ""),
        "diameter_mm": diameter_mm,
        "material": material,
        "length_m": length_m,
        "install_year": install_year,
    }


def create_lateral_payload(address=None, connection_type="WYE", active=None) -> dict:
    payload = {
        "address": address or f"{uuid.uuid4().int % 9000 + 1000} Test St",
        "connection_type": connection_type,
    }
    if active is not None:
        payload["active"] = active
    return payload


def create_inspection_payload(cycle_id, coder_id, scheduled_at="2026-08-10T06:00:00Z",
                              purpose="BASELINE") -> dict:
    return {
        "cycle_id": cycle_id,
        "scheduled_at": scheduled_at,
        "coder_id": coder_id,
        "purpose": purpose,
    }


def create_defect_payload(pacp_code="CRK", family="STRUCTURAL", grade=3,
                          distance_m=10, clock_position=6, extent_m=None) -> dict:
    """extent_m is optional (PRD §3.3: defaults to 0 for point defects);
    included only when explicitly supplied."""
    payload = {
        "pacp_code": pacp_code,
        "family": family,
        "grade": grade,
        "distance_m": distance_m,
        "clock_position": clock_position,
    }
    if extent_m is not None:
        payload["extent_m"] = extent_m
    return payload


def create_plan_payload(method="SPOT_REPAIR", basis_inspection_id=None) -> dict:
    return {"method": method, "basis_inspection_id": basis_inspection_id}


def create_work_order_payload(crew_lead_id) -> dict:
    return {"crew_lead_id": crew_lead_id}


def create_line_item_payload(pay_item_code="SPOT-EA", scheduled_qty=1,
                             unit_price_cents=250000, expected_work_order_version=None) -> dict:
    return {
        "pay_item_code": pay_item_code,
        "scheduled_qty": scheduled_qty,
        "unit_price_cents": unit_price_cents,
        "expected_work_order_version": expected_work_order_version,
    }


def create_bypass_payload(window_start="2026-08-12T08:00:00Z",
                          window_end="2026-08-12T18:00:00Z",
                          pump_capacity_gpm=300) -> dict:
    return {
        "window_start": window_start,
        "window_end": window_end,
        "pump_capacity_gpm": pump_capacity_gpm,
    }


def create_notice_payload(address, channel="EMAIL", event_start="2026-08-14T00:00:00Z") -> dict:
    return {"address": address, "channel": channel, "event_start": event_start}


def create_warranty_case_payload(work_order_id, cycle_id, coder_id,
                                 defect_summary="post-rehabilitation defect",
                                 scheduled_at="2026-09-02T08:00:00Z") -> dict:
    return {
        "work_order_id": work_order_id,
        "defect_summary": defect_summary,
        "cycle_id": cycle_id,
        "scheduled_at": scheduled_at,
        "coder_id": coder_id,
    }


def create_flow_period_payload(basin_label="B1", phase="PRE_REHAB",
                               window_start="2026-03-01T00:00:00Z",
                               window_end="2026-03-15T00:00:00Z") -> dict:
    return {
        "basin_label": basin_label,
        "phase": phase,
        "window_start": window_start,
        "window_end": window_end,
    }
