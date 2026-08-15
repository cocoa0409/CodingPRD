"""Similar-exposure groups and memberships."""

from flask import Blueprint, request

import db
from errors import (
    ERR_ANALYTE_MISMATCH,
    ERR_DUPLICATE_MEMBERSHIP,
    ERR_INVALID_REQUEST,
    raise_error,
)
from helpers import (
    reject_unknown,
    body, get_or_404, list_response, opt_bool, req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import membership_out, seg_out

bp = Blueprint("segs", __name__)

IH = ("IndustrialHygienist",)


def recompute_headcount(seg):
    seg["headcount"] = sum(1 for m in db.seg_memberships.values() if m["seg_id"] == seg["id"])


# ---------------------------------------------------------------------------
# SEGs
# ---------------------------------------------------------------------------

@bp.route("/ih/segs", methods=["POST"])
def create_seg():
    require_auth(IH)
    data = body()
    reject_unknown(data, {"site_id", "name", "analyte_code", "exposure_limit_id", "task_description"})
    site_id = req_string(data, "site_id")
    name = req_string(data, "name")
    analyte_code = req_string(data, "analyte_code")
    exposure_limit_id = req_string(data, "exposure_limit_id")
    task_description = req_string(data, "task_description")
    get_or_404(db.sites, site_id, "Site")
    limit = get_or_404(db.exposure_limits, exposure_limit_id, "ExposureLimit")
    if limit["analyte_code"] != analyte_code:
        raise_error(ERR_ANALYTE_MISMATCH,
                    "SEG analyte_code must equal the linked limit's analyte_code")
    seg = {
        "site_id": site_id,
        "name": name,
        "analyte_code": analyte_code,
        "exposure_limit_id": exposure_limit_id,
        "task_description": task_description,
        "headcount": 0,
        "current_class": "NONE",
        "next_sample_due_date": None,
    }
    stamp_new(seg)
    db.segs[seg["id"]] = seg
    return success_object(seg_out(seg), 201)


@bp.route("/ih/segs", methods=["GET"])
def list_segs():
    require_auth(ALL_ROLES)
    return list_response(list(db.segs.values()), seg_out, {
        "site_id": request.args.get("site_id"),
        "exposure_limit_id": request.args.get("exposure_limit_id"),
    })


@bp.route("/ih/segs/<sid>", methods=["GET"])
def get_seg(sid):
    require_auth(ALL_ROLES)
    return success_object(seg_out(get_or_404(db.segs, sid, "SimilarExposureGroup")))


# ---------------------------------------------------------------------------
# SEG memberships
# ---------------------------------------------------------------------------

@bp.route("/ih/seg-memberships", methods=["POST"])
def create_membership():
    require_auth(IH)
    data = body()
    reject_unknown(data, {"seg_id", "employee_id", "is_primary"})
    seg_id = req_string(data, "seg_id")
    employee_id = req_string(data, "employee_id")
    is_primary = opt_bool(data, "is_primary", False)
    seg = get_or_404(db.segs, seg_id, "SimilarExposureGroup")
    get_or_404(db.employees, employee_id, "Employee")
    for existing in db.seg_memberships.values():
        if existing["seg_id"] == seg_id and existing["employee_id"] == employee_id:
            raise_error(ERR_DUPLICATE_MEMBERSHIP,
                        "SEGMembership with same (seg_id, employee_id) exists")
    membership = {
        "seg_id": seg_id,
        "employee_id": employee_id,
        "is_primary": is_primary,
    }
    stamp_new(membership)
    db.seg_memberships[membership["id"]] = membership
    recompute_headcount(seg)
    touch(seg)
    return success_object(membership_out(membership), 201)


@bp.route("/ih/seg-memberships", methods=["GET"])
def list_memberships():
    require_auth(ALL_ROLES)
    return list_response(list(db.seg_memberships.values()), membership_out, {
        "seg_id": request.args.get("seg_id"),
        "employee_id": request.args.get("employee_id"),
    })


@bp.route("/ih/seg-memberships/<mid>", methods=["GET"])
def get_membership(mid):
    require_auth(ALL_ROLES)
    return success_object(membership_out(get_or_404(db.seg_memberships, mid, "SEGMembership")))


@bp.route("/ih/seg-memberships/<mid>/transfer", methods=["POST"])
def transfer_membership(mid):
    require_auth(IH)
    data = body()
    reject_unknown(data, {"target_seg_id"})
    target_seg_id = req_string(data, "target_seg_id")
    membership = get_or_404(db.seg_memberships, mid, "SEGMembership")
    target = get_or_404(db.segs, target_seg_id, "SimilarExposureGroup")
    source = db.segs[membership["seg_id"]]
    if target["site_id"] != source["site_id"]:
        raise_error(ERR_INVALID_REQUEST,
                    "target SEG must belong to the same site")
    for existing in db.seg_memberships.values():
        if (existing["id"] != membership["id"]
                and existing["seg_id"] == target_seg_id
                and existing["employee_id"] == membership["employee_id"]):
            raise_error(ERR_DUPLICATE_MEMBERSHIP,
                        "SEGMembership with same (seg_id, employee_id) exists")
    membership["seg_id"] = target_seg_id
    touch(membership)
    recompute_headcount(source)
    touch(source)
    if target["id"] != source["id"]:
        recompute_headcount(target)
        touch(target)
    return success_object(membership_out(membership), 200)
