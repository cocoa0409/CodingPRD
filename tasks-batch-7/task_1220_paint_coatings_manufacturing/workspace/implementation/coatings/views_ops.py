"""Operations endpoints: daily sweep and the logical clock."""
from flask import Blueprint

from .store import now, store
from .util import auth, body, fmt_ts, success, touch, v_str, parse_datetime_value

bp = Blueprint("ops", __name__)


@bp.post("/coatings/ops/run-daily-sweep")
def run_daily_sweep():
    auth(("PlantManager",))
    today = now().date()
    obsolete_ids = []
    purged_ids = []
    for c in store.containers.values():
        if c["status"] == "IN_STOCK" and c["expiry_date"] is not None and c["expiry_date"].date() <= today:
            c["status"] = "OBSOLETE"
            touch(c)
            obsolete_ids.append(c["id"])
    for m in store.color_matches.values():
        if (
            m["status"] == "APPROVED"
            and m["retain_until"] is not None
            and m["retain_purged_at"] is None
            and m["retain_until"].date() < today
        ):
            m["retain_purged_at"] = now()
            touch(m)
            purged_ids.append(m["retain_sample_id"])
    return success({"obsolete_container_ids": obsolete_ids, "purged_retain_sample_ids": purged_ids}, 200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(("PlantManager",))
    b = body()
    raw = v_str(b, "to_iso8601")
    store.clock = parse_datetime_value(raw, "to_iso8601")
    return success({"current_utc": fmt_ts(store.clock)}, 200)
