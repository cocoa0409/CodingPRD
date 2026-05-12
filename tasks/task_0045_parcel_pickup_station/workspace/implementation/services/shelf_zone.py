"""ShelfZone service."""
from db import store, GLOBAL_LOCK
from errors import E, raise_error
from services.common import stamp_create, bump


def create_zone(station_id, body):
    from services.station import get_station
    get_station(station_id, allow_not_found=False)
    zone_code = body.get("zone_code")
    row_count = body.get("row_count")
    column_count = body.get("column_count")
    zone_type = body.get("zone_type") or "STANDARD"

    if not isinstance(zone_code, str) or not (1 <= len(zone_code) <= 16):
        raise_error(E.VALIDATION, "zone_code 1..16 chars")
    if not isinstance(row_count, int) or row_count < 1:
        raise_error(E.VALIDATION, "row_count >= 1")
    if not isinstance(column_count, int) or column_count < 1:
        raise_error(E.VALIDATION, "column_count >= 1")
    if zone_type not in ("STANDARD", "OVERSIZED", "FRAGILE", "COLD"):
        raise_error(E.VALIDATION, "zone_type invalid")

    with GLOBAL_LOCK:
        # zone_code unique per station
        for z in store.shelf_zones.values():
            if z["station_id"] == station_id and z["zone_code"] == zone_code:
                raise_error(E.VALIDATION, "zone_code already exists for this station")

        row = stamp_create({
            "station_id": station_id,
            "zone_code": zone_code,
            "row_count": row_count,
            "column_count": column_count,
            "zone_type": zone_type,
            "capacity": row_count * column_count,
            "occupied_slots": 0,
        })
        store.shelf_zones[row["id"]] = row
        return row


def get_zone(zone_id, allow_not_found=False):
    z = store.shelf_zones.get(zone_id)
    if z is None and not allow_not_found:
        raise_error(E.RESOURCE_NOT_FOUND, "Shelf zone not found")
    return z


def list_zones_for_station(station_id):
    return [z for z in store.shelf_zones.values() if z["station_id"] == station_id]
