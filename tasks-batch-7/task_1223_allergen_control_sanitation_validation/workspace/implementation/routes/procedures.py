from flask import Blueprint, request

from db import db, new_entity, public, touch
from errors import ApiError
from logic import get_or_404
from middleware import require_roles
from response import ok, ok_list
from util import body, req_enum, req_int, req_num, req_str

bp = Blueprint("procedures", __name__)

METHODS = ("FULL_WET_WASH", "DRY_SCRAPE", "PURGE", "VACUUM_ONLY")
READ_ROLES = ("QaManager", "QaSupervisor", "QaTechnician", "Auditor")
ACTIVE_CHANGEOVER_STATES = ("PLANNED", "IN_EXECUTION", "SWAB_PENDING",
                            "REWORK_REQUIRED")


@bp.post("/qa/changeover-procedures")
@require_roles("QaManager")
def create_procedure():
    b = body()
    procedure_code = req_str(b, "procedure_code")
    allergen = get_or_404("allergens", req_str(b, "target_allergen_id"))
    method = req_enum(b, "method", METHODS)
    min_swab_zones = req_int(b, "min_swab_zones")
    atp_level = req_int(b, "atp_action_level_rlu")
    ppm_level = req_num(b, "allergen_action_level_ppm")
    family = [p for p in db["procedures"].values()
              if p["procedure_code"] == procedure_code]
    version_seq = max([p["version_seq"] for p in family], default=0) + 1
    ent = new_entity({
        "procedure_code": procedure_code,
        "target_allergen_id": allergen["id"],
        "method": method,
        "min_swab_zones": min_swab_zones,
        "atp_action_level_rlu": atp_level,
        "allergen_action_level_ppm": ppm_level,
        "version_seq": version_seq,
        "is_current": False,
        "status": "DRAFT",
    })
    db["procedures"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/changeover-procedures")
@require_roles(*READ_ROLES)
def list_procedures():
    code = request.args.get("procedure_code")
    target = request.args.get("target_allergen_id")
    status = request.args.get("status")
    items = list(db["procedures"].values())
    if code is not None:
        items = [p for p in items if p["procedure_code"] == code]
    if target is not None:
        items = [p for p in items if p["target_allergen_id"] == target]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return ok_list(items)


@bp.get("/qa/changeover-procedures/<procedureId>")
@require_roles(*READ_ROLES)
def get_procedure(procedureId):
    return ok(public(get_or_404("procedures", procedureId)))


@bp.post("/qa/changeover-procedures/<procedureId>/approve")
@require_roles("QaManager")
def approve_procedure(procedureId):
    b = body()
    proc = get_or_404("procedures", procedureId)
    expected = req_int(b, "expected_procedure_version")
    if expected != proc["version"]:
        raise ApiError("ERR_STALE_PROCEDURE_VERSION", 412,
                       "expected_procedure_version does not match current version")
    if proc["status"] != "DRAFT":
        raise ApiError("ERR_PROCEDURE_NOT_DRAFT", 409, "Procedure is not in DRAFT")
    if (proc["min_swab_zones"] < 1 or proc["atp_action_level_rlu"] <= 0
            or proc["allergen_action_level_ppm"] <= 0):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Validation parameters must be positive (min_swab_zones >= 1)")
    for sibling in db["procedures"].values():
        if (sibling["id"] != proc["id"]
                and sibling["procedure_code"] == proc["procedure_code"]
                and sibling["status"] == "APPROVED"):
            sibling["status"] = "SUPERSEDED"
            sibling["is_current"] = False
            touch(sibling)
    proc["status"] = "APPROVED"
    proc["is_current"] = True
    touch(proc)
    return ok(public(proc))


@bp.post("/qa/changeover-procedures/<procedureId>/retire")
@require_roles("QaManager")
def retire_procedure(procedureId):
    proc = get_or_404("procedures", procedureId)
    if proc["status"] != "APPROVED":
        raise ApiError("ERR_PROCEDURE_NOT_APPROVED", 409,
                       "Procedure is not in APPROVED")
    for c in db["changeovers"].values():
        if (c["procedure_id"] == proc["id"]
                and c["status"] in ACTIVE_CHANGEOVER_STATES):
            raise ApiError("ERR_PROCEDURE_IN_USE", 409,
                           "An active changeover references this procedure")
    proc["status"] = "RETIRED"
    proc["is_current"] = False
    touch(proc)
    return ok(public(proc))
