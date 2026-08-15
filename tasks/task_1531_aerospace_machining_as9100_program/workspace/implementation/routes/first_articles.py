"""First-article inspection and ballooned characteristic endpoints."""

from flask import Blueprint, request

from db import db, base_record, public, touch
from errors import (
    ApiError,
    ERR_BALLOON_NUMBER_EXISTS,
    ERR_CHARACTERISTIC_LOCKED,
    ERR_CHARACTERISTIC_NOT_FOUND,
    ERR_CHARACTERISTIC_NOT_MEASURABLE,
    ERR_FAI_CHARACTERISTIC_FAILURE,
    ERR_FAI_INCOMPLETE_CHARACTERISTICS,
    ERR_FAI_NOT_FOUND,
    ERR_FAI_NOT_REOPENABLE,
    ERR_FAI_NOT_SUBMITTABLE,
    ERR_FAI_NOT_SUBMITTED,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import dec, num_out, recompute_fai_completeness
from validate import (
    json_body,
    no_unknown,
    opt_bool,
    paginate,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("first_articles", __name__)

QI = "QualityInspector"
CQR = "CustomerQualityRep"
FAI_TYPES = {"FULL", "PARTIAL"}


def get_fai(fai_id):
    fai = db.fais.get(fai_id)
    if fai is None:
        raise ApiError(ERR_FAI_NOT_FOUND, 404, "FAI %s not found" % fai_id)
    return fai


def get_char(char_id):
    c = db.characteristics.get(char_id)
    if c is None:
        raise ApiError(ERR_CHARACTERISTIC_NOT_FOUND, 404, "Characteristic %s not found" % char_id)
    return c


@bp.route("/api/first-articles", methods=["POST"])
def create_fai():
    require_roles(QI)
    data = json_body()
    no_unknown(data, {"part_number", "part_revision", "fai_type"})
    part_number = req_str(data, "part_number")
    part_revision = req_str(data, "part_revision")
    fai_type = req_enum(data, "fai_type", FAI_TYPES)

    rec = base_record(db.new_id())
    rec.update(
        {
            "part_number": part_number,
            "part_revision": part_revision,
            "fai_type": fai_type,
            "status": "DRAFT",
            "characteristic_count": 0,
            "measured_count": 0,
            "characteristics_complete": False,
            "submitted_by_user_id": None,
            "approved_revision": None,
        }
    )
    db.fais[rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/api/first-articles", methods=["GET"])
def list_fais():
    require_roles(*ALL_ROLES)
    items = list(db.fais.values())
    part_number = request.args.get("part_number")
    part_revision = request.args.get("part_revision")
    status = request.args.get("status")
    if part_number is not None:
        items = [f for f in items if f["part_number"] == part_number]
    if part_revision is not None:
        items = [f for f in items if f["part_revision"] == part_revision]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/first-articles/<faiId>", methods=["GET"])
def get_one_fai(faiId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_fai(faiId)))


@bp.route("/api/first-articles/<faiId>/characteristics", methods=["POST"])
def add_characteristic(faiId):
    require_roles(QI)
    data = json_body()
    no_unknown(
        data,
        {"balloon_number", "nominal", "tolerance_plus", "tolerance_minus", "is_key_characteristic"},
    )
    balloon_number = req_int(data, "balloon_number")
    nominal = req_num(data, "nominal")
    tol_plus = req_num(data, "tolerance_plus", min_val=0)
    tol_minus = req_num(data, "tolerance_minus", min_val=0)
    is_kc = opt_bool(data, "is_key_characteristic", False)

    fai = get_fai(faiId)
    if fai["status"] not in ("DRAFT", "IN_INSPECTION"):
        raise ApiError(ERR_CHARACTERISTIC_LOCKED, 409, "FAI is locked for characteristic adds")
    if any(
        c["fai_id"] == fai["id"] and c["balloon_number"] == balloon_number
        for c in db.characteristics.values()
    ):
        raise ApiError(ERR_BALLOON_NUMBER_EXISTS, 409, "balloon_number already exists on this FAI")

    usl_d = dec(nominal) + dec(tol_plus)
    lsl_d = dec(nominal) - dec(tol_minus)
    rec = base_record(db.new_id())
    rec.update(
        {
            "fai_id": fai["id"],
            "balloon_number": balloon_number,
            "nominal": nominal,
            "tolerance_plus": tol_plus,
            "tolerance_minus": tol_minus,
            "is_key_characteristic": is_kc,
            "usl": num_out(usl_d),
            "lsl": num_out(lsl_d),
            "measured_value": None,
            "result": "UNMEASURED",
            "measured_by_user_id": None,
            "spc_eval_status": "NONE",
            "cpk_provisional": None,
            "cpk_final": None,
            "_usl_d": usl_d,
            "_lsl_d": lsl_d,
        }
    )
    db.characteristics[rec["id"]] = rec
    if fai["status"] == "DRAFT":
        fai["status"] = "IN_INSPECTION"
    recompute_fai_completeness(fai)
    return success_object(public(rec), 201)


@bp.route("/api/first-articles/<faiId>/characteristics", methods=["GET"])
def list_characteristics(faiId):
    require_roles(*ALL_ROLES)
    fai = get_fai(faiId)
    items = [c for c in db.characteristics.values() if c["fai_id"] == fai["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/first-articles/<faiId>/submit", methods=["POST"])
def submit_fai(faiId):
    uid = require_roles(QI)
    data = json_body()
    no_unknown(data, set())
    fai = get_fai(faiId)
    if fai["status"] != "IN_INSPECTION":
        raise ApiError(ERR_FAI_NOT_SUBMITTABLE, 409, "FAI submit requires IN_INSPECTION")
    # Segregation of duties (priority 6) precedes content gates (priority 9)
    chars = [c for c in db.characteristics.values() if c["fai_id"] == fai["id"]]
    if any(c["measured_by_user_id"] == uid for c in chars):
        raise ApiError(ERR_SOD_VIOLATION, 403, "Submitter recorded a characteristic measurement")
    if not fai["characteristics_complete"]:
        raise ApiError(
            ERR_FAI_INCOMPLETE_CHARACTERISTICS, 422, "FAI has unmeasured or zero characteristics"
        )
    if any(c["result"] == "FAIL" for c in chars):
        raise ApiError(ERR_FAI_CHARACTERISTIC_FAILURE, 422, "FAI carries a FAIL characteristic")
    fai["status"] = "SUBMITTED"
    fai["submitted_by_user_id"] = uid
    touch(fai)
    return success_object(public(fai))


@bp.route("/api/first-articles/<faiId>/approve", methods=["POST"])
def approve_fai(faiId):
    require_roles(CQR)
    data = json_body()
    no_unknown(data, set())
    fai = get_fai(faiId)
    if fai["status"] != "SUBMITTED":
        raise ApiError(ERR_FAI_NOT_SUBMITTED, 409, "FAI approve requires SUBMITTED")
    fai["status"] = "APPROVED"
    fai["approved_revision"] = fai["part_revision"]
    touch(fai)
    # Supersede every other APPROVED FAI of the same (part_number, part_revision)
    for other in db.fais.values():
        if (
            other["id"] != fai["id"]
            and other["status"] == "APPROVED"
            and other["part_number"] == fai["part_number"]
            and other["part_revision"] == fai["part_revision"]
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    return success_object(public(fai))


@bp.route("/api/first-articles/<faiId>/reject", methods=["POST"])
def reject_fai(faiId):
    require_roles(CQR)
    data = json_body()
    no_unknown(data, {"reason"})
    req_str(data, "reason")
    fai = get_fai(faiId)
    if fai["status"] != "SUBMITTED":
        raise ApiError(ERR_FAI_NOT_SUBMITTED, 409, "FAI reject requires SUBMITTED")
    fai["status"] = "REJECTED"
    touch(fai)
    return success_object(public(fai))


@bp.route("/api/first-articles/<faiId>/reopen", methods=["POST"])
def reopen_fai(faiId):
    require_roles(QI)
    data = json_body()
    no_unknown(data, set())
    fai = get_fai(faiId)
    if fai["status"] != "REJECTED":
        raise ApiError(ERR_FAI_NOT_REOPENABLE, 409, "FAI reopen requires REJECTED")
    fai["status"] = "IN_INSPECTION"
    touch(fai)
    return success_object(public(fai))


@bp.route("/api/characteristics/<charId>", methods=["GET"])
def get_one_char(charId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_char(charId)))


@bp.route("/api/characteristics/<charId>/record-measurement", methods=["POST"])
def record_measurement(charId):
    uid = require_roles(QI)
    data = json_body()
    no_unknown(data, {"measured_value"})
    measured = req_num(data, "measured_value")
    c = get_char(charId)
    if c["result"] not in ("UNMEASURED", "FAIL"):
        raise ApiError(
            ERR_CHARACTERISTIC_NOT_MEASURABLE, 409, "Characteristic is already PASS"
        )
    fai = db.fais.get(c["fai_id"])
    if fai is None or fai["status"] not in ("DRAFT", "IN_INSPECTION"):
        raise ApiError(ERR_CHARACTERISTIC_LOCKED, 409, "Parent FAI is locked")

    mv = dec(measured)
    c["measured_value"] = measured
    c["measured_by_user_id"] = uid
    c["result"] = "PASS" if (c["_lsl_d"] <= mv <= c["_usl_d"]) else "FAIL"
    touch(c)
    recompute_fai_completeness(fai)
    return success_object(public(c))


@bp.route("/api/characteristics/<charId>/spc-measurements", methods=["GET"])
def list_char_spc(charId):
    require_roles(*ALL_ROLES)
    c = get_char(charId)
    items = [m for m in db.spc_measurements.values() if m["characteristic_id"] == c["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)
