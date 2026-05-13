"""Region maintenance: deployed_count, available_count, density_posture."""
from __future__ import annotations

from typing import Dict, Any

from db import bikes, regions


def recompute_region_counts(region_id: str) -> None:
    """Reconcile a single region's derived counts and posture (PRD §2.7)."""
    if region_id is None or region_id not in regions:
        return
    region = regions[region_id]
    deployed = 0
    available = 0
    for bike in bikes.values():
        if bike.get("region_id") != region_id:
            continue
        if bike.get("shelf_state") == "ON_SHELF":
            deployed += 1
            if bike.get("status") == "AVAILABLE":
                available += 1
    region["deployed_count"] = deployed
    region["available_count"] = available
    region["density_posture"] = _compute_posture(
        available,
        region["low_density_threshold"],
        region["high_density_threshold"],
    )


def _compute_posture(available: int, low_thr: int, high_thr: int) -> str:
    """PRD §2.7: inclusive boundaries on both ends."""
    if available <= low_thr:
        return "LOW"
    if available >= high_thr:
        return "HIGH"
    return "NORMAL"


def serialize_region(region: Dict[str, Any]) -> Dict[str, Any]:
    return dict(region)
