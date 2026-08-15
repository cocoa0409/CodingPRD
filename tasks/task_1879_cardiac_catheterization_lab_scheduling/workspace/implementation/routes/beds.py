"""RecoveryBed endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_BED_INVALID_STATE,
    ERR_BED_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_IN_USE,
)
from helpers import get_payload, new_id, paginate, req_str
from middleware import ALL_ROLES, require_roles
from response import success
from services import bed_out, new_entity, touch

bp = Blueprint("beds", __name__)


@bp.route("/cath-lab/recovery-beds", methods=["POST"])
@require_roles("RecoveryNurseManager")
def create_bed():
    data = get_payload()
    bed_label = req_str(data, "bed_label")
    bed = new_entity()
    bed["id"] = new_id()
    bed.update(
        {
            "bed_label": bed_label,
            "status": "AVAILABLE",
            "held_case_id": None,
            "window_start": None,
            "window_end": None,
        }
    )
    STORE["beds"][bed["id"]] = bed
    return success(bed_out(bed), 201)


@bp.route("/cath-lab/recovery-beds", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_beds():
    status = request.args.get("status")
    held_case_id = request.args.get("held_case_id")
    items = []
    for b in STORE["beds"].values():
        if status is not None and b["status"] != status:
            continue
        if held_case_id is not None and b["held_case_id"] != held_case_id:
            continue
        items.append(b)
    items.sort(key=lambda b: b["_seq"])
    page, pg = paginate(items)
    return success([bed_out(b) for b in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/recovery-beds/<bed_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_bed(bed_id):
    bed = STORE["beds"].get(bed_id)
    if bed is None:
        raise ApiError(ERR_BED_NOT_FOUND, "No RecoveryBed with the given id", 404)
    return success(bed_out(bed), 200)


@bp.route("/cath-lab/recovery-beds/<bed_id>", methods=["PATCH"])
@require_roles("RecoveryNurseManager")
def patch_bed(bed_id):
    bed = STORE["beds"].get(bed_id)
    if bed is None:
        raise ApiError(ERR_BED_NOT_FOUND, "No RecoveryBed with the given id", 404)
    data = get_payload()
    status = req_str(data, "status")
    if status not in ("AVAILABLE", "OUT_OF_SERVICE"):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "status must be AVAILABLE or OUT_OF_SERVICE",
            400,
        )
    if status == bed["status"]:
        raise ApiError(ERR_INVALID_REQUEST, "status is already %s" % status, 400)
    if bed["status"] in ("RESERVED", "OCCUPIED"):
        raise ApiError(
            ERR_RESOURCE_IN_USE,
            "A RESERVED or OCCUPIED bed cannot change status",
            409,
        )
    bed["status"] = status
    touch(bed)
    return success(bed_out(bed), 200)


@bp.route("/cath-lab/recovery-beds/<bed_id>/release", methods=["POST"])
@require_roles("RecoveryNurseManager")
def release_bed(bed_id):
    bed = STORE["beds"].get(bed_id)
    if bed is None:
        raise ApiError(ERR_BED_NOT_FOUND, "No RecoveryBed with the given id", 404)
    if bed["status"] != "OCCUPIED":
        raise ApiError(
            ERR_BED_INVALID_STATE,
            "Only an OCCUPIED bed can be released",
            409,
        )
    bed["status"] = "AVAILABLE"
    bed["held_case_id"] = None
    bed["window_start"] = None
    bed["window_end"] = None
    touch(bed)
    return success(bed_out(bed), 200)
