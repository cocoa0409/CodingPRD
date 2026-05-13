"""sla_breached computation for WorkOrder reads (PRD §3.6)."""
from __future__ import annotations

from typing import Any, Dict

from db import regions


def sla_breached(wo: Dict[str, Any]) -> bool:
    status = wo.get("status")
    if status == "CANCELLED":
        return False
    if status == "RESOLVED":
        delta = int(wo.get("resolved_minute", 0)) - int(wo.get("opened_minute", 0))
        return delta > int(wo.get("sla_minutes", 0))
    # OPEN / ASSIGNED
    region_id = wo.get("region_id")
    if region_id and region_id in regions:
        current = int(regions[region_id].get("clock_minutes", 0))
    else:
        current = 0
    delta = current - int(wo.get("opened_minute", 0))
    return delta > int(wo.get("sla_minutes", 0))


def serialize_workorder(wo: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(wo)
    out["sla_breached"] = sla_breached(wo)
    return out
