"""Plant.available_count recomputation & stock unit lookups."""
from db import DB


def recompute_available_count(plant_id: str) -> None:
    plant = DB.plants.get(plant_id)
    if plant is None:
        return
    count = 0
    for su in DB.stock_units.values():
        if su["plant_id"] != plant_id:
            continue
        if su["sale_status"] == "FOR_SALE" and su["health_status"] in ("HEALTHY", "RECOVERING"):
            count += 1
    plant["available_count"] = count


def select_stock_unit_for_line(plant_id: str, exclude_ids: set = None):
    """Select a FOR_SALE, HEALTHY unit under plant_id ordered by oldest
    acquisition_date ASC then oldest created_at ASC."""
    if exclude_ids is None:
        exclude_ids = set()
    candidates = [
        su for su in DB.stock_units.values()
        if su["plant_id"] == plant_id
        and su["sale_status"] == "FOR_SALE"
        and su["health_status"] == "HEALTHY"
        and su["id"] not in exclude_ids
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda su: (su["acquisition_date"], su["created_at"]))
    return candidates[0]
