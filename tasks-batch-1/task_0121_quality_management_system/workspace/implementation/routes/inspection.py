"""InspectionPlan and InspectionLot routes (PRD 3.1, 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

from common import (require_enum, require_fields, require_non_negative_int,
                    require_string, stamp_create, touch)
from db import db
from errors import (ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, err)
from middleware import (ROLE_INSPECTOR, ROLE_QUALITY_MANAGER,
                        authenticate, require_role)
from response import list_success, success
from services.calculations import aql_sampling
from services.helpers import (get_or_404, paginate, paginate_args,
                              recompute_supplier_rating)
from services.serializers import inspection_lot_out, inspection_plan_out

bp = Blueprint("inspection", __name__)

ALLOWED_AQL = {Decimal("0.65"), Decimal("1.0"), Decimal("1.5"),
               Decimal("2.5"), Decimal("4.0"), Decimal("6.5")}
INSPECTION_LEVELS = {"GI", "GII", "GIII"}
LOT_ACTIONS = {"START", "DISPOSITION"}


@bp.route("/inspection-plans", methods=["POST"])
def create_inspection_plan():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    body = request.get_json(silent=True) or {}

    # FK resolution (priority 4).
    control_plan_id = body.get("control_plan_id")
    if control_plan_id is not None and control_plan_id not in db.control_plans:
        raise err(ERR_FK_NOT_FOUND, "control_plan_id does not resolve")

    # Well-formedness (priority 5).
    require_fields(body, ["name", "control_plan_id", "part_number", "lot_size", "aql_pct"])
    require_string(body["name"], "name")
    require_string(body["part_number"], "part_number")
    require_non_negative_int(body["lot_size"], "lot_size", minimum=1)

    aql_raw = body["aql_pct"]
    if not isinstance(aql_raw, (int, float)) or isinstance(aql_raw, bool):
        raise err(ERR_INVALID_REQUEST, "aql_pct must be a number")
    aql_dec = Decimal(str(aql_raw))
    if aql_dec not in ALLOWED_AQL:
        raise err(ERR_INVALID_REQUEST, "aql_pct not in permitted set")

    level = body.get("inspection_level", "GII")
    if level is None:
        level = "GII"
    require_enum(level, INSPECTION_LEVELS, "inspection_level")

    rec = {
        "name": body["name"],
        "control_plan_id": control_plan_id,
        "part_number": body["part_number"],
        "lot_size": body["lot_size"],
        "aql_pct": aql_dec,
        "inspection_level": level,
        "severity_mode": "NORMAL",
        "consecutive_rejects": 0,
        "needs_review": False,
    }
    stamp_create(rec)
    db.inspection_plans[rec["id"]] = rec
    return success(inspection_plan_out(rec), status=201)


@bp.route("/inspection-plans/<rid>", methods=["GET"])
def get_inspection_plan(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_INSPECTOR})
    rec = get_or_404(db.inspection_plans, rid)
    return success(inspection_plan_out(rec))


@bp.route("/inspection-lots", methods=["POST"])
def create_inspection_lot():
    auth = authenticate()
    require_role(auth, {ROLE_INSPECTOR})
    body = request.get_json(silent=True) or {}

    # FK resolution (priority 4).
    inspection_plan_id = body.get("inspection_plan_id")
    supplier_id = body.get("supplier_id")
    if inspection_plan_id is not None and inspection_plan_id not in db.inspection_plans:
        raise err(ERR_FK_NOT_FOUND, "inspection_plan_id does not resolve")
    if supplier_id is not None and supplier_id not in db.suppliers:
        raise err(ERR_FK_NOT_FOUND, "supplier_id does not resolve")

    # Well-formedness (priority 5).
    require_fields(body, ["inspection_plan_id", "supplier_id", "actual_lot_size"])
    require_non_negative_int(body["actual_lot_size"], "actual_lot_size", minimum=1)

    rec = {
        "inspection_plan_id": inspection_plan_id,
        "supplier_id": supplier_id,
        "actual_lot_size": body["actual_lot_size"],
        "sample_size": None,
        "acceptance_number": None,
        "rejection_number": None,
        "defects_found": 0,
        "severity_mode_used": None,
        "status": "PENDING",
        "inspected_by_personnel_id": auth.user_id,
    }
    stamp_create(rec)
    db.inspection_lots[rec["id"]] = rec
    return success(inspection_lot_out(rec), status=201)


@bp.route("/inspection-lots/<rid>", methods=["GET"])
def get_inspection_lot(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_INSPECTOR})
    rec = get_or_404(db.inspection_lots, rid)
    return success(inspection_lot_out(rec))


@bp.route("/inspection-plans/<rid>/inspection-lots", methods=["GET"])
def list_plan_lots(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_INSPECTOR})
    get_or_404(db.inspection_plans, rid)
    limit, offset = paginate_args()
    matches = [l for l in db.inspection_lots.values()
               if l["inspection_plan_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([inspection_lot_out(l) for l in page], limit, offset, total)


@bp.route("/inspection-lots/<rid>/transition", methods=["POST"])
def transition_lot(rid):
    auth = authenticate()
    require_role(auth, {ROLE_INSPECTOR})
    rec = get_or_404(db.inspection_lots, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["action"])
    action = body["action"]
    require_enum(action, LOT_ACTIONS, "action")

    if action == "START":
        if rec["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "START requires PENDING")
        plan = db.inspection_plans.get(rec["inspection_plan_id"])
        if plan is None:
            raise err(ERR_INVALID_STATE, "Linked inspection plan does not exist")
        # Freeze sampling numbers from the plan (PRD 3.6).
        n, ac, re_ = aql_sampling(
            plan["inspection_level"], plan["lot_size"],
            plan["aql_pct"], plan["severity_mode"])
        rec["sample_size"] = n
        rec["acceptance_number"] = ac
        rec["rejection_number"] = re_
        rec["severity_mode_used"] = plan["severity_mode"]
        rec["status"] = "IN_INSPECTION"
        touch(rec)
        return success(inspection_lot_out(rec))

    # DISPOSITION
    if rec["status"] != "IN_INSPECTION":
        raise err(ERR_INVALID_STATE, "DISPOSITION requires IN_INSPECTION")
    defects = body.get("defects_found")
    if defects is None:
        raise err(ERR_INVALID_REQUEST, "defects_found required")
    require_non_negative_int(defects, "defects_found", minimum=0)
    rec["defects_found"] = defects

    supplier = db.suppliers.get(rec["supplier_id"])
    plan = db.inspection_plans.get(rec["inspection_plan_id"])

    if defects <= rec["acceptance_number"]:
        # ACCEPTED (PRD 3.6).
        rec["status"] = "ACCEPTED"
        touch(rec)
        if supplier is not None:
            supplier["lots_inspected"] += 1
        if plan is not None:
            plan["consecutive_rejects"] = 0
            touch(plan)
        if supplier is not None:
            recompute_supplier_rating(supplier)
    elif defects >= rec["rejection_number"]:
        # REJECTED (PRD 3.6).
        rec["status"] = "REJECTED"
        touch(rec)
        if supplier is not None:
            supplier["lots_inspected"] += 1
            supplier["lots_rejected"] += 1
        if plan is not None:
            plan["consecutive_rejects"] += 1
            if plan["consecutive_rejects"] >= 2:
                plan["severity_mode"] = "TIGHTENED"
            touch(plan)
        if supplier is not None:
            recompute_supplier_rating(supplier)
    else:
        # Between Ac and Re cannot occur (Re = Ac + 1); guard anyway.
        raise err(ERR_INVALID_STATE, "Ambiguous defect count")

    return success(inspection_lot_out(rec))
