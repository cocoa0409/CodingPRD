"""OutageWindow endpoints: propose, approve (duration + crew capacity),
notify (72h lead), execute (window + temp-service coverage), reschedule, cancel."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_OUTAGE_DURATION_EXCEEDED,
    ERR_CREW_CAPACITY_EXCEEDED,
    ERR_NOTIFICATION_LEAD_TIME,
    ERR_OUTAGE_WINDOW_MISSED,
    ERR_TEMP_SERVICE_REQUIRED,
)
from middleware import require_roles, forbid
from response import success_object, success_list
from services import domain
from services.serializers import outage_view
from util import (
    get_json_body,
    get_or_404,
    parse_iso8601,
    parse_pagination,
    paginate,
    query_arg,
    require_field,
    require_id_array,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("outages", __name__, url_prefix="/api/outage-windows")

PM = "ProgramManager"
UC = "UtilityCoordinator"
ANY = "Any"

TRANSITION_TARGETS = {"APPROVED", "NOTIFIED", "EXECUTED", "CLOSED", "CANCELLED", "PROPOSED"}
ACTIVE_STATUSES = {"APPROVED", "NOTIFIED", "EXECUTED"}


@bp.route("", methods=["POST"])
@require_roles(UC, PM)
def create_outage(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    project_id = require_string(body, "project_id")
    feeder_id = require_string(body, "feeder_id")
    start_at = require_ts(body, "start_at")
    end_at = require_ts(body, "end_at")
    conversion_ids = require_id_array(body, "conversion_ids", default=[])
    for cid in conversion_ids:
        get_or_404(db.conversions, cid, "ServiceConversion")
    if parse_iso8601(start_at) >= parse_iso8601(end_at):
        raise_err(ERR_VALIDATION, "end_at must be after start_at")

    outage = stamp_new({
        "project_id": project_id,
        "feeder_id": feeder_id,
        "start_at": start_at,
        "end_at": end_at,
        "conversion_ids": list(conversion_ids),
        "status": "PROPOSED",
        "notified_at": None,
    })
    db.outages[outage["id"]] = outage
    return success_object(outage_view(outage), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_outages(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.outages.values())
    project_id = query_arg("project_id")
    feeder_id = query_arg("feeder_id")
    status = query_arg("status")
    conversion_id = query_arg("conversion_ids")
    if project_id:
        items = [o for o in items if o["project_id"] == project_id]
    if feeder_id:
        items = [o for o in items if o["feeder_id"] == feeder_id]
    if status:
        items = [o for o in items if o["status"] == status]
    if conversion_id:
        items = [o for o in items if conversion_id in (o.get("conversion_ids") or [])]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([outage_view(o) for o in page], limit, offset, total)


@bp.route("/<oid>", methods=["GET"])
@require_roles(ANY)
def get_outage(oid: str, _user_id: str, _role: str):
    return success_object(outage_view(get_or_404(db.outages, oid, "OutageWindow")))


def _max_concurrency(windows: list) -> int:
    """Max simultaneous coverage over half-open intervals [(start, end)]."""
    events = []
    for start_dt, end_dt in windows:
        events.append((start_dt, 1))
        events.append((end_dt, -1))
    # Half-open: at a shared instant, endings are processed before beginnings.
    events.sort(key=lambda ev: (ev[0], ev[1]))
    current = best = 0
    for _, delta in events:
        current += delta
        best = max(best, current)
    return best


@bp.route("/<oid>/transition", methods=["POST"])
@require_roles(PM, UC)
def transition_outage(oid: str, _user_id: str, _role: str):
    outage = get_or_404(db.outages, oid, "OutageWindow")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    # Per-transition actors (PM: approve/cancel/reschedule; UC: notify/execute/close)
    if to in {"APPROVED", "CANCELLED", "PROPOSED"} and _role != PM:
        forbid("this outage transition is ProgramManager-only")
    if to in {"NOTIFIED", "EXECUTED", "CLOSED"} and _role != UC:
        forbid("this outage transition is UtilityCoordinator-only")

    current = outage["status"]
    if current in {"CLOSED", "CANCELLED"}:
        raise_err(ERR_INVALID_STATE, f"outage window is terminal ({current})")

    if to == "APPROVED":
        if current != "PROPOSED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> APPROVED")
        start_dt = parse_iso8601(outage["start_at"])
        end_dt = parse_iso8601(outage["end_at"])
        if (end_dt - start_dt).total_seconds() > domain.MAX_OUTAGE_SECONDS:
            raise_err(ERR_OUTAGE_DURATION_EXCEEDED,
                      "outage window longer than 8h")
        overlapping = []
        for w in db.outages.values():
            if (w["id"] != oid and w["project_id"] == outage["project_id"]
                    and w["feeder_id"] == outage["feeder_id"]
                    and w["status"] in ACTIVE_STATUSES):
                w_start = parse_iso8601(w["start_at"])
                w_end = parse_iso8601(w["end_at"])
                if w_start < end_dt and start_dt < w_end:  # half-open overlap
                    overlapping.append((w_start, w_end))
        if _max_concurrency(overlapping + [(start_dt, end_dt)]) > domain.MAX_CONCURRENT_OUTAGES:
            raise_err(ERR_CREW_CAPACITY_EXCEEDED,
                      "more than 2 overlapping active outage windows on the feeder")
        for cid in outage.get("conversion_ids") or []:
            conv = db.conversions.get(cid)
            if conv is None or conv["project_id"] != outage["project_id"]:
                raise_err(ERR_VALIDATION,
                          "every conversion_ids entry must exist and belong to the project")
        outage["status"] = "APPROVED"

    elif to == "NOTIFIED":
        if current != "APPROVED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> NOTIFIED")
        start_dt = parse_iso8601(outage["start_at"])
        if (start_dt - domain.clock_dt()).total_seconds() < domain.NOTIFICATION_LEAD_SECONDS:
            raise_err(ERR_NOTIFICATION_LEAD_TIME,
                      "notification requires start_at - clock >= 72h")
        outage["notified_at"] = domain.clock_str()
        outage["status"] = "NOTIFIED"

    elif to == "EXECUTED":
        if current != "NOTIFIED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> EXECUTED")
        now = domain.clock_dt()
        if now < parse_iso8601(outage["start_at"]):
            raise_err(ERR_INVALID_STATE, "execution before the window start")
        for cid in outage.get("conversion_ids") or []:
            conv = db.conversions.get(cid)
            if conv is None:
                raise_err(ERR_VALIDATION, "conversion reference no longer exists")
            if not (conv["work_status"] in {"ENERGIZED", "INSPECTED", "COMPLETE"}
                    or conv["temp_service_status"] == "TEMP_ACTIVE"):
                raise_err(ERR_TEMP_SERVICE_REQUIRED,
                          "affected conversions must be energized or on active "
                          "temporary service")
        if now > parse_iso8601(outage["end_at"]):
            raise_err(ERR_OUTAGE_WINDOW_MISSED, "execution attempted after end_at")
        outage["status"] = "EXECUTED"

    elif to == "CLOSED":
        if current != "EXECUTED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> CLOSED")
        outage["status"] = "CLOSED"

    elif to == "PROPOSED":
        # Reschedule cycle: NOTIFIED -> PROPOSED with a replacement window.
        if current != "NOTIFIED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> PROPOSED")
        new_start = require_ts(body, "new_start_at")
        new_end = require_ts(body, "new_end_at")
        if parse_iso8601(new_start) >= parse_iso8601(new_end):
            raise_err(ERR_VALIDATION, "new_end_at must be after new_start_at")
        outage["start_at"] = new_start
        outage["end_at"] = new_end
        outage["notified_at"] = None
        outage["status"] = "PROPOSED"

    elif to == "CANCELLED":
        if current not in {"PROPOSED", "APPROVED", "NOTIFIED"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> CANCELLED")
        outage["status"] = "CANCELLED"

    touch(outage)
    return success_object(outage_view(outage))
