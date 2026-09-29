"""Carpet styles, tufting machines and dye vessels (PRD 3.3, 3.6)."""

from flask import Blueprint

from db import insert, store, touch
from errors import ApiError
from response import obj
from routes.common import authenticate, created, fetch, listing, ok, unique
from services import cascades, compliance
from validators import (
    bad,
    json_body,
    opt_enum,
    opt_num,
    opt_str,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("styles", __name__)

LINE_TYPES = ("RUNNING_LINE", "CUSTOM")
GAUGE_CODES = ("G_1_8", "G_1_10", "G_5_64")
PILE_CONSTRUCTIONS = ("CUT", "LOOP")
STYLE_DYE_METHODS = ("SOLUTION_DYED", "PIECE_DYED")
STYLE_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "RUNOUT", "DISCONTINUED")
MACHINE_STATUSES = ("IDLE", "MAINTENANCE")
VESSEL_TYPES = ("BECK", "JET")
VESSEL_STATUSES = ("AVAILABLE", "MAINTENANCE")

STYLE_READ_ROLES = (
    "MillPlanner",
    "CertificationOfficer",
    "DyeHouseOperator",
    "QALabTechnician",
    "DealerBuyer",
    "PlantAdmin",
)
PLANNER_ROLES = ("MillPlanner", "PlantAdmin")
VESSEL_ROLES = ("MillPlanner", "DyeHouseOperator", "PlantAdmin")


def _check_colour_coherence(dye_method, solution_color_code):
    """Rung 16 — the solution_color_code presence rule."""
    if dye_method == "SOLUTION_DYED":
        if not solution_color_code:
            raise ApiError(
                "ERR_DYE_METHOD_COLOR_MISMATCH",
                "A SOLUTION_DYED style must carry a solution_color_code",
            )
    elif solution_color_code:
        raise ApiError(
            "ERR_DYE_METHOD_COLOR_MISMATCH",
            "solution_color_code is only valid on a SOLUTION_DYED style",
        )


@bp.post("/mill/styles")
def draft_style():
    authenticate(PLANNER_ROLES)
    body = json_body()
    style_code = req_str(body, "style_code")
    line_type = req_enum(body, "line_type", LINE_TYPES)
    gauge_code = req_enum(body, "gauge_code", GAUGE_CODES)
    pile_construction = req_enum(body, "pile_construction", PILE_CONSTRUCTIONS)
    pile_height_mm = req_num(body, "pile_height_mm", 1, gt=0)
    pattern_repeat_mm = req_num(body, "pattern_repeat_mm", 1, gt=0)
    plies = req_int(body, "plies", ge=1)
    target_face_weight_oz = req_num(body, "target_face_weight_oz", 2, gt=0)
    dye_method = req_enum(body, "dye_method", STYLE_DYE_METHODS)
    list_price_cents_per_yard = req_int(body, "list_price_cents_per_yard", gt=0)
    solution_color_code = opt_str(body, "solution_color_code")

    unique("styles", "style_code", style_code)
    _check_colour_coherence(dye_method, solution_color_code)

    style = insert(
        store.styles,
        {
            "style_code": style_code,
            "line_type": line_type,
            "gauge_code": gauge_code,
            "pile_construction": pile_construction,
            "pile_height_mm": pile_height_mm,
            "pattern_repeat_mm": pattern_repeat_mm,
            "plies": plies,
            "target_face_weight_oz": target_face_weight_oz,
            "dye_method": dye_method,
            "solution_color_code": solution_color_code,
            "list_price_cents_per_yard": list_price_cents_per_yard,
            "open_backorder_yards": 0.0,
            "replenishment_flag": "NONE",
            "status": "DRAFT",
        },
    )
    return created("style", style)


@bp.post("/mill/styles/<style_id>/activate")
def activate_style(style_id):
    authenticate(PLANNER_ROLES)
    style = fetch("styles", style_id)
    if style["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT style may be activated")
    _check_colour_coherence(style["dye_method"], style.get("solution_color_code"))
    style["status"] = "ACTIVE"
    touch(style)
    return ok("style", style)


