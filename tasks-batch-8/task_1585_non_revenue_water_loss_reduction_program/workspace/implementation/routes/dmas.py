"""DistrictMeteredArea endpoints and per-DMA reverse collections."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_list, success_object
from routes import make_bp
from util import paginate, sort_created, v_int, v_num, v_str

bp = make_bp("dmas")

ALL_ROLES = {"ProgramDirector", "UtilityAnalyst", "FieldSupervisor",
             "MeterTechnician", "Investigator", "RegulatorLiaison"}


def _get_dma_or_404(dma_id):
    dma = db.store["dmas"].get(dma_id)
    if dma is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    return dma


@bp.route("/nrw/dmas", methods=["POST"])
def create_dma():
    uid, role = require_roles({"ProgramDirector"})
    body = get_body()
    # priority 4: uniqueness (before scalar, priority 9)
    code = body.get("code")
    if isinstance(code, str) and any(d["code"] == code for d in db.store["dmas"].values()):
        raise ApiError(errors.ERR_DUPLICATE, 409, "a DMA with this code already exists")
    # priority 9: scalar constraints
    code = v_str(body, "code", min_len=3, max_len=40)
    name = v_str(body, "name")
    connection_count = v_int(body, "connection_count", ge=1)
    mains_length_km = v_num(body, "mains_length_km", gt=0)
    target_nrw_pct = v_num(body, "target_nrw_pct", ge=0, lt=100)

    rec = db.new_record()
    rec.update({
        "code": code,
        "name": name,
        "connection_count": connection_count,
        "mains_length_km": mains_length_km,
        "target_nrw_pct": target_nrw_pct,
        "posture": "OPEN",
        "latest_nrw_pct": None,
        "open_leak_count": 0,
    })
    db.store["dmas"][rec["id"]] = rec
    db.append_audit("DistrictMeteredArea", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/dmas", methods=["GET"])
def list_dmas():
    require_roles(ALL_ROLES)
    items = list(db.store["dmas"].values())
    posture = _arg("posture")
    if posture is not None:
        items = [d for d in items if d["posture"] == posture]
    code = _arg("code")
    if code is not None:
        items = [d for d in items if d["code"] == code]
    items = sort_created(items)
    page, meta = paginate(items)
    return success_list([db.serialize(d) for d in page], meta)


@bp.route("/nrw/dmas/<dma_id>", methods=["GET"])
def get_dma(dma_id):
    require_roles(ALL_ROLES)
    dma = _get_dma_or_404(dma_id)
    return success_object(db.serialize(dma))


def _arg(name):
    from flask import request
    return request.args.get(name)


def _child_list(dma_id, store_key, roles, filters):
    require_roles(roles)
    _get_dma_or_404(dma_id)
    items = [r for r in db.store[store_key].values() if r.get("dma_id") == dma_id]
    for fname, fkey in filters:
        val = _arg(fname)
        if val is not None:
            items = [r for r in items if _match(r.get(fkey), val)]
    items = sort_created(items)
    page, meta = paginate(items)
    return success_list([db.serialize(r) for r in page], meta)


def _match(value, raw):
    if isinstance(value, bool):
        if raw.lower() == "true":
            return value is True
        if raw.lower() == "false":
            return value is False
        return False
    return str(value) == raw


@bp.route("/nrw/dmas/<dma_id>/water-balance-periods", methods=["GET"])
def dma_water_balance_periods(dma_id):
    return _child_list(dma_id, "water_balance_periods",
                       {"ProgramDirector", "UtilityAnalyst", "RegulatorLiaison"},
                       [("status", "status")])


@bp.route("/nrw/dmas/<dma_id>/night-flow-assessments", methods=["GET"])
def dma_night_flow(dma_id):
    return _child_list(dma_id, "night_flow_assessments",
                       {"ProgramDirector", "UtilityAnalyst"},
                       [("status", "status")])


@bp.route("/nrw/dmas/<dma_id>/leak-surveys", methods=["GET"])
def dma_leak_surveys(dma_id):
    return _child_list(dma_id, "leak_surveys",
                       {"ProgramDirector", "UtilityAnalyst", "FieldSupervisor"},
                       [("status", "status")])


@bp.route("/nrw/dmas/<dma_id>/customer-meters", methods=["GET"])
def dma_customer_meters(dma_id):
    return _child_list(dma_id, "customer_meters",
                       {"ProgramDirector", "MeterTechnician", "UtilityAnalyst"},
                       [("status", "status"), ("replacement_due", "replacement_due")])


@bp.route("/nrw/dmas/<dma_id>/unauthorized-consumption-cases", methods=["GET"])
def dma_cases(dma_id):
    return _child_list(dma_id, "unauthorized_consumption_cases",
                       {"ProgramDirector", "Investigator"},
                       [("investigation_status", "investigation_status"),
                        ("billing_adjustment_status", "billing_adjustment_status")])


@bp.route("/nrw/dmas/<dma_id>/pressure-projects", methods=["GET"])
def dma_pressure_projects(dma_id):
    return _child_list(dma_id, "pressure_projects",
                       {"ProgramDirector", "UtilityAnalyst"},
                       [("status", "status")])


@bp.route("/nrw/dmas/<dma_id>/intervention-proposals", methods=["GET"])
def dma_proposals(dma_id):
    return _child_list(dma_id, "intervention_proposals",
                       {"ProgramDirector", "UtilityAnalyst"},
                       [("status", "status"), ("kind", "kind")])
