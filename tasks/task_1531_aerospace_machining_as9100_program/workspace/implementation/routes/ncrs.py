"""Nonconformance report endpoints (MRB pipeline)."""

from flask import Blueprint, request

from db import db, public, touch
from errors import (
    ApiError,
    ERR_ESCAPE_NOT_ACKNOWLEDGED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NCR_NOT_FOUND,
    ERR_NCR_REQUIRES_CONCESSION,
    ERR_SERIAL_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_WO_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import create_ncr, ncr_cost_cents, recompute_wo_counters
from validate import (
    json_body,
    no_unknown,
    opt_bool,
    opt_num,
    opt_str_list,
    paginate,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("ncrs", __name__)

QI = "QualityInspector"
QM = "QualityManager"
MRB = "MRBMember"
CQR = "CustomerQualityRep"

DISPOSITIONS = {"USE_AS_IS", "REWORK", "SCRAP", "RETURN_TO_SUPPLIER"}


def get_ncr(ncr_id):
    n = db.ncrs.get(ncr_id)
    if n is None:
        raise ApiError(ERR_NCR_NOT_FOUND, 404, "NCR %s not found" % ncr_id)
    return n


@bp.route("/api/ncrs", methods=["POST"])
def create_ncr_manual():
    uid = require_roles(QI)
    data = json_body()
    no_unknown(
        data,
        {
            "wo_id",
            "defect_code",
            "description",
            "quantity_affected",
            "affected_serial_ids",
            "detected_post_shipment",
        },
    )
    wo_id = req_str(data, "wo_id")
    defect_code = req_str(data, "defect_code")
    description = req_str(data, "description")
    qty = req_int(data, "quantity_affected", min_val=1)
    serial_ids = opt_str_list(data, "affected_serial_ids", default=[])
    post_shipment = opt_bool(data, "detected_post_shipment", False)

    wo = db.work_orders.get(wo_id)
    if wo is None:
        raise ApiError(ERR_WO_NOT_FOUND, 404, "Work order %s not found" % wo_id)
    for sid in serial_ids:
        if sid not in db.serials:
            raise ApiError(ERR_SERIAL_NOT_FOUND, 404, "Serial %s not found" % sid)
    for sid in serial_ids:
        if db.serials[sid]["wo_id"] != wo["id"]:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "Serial %s does not belong to work order" % sid
            )

    ncr = create_ncr(
        wo_id=wo["id"],
        defect_code=defect_code,
        description=description,
        quantity_affected=qty,
        affected_serial_ids=serial_ids,
        detected_post_shipment=post_shipment,
        origin="MANUAL",
        discovered_by_user_id=uid,
    )
    return success_object(public(ncr), 201)


@bp.route("/api/ncrs", methods=["GET"])
def list_ncrs():
    require_roles(*ALL_ROLES)
    items = list(db.ncrs.values())
    wo_id = request.args.get("wo_id")
    status = request.args.get("status")
    disposition = request.args.get("disposition")
    if wo_id is not None:
        items = [n for n in items if n["wo_id"] == wo_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    if disposition is not None:
        items = [n for n in items if n["disposition"] == disposition]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/ncrs/<ncrId>", methods=["GET"])
def get_one_ncr(ncrId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_ncr(ncrId)))


@bp.route("/api/ncrs/<ncrId>/submit-mrb", methods=["POST"])
def submit_mrb(ncrId):
    require_roles(QM)
    data = json_body()
    no_unknown(data, set())
    ncr = get_ncr(ncrId)
    if ncr["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "submit-mrb requires OPEN")
    ncr["status"] = "MRB_REVIEW"
    touch(ncr)
    return success_object(public(ncr))


@bp.route("/api/ncrs/<ncrId>/kickback", methods=["POST"])
def kickback(ncrId):
    require_roles(MRB)
    data = json_body()
    no_unknown(data, {"reason"})
    req_str(data, "reason")
    ncr = get_ncr(ncrId)
    if ncr["status"] != "MRB_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "kickback requires MRB_REVIEW")
    ncr["status"] = "OPEN"
    touch(ncr)
    return success_object(public(ncr))


@bp.route("/api/ncrs/<ncrId>/disposition", methods=["POST"])
def disposition(ncrId):
    uid = require_roles(MRB)
    data = json_body()
    no_unknown(data, {"disposition", "rework_hours_per_unit", "material_cost_per_unit_cents"})
    disp = req_enum(data, "disposition", DISPOSITIONS)
    hours = opt_num(data, "rework_hours_per_unit")
    material = opt_num(data, "material_cost_per_unit_cents")

    ncr = get_ncr(ncrId)
    if ncr["status"] != "MRB_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "disposition requires MRB_REVIEW")
    if uid == ncr["discovered_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Disposer must differ from NCR discoverer")

    ncr["disposition"] = disp
    ncr["disposition_by_user_id"] = uid
    ncr["status"] = "DISPOSITIONED"
    ncr["estimated_cost_cents"] = ncr_cost_cents(
        hours if hours is not None else 0,
        material if material is not None else 0,
        ncr["quantity_affected"],
    )
    touch(ncr)

    wo = db.work_orders.get(ncr["wo_id"])
    if disp == "SCRAP":
        changed = False
        for sid in ncr["affected_serial_ids"]:
            s = db.serials.get(sid)
            if s is not None and s["status"] in ("CREATED", "QUARANTINED"):
                s["status"] = "SCRAPPED"
                touch(s)
                changed = True
        if wo is not None and (changed or ncr["affected_serial_ids"]):
            recompute_wo_counters(wo)
            if (
                wo["good_quantity"] == 0
                and wo["serials_created_count"] > 0
                and wo["status"] == "IN_PRODUCTION"
            ):
                wo["status"] = "QUALITY_HOLD"
                touch(wo)
    elif disp == "USE_AS_IS":
        for sid in ncr["affected_serial_ids"]:
            s = db.serials.get(sid)
            if s is not None and s["status"] == "QUARANTINED":
                s["status"] = "CREATED"
                touch(s)
        if wo is not None and ncr["affected_serial_ids"]:
            recompute_wo_counters(wo)
    # REWORK / RETURN_TO_SUPPLIER: no serial changes
    return success_object(public(ncr))


@bp.route("/api/ncrs/<ncrId>/verify", methods=["POST"])
def verify(ncrId):
    require_roles(QI)
    data = json_body()
    no_unknown(data, {"actual_rework_hours_per_unit", "actual_material_cost_per_unit_cents"})
    a_hours = opt_num(data, "actual_rework_hours_per_unit")
    a_material = opt_num(data, "actual_material_cost_per_unit_cents")

    ncr = get_ncr(ncrId)
    if ncr["status"] != "DISPOSITIONED":
        raise ApiError(ERR_INVALID_STATE, 409, "verify requires DISPOSITIONED")
    if ncr["disposition"] == "USE_AS_IS" and not ncr["concession_approved"]:
        raise ApiError(
            ERR_NCR_REQUIRES_CONCESSION, 422, "USE_AS_IS verify requires a customer concession"
        )
    if a_hours is not None or a_material is not None:
        ncr["actual_cost_cents"] = ncr_cost_cents(
            a_hours if a_hours is not None else 0,
            a_material if a_material is not None else 0,
            ncr["quantity_affected"],
        )
    ncr["status"] = "VERIFIED"
    touch(ncr)
    return success_object(public(ncr))


@bp.route("/api/ncrs/<ncrId>/close", methods=["POST"])
def close_ncr(ncrId):
    require_roles(QM)
    data = json_body()
    no_unknown(data, set())
    ncr = get_ncr(ncrId)
    if ncr["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "close requires VERIFIED")
    if ncr["detected_post_shipment"]:
        escape = next((e for e in db.escape_reports.values() if e["ncr_id"] == ncr["id"]), None)
        if escape is None or escape["status"] != "ACKNOWLEDGED":
            raise ApiError(
                ERR_ESCAPE_NOT_ACKNOWLEDGED,
                409,
                "Linked escape report must be ACKNOWLEDGED before close",
            )
    ncr["status"] = "CLOSED"
    touch(ncr)
    return success_object(public(ncr))


@bp.route("/api/ncrs/<ncrId>/customer-concession", methods=["POST"])
def customer_concession(ncrId):
    require_roles(CQR)
    data = json_body()
    no_unknown(data, {"concession_reference"})
    req_str(data, "concession_reference")
    ncr = get_ncr(ncrId)
    if ncr["status"] != "DISPOSITIONED" or ncr["disposition"] != "USE_AS_IS":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "customer-concession requires DISPOSITIONED with USE_AS_IS disposition",
        )
    ncr["concession_approved"] = True
    touch(ncr)
    return success_object(public(ncr))
