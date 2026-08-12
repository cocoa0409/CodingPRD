"""Card program, peak calendar, and blackout window endpoints."""

from flask import Blueprint, request

from httpkit import (
    ApiError, authenticate, ensure_empty_body, err_invalid_request,
    err_not_found, get_body, paginate, require_roles, respond_object,
    sorted_items,
)
from serializers import blackout_window_json, peak_window_json, program_json
from services import new_common
from store import db

bp = Blueprint("programs", __name__)

CATEGORIES = ["LIGHT", "MIDSIZE", "SUPER_MID", "HEAVY"]

PROGRAM_FIELDS = [
    {"name": "program_code", "type": "string", "required": True},
    {"name": "aircraft_category", "type": "enum", "values": CATEGORIES, "required": True},
    {"name": "hours_purchased", "type": "integer", "required": True},
    {"name": "purchase_price_cents", "type": "integer", "required": True},
    {"name": "swap_ratio_to_lower", "type": "number", "required": True},
    {"name": "swap_ratio_to_higher", "type": "number", "required": True},
    {"name": "expiry_months", "type": "integer", "required": True},
    {"name": "taxi_minutes_per_leg", "type": "integer", "required": True},
    {"name": "min_billable_minutes_per_leg", "type": "integer", "required": True},
    {"name": "peak_surcharge_pct", "type": "number", "required": True},
    {"name": "availability_window_hours", "type": "integer", "required": True},
    {"name": "round_trip_discount_pct", "type": "number", "required": True},
    {"name": "early_termination_penalty_pct", "type": "number", "required": True},
    {"name": "fractional_upgrade_ratio", "type": "number", "required": True},
]


def _get_program_or_404(program_id):
    p = db.programs.get(program_id)
    if p is None:
        raise err_not_found(f"CardProgram {program_id} does not exist")
    return p


@bp.post("/programs")
def create_program():
    data = get_body(PROGRAM_FIELDS)
    authenticate()
    require_roles("Ops")
    for existing in db.programs.values():
        if existing["program_code"] == data["program_code"]:
            raise err_invalid_request("program_code must be unique")
    p = new_common()
    p.update({f["name"]: data[f["name"]] for f in PROGRAM_FIELDS})
    db.programs[p["id"]] = p
    return respond_object(program_json(p), 201)


@bp.get("/programs/<programId>")
def get_program(programId):
    authenticate()
    require_roles("Ops", "Member", "Anonymous")
    p = _get_program_or_404(programId)
    return respond_object(program_json(p))


@bp.get("/programs")
def list_programs():
    authenticate()
    require_roles("Ops", "Member", "Anonymous")
    items = sorted_items(db.programs.values())
    flt = request.args.get("aircraft_category")
    if flt is not None:
        items = [p for p in items if p["aircraft_category"] == flt]
    return paginate([program_json(p) for p in items])


@bp.post("/programs/<programId>/peak_windows")
def create_peak_window(programId):
    data = get_body([
        {"name": "window_start_utc", "type": "datetime", "required": True},
        {"name": "window_end_utc", "type": "datetime", "required": True},
        {"name": "label", "type": "string", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    _get_program_or_404(programId)
    w = new_common()
    w.update({
        "program_id": programId,
        "window_start_utc": data["window_start_utc"],
        "window_end_utc": data["window_end_utc"],
        "label": data["label"],
    })
    db.peak_windows[w["id"]] = w
    return respond_object(peak_window_json(w), 201)


@bp.get("/programs/<programId>/peak_windows")
def list_peak_windows(programId):
    authenticate()
    require_roles("Ops", "Member", "Anonymous")
    _get_program_or_404(programId)
    items = sorted_items(
        w for w in db.peak_windows.values() if w["program_id"] == programId)
    return paginate([peak_window_json(w) for w in items])


@bp.post("/programs/<programId>/blackout_windows")
def create_blackout_window(programId):
    data = get_body([
        {"name": "window_start_utc", "type": "datetime", "required": True},
        {"name": "window_end_utc", "type": "datetime", "required": True},
        {"name": "applies_to_category", "type": "enum", "values": CATEGORIES,
         "required": True},
        {"name": "reason", "type": "string", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    _get_program_or_404(programId)
    w = new_common()
    w.update({
        "program_id": programId,
        "window_start_utc": data["window_start_utc"],
        "window_end_utc": data["window_end_utc"],
        "applies_to_category": data["applies_to_category"],
        "reason": data["reason"],
    })
    db.blackout_windows[w["id"]] = w
    return respond_object(blackout_window_json(w), 201)


@bp.get("/programs/<programId>/blackout_windows")
def list_blackout_windows(programId):
    authenticate()
    require_roles("Ops", "Member", "Anonymous")
    _get_program_or_404(programId)
    items = sorted_items(
        w for w in db.blackout_windows.values() if w["program_id"] == programId)
    flt = request.args.get("applies_to_category")
    if flt is not None:
        items = [w for w in items if w["applies_to_category"] == flt]
    return paginate([blackout_window_json(w) for w in items])


# --- FK reverse-reachability reads -----------------------------------------

@bp.get("/programs/<id>/jet_cards")
def list_program_jet_cards(id):
    from serializers import card_json
    from httpkit import require_member_ownership
    authenticate()
    require_roles("Ops", "Member")
    _get_program_or_404(id)
    items = sorted_items(
        c for c in db.cards.values() if c["program_id"] == id)
    from flask import g
    if g.role == "Member":
        items = [c for c in items if c["member_id"] == g.user_id]
    return paginate([card_json(c) for c in items])


@bp.get("/programs/<id>/peak_calendars")
def list_program_peak_calendars(id):
    authenticate()
    require_roles("Ops", "Member")
    _get_program_or_404(id)
    items = sorted_items(
        w for w in db.peak_windows.values() if w["program_id"] == id)
    return paginate([peak_window_json(w) for w in items])


@bp.get("/programs/<id>/blackout_windows_fk")
def list_program_blackout_windows_fk(id):
    authenticate()
    require_roles("Ops", "Member")
    _get_program_or_404(id)
    items = sorted_items(
        w for w in db.blackout_windows.values() if w["program_id"] == id)
    flt = request.args.get("applies_to_category")
    if flt is not None:
        items = [w for w in items if w["applies_to_category"] == flt]
    return paginate([blackout_window_json(w) for w in items])