@bp.post("/mill/styles/<style_id>/discontinue")
def discontinue_style(style_id):
    authenticate(PLANNER_ROLES)
    body = json_body()
    opt_str(body, "reason")
    style = fetch("styles", style_id)
    if style["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE or SUSPENDED style may be discontinued",
        )
    cascades.discontinue_style(style)
    return ok("style", style)


@bp.get("/mill/styles/<style_id>")
def read_style(style_id):
    authenticate(STYLE_READ_ROLES)
    return ok("style", fetch("styles", style_id))


@bp.get("/mill/styles")
def list_styles():
    authenticate(STYLE_READ_ROLES)
    return listing(
        "style",
        "styles",
        enum_filters={
            "status": STYLE_STATUSES,
            "line_type": LINE_TYPES,
            "dye_method": STYLE_DYE_METHODS,
        },
    )


@bp.get("/mill/styles/<style_id>/recycled-content")
def read_recycled_content(style_id):
    authenticate(("MillPlanner", "CertificationOfficer", "PlantAdmin"))
    style = fetch("styles", style_id)
    return obj(compliance.recycled_content(style["id"]))


# ---- tufting machines -----------------------------------------------------

@bp.post("/mill/tufting-machines")
def register_machine():
    authenticate(PLANNER_ROLES)
    body = json_body()
    machine_code = req_str(body, "machine_code")
    native_gauge_code = req_enum(body, "native_gauge_code", GAUGE_CODES)
    min_pile_height_mm = req_num(body, "min_pile_height_mm", 1, gt=0)
    max_pile_height_mm = req_num(body, "max_pile_height_mm", 1, gt=0)
    changeover_minutes = req_int(body, "changeover_minutes", ge=0)
    needle_bar_width_in = req_num(body, "needle_bar_width_in", 1, gt=0)
    status = opt_enum(body, "status", MACHINE_STATUSES, default="IDLE")

    if not max_pile_height_mm > min_pile_height_mm:
        bad("max_pile_height_mm must be strictly greater than min_pile_height_mm")

    unique("machines", "machine_code", machine_code)

    machine = insert(
        store.machines,
        {
            "machine_code": machine_code,
            "native_gauge_code": native_gauge_code,
            "min_pile_height_mm": min_pile_height_mm,
            "max_pile_height_mm": max_pile_height_mm,
            "changeover_minutes": changeover_minutes,
            "needle_bar_width_in": needle_bar_width_in,
            "status": status,
        },
    )
    return created("machine", machine)


@bp.get("/mill/tufting-machines/<machine_id>")
def read_machine(machine_id):
    authenticate(PLANNER_ROLES)
    return ok("machine", fetch("machines", machine_id))


@bp.get("/mill/tufting-machines")
def list_machines():
    authenticate(PLANNER_ROLES)
    return listing(
        "machine",
        "machines",
        enum_filters={"status": MACHINE_STATUSES, "native_gauge_code": GAUGE_CODES},
    )


# ---- dye vessels ---------------------------------------------------------

@bp.post("/mill/dye-vessels")
def register_vessel():
    authenticate(VESSEL_ROLES)
    body = json_body()
    vessel_code = req_str(body, "vessel_code")
    vessel_type = req_enum(body, "vessel_type", VESSEL_TYPES)
    capacity_kg = req_num(body, "capacity_kg", 1, gt=0)
    status = opt_enum(body, "status", VESSEL_STATUSES, default="AVAILABLE")

    unique("vessels", "vessel_code", vessel_code)

    vessel = insert(
        store.vessels,
        {
            "vessel_code": vessel_code,
            "vessel_type": vessel_type,
            "capacity_kg": capacity_kg,
            "status": status,
        },
    )
    return created("vessel", vessel)


@bp.get("/mill/dye-vessels/<vessel_id>")
def read_vessel(vessel_id):
    authenticate(VESSEL_ROLES)
    return ok("vessel", fetch("vessels", vessel_id))


@bp.get("/mill/dye-vessels")
def list_vessels():
    authenticate(VESSEL_ROLES)
    return listing(
        "vessel",
        "vessels",
        enum_filters={"status": VESSEL_STATUSES, "vessel_type": VESSEL_TYPES},
    )
