"""Nesting runs and generated parts (PRD §3.5)."""
from flask import Blueprint, request

from auth import require_any_role, require_roles
from domain import compute_nesting_yield, part_sequence_key, place_hold
from errors import api_error
from serializers import ser_nesting_run, ser_part
from store import db, new_id, now, stamp, stamp_part, touch
from util import Body, paginate, respond_list, respond_object, sort_records

bp = Blueprint("nesting", __name__)


def _get_run(run_id):
    run = db.runs.get(run_id)
    if run is None:
        raise api_error("ERR_RUN_NOT_FOUND", f"NestingRun {run_id} not found")
    return run


def _check_lines_released_to_production(lines):
    for line in lines:
        order = db.orders[line["order_id"]]
        if order["status"] not in ("SUBMITTED", "IN_PRODUCTION"):
            raise api_error(
                "ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION",
                f"Order {order['id']} is not in SUBMITTED or IN_PRODUCTION",
            )


@bp.post("/kcma/nesting-runs")
def create_nesting_run():
    require_roles({"ProductionPlanner"})
    body = Body(request.get_json(silent=True))
    station_id = body.req_str("station_id")
    sheet_component_id = body.req_str("sheet_component_id")
    door_line_ids = body.req_str_list("door_line_ids")
    scheduled_date = body.req_date("scheduled_date")
    start_minute = body.req_int("start_minute", min_value=0, range_error="ERR_INVALID_TIME_WINDOW")
    end_minute = body.req_int("end_minute")

    # priority 5: body FKs exist
    station = None
    if station_id is not None:
        station = db.stations.get(station_id)
        if station is None:
            raise api_error("ERR_STATION_NOT_FOUND", f"NestingStation {station_id} not found")
    component = None
    if sheet_component_id is not None:
        component = db.components.get(sheet_component_id)
        if component is None:
            raise api_error("ERR_COMPONENT_NOT_FOUND", f"Component {sheet_component_id} not found")
    lines = []
    if door_line_ids is not None:
        for line_id in door_line_ids:
            line = db.order_lines.get(line_id)
            if line is None:
                raise api_error("ERR_ORDER_LINE_NOT_FOUND", f"OrderLine {line_id} not found")
            lines.append(line)

    # priority 6: every referenced door line's order is SUBMITTED/IN_PRODUCTION
    _check_lines_released_to_production(lines)

    # priority 8: station must be active
    if station is not None and not station["active"]:
        raise api_error("ERR_STATION_INACTIVE", f"NestingStation {station['id']} is inactive")

    # priority 9: every line a DOOR line; sheet component must be SHEET_GOODS
    if any(l["line_type"] != "DOOR" for l in lines):
        raise api_error("ERR_COMPONENT_KIND_MISMATCH", "door_line_ids must reference DOOR lines")
    if component is not None and component["kind"] != "SHEET_GOODS":
        raise api_error(
            "ERR_COMPONENT_KIND_MISMATCH",
            "sheet_component_id must reference a SHEET_GOODS component",
        )

    # priority 11: changeover-buffer window check, then schedule date
    window_well_formed = (
        start_minute is not None and end_minute is not None
        and 0 <= start_minute <= 1439 and start_minute < end_minute <= 1440
    )
    if station is not None and scheduled_date is not None and window_well_formed:
        changeover = station["changeover_minutes"]
        for other in db.runs.values():
            if (
                other["station_id"] == station["id"]
                and other["scheduled_date"] == scheduled_date.isoformat()
                and other["status"] in ("DRAFT", "RELEASED")
            ):
                clears = (
                    start_minute >= other["end_minute"] + changeover
                    or end_minute + changeover <= other["start_minute"]
                )
                if not clears:
                    raise api_error(
                        "ERR_STATION_WINDOW_OVERLAP",
                        "Run window fails to clear another run by the station changeover buffer",
                    )
    if scheduled_date is not None and scheduled_date < now().date():
        raise api_error("ERR_SCHEDULE_DATE_IN_PAST", "scheduled_date is before the current date")

    # priority 14: field-level sanity (incl. window shape)
    if start_minute is not None and start_minute > 1439:
        body.add_error("ERR_INVALID_TIME_WINDOW", "start_minute must be within 0..1439")
    if end_minute is not None and start_minute is not None:
        if end_minute <= start_minute or end_minute > 1440:
            body.add_error(
                "ERR_INVALID_TIME_WINDOW",
                "end_minute must satisfy start_minute < end_minute <= 1440",
            )
    body.raise_field_errors()

    run = {
        "id": new_id(),
        "station_id": station_id,
        "sheet_component_id": sheet_component_id,
        "door_line_ids": door_line_ids,
        "scheduled_date": scheduled_date.isoformat(),
        "start_minute": start_minute,
        "end_minute": end_minute,
        "status": "DRAFT",
        "total_blank_area_in2": None,
        "sheets_required": None,
        "utilization_pct": None,
    }
    stamp(run)
    db.runs[run["id"]] = run
    return respond_object(ser_nesting_run(run), 201)


