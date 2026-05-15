"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body. Only PRD-declared input fields are produced; computed
fields are intentionally omitted so the implementation cannot
accidentally accept them.

PRD §2.4 timestamps are ISO 8601 UTC with three fractional digits
(e.g. "2025-05-24T10:30:00.123Z"). PRD §2.8 monetary fields are integer
cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


# ---------------------------------------------------------------------------
# Random suffix for uniqueness (exhibition names, hall codes, booth
# codes, etc.).
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_exhibitor_id() -> str:
    return f"exhibitor-{random_suffix(8).lower()}"


def random_group_id(prefix: str = "G") -> str:
    return f"{prefix}-{random_suffix(6)}"


# ===========================================================================
# Clock advance (PRD §4)
# ===========================================================================
def clock_advance_payload(*, to: str) -> Dict[str, Any]:
    """Build a POST /_clock/advance payload.

    PRD §4 declares `to` as an ISO 8601 timestamp to which the logical
    clock is advanced.
    """
    return {"to": to}


# ===========================================================================
# Exhibition (PRD §3.1)
# ===========================================================================
def create_exhibition_payload(
    *,
    name: Optional[str] = None,
    theme_code: str = "GEN",
    open_date: Optional[str] = None,
    close_date: Optional[str] = None,
    capacity_max: int = 100,
    objection_window_hours: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /exhibitions payload.

    PRD §3.1 input fields: name, theme_code, open_date, close_date,
    capacity_max, objection_window_hours (optional, default 72 per
    PRD §3.1).
    """
    if open_date is None:
        open_date = iso_offset(days=30)
    if close_date is None:
        close_date = iso_offset(days=37)
    if name is None:
        name = f"Exhibition {random_suffix(4)}"
    payload: Dict[str, Any] = {
        "name": name,
        "theme_code": theme_code,
        "open_date": open_date,
        "close_date": close_date,
        "capacity_max": capacity_max,
    }
    if objection_window_hours is not None:
        payload["objection_window_hours"] = objection_window_hours
    payload.update(overrides)
    return payload


# ===========================================================================
# Hall (PRD §3.2)
# ===========================================================================
def create_hall_payload(
    *,
    hall_code: Optional[str] = None,
    zone_label: str = "Z1",
    aisle_label: str = "A1",
    grid_rows: int = 5,
    grid_cols: int = 5,
    fire_safety_zone_cells: Optional[List[Dict[str, int]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /exhibitions/{id}/halls payload.

    PRD §3.2 input fields: hall_code (unique within the exhibition),
    zone_label, aisle_label, grid_rows, grid_cols, fire_safety_zone_cells
    (array of {row, col}).
    """
    if hall_code is None:
        hall_code = f"H{random_suffix(3)}"
    if fire_safety_zone_cells is None:
        fire_safety_zone_cells = []
    payload: Dict[str, Any] = {
        "hall_code": hall_code,
        "zone_label": zone_label,
        "aisle_label": aisle_label,
        "grid_rows": grid_rows,
        "grid_cols": grid_cols,
        "fire_safety_zone_cells": fire_safety_zone_cells,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# FloorPlanVersion (PRD §3.2)
# ===========================================================================
def make_full_modular_cells(
    grid_rows: int,
    grid_cols: int,
    *,
    fire_safety_cells: Optional[List[Dict[str, int]]] = None,
    power_kw: float = 2.0,
    water_lpm: float = 10.0,
    network_mbps: int = 100,
    default_kind: str = "MODULAR",
) -> List[Dict[str, Any]]:
    """Build a cells array covering grid_rows x grid_cols.

    PRD §3.2: every cell in the active plan is a
    {row, col, kind, power_kw, water_lpm, network_mbps} descriptor.

    fire_safety_cells (a list of {row, col}) marks those positions as
    kind=FIRE_SAFETY; every other position uses default_kind.
    """
    fs = {(c["row"], c["col"]) for c in (fire_safety_cells or [])}
    cells: List[Dict[str, Any]] = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            kind = "FIRE_SAFETY" if (r, c) in fs else default_kind
            cells.append({
                "row": r,
                "col": c,
                "kind": kind,
                "power_kw": power_kw,
                "water_lpm": water_lpm,
                "network_mbps": network_mbps,
            })
    return cells


def create_floor_plan_payload(
    *,
    cells: Optional[List[Dict[str, Any]]] = None,
    grid_rows: int = 5,
    grid_cols: int = 5,
    fire_safety_cells: Optional[List[Dict[str, int]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /halls/{hall_id}/floor-plans payload.

    PRD §3.2 input fields: cells (array of {row, col, kind, power_kw,
    water_lpm, network_mbps}).
    """
    if cells is None:
        cells = make_full_modular_cells(
            grid_rows, grid_cols, fire_safety_cells=fire_safety_cells,
        )
    payload: Dict[str, Any] = {"cells": cells}
    payload.update(overrides)
    return payload


# ===========================================================================
# Booth (PRD §3.2)
# ===========================================================================
def create_booth_payload(
    *,
    code: Optional[str] = None,
    cells: Optional[List[Dict[str, int]]] = None,
    tier: str = "STANDARD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /halls/{hall_id}/booths payload.

    PRD §3.2 input fields: code (unique within the hall), cells (array
    of {row, col} occupied; at least one), tier in {STANDARD, PREMIUM,
    ISLAND}.
    """
    if code is None:
        code = f"B-{random_suffix(4)}"
    if cells is None:
        cells = [{"row": 0, "col": 0}]
    payload: Dict[str, Any] = {
        "code": code,
        "cells": cells,
        "tier": tier,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# ExhibitorApplication (PRD §3.3)
# ===========================================================================
def create_application_payload(
    *,
    theme_tags: Optional[List[str]] = None,
    requested_tier: str = "STANDARD",
    sponsorship_level: Optional[str] = None,
    seniority_years: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /exhibitions/{id}/applications payload.

    PRD §3.3 input fields: theme_tags, requested_tier, sponsorship_level
    (optional, default NONE), seniority_years (optional, default 0).
    """
    if theme_tags is None:
        theme_tags = ["GEN"]
    payload: Dict[str, Any] = {
        "theme_tags": theme_tags,
        "requested_tier": requested_tier,
    }
    if sponsorship_level is not None:
        payload["sponsorship_level"] = sponsorship_level
    if seniority_years is not None:
        payload["seniority_years"] = seniority_years
    payload.update(overrides)
    return payload


def reject_application_payload(*, rejection_reason: str = "Out of scope",
                               **overrides: Any) -> Dict[str, Any]:
    """Build a POST /applications/{id}/reject payload. PRD §3.3
    requires a non-empty rejection_reason.
    """
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ===========================================================================
# BoothAllocation (PRD §3.4)
# ===========================================================================
def create_allocation_payload(
    *,
    application_id: str,
    booth_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /allocations payload. PRD §3.4: input fields are
    application_id and booth_id.
    """
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "booth_id": booth_id,
    }
    payload.update(overrides)
    return payload


def object_allocation_payload(*, reason: str = "Booth not satisfactory",
                              **overrides: Any) -> Dict[str, Any]:
    """Build a POST /allocations/{id}/object payload. PRD §3.4: the
    request body carries a reason string.
    """
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def relocate_payload(*, target_booth_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    """Build a POST /allocations/{id}/relocate payload. PRD §3.4: the
    admin supplies a target_booth_id.
    """
    payload: Dict[str, Any] = {"target_booth_id": target_booth_id}
    payload.update(overrides)
    return payload


def revoke_allocation_payload(*, reason: str = "Withdrawing offer",
                              **overrides: Any) -> Dict[str, Any]:
    """Build a POST /allocations/{id}/revoke payload. PRD §3.4: the
    admin supplies a reason string.
    """
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ===========================================================================
# DockSlot (PRD §3.5)
# ===========================================================================
def create_dock_slot_payload(
    *,
    dock_code: str = "D1",
    window_kind: str = "MOVE_IN",
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    allocation_id: str,
    crane_required: Optional[bool] = None,
    forklift_required: Optional[bool] = None,
    overnight_permit: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /exhibitions/{id}/dock-slots payload.

    PRD §3.5 input fields: dock_code, window_kind (MOVE_IN | MOVE_OUT),
    start_at, end_at, allocation_id, crane_required (optional,
    default false), forklift_required (optional, default false),
    overnight_permit (optional, default false).
    """
    if start_at is None:
        start_at = iso_offset(hours=1)
    if end_at is None:
        end_at = iso_offset(hours=2)
    payload: Dict[str, Any] = {
        "dock_code": dock_code,
        "window_kind": window_kind,
        "start_at": start_at,
        "end_at": end_at,
        "allocation_id": allocation_id,
    }
    if crane_required is not None:
        payload["crane_required"] = crane_required
    if forklift_required is not None:
        payload["forklift_required"] = forklift_required
    if overnight_permit is not None:
        payload["overnight_permit"] = overnight_permit
    payload.update(overrides)
    return payload


# ===========================================================================
# SafetyInspection (PRD §3.5)
# ===========================================================================
def create_safety_inspection_payload(
    *,
    kind: str = "PRE_OPEN",
    result: str = "PASS",
    inspector_id: str = "inspector-001",
    dock_slot_id: Optional[str] = None,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /exhibitions/{id}/safety-inspections payload.

    PRD §3.5 input fields: kind, result, inspector_id, dock_slot_id
    (required when kind==BOOTH_MOVE_IN, null otherwise), notes
    (optional, free text).
    """
    payload: Dict[str, Any] = {
        "kind": kind,
        "result": result,
        "inspector_id": inspector_id,
    }
    if dock_slot_id is not None:
        payload["dock_slot_id"] = dock_slot_id
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ===========================================================================
# WorkOrder (PRD §3.6)
# ===========================================================================
def work_order_line(
    *,
    service_code: str = "FURNITURE",
    quantity: int = 1,
    unit_price_cents: int = 10000,
) -> Dict[str, Any]:
    """Build one WorkOrder.line. PRD §3.6: service_code in
    {EXTRA_POWER, FURNITURE, NETWORK, CLEANING, SECURITY}, quantity
    integer > 0, unit_price_cents integer > 0.
    """
    return {
        "service_code": service_code,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
    }


def create_work_order_payload(
    *,
    exhibition_id: str,
    allocation_id: str,
    lines: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /work-orders payload.

    PRD §3.6 input fields: exhibition_id, allocation_id, lines.
    """
    if lines is None:
        lines = [work_order_line()]
    payload: Dict[str, Any] = {
        "exhibition_id": exhibition_id,
        "allocation_id": allocation_id,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def dispute_work_order_payload(
    *,
    dispute_reason: str = "Service unsatisfactory",
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /work-orders/{id}/dispute payload. PRD §3.6: the
    exhibitor supplies a non-empty dispute_reason.
    """
    payload: Dict[str, Any] = {"dispute_reason": dispute_reason}
    payload.update(overrides)
    return payload


def resolve_work_order_payload(
    *,
    resolved_total_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /work-orders/{id}/resolve payload. PRD §3.6: ops
    supplies a resolved_total_cents in [0, total_cents].
    """
    payload: Dict[str, Any] = {
        "resolved_total_cents": resolved_total_cents,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Ticket (PRD §3.7)
# ===========================================================================
def create_ticket_payload(
    *,
    kind: str = "VISITOR",
    channel: str = "ONLINE_PRESALE",
    group_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /exhibitions/{id}/tickets payload.

    PRD §3.7 input fields: kind, channel, group_id (optional).
    """
    payload: Dict[str, Any] = {
        "kind": kind,
        "channel": channel,
    }
    if group_id is not None:
        payload["group_id"] = group_id
    payload.update(overrides)
    return payload


# ===========================================================================
# SponsorEntitlement (PRD §3.8)
# ===========================================================================
def create_entitlement_payload(
    *,
    exhibitor_id: str,
    entitlement_code: str = "SIGNAGE",
    sponsor_tier: str = "GOLD",
    deadline: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /exhibitions/{id}/entitlements payload.

    PRD §3.8 input fields: exhibitor_id, entitlement_code, sponsor_tier,
    deadline (ISO 8601 timestamp).
    """
    if deadline is None:
        deadline = iso_offset(days=10)
    payload: Dict[str, Any] = {
        "exhibitor_id": exhibitor_id,
        "entitlement_code": entitlement_code,
        "sponsor_tier": sponsor_tier,
        "deadline": deadline,
    }
    payload.update(overrides)
    return payload


def fulfill_entitlement_payload(
    *,
    evidence_url: str = "https://example.com/evidence/photo.jpg",
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /entitlements/{id}/fulfill payload. PRD §3.8: the
    request body carries a non-empty evidence_url.
    """
    payload: Dict[str, Any] = {"evidence_url": evidence_url}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "random_suffix",
    "random_exhibitor_id",
    "random_group_id",
    "clock_advance_payload",
    "create_exhibition_payload",
    "create_hall_payload",
    "make_full_modular_cells",
    "create_floor_plan_payload",
    "create_booth_payload",
    "create_application_payload",
    "reject_application_payload",
    "create_allocation_payload",
    "object_allocation_payload",
    "relocate_payload",
    "revoke_allocation_payload",
    "create_dock_slot_payload",
    "create_safety_inspection_payload",
    "work_order_line",
    "create_work_order_payload",
    "dispute_work_order_payload",
    "resolve_work_order_payload",
    "create_ticket_payload",
    "create_entitlement_payload",
    "fulfill_entitlement_payload",
]
