"""Audit-event and revenue listing/aggregation services."""
from __future__ import annotations

from typing import Any, Optional

from ..calculations import revenue_aggregate_split
from ..clock import parse_iso
from ..errors import ApiError
from ..store import get_store
from .cabinets import get_cabinet_or_404
from .serializers import serialize_audit_event, serialize_revenue_record


def _parse_optional_iso(value: Optional[str], field: str):
    if value is None:
        return None
    try:
        return parse_iso(value)
    except ValueError:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid {field}: {value!r}")


def list_revenue_records(
    cabinet_id: Optional[str],
    revenue_kind: Optional[str],
    occurred_at_from: Optional[str],
    occurred_at_to: Optional[str],
) -> list[dict[str, Any]]:
    store = get_store()
    items = list(store.revenue_records.values())
    if cabinet_id:
        items = [r for r in items if r["cabinet_id"] == cabinet_id]
    if revenue_kind:
        items = [r for r in items if r["revenue_kind"] == revenue_kind]
    from_dt = _parse_optional_iso(occurred_at_from, "occurred_at_from")
    to_dt = _parse_optional_iso(occurred_at_to, "occurred_at_to")
    if from_dt is not None:
        items = [r for r in items if parse_iso(r["occurred_at"]) >= from_dt]
    if to_dt is not None:
        items = [r for r in items if parse_iso(r["occurred_at"]) <= to_dt]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return [serialize_revenue_record(r) for r in items]


def cabinet_revenue_summary(
    cabinet_id: str,
    occurred_at_from: Optional[str],
    occurred_at_to: Optional[str],
) -> dict[str, Any]:
    cabinet = get_cabinet_or_404(cabinet_id)
    store = get_store()

    from_dt = _parse_optional_iso(occurred_at_from, "occurred_at_from")
    to_dt = _parse_optional_iso(occurred_at_to, "occurred_at_to")

    total_gross = 0
    for rec in store.revenue_records.values():
        if rec["cabinet_id"] != cabinet_id:
            continue
        occ = parse_iso(rec["occurred_at"])
        if from_dt is not None and occ < from_dt:
            continue
        if to_dt is not None and occ > to_dt:
            continue
        total_gross += int(rec["gross_cents"])

    partner, platform = revenue_aggregate_split(total_gross, int(cabinet["partner_share_pct"]))
    return {
        "cabinet_id": cabinet_id,
        "total_gross_cents": total_gross,
        "total_partner_cents": partner,
        "total_platform_cents": platform,
    }


def list_audit_events(
    event_kind: Optional[str],
    subject_id: Optional[str],
    subject_type: Optional[str],
    actor_id: Optional[str],
    occurred_at_from: Optional[str],
    occurred_at_to: Optional[str],
) -> list[dict[str, Any]]:
    store = get_store()
    items = list(store.audit_events.values())
    if event_kind:
        items = [e for e in items if e["event_kind"] == event_kind]
    if subject_id:
        items = [e for e in items if e["subject_id"] == subject_id]
    if subject_type:
        items = [e for e in items if e["subject_type"] == subject_type]
    if actor_id:
        items = [e for e in items if e["actor_id"] == actor_id]
    from_dt = _parse_optional_iso(occurred_at_from, "occurred_at_from")
    to_dt = _parse_optional_iso(occurred_at_to, "occurred_at_to")
    if from_dt is not None:
        items = [e for e in items if parse_iso(e["occurred_at"]) >= from_dt]
    if to_dt is not None:
        items = [e for e in items if parse_iso(e["occurred_at"]) <= to_dt]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    return [serialize_audit_event(e) for e in items]
