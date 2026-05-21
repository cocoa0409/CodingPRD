"""PaymentStandard configuration table."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app import clock, store
from app.errors import validation
from app.util import new_id, parse_iso, require_int, require_str


_VALID_ZONES = ("ZONE_A", "ZONE_B", "ZONE_C")


def create_payment_standard(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")
    try:
        zone = require_str(payload.get("zone"), field="zone", allowed=_VALID_ZONES)
        bedroom_size = require_int(payload.get("bedroom_size"), field="bedroom_size", min_value=0, max_value=5)
        standard = require_int(payload.get("standard_amount_cents"), field="standard_amount_cents", min_value=1)
        mobility = require_int(payload.get("mobility_amount_cents"), field="mobility_amount_cents", min_value=1)
        if mobility < standard:
            raise ValueError("mobility_amount_cents must be >= standard_amount_cents")
        effective_from = parse_iso(payload.get("effective_from"))
        if effective_from is None:
            raise ValueError("effective_from is required")
    except ValueError as exc:
        raise validation(str(exc))

    now = clock.now()
    ps_id = new_id()
    record = {
        "id": ps_id,
        "created_at": now,
        "zone": zone,
        "bedroom_size": bedroom_size,
        "standard_amount_cents": standard,
        "mobility_amount_cents": mobility,
        "effective_from": effective_from,
    }
    store.payment_standards[ps_id] = record
    return record


def list_payment_standards(*, zone: Optional[str], bedroom_size: Optional[int], active_only: bool):
    rows = []
    for ps in store.payment_standards.values():
        if zone and ps.get("zone") != zone:
            continue
        if bedroom_size is not None and ps.get("bedroom_size") != bedroom_size:
            continue
        rows.append(ps)

    if not active_only:
        return rows

    # For each (zone, bedroom_size) cell return only the row with latest effective_from <= now.
    now = clock.now()
    by_cell: dict = {}
    for ps in rows:
        if ps["effective_from"] > now:
            continue
        key = (ps["zone"], ps["bedroom_size"])
        current = by_cell.get(key)
        if current is None or ps["effective_from"] > current["effective_from"]:
            by_cell[key] = ps
    return list(by_cell.values())


def active_standard_for(*, zone: str, bedroom_size: int, asof: datetime) -> Optional[dict]:
    """Look up the active PaymentStandard row for a (zone, bedroom_size) cell."""
    best = None
    for ps in store.payment_standards.values():
        if ps["zone"] != zone or ps["bedroom_size"] != bedroom_size:
            continue
        if ps["effective_from"] > asof:
            continue
        if best is None or ps["effective_from"] > best["effective_from"]:
            best = ps
    return best
