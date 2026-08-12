"""SyrupLot and FlavorEvaluation endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role, enforce_entity_identity
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_int, as_str,
                  as_number, d, round2, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_LOT_NOT_GRADABLE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_GRADER_NOT_CERTIFIED, ERR_CREW_NOT_ACTIVE)
from services import core

bp = Blueprint("syrup_lots", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}
GRADERS = {"SugarhouseManager", "SugarMaker"}


def get_lot_or_404(lid):
    l = db.syrup_lots.get(lid)
    if not l:
        raise_err(ERR_NOT_FOUND, f"syrup lot {lid} not found")
    return l


@bp.get("/sugarhouse/syrup-lots/<lid>")
def get_lot(lid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    lot = get_lot_or_404(lid)
    return success_object(core.ser_syrup_lot(lot))


@bp.get("/sugarhouse/syrup-lots")
def list_lots():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    batch_id = request.args.get("batch_id")
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    rows = list(db.syrup_lots.values())
    if batch_id is not None:
        rows = [r for r in rows if r["batch_id"] == batch_id]
    if season_id is not None:
        rows = [r for r in rows if r["season_id"] == season_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_syrup_lot(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/syrup-lots/<lid>/grade")
def grade_lot(lid):
    caller = authenticate()
    require_role(caller, GRADERS)
    lot = get_lot_or_404(lid)
    data = body_json()
    check_unknown_fields(data, {"light_transmittance_pct"})
    require_fields(data, ["light_transmittance_pct"])
    light_transmittance_pct = as_number(data["light_transmittance_pct"],
                                        "light_transmittance_pct",
                                        minimum=0, maximum=100)
    if lot["status"] not in ("UNGRADED", "HELD"):
        raise_err(ERR_INVALID_STATE,
                  f"lot is {lot['status']}, expected UNGRADED or HELD")
    latest = core.latest_evaluation(lot["id"])
    if not latest:
        raise_err(ERR_LOT_NOT_GRADABLE, "no flavor evaluation on this lot")
    lot["grade"] = core.classify_grade(light_transmittance_pct, latest)
    lot["light_transmittance_pct"] = light_transmittance_pct
    lot["status"] = "GRADED"
    core.bump(lot)
    return success_object(core.ser_syrup_lot(lot))


@bp.post("/sugarhouse/syrup-lots/<lid>/hold")
def hold_lot(lid):
    caller = authenticate()
    require_role(caller, MGR)
    lot = get_lot_or_404(lid)
    if lot["status"] not in ("UNGRADED", "GRADED"):
        raise_err(ERR_INVALID_STATE,
                  f"lot is {lot['status']}, expected UNGRADED or GRADED")
    lot["status"] = "HELD"
    core.bump(lot)
    return success_object(core.ser_syrup_lot(lot))


@bp.post("/sugarhouse/syrup-lots/<lid>/condemn")
def condemn_lot(lid):
    caller = authenticate()
    require_role(caller, MGR)
    lot = get_lot_or_404(lid)
    if lot["status"] not in ("UNGRADED", "HELD"):
        raise_err(ERR_INVALID_STATE,
                  f"lot is {lot['status']}, expected UNGRADED or HELD")
    lot["status"] = "CONDEMNED"
    core.bump(lot)
    return success_object(core.ser_syrup_lot(lot))


# ---------------- Flavor evaluations (sub-resource) ----------------

@bp.post("/sugarhouse/syrup-lots/<lid>/evaluations")
def record_evaluation(lid):
    caller = authenticate()
    require_role(caller, GRADERS)
    lot = get_lot_or_404(lid)
    data = body_json()
    check_unknown_fields(data, {"evaluator_id", "flavor_score", "defect_flags"})
    require_fields(data, ["evaluator_id", "flavor_score"])
    evaluator_id = as_str(data["evaluator_id"], "evaluator_id")
    flavor_score = as_int(data["flavor_score"], "flavor_score", minimum=0, maximum=100)
    defect_flags = data.get("defect_flags", [])
    if not isinstance(defect_flags, list) or not all(isinstance(x, str) for x in defect_flags):
        raise_err(ERR_VALIDATION, "defect_flags must be a list of strings")

    # Priority 2: entity-backed identity (SugarMaker evaluator_id == X-User-ID)
    enforce_entity_identity(caller, evaluator_id, "evaluator_id")

    # Priority 3: evaluator exists
    evaluator = db.crew_members.get(evaluator_id)
    if not evaluator:
        raise_err(ERR_NOT_FOUND, f"crew member {evaluator_id} not found")

    # Priority 5: lot state + evaluator crew state
    if lot["status"] in ("CONDEMNED", "EXHAUSTED"):
        raise_err(ERR_LOT_NOT_GRADABLE,
                  f"lot is {lot['status']} (terminal); cannot evaluate")
    if evaluator["status"] != "ACTIVE" or evaluator["crew_role"] != "GRADER":
        raise_err(ERR_CREW_NOT_ACTIVE,
                  "evaluator must be an ACTIVE crew member with crew_role GRADER")

    # Priority 6: compliance gates
    batch = db.batches.get(lot["batch_id"])
    if not batch:
        raise_err(ERR_NOT_FOUND, f"batch {lot['batch_id']} not found")
    if evaluator_id == batch["boiled_by"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "evaluator may not be the batch's boiled_by")
    # organic gate: if batch drew from any organic_certified bush
    contributing = core.bushes_contributing_to_batch(batch["id"])
    organic_involved = False
    for bush_id in contributing:
        bush = db.sugarbushes.get(bush_id)
        if bush and bush["organic_certified"]:
            organic_involved = True
            break
    if organic_involved and not evaluator["cert_organic_handler"]:
        raise_err(ERR_GRADER_NOT_CERTIFIED,
                  "lot from organic_certified bush requires cert_organic_handler evaluator")

    ev = core.new_flavor_evaluation(lot["id"], evaluator_id, flavor_score, defect_flags)
    db.flavor_evaluations[ev["id"]] = ev
    return success_object(core.ser_flavor_evaluation(ev), status=201)


@bp.get("/sugarhouse/syrup-lots/<lid>/evaluations")
def list_evaluations(lid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    lot = get_lot_or_404(lid)
    limit, offset = parse_pagination(request.args)
    rows = [e for e in db.flavor_evaluations.values() if e["syrup_lot_id"] == lot["id"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_flavor_evaluation(r) for r in page], limit, offset, total)
