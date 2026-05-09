"""Cabinet online_status and maintenance-window helpers."""
from clock import clock


HEARTBEAT_TIMEOUT_SECONDS = 300


def recompute_online_status(cabinet: dict) -> None:
    """Recompute cabinet.online_status from last_heartbeat_at and current logical clock."""
    last = cabinet.get("last_heartbeat_at")
    if last is None:
        cabinet["online_status"] = "OFFLINE"
        return
    delta = (clock.now() - last).total_seconds()
    cabinet["online_status"] = "ONLINE" if delta < HEARTBEAT_TIMEOUT_SECONDS else "OFFLINE"


def is_under_maintenance(cabinet_id: str) -> bool:
    from db import db
    now = clock.now()
    for w in db.maintenance_windows.values():
        if w["cabinet_id"] != cabinet_id:
            continue
        if w["status"] != "SCHEDULED":
            continue
        if w["window_start"] <= now < w["window_end"]:
            return True
    return False
