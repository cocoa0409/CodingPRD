"""The logical clock and the three configuration roots (PRD §3.1)."""

from flask import Blueprint

import clock
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("config_roots", __name__)


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    M.authenticate("PortfolioAdmin")
    data = V.body()
    raw, parsed = V.datetime_field(data, "to_iso8601")
    clock.set_current(raw, parsed)
    return R.object_response({"current_utc": raw}, 200)


# ---------------------------------------------------------------------------
# stage gates
# ---------------------------------------------------------------------------
@bp.post("/stage-gates")
def create_stage_gate():
    M.authenticate("PortfolioAdmin")
    data = V.body()
    gate_number = V.int_field(data, "gate_number", minimum=2)
    category = V.enum_field(data, "category", V.CATEGORIES)
    stage_from = V.enum_field(data, "stage_from", V.STAGE_FROM)
    stage_to = V.enum_field(data, "stage_to", V.STAGE_TO)
    required = V.enum_array_field(data, "required_deliverable_types",
                                 V.DELIVERABLE_TYPES, unique=True)
    quorum_size = V.int_field(data, "quorum_size", minimum=1)
    veto_functions = V.enum_array_field(data, "veto_functions", V.FUNCTIONS)
    npv_hurdle = V.number_field(data, "npv_hurdle_usd", minimum=0)
    payback_max = V.int_field(data, "payback_months_max", minimum=0)
    gm_floor = V.number_field(data, "gross_margin_floor_pct", minimum=0)
    readiness_floor = V.number_field(data, "readiness_floor_index",
                                     minimum=0, maximum=100)

    if core.gate_for(category, gate_number) is not None:
        E.fail(E.ERR_DUPLICATE_RESOURCE,
               "A gate %d is already registered for %s." % (gate_number, category))

    row = core.new_row(db.stage_gates, {
        "gate_number": gate_number,
        "category": category,
        "stage_from": stage_from,
        "stage_to": stage_to,
        "required_deliverable_types": required,
        "quorum_size": quorum_size,
        "veto_functions": veto_functions,
        "npv_hurdle_usd": npv_hurdle,
        "payback_months_max": payback_max,
        "gross_margin_floor_pct": gm_floor,
        "readiness_floor_index": readiness_floor,
    })
    return R.object_response(row, 201)


@bp.get("/stage-gates")
def list_stage_gates():
    M.reader()
    rows = M.apply_filters(db.rows(db.stage_gates),
                           {"category": "category", "gate_number": "gate_number"})
    # "newest configuration first": created_at DESC, and because audit stamps
    # come from the logical clock several configurations legitimately share one
    # created_at, the insertion ordinal carries the "newest" sense through the
    # tie (id is never an ordering key).
    rows = M.order(rows, [(lambda r: (r["created_at"], r["_seq"]), True)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/stage-gates/<gate_id>")
def read_stage_gate(gate_id):
    M.reader()
    return R.object_response(common.stage_gate(gate_id))


# ---------------------------------------------------------------------------
# retailers
# ---------------------------------------------------------------------------
@bp.post("/retailers")
def create_retailer():
    M.authenticate("PortfolioAdmin")
    data = V.body()
    name = V.string_field(data, "name", min_len=1, max_len=80)
    channel = V.enum_field(data, "channel", V.CHANNELS)
    acv = V.number_field(data, "acv_contribution_pct", minimum=0, maximum=100)
    lead_days = V.int_field(data, "presentation_lead_days", minimum=0)

    for row in db.rows(db.retailers):
        if row["name"] == name:
            E.fail(E.ERR_DUPLICATE_RESOURCE, "Retailer %s already exists." % name)

    row = core.new_row(db.retailers, {
        "name": name,
        "channel": channel,
        "acv_contribution_pct": acv,
        "presentation_lead_days": lead_days,
    })
    return R.object_response(row, 201)


@bp.get("/retailers")
def list_retailers():
    M.reader()
    rows = M.apply_filters(db.rows(db.retailers), {"channel": "channel"})
    rows = M.order(rows)
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/retailers/<retailer_id>")
def read_retailer(retailer_id):
    M.reader()
    return R.object_response(common.retailer(retailer_id))


# ---------------------------------------------------------------------------
# shelf reset windows
# ---------------------------------------------------------------------------
@bp.post("/retailers/<retailer_id>/shelf-reset-windows")
def create_reset_window(retailer_id):
    M.authenticate("PortfolioAdmin")
    retailer = common.retailer(retailer_id)
    data = V.body()
    category = V.enum_field(data, "category", V.CATEGORIES)
    start_raw, start_dt = V.datetime_field(data, "window_start")
    end_raw, end_dt = V.datetime_field(data, "window_end")
    max_presentations = V.int_field(data, "max_presentations", minimum=1)
    if end_dt <= start_dt:
        E.fail(E.ERR_INVALID_REQUEST, "window_end must be after window_start.")

    row = core.new_row(db.shelf_reset_windows, {
        "retailer_id": retailer["id"],
        "category": category,
        "window_start": start_raw,
        "window_end": end_raw,
        "max_presentations": max_presentations,
        "booked_slot_count": 0,
    })
    row["_dt_window_start"] = start_dt
    row["_dt_window_end"] = end_dt
    return R.object_response(row, 201)


@bp.get("/retailers/<retailer_id>/shelf-reset-windows")
def list_reset_windows(retailer_id):
    M.reader()
    retailer = common.retailer(retailer_id)
    rows = db.children(db.shelf_reset_windows, "retailer_id", retailer["id"])
    rows = M.apply_filters(rows, {"category": "category"})
    rows = M.order(rows, [(lambda r: r["_dt_window_start"], False)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/shelf-reset-windows/<window_id>")
def read_reset_window(window_id):
    M.reader()
    return R.object_response(common.reset_window(window_id))


# ---------------------------------------------------------------------------
# pilot lines
# ---------------------------------------------------------------------------
@bp.post("/pilot-lines")
def create_pilot_line():
    M.authenticate("PortfolioAdmin")
    data = V.body()
    plant_name = V.string_field(data, "plant_name")
    line_code = V.string_field(data, "line_code", min_len=1, max_len=40)
    buffer_minutes = V.int_field(data, "changeover_buffer_minutes",
                                 minimum=0, maximum=1440)
    allergen_regime = V.enum_field(data, "allergen_regime", V.ALLERGEN_REGIMES)
    hourly_cost = V.number_field(data, "hourly_cost_usd", minimum=0)

    for row in db.rows(db.pilot_lines):
        if row["line_code"] == line_code:
            E.fail(E.ERR_DUPLICATE_RESOURCE,
                   "Pilot line %s already exists." % line_code)

    row = core.new_row(db.pilot_lines, {
        "plant_name": plant_name,
        "line_code": line_code,
        "changeover_buffer_minutes": buffer_minutes,
        "allergen_regime": allergen_regime,
        "hourly_cost_usd": hourly_cost,
    })
    return R.object_response(row, 201)


@bp.get("/pilot-lines")
def list_pilot_lines():
    M.reader()
    rows = M.apply_filters(db.rows(db.pilot_lines),
                           {"allergen_regime": "allergen_regime"})
    rows = M.order(rows)
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/pilot-lines/<pilot_line_id>")
def read_pilot_line(pilot_line_id):
    M.reader()
    return R.object_response(common.pilot_line(pilot_line_id))
