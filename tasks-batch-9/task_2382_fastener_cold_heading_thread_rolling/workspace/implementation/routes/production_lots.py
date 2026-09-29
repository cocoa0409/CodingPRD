"""Production lots: opening, heading, abort, hold and release (PRD 3.4)."""

from flask import Blueprint, g

import enums
from db import db, new_record, sorted_records, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services import calc
from services.cascades import cascade_tool_worn
from services.lookup import (
    guard_disposition,
    guard_quarantined,
    heading_tool_or_404,
    part_spec_or_404,
    production_lot_or_404,
    project_traceability,
    require_unique,
    spec_for_lot,
    wire_lot_or_404,
)
from util import dec, dt_of, parse_dt, rhu
from validate import (
    field_dt,
    field_int,
    field_str,
    paginate,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("production_lots", __name__)


@bp.post("/production-lots")
@endpoint("ProcessEngineer")
def create_production_lot():
    body = g.body
    lot_code = field_str(body, "lot_code")
    part_spec_id = field_str(body, "part_spec_id")
    wire_lot_id = field_str(body, "wire_lot_id")
    heading_tool_id = field_str(body, "heading_tool_id")
    press_code = field_str(body, "press_code", allow_empty=True)
    window_start = field_dt(body, "press_window_start_at")
    window_end = field_dt(body, "press_window_end_at")
    planned_pieces = field_int(body, "planned_pieces", minimum=1)
    expected_wire_lot_version = field_int(body, "expected_wire_lot_version")
    if window_end <= window_start:
        raise ApiError(
            "ERR_VALIDATION", "press_window_end_at must be later than press_window_start_at."
        )

    # tier 5 - body foreign keys, in input-field order
    spec = part_spec_or_404(part_spec_id)
    wire = wire_lot_or_404(wire_lot_id)
    tool = heading_tool_or_404(heading_tool_id)

    # tier 6 - uniqueness
    require_unique("production_lots", "lot_code", lot_code)

    # tier 7 - optimistic concurrency on the wire lot
    if expected_wire_lot_version != wire["version"]:
        raise ApiError("ERR_STALE_WIRE_LOT_VERSION")

    # tier 11 - cross entity state
    if wire["status"] != "RELEASED":
        raise ApiError("ERR_WIRE_LOT_NOT_RELEASED")
    heat = db.steel_heats.get(wire["steel_heat_id"])
    if heat is None or heat["cert_status"] != "VERIFIED":
        raise ApiError("ERR_STEEL_HEAT_NOT_VERIFIED")

    # tier 15 - press window exclusivity on the tool (half open window)
    for other in db.production_lots.values():
        if other["heading_tool_id"] != heading_tool_id:
            continue
        if other["process_state"] == "ABORTED":
            continue
        other_start = dt_of(other, "press_window_start_at")
        other_end = dt_of(other, "press_window_end_at")
        if other_start is None or other_end is None:
            continue
        if window_start < other_end and window_end > other_start:
            raise ApiError("ERR_TOOL_WINDOW_CONFLICT")

    # tier 16 - the heat's grade must be allowed by the specification
    if heat["grade"] not in (spec.get("allowed_steel_grades") or []):
        raise ApiError("ERR_GRADE_NOT_ALLOWED")

    # tier 17 - capacity: remaining die life, then wire mass
    demand = calc.heading_demand_pieces(planned_pieces, spec["scrap_allowance_pct"])
    budget = calc.life_budget(tool, spec.get("qualification_program"))
    remaining = budget - int(tool["cumulative_pieces_current_cycle"] or 0)
    if demand > remaining:
        raise ApiError("ERR_TOOL_LIFE_EXHAUSTED")

    required_kg = calc.required_reservation_kg(
        planned_pieces, spec["blank_mass_g"], spec["scrap_allowance_pct"]
    )
    if dec(wire["available_mass_kg"]) < required_kg:
        raise ApiError("ERR_WIRE_MASS_INSUFFICIENT")

    # commit
    wire["available_mass_kg"] = rhu(dec(wire["available_mass_kg"]) - required_kg, 3)
    wire["reserved_mass_kg"] = rhu(dec(wire["reserved_mass_kg"]) + required_kg, 3)
    touch(wire)

    lot = new_record(
        {
            "lot_code": lot_code,
            "part_spec_id": part_spec_id,
            "pinned_part_spec_version": spec["version"],
            "wire_lot_id": wire_lot_id,
            "heading_tool_id": heading_tool_id,
            "traceability_heat_id": wire["steel_heat_id"],
            "press_code": press_code,
            "press_window_start_at": body["press_window_start_at"],
            "press_window_end_at": body["press_window_end_at"],
            "planned_pieces": planned_pieces,
            "wire_reserved_kg": required_kg,
            "wire_consumed_kg": None,
            "headed_count": 0,
            "heading_scrap_count": 0,
            "available_count": 0,
            "scrap_count": 0,
            "destructive_test_count": 0,
            "packed_count": 0,
            "tool_utilization_pct": None,
            "heat_treat_completed": False,
            "process_state": "SETUP",
            "disposition": "IN_PROCESS",
            "hold_source": "NONE",
            "risk_score_pre_test": None,
            "risk_score_final": None,
            "inspection_severity": None,
            "achieved_strength_class": None,
            "abort_reason": None,
        }
    )
    db.production_lots[lot["id"]] = lot
    return created(lot)


@bp.get("/production-lots/<lot_id>")
@endpoint(ANY_ROLE)
def get_production_lot(lot_id):
    return ok(production_lot_or_404(lot_id))


@bp.get("/production-lots")
@endpoint(ANY_ROLE)
def list_production_lots():
    limit, offset = pagination()
    part_spec_id = query_str("part_spec_id")
    wire_lot_id = query_str("wire_lot_id")
    heading_tool_id = query_str("heading_tool_id")
    traceability_heat_id = query_str("traceability_heat_id")
    process_state = query_enum("process_state", enums.PROCESS_STATES)
    disposition = query_enum("disposition", enums.DISPOSITIONS)

    records = sorted_records(db.production_lots.values())
    if part_spec_id is not None:
        records = [r for r in records if r["part_spec_id"] == part_spec_id]
    if wire_lot_id is not None:
        records = [r for r in records if r["wire_lot_id"] == wire_lot_id]
    if heading_tool_id is not None:
        records = [r for r in records if r["heading_tool_id"] == heading_tool_id]
    if traceability_heat_id is not None:
        records = [r for r in records if r["traceability_heat_id"] == traceability_heat_id]
    if process_state is not None:
        records = [r for r in records if r["process_state"] == process_state]
    if disposition is not None:
        records = [r for r in records if r["disposition"] == disposition]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/production-lots/<lot_id>/traceability")
@endpoint(ANY_ROLE)
def get_traceability(lot_id):
    lot = production_lot_or_404(lot_id)
    return ok(project_traceability(lot))


@bp.post("/production-lots/<lot_id>/complete-heading")
@endpoint("ProcessEngineer")
def complete_heading(lot_id):
    body = g.body
    headed_count = field_int(body, "headed_count", minimum=0)
    heading_scrap_count = field_int(body, "heading_scrap_count", minimum=0)

    lot = production_lot_or_404(lot_id)
    guard_disposition(lot)
    if lot["process_state"] != "SETUP":
        raise ApiError("ERR_INVALID_LOT_STATE")

    tool = db.heading_tools.get(lot["heading_tool_id"])
    if tool is None or tool["status"] != "MOUNTED":
        raise ApiError("ERR_INVALID_TOOL_STATE")

    spec = spec_for_lot(lot)
    allowance = calc.heading_allowance_pieces(
        lot["planned_pieces"], spec["scrap_allowance_pct"]
    )
    if headed_count + heading_scrap_count > allowance:
        raise ApiError("ERR_PIECE_COUNT_INVALID")

    # lot bookkeeping
    lot["headed_count"] = headed_count
    lot["heading_scrap_count"] = heading_scrap_count
    lot["scrap_count"] = heading_scrap_count
    lot["available_count"] = headed_count
    lot["process_state"] = "HEADED"

    # wire mass settlement
    wire = db.wire_lots.get(lot["wire_lot_id"])
    consumed = calc.consumed_kg(headed_count, heading_scrap_count, spec["blank_mass_g"])
    reserved = dec(lot["wire_reserved_kg"] or 0)
    if wire is not None:
        wire["reserved_mass_kg"] = rhu(dec(wire["reserved_mass_kg"]) - reserved, 3)
        wire["consumed_mass_kg"] = rhu(dec(wire["consumed_mass_kg"]) + consumed, 3)
        wire["available_mass_kg"] = rhu(
            dec(wire["available_mass_kg"]) + (reserved - consumed), 3
        )
        touch(wire)
    lot["wire_consumed_kg"] = consumed
    lot["wire_reserved_kg"] = calc.D(0)

    # tool wear
    tool["cumulative_pieces_current_cycle"] = int(
        tool["cumulative_pieces_current_cycle"] or 0
    ) + headed_count + heading_scrap_count
    calc.refresh_tool_life(tool)
    lot["tool_utilization_pct"] = calc.tool_utilization_pct(
        tool["cumulative_pieces_current_cycle"], tool["rated_derated_life_pieces"]
    )
    touch(lot)

    worn = int(tool["cumulative_pieces_current_cycle"]) >= int(
        tool["rated_derated_life_pieces"]
    )
    if worn:
        tool["status"] = "WORN"
        tool["mounted_press_code"] = None
    touch(tool)
    if worn:
        cascade_tool_worn(tool)

    return ok(lot)


@bp.post("/production-lots/<lot_id>/abort-heading")
@endpoint("ProcessEngineer")
def abort_heading(lot_id):
    reason = field_str(g.body, "reason", allow_empty=True)

    lot = production_lot_or_404(lot_id)
    guard_disposition(lot)
    if lot["process_state"] != "SETUP":
        raise ApiError("ERR_INVALID_LOT_STATE")

    wire = db.wire_lots.get(lot["wire_lot_id"])
    reserved = dec(lot["wire_reserved_kg"] or 0)
    if wire is not None:
        wire["reserved_mass_kg"] = rhu(dec(wire["reserved_mass_kg"]) - reserved, 3)
        wire["available_mass_kg"] = rhu(dec(wire["available_mass_kg"]) + reserved, 3)
        touch(wire)
    lot["wire_reserved_kg"] = calc.D(0)
    lot["process_state"] = "ABORTED"
    lot["disposition"] = "SCRAPPED"
    lot["abort_reason"] = reason
    touch(lot)
    return ok(lot)


@bp.post("/production-lots/<lot_id>/hold")
@endpoint("QualityInspector", "QualityManager")
def hold_lot(lot_id):
    field_str(g.body, "reason", allow_empty=True)

    lot = production_lot_or_404(lot_id)
    guard_quarantined(lot)
    if lot["disposition"] == "HOLD":
        raise ApiError("ERR_LOT_ON_HOLD")
    if lot["disposition"] != "IN_PROCESS":
        raise ApiError("ERR_INVALID_LOT_STATE")

    lot["disposition"] = "HOLD"
    lot["hold_source"] = "QUALITY"
    touch(lot)
    return ok(lot)


@bp.post("/production-lots/<lot_id>/release-hold")
@endpoint("QualityManager")
def release_hold(lot_id):
    field_str(g.body, "note", required=False, allow_empty=True)

    lot = production_lot_or_404(lot_id)
    guard_quarantined(lot)
    if lot["disposition"] != "HOLD":
        raise ApiError("ERR_INVALID_LOT_STATE")

    if lot.get("hold_source") == "HEAT_COUNTERFEIT":
        heat = db.steel_heats.get(lot.get("traceability_heat_id"))
        if heat is None or heat["cert_status"] != "VERIFIED":
            raise ApiError("ERR_STEEL_HEAT_NOT_VERIFIED")

    lot["disposition"] = "IN_PROCESS"
    lot["hold_source"] = "NONE"
    touch(lot)
    return ok(lot)
