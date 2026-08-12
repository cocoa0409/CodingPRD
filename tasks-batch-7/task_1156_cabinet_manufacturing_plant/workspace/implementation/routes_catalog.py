"""Plant administration: dealers, door styles, finish specs, components,
nesting stations, assembly lines, and the test-driving logical clock."""
from flask import Blueprint, request

from auth import require_any_role, require_roles
from domain import COMPONENT_KINDS, CONSTRUCTIONS, PRICE_LEVELS, SHEENS
from errors import api_error
from serializers import (
    ser_assembly_line,
    ser_component,
    ser_dealer,
    ser_door_style,
    ser_finish_spec,
    ser_hold,
    ser_nesting_station,
)
from store import db, new_id, stamp, touch
from util import (
    Body,
    bool_filter,
    fmt_ts,
    paginate,
    respond_list,
    respond_object,
    sort_records,
)

bp = Blueprint("catalog", __name__)


def _get_or_404(table, rid, error_id):
    rec = table.get(rid)
    if rec is None:
        raise api_error(error_id, f"Resource {rid} not found")
    return rec


# ---------------------------------------------------------------------------
# Dealers
# ---------------------------------------------------------------------------

@bp.post("/kcma/dealers")
def create_dealer():
    require_roles({"PlantAdmin"})
    body = Body(request.get_json(silent=True))
    name = body.req_str("name")
    dealer_code = body.req_str("dealer_code")
    price_level = body.req_enum("price_level", PRICE_LEVELS)
    credit_limit_cents = body.req_int("credit_limit_cents", min_value=0)
    if dealer_code is not None and any(
        d["dealer_code"] == dealer_code for d in db.dealers.values()
    ):
        body.add_error("ERR_DUPLICATE_CODE", f"dealer_code {dealer_code} already exists")
    body.raise_field_errors()

    rec = {
        "id": new_id(),
        "name": name,
        "dealer_code": dealer_code,
        "price_level": price_level,
        "credit_limit_cents": credit_limit_cents,
    }
    stamp(rec)
    db.dealers[rec["id"]] = rec
    return respond_object(ser_dealer(rec), 201)


@bp.put("/kcma/dealers/<dealerId>")
def update_dealer(dealerId):
    require_roles({"PlantAdmin"})
    dealer = _get_or_404(db.dealers, dealerId, "ERR_DEALER_NOT_FOUND")
    body = Body(request.get_json(silent=True))
    credit_limit_cents = body.opt_int("credit_limit_cents", min_value=0)
    price_level = body.opt_enum("price_level", PRICE_LEVELS)
    body.raise_field_errors()

    changed = False
    if credit_limit_cents is not None and credit_limit_cents != dealer["credit_limit_cents"]:
        dealer["credit_limit_cents"] = credit_limit_cents
        changed = True
    if price_level is not None and price_level != dealer["price_level"]:
        dealer["price_level"] = price_level
        changed = True
    if changed:
        touch(dealer)
    return respond_object(ser_dealer(dealer), 200)


@bp.get("/kcma/dealers")
def list_dealers():
    require_any_role()
    records = list(db.dealers.values())
    price_level = request.args.get("price_level")
    if price_level is not None:
        records = [d for d in records if d["price_level"] == price_level]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_dealer(d) for d in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Door styles
# ---------------------------------------------------------------------------

@bp.post("/kcma/door-styles")
def create_door_style():
    require_roles({"PlantAdmin"})
    body = Body(request.get_json(silent=True))
    style_code = body.req_str("style_code")
    name = body.req_str("name")
    construction = body.req_enum("construction", CONSTRUCTIONS)
    base_list_price_cents = body.req_int("base_list_price_cents", min_value=1)
    active = body.opt_bool("active", default=True)
    if style_code is not None and any(
        s["style_code"] == style_code for s in db.door_styles.values()
    ):
        body.add_error("ERR_DUPLICATE_CODE", f"style_code {style_code} already exists")
    body.raise_field_errors()

    rec = {
        "id": new_id(),
        "style_code": style_code,
        "name": name,
        "construction": construction,
        "base_list_price_cents": base_list_price_cents,
        "active": active,
    }
    stamp(rec)
    db.door_styles[rec["id"]] = rec
    return respond_object(ser_door_style(rec), 201)


