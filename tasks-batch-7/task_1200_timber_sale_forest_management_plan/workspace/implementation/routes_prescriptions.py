"""Harvest prescriptions with the PROPOSED<->APPROVED revision loop."""
from flask import Blueprint, g

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_date, f_enum, bad_request, err, paginate, get_stand, get_cruise,
    get_prescription, parse_date_str, check_transition,
)

bp = Blueprint("prescriptions", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

METHODS = {"CLEARCUT", "SHELTERWOOD", "SEED_TREE", "SELECTION",
           "COMMERCIAL_THINNING"}
RX_TERMINAL = {"COMPLETED", "WITHDRAWN"}


def _check_window(start, end):
    if parse_date_str(end) <= parse_date_str(start):
        bad_request("window_end must be after window_start")


def _owning_tract(p):
    stand = db["stands"][p["stand_id"]]
    return db["tracts"][stand["tract_id"]]


@bp.route("/forestry/prescriptions", methods=["POST"])
@require_roles("Forester")
def create_prescription():
    body = get_body()
    st = body.get("stand_id")
    if isinstance(st, str):
        get_stand(st)
    cr = body.get("cruise_id")
    if isinstance(cr, str):
        get_cruise(cr)
    check_known(body, {"stand_id", "cruise_id", "silvicultural_method",
                       "window_start", "window_end"})
    stand_id = f_str(body, "stand_id")
    get_stand(stand_id)
    cruise_id = f_str(body, "cruise_id")
    get_cruise(cruise_id)
    method = f_enum(body, "silvicultural_method", METHODS)
    ws = f_date(body, "window_start")
    we = f_date(body, "window_end")
    _check_window(ws, we)
    ent = new_common({
        "stand_id": stand_id,
        "cruise_id": cruise_id,
        "silvicultural_method": method,
        "window_start": ws,
        "window_end": we,
        "status": "DRAFT",
    })
    db["prescriptions"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/prescriptions/<pid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_prescription_ep(pid):
    return success(pub(get_prescription(pid)), 200)


@bp.route("/forestry/prescriptions", methods=["GET"])
@require_roles(*READ_ROLES)
def list_prescriptions():
    page, meta = paginate(db["prescriptions"].values(), {
        "stand_id": "stand_id",
        "cruise_id": "cruise_id",
        "status": "status",
    })
    return success([pub(p) for p in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/prescriptions/<pid>/propose", methods=["POST"])
@require_roles("Forester")
def propose(pid):
    p = get_prescription(pid)
    body = get_body()
    check_known(body, set())
    check_transition(p, {"DRAFT"}, RX_TERMINAL, "prescription")
    p["status"] = "PROPOSED"
    bump(p)
    return success(pub(p), 200)


@bp.route("/forestry/prescriptions/<pid>/approve", methods=["POST"])
@require_roles("Landowner")
def approve(pid):
    p = get_prescription(pid)
    body = get_body()
    check_known(body, set())
    # ownership (layer 3) precedes state (layer 6)
    tract = _owning_tract(p)
    if tract["landowner_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "landowner does not own this tract")
    check_transition(p, {"PROPOSED"}, RX_TERMINAL, "prescription")
    cruise = db["cruises"][p["cruise_id"]]
    if cruise["status"] != "CERTIFIED":
        err("ERR_CRUISE_NOT_CERTIFIED", 409, "cruise is not CERTIFIED")
    p["status"] = "APPROVED"
    bump(p)
    return success(pub(p), 200)


@bp.route("/forestry/prescriptions/<pid>/revise", methods=["POST"])
@require_roles("Forester")
def revise(pid):
    p = get_prescription(pid)
    body = get_body()
    check_known(body, {"window_start", "window_end", "silvicultural_method"})
    ws = f_date(body, "window_start", required=False)
    we = f_date(body, "window_end", required=False)
    method = f_enum(body, "silvicultural_method", METHODS, required=False)
    check_transition(p, {"APPROVED"}, RX_TERMINAL, "prescription")
    new_ws = ws if ws is not None else p["window_start"]
    new_we = we if we is not None else p["window_end"]
    _check_window(new_ws, new_we)
    p["window_start"] = new_ws
    p["window_end"] = new_we
    if method is not None:
        p["silvicultural_method"] = method
    p["status"] = "PROPOSED"
    bump(p)
    return success(pub(p), 200)


@bp.route("/forestry/prescriptions/<pid>/activate", methods=["POST"])
@require_roles("Forester")
def activate(pid):
    p = get_prescription(pid)
    body = get_body()
    check_known(body, set())
    check_transition(p, {"APPROVED"}, RX_TERMINAL, "prescription")
    start = parse_date_str(p["window_start"])
    end = parse_date_str(p["window_end"])
    for other in db["prescriptions"].values():
        if other["id"] == p["id"] or other["stand_id"] != p["stand_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        o_start = parse_date_str(other["window_start"])
        o_end = parse_date_str(other["window_end"])
        # half-open overlap: touching endpoints do NOT overlap
        if start < o_end and o_start < end:
            err("ERR_STAND_WINDOW_OVERLAP", 409,
                "overlaps an ACTIVE prescription on this stand")
    p["status"] = "ACTIVE"
    bump(p)
    return success(pub(p), 200)


@bp.route("/forestry/prescriptions/<pid>/complete", methods=["POST"])
@require_roles("Forester")
def complete(pid):
    p = get_prescription(pid)
    body = get_body()
    check_known(body, set())
    check_transition(p, {"ACTIVE"}, RX_TERMINAL, "prescription")
    p["status"] = "COMPLETED"
    bump(p)
    return success(pub(p), 200)


@bp.route("/forestry/prescriptions/<pid>/withdraw", methods=["POST"])
@require_roles("Forester")
def withdraw(pid):
    p = get_prescription(pid)
    body = get_body()
    check_known(body, set())
    check_transition(p, {"DRAFT", "PROPOSED", "APPROVED"}, RX_TERMINAL,
                     "prescription")
    p["status"] = "WITHDRAWN"
    bump(p)
    return success(pub(p), 200)
