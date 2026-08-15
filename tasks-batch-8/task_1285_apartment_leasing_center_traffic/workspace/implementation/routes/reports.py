"""Closing-ratio report and the logical-clock test-driving endpoint."""
from flask import Blueprint, request

from db import DB, fmt_dt, set_clock
from errors import ApiError
from middleware import AGENT, PM, auth
from response import ok
from services import INQUIRY_SOURCES, closing_ratio_pct
from util import as_dt, body, required

bp = Blueprint("reports", __name__)

STAFF = [PM, AGENT]
BASES = ("ALL", "QUALIFIED")


@bp.get("/leasing/reports/closing")
def closing_report():
    auth(STAFF)
    args = request.args
    property_id = args.get("property_id")
    if not property_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "property_id is required")
    window_start_raw = args.get("window_start")
    window_end_raw = args.get("window_end")
    if not window_start_raw:
        raise ApiError("ERR_INVALID_REQUEST", 400, "window_start is required")
    if not window_end_raw:
        raise ApiError("ERR_INVALID_REQUEST", 400, "window_end is required")
    window_start = as_dt(window_start_raw, "window_start")
    window_end = as_dt(window_end_raw, "window_end")
    basis = args.get("basis", "ALL")
    if basis not in BASES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "basis must be ALL or QUALIFIED")
    agent_filter = args.get("agent_id")
    source_filter = args.get("source")
    if source_filter is not None and source_filter not in INQUIRY_SOURCES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "source is not a valid enum member")

    if property_id not in DB["properties"]:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", 404, "Property does not exist")

    groups = {}
    for inq in DB["inquiries"].values():
        if inq["property_id"] != property_id:
            continue
        # Half-open window on created_at: [window_start, window_end).
        if not (window_start <= inq["created_at"] < window_end):
            continue
        if inq["assigned_agent_id"] is None:
            continue
        if agent_filter is not None and inq["assigned_agent_id"] != agent_filter:
            continue
        if source_filter is not None and inq["source"] != source_filter:
            continue
        key = (inq["assigned_agent_id"], inq["source"])
        bucket = groups.setdefault(key, {"total": 0, "closed": 0, "qualified": 0})
        bucket["total"] += 1
        if inq["status"] == "CONVERTED":
            bucket["closed"] += 1
        if inq["first_responded_at"] is not None:
            bucket["qualified"] += 1

    rows = []
    for (agent_id, source) in sorted(groups.keys()):
        bucket = groups[(agent_id, source)]
        denominator = bucket["total"] if basis == "ALL" else bucket["qualified"]
        if denominator == 0:
            continue
        rows.append(
            {
                "agent_id": agent_id,
                "source": source,
                "inquiries_count": denominator,
                "closed_count": bucket["closed"],
                "closing_ratio_pct": closing_ratio_pct(
                    bucket["closed"], denominator
                ),
            }
        )

    return ok(
        {
            "property_id": property_id,
            "window_start": fmt_dt(window_start),
            "window_end": fmt_dt(window_end),
            "basis": basis,
            "rows": rows,
        }
    )


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth([PM])
    data = body()
    to_iso8601 = as_dt(required(data, "to_iso8601"), "to_iso8601")
    set_clock(to_iso8601)
    return ok({"current_utc": fmt_dt(to_iso8601)})