@bp.get("/kcma/door-styles")
def list_door_styles():
    require_any_role()
    records = list(db.door_styles.values())
    active = bool_filter(request.args.get("active"))
    if active is not None:
        records = [s for s in records if s["active"] == active]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_door_style(s) for s in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Finish specs
# ---------------------------------------------------------------------------

@bp.post("/kcma/finish-specs")
def create_finish_spec():
    require_roles({"PlantAdmin"})
    body = Body(request.get_json(silent=True))
    finish_code = body.req_str("finish_code")
    color_name = body.req_str("color_name")
    sheen = body.req_enum("sheen", SHEENS)
    upcharge_pct = body.req_num("upcharge_pct", min_value=0)
    delta_e_tolerance = body.opt_num("delta_e_tolerance", default=1.5, min_value=0, exclusive_min=True)
    active = body.opt_bool("active", default=True)
    if finish_code is not None and any(
        f["finish_code"] == finish_code for f in db.finish_specs.values()
    ):
        body.add_error("ERR_DUPLICATE_CODE", f"finish_code {finish_code} already exists")
    body.raise_field_errors()

    rec = {
        "id": new_id(),
        "finish_code": finish_code,
        "color_name": color_name,
        "sheen": sheen,
        "upcharge_pct": upcharge_pct,
        "delta_e_tolerance": delta_e_tolerance,
        "active": active,
    }
    stamp(rec)
    db.finish_specs[rec["id"]] = rec
    return respond_object(ser_finish_spec(rec), 201)


@bp.get("/kcma/finish-specs")
def list_finish_specs():
    require_any_role()
    records = list(db.finish_specs.values())
    active = bool_filter(request.args.get("active"))
    if active is not None:
        records = [f for f in records if f["active"] == active]
    sheen = request.args.get("sheen")
    if sheen is not None:
        records = [f for f in records if f["sheen"] == sheen]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_finish_spec(f) for f in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Components / inventory
# ---------------------------------------------------------------------------

@bp.post("/kcma/components")
def create_component():
    require_roles({"PlantAdmin"})
    body = Body(request.get_json(silent=True))
    sku = body.req_str("sku")
    description = body.req_str("description")
    kind = body.req_enum("kind", COMPONENT_KINDS)
    on_hand_qty = body.req_int("on_hand_qty", min_value=0)
    reorder_level = body.opt_int("reorder_level", min_value=0, default=0)
    # Sheet dimensions are required exactly when kind == SHEET_GOODS.
    sheet_width_in = sheet_height_in = None
    if kind == "SHEET_GOODS":
        sheet_width_in = body.req_int("sheet_width_in", min_value=1)
        sheet_height_in = body.req_int("sheet_height_in", min_value=1)
    if sku is not None and any(c["sku"] == sku for c in db.components.values()):
        body.add_error("ERR_DUPLICATE_CODE", f"sku {sku} already exists")
    body.raise_field_errors()

    rec = {
        "id": new_id(),
        "sku": sku,
        "description": description,
        "kind": kind,
        "sheet_width_in": sheet_width_in,
        "sheet_height_in": sheet_height_in,
        "on_hand_qty": on_hand_qty,
        "reserved_qty": 0,
        "reorder_level": reorder_level,
    }
    stamp(rec)
    db.components[rec["id"]] = rec
    return respond_object(ser_component(rec), 201)


@bp.get("/kcma/components")
def list_components():
    require_any_role()
    records = list(db.components.values())
    kind = request.args.get("kind")
    if kind is not None:
        records = [c for c in records if c["kind"] == kind]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_component(c) for c in page], total, limit, offset)


@bp.get("/kcma/components/<componentId>")
def get_component(componentId):
    require_any_role()
    rec = _get_or_404(db.components, componentId, "ERR_COMPONENT_NOT_FOUND")
    return respond_object(ser_component(rec), 200)


