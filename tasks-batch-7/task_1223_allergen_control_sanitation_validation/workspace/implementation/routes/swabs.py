from flask import Blueprint, request

from db import CLOCK, db, new_entity, public
from errors import ApiError
from logic import converge_changeover, get_or_404
from middleware import require_roles
from response import ok, ok_list
from util import body, opt_str, parse_dt, req_enum, req_num, req_str

bp = Blueprint("swabs", __name__)

SWAB_TYPES = ("ATP", "ALLERGEN_PROTEIN", "ALLERGEN_ELISA")
READ_ROLES = ("QaManager", "QaSupervisor", "QaTechnician", "Auditor")


@bp.post("/qa/changeovers/<changeoverId>/swab-results")
@require_roles("QaTechnician")
def create_swab(changeoverId):
    changeover = get_or_404("changeovers", changeoverId)
    b = body()
    zone_code = req_str(b, "zone_code")
    swab_type = req_enum(b, "swab_type", SWAB_TYPES)
    measured = req_num(b, "measured_value")
    invalidated_reason = opt_str(b, "invalidated_reason")
    tech = get_or_404("technicians", req_str(b, "recorded_by_id"))
    if changeover["status"] != "SWAB_PENDING":
        raise ApiError("ERR_SWAB_NOT_PENDING", 409,
                       "Changeover is not in SWAB_PENDING")
    if tech["status"] != "ACTIVE":
        raise ApiError("ERR_TECH_NOT_ACTIVE", 403,
                       "Technician is not ACTIVE")
    procedure = get_or_404("procedures", changeover["procedure_id"])
    if (procedure["target_allergen_id"] not in tech["certified_allergen_ids"]
            or CLOCK["current"] > parse_dt(tech["certification_expiry_utc"])):
        raise ApiError("ERR_TECH_NOT_CERTIFIED", 403,
                       "Technician is not certified for the procedure's target allergen "
                       "or certification has expired")
    if swab_type == "ATP":
        action_level = procedure["atp_action_level_rlu"]
    else:
        action_level = procedure["allergen_action_level_ppm"]
    if invalidated_reason:
        outcome = "INVALIDATED"
    elif float(measured) < float(action_level):
        outcome = "PASS"
    else:
        outcome = "FAIL"
    ent = new_entity({
        "changeover_id": changeover["id"],
        "zone_code": zone_code,
        "swab_type": swab_type,
        "measured_value": measured,
        "action_level_used": action_level,
        "outcome": outcome,
        "invalidated_reason": invalidated_reason if outcome == "INVALIDATED" else None,
        "recorded_by_id": tech["id"],
    })
    db["swabs"][ent["id"]] = ent
    if changeover["status"] == "SWAB_PENDING":
        converge_changeover(changeover)
    return ok(public(ent), 201)


@bp.get("/qa/swab-results")
@require_roles(*READ_ROLES)
def list_swabs():
    items = list(db["swabs"].values())
    for param in ("changeover_id", "outcome", "recorded_by_id"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(param) == v]
    return ok_list(items)


@bp.get("/qa/swab-results/<swabId>")
@require_roles(*READ_ROLES)
def get_swab(swabId):
    return ok(public(get_or_404("swabs", swabId)))
