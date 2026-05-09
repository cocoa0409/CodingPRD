"""Test-driving admin endpoints: clock advance + stale-KR sweep."""

from flask import Blueprint

import db
from audit import write_audit
from auth import require_role
from clock import advance, now, parse_ts
from envelope import success_object
from errors import ApiError
from util import get_json_body, require_fields, stamp_update


bp = Blueprint("admin", __name__)


@bp.post("/_clock/advance")
def clock_advance():
    require_role("PlatformAdmin")
    body = get_json_body()
    require_fields(body, "seconds")
    try:
        sec = float(body["seconds"])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "seconds must be number")
    if sec < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "seconds must be >= 0")
    advance(sec)
    return success_object({"advanced_seconds": sec})


@bp.post("/_sweep/stale-kr-reminders")
def stale_kr_sweep():
    require_role("PlatformAdmin")
    cur = now()
    affected = []
    for kr in db.key_results.values():
        if kr["status"] != "ACTIVE":
            continue
        obj = db.objectives.get(kr["objective_id"])
        if not obj or obj["status"] != "ACTIVE":
            continue
        last = kr.get("last_update_at")
        if last:
            baseline = parse_ts(last)
        else:
            baseline = parse_ts(obj["created_at"])
        diff_days = int((cur - baseline).total_seconds() // 86400)
        if diff_days >= 14:
            obj["stale_warning_count"] = int(obj.get("stale_warning_count", 0)) + 1
            stamp_update(obj)
            write_audit(entity_type="OBJECTIVE", entity_id=obj["id"],
                        action="UPDATE",
                        before=None,
                        after={"stale_warning_count": obj["stale_warning_count"]},
                        actor_override="SYSTEM", role_override="SYSTEM")
            affected.append(obj["id"])
    return success_object({"affected_objective_ids": list(set(affected)),
                           "affected_count": len(set(affected))})
