"""SeasonalEvent endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_enum,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.lookup import get_pool_or_404, get_seasonal_event_or_404

bp = Blueprint("seasonal_events", __name__)

EVENT_TYPES = {"OPEN", "CLOSE"}
_OPEN_WO_STATUSES = {"OPEN", "DIAGNOSED", "AWAITING_APPROVAL", "ON_HOLD"}


@bp.post("/pools/<pool_id>/seasonal-events")
@require_roles("RouteManager")
def create_seasonal_event(pool_id):
    with db.lock:
        get_pool_or_404(pool_id)
        body = require_json_object(request.get_json(silent=True))
        event_type = require_enum(body, "event_type", EVENT_TYPES)
        effective_date = require_str(body, "effective_date")
        rec = new_record(
            {
                "pool_id": pool_id,
                "event_type": event_type,
                "effective_date": effective_date,
                "status": "REQUESTED",
            }
        )
        db.seasonal_events[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/seasonal-events/<ev_id>")
@require_roles("RouteManager", "AccountManager")
def get_seasonal_event(ev_id):
    with db.lock:
        ev = get_seasonal_event_or_404(ev_id)
        return success(serialize(ev), 200)


@bp.get("/pools/<pool_id>/seasonal-events")
@require_roles("RouteManager", "AccountManager")
def list_pool_seasonal_events(pool_id):
    with db.lock:
        get_pool_or_404(pool_id)
        limit, offset = paginate(request.args)
        items = [e for e in db.seasonal_events.values() if e["pool_id"] == pool_id]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(e) for e in page], limit, offset, total)


@bp.post("/seasonal-events/<ev_id>/apply")
@require_roles("RouteManager")
def apply_seasonal_event(ev_id):
    with db.lock:
        ev = get_seasonal_event_or_404(ev_id)
        # State validity (priority 5).
        if ev["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Seasonal event cannot be applied from its current state")
        pool = db.pools.get(ev["pool_id"])
        if ev["event_type"] == "OPEN":
            # Pool transition CLOSED/WINTERIZED -> OPEN must be defined (priority 5).
            if pool["service_status"] not in ("CLOSED", "WINTERIZED"):
                raise err("ERR_INVALID_STATE", "Pool cannot be opened from its current state")
            # CRITICAL repair blocks open (priority 9).
            has_critical = any(
                wo["pool_id"] == pool["id"]
                and wo["severity"] == "CRITICAL"
                and wo["status"] in _OPEN_WO_STATUSES
                for wo in db.work_orders.values()
            )
            if has_critical:
                raise err(
                    "ERR_CRITICAL_REPAIR_BLOCKS_OPEN",
                    "An unresolved CRITICAL work order blocks opening",
                )
            pool["service_status"] = "OPEN"
            touch(pool)
        else:  # CLOSE
            # Pool transition OPEN -> WINTERIZED must be defined (priority 5).
            if pool["service_status"] != "OPEN":
                raise err("ERR_INVALID_STATE", "Pool cannot be winterized from its current state")
            # Open visits block close (priority 10).
            has_open_visits = any(
                v["pool_id"] == pool["id"]
                and v["status"] in ("SCHEDULED", "RECOVERY_SCHEDULED")
                for v in db.visits.values()
            )
            if has_open_visits:
                raise err(
                    "ERR_OPEN_VISITS_BLOCK_CLOSE",
                    "Open visits block winterizing",
                )
            pool["service_status"] = "WINTERIZED"
            touch(pool)
        ev["status"] = "APPLIED"
        touch(ev)
        return success(serialize(ev), 200)


@bp.post("/seasonal-events/<ev_id>/void")
@require_roles("RouteManager")
def void_seasonal_event(ev_id):
    with db.lock:
        ev = get_seasonal_event_or_404(ev_id)
        if ev["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Seasonal event cannot be voided from its current state")
        ev["status"] = "VOIDED"
        touch(ev)
        return success(serialize(ev), 200)