@bp.post("/kcma/components/<componentId>/receipts")
def receive_component(componentId):
    require_roles({"ProductionPlanner"})
    component = _get_or_404(db.components, componentId, "ERR_COMPONENT_NOT_FOUND")
    body = Body(request.get_json(silent=True))
    qty = body.req_int("qty", min_value=1)
    body.raise_field_errors()

    component["on_hand_qty"] += qty
    touch(component)
    # Auto-release: availability recovered to >= 0 releases every PLACED
    # COMPONENT_SHORTAGE hold referencing this component.
    if component["on_hand_qty"] - component["reserved_qty"] >= 0:
        from domain import release_hold  # local import to avoid cycle

        for hold in list(db.holds.values()):
            if (
                hold["component_id"] == component["id"]
                and hold["reason"] == "COMPONENT_SHORTAGE"
                and hold["status"] == "PLACED"
            ):
                release_hold(hold)
    return respond_object(ser_component(component), 200)


@bp.get("/kcma/components/<componentId>/holds")
def list_component_holds(componentId):
    require_any_role()
    component = _get_or_404(db.components, componentId, "ERR_COMPONENT_NOT_FOUND")
    records = [h for h in db.holds.values() if h["component_id"] == component["id"]]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_hold(h) for h in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Nesting stations
# ---------------------------------------------------------------------------

@bp.post("/kcma/nesting-stations")
def create_nesting_station():
    require_roles({"PlantAdmin"})
    body = Body(request.get_json(silent=True))
    station_code = body.req_str("station_code")
    changeover_minutes = body.req_int("changeover_minutes", min_value=0)
    active = body.opt_bool("active", default=True)
    if station_code is not None and any(
        s["station_code"] == station_code for s in db.stations.values()
    ):
        body.add_error("ERR_DUPLICATE_CODE", f"station_code {station_code} already exists")
    body.raise_field_errors()

    rec = {
        "id": new_id(),
        "station_code": station_code,
        "changeover_minutes": changeover_minutes,
        "active": active,
    }
    stamp(rec)
    db.stations[rec["id"]] = rec
    return respond_object(ser_nesting_station(rec), 201)


@bp.get("/kcma/nesting-stations")
def list_nesting_stations():
    require_any_role()
    page, total, limit, offset = paginate(sort_records(list(db.stations.values())))
    return respond_list([ser_nesting_station(s) for s in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Assembly lines
# ---------------------------------------------------------------------------

@bp.post("/kcma/assembly-lines")
def create_assembly_line():
    require_roles({"PlantAdmin"})
    body = Body(request.get_json(silent=True))
    line_code = body.req_str("line_code")
    capacity_minutes_per_day = body.req_int("capacity_minutes_per_day", min_value=1)
    standard_minutes_per_box = body.req_int("standard_minutes_per_box", min_value=1)
    setup_minutes_per_sub_lot = body.req_int("setup_minutes_per_sub_lot", min_value=0)
    active = body.opt_bool("active", default=True)
    if line_code is not None and any(
        a["line_code"] == line_code for a in db.assembly_lines.values()
    ):
        body.add_error("ERR_DUPLICATE_CODE", f"line_code {line_code} already exists")
    body.raise_field_errors()

    rec = {
        "id": new_id(),
        "line_code": line_code,
        "capacity_minutes_per_day": capacity_minutes_per_day,
        "standard_minutes_per_box": standard_minutes_per_box,
        "setup_minutes_per_sub_lot": setup_minutes_per_sub_lot,
        "active": active,
    }
    stamp(rec)
    db.assembly_lines[rec["id"]] = rec
    return respond_object(ser_assembly_line(rec), 201)


@bp.get("/kcma/assembly-lines")
def list_assembly_lines():
    require_any_role()
    page, total, limit, offset = paginate(sort_records(list(db.assembly_lines.values())))
    return respond_list([ser_assembly_line(a) for a in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Logical clock (test-driving; PlantAdmin only)
# ---------------------------------------------------------------------------

@bp.post("/kcma/_clock/set_current_utc")
def set_current_utc():
    require_roles({"PlantAdmin"})
    body = Body(request.get_json(silent=True))
    to_dt = body.req_datetime_utc("to_iso8601")
    body.raise_field_errors()
    db.clock = to_dt
    return respond_object({"current_utc": fmt_ts(db.clock)}, 200)