@bp.get("/kcma/nesting-runs")
def list_nesting_runs():
    require_any_role()
    records = list(db.runs.values())
    station_id = request.args.get("station_id")
    if station_id is not None:
        records = [r for r in records if r["station_id"] == station_id]
    component_id = request.args.get("sheet_component_id")
    if component_id is not None:
        records = [r for r in records if r["sheet_component_id"] == component_id]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_nesting_run(r) for r in page], total, limit, offset)


@bp.get("/kcma/nesting-runs/<runId>")
def get_nesting_run(runId):
    require_any_role()
    return respond_object(ser_nesting_run(_get_run(runId)), 200)


@bp.post("/kcma/nesting-runs/<runId>/release")
def release_nesting_run(runId):
    require_roles({"ProductionPlanner"})
    run = _get_run(runId)                                         # priority 4
    if run["status"] != "DRAFT":                                  # priority 6
        raise api_error("ERR_RUN_NOT_RELEASABLE", "Release requires the run in DRAFT")
    lines = [db.order_lines[lid] for lid in run["door_line_ids"]]
    _check_lines_released_to_production(lines)
    component = db.components[run["sheet_component_id"]]

    # hop 1: yield + deterministic part generation
    total_area, sheets, utilization = compute_nesting_yield(lines, component)
    for seq, line in enumerate(sorted(lines, key=part_sequence_key), start=1):
        part = {
            "id": new_id(),
            "nesting_run_id": run["id"],
            "order_line_id": line["id"],
            "component_id": component["id"],
            "part_kind": "DOOR_BLANK",
            "width_in": line["width_in"],
            "height_in": line["height_in"],
            "qty": line["qty"],
            "part_seq": seq,
        }
        stamp_part(part)
        db.parts[part["id"]] = part
    run["total_blank_area_in2"] = total_area
    run["sheets_required"] = sheets
    run["utilization_pct"] = float(utilization)
    run["status"] = "RELEASED"
    touch(run)

    # hop 2: reserve sheets (sunk — released runs are terminal)
    component["reserved_qty"] += sheets
    available = component["on_hand_qty"] - component["reserved_qty"]

    # hops 3-4: overdraft places COMPONENT_SHORTAGE holds on each distinct
    # owning order (skipping orders already holding one on this component)
    if available < 0:
        shortfall = -available
        seen_orders = []
        for line in lines:
            oid = line["order_id"]
            if oid in seen_orders:
                continue
            seen_orders.append(oid)
            already = any(
                h["order_id"] == oid
                and h["component_id"] == component["id"]
                and h["reason"] == "COMPONENT_SHORTAGE"
                and h["status"] == "PLACED"
                for h in db.holds.values()
            )
            if not already:
                place_hold(oid, "COMPONENT_SHORTAGE", component["id"], shortfall)
    return respond_object(ser_nesting_run(run), 200)


@bp.post("/kcma/nesting-runs/<runId>/cancel")
def cancel_nesting_run(runId):
    require_roles({"ProductionPlanner"})
    run = _get_run(runId)
    if run["status"] != "DRAFT":
        raise api_error("ERR_RUN_NOT_CANCELLABLE", "Cancel requires the run in DRAFT")
    run["status"] = "CANCELLED"
    touch(run)
    return respond_object(ser_nesting_run(run), 200)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

@bp.get("/kcma/parts")
def list_parts():
    require_any_role()
    records = list(db.parts.values())
    run_id = request.args.get("nesting_run_id")
    if run_id is not None:
        records = [p for p in records if p["nesting_run_id"] == run_id]
    component_id = request.args.get("component_id")
    if component_id is not None:
        records = [p for p in records if p["component_id"] == component_id]
    line_id = request.args.get("order_line_id")
    if line_id is not None:
        records = [p for p in records if p["order_line_id"] == line_id]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_part(p) for p in page], total, limit, offset)


@bp.get("/kcma/parts/<partId>")
def get_part(partId):
    require_any_role()
    part = db.parts.get(partId)
    if part is None:
        raise api_error("ERR_PART_NOT_FOUND", f"Part {partId} not found")
    return respond_object(ser_part(part), 200)
