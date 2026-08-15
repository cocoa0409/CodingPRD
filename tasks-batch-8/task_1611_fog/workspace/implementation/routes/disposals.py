"""Disposal record endpoints: file (immutable), list, read."""
import uuid

from flask import Blueprint, request

from db import STORE, now, next_seq
from errors import ApiError, ERR_INVALID_STATE, ERR_HAULER_NOT_PERMITTED, ERR_DUPLICATE_DISPOSAL
from middleware import auth, require_roles, forbid_unless, get_or_404, paginate, by_creation
from response import success
from services.serializers import ser_disposal
from validation import body_json, v_str, v_num, v_dt

bp = Blueprint("disposals", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "HaulerAdmin"]


@bp.post("/disposal-records")
def create_disposal():
    uid, role = auth()
    body = body_json()
    hauler_id = v_str(body, "hauler_id")
    manifest_id = v_str(body, "manifest_id")
    volume = v_num(body, "disposed_volume_gal", gt=0)
    site = v_str(body, "disposal_site_name")
    disposed_at = v_dt(body, "disposed_at")
    require_roles(role, ["HaulerAdmin"])
    forbid_unless(uid == hauler_id)
    hauler = get_or_404("haulers", hauler_id)
    manifest = get_or_404("manifests", manifest_id)
    if manifest["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Manifest is not in SUBMITTED status")
    if hauler["status"] != "PERMITTED":
        raise ApiError(ERR_HAULER_NOT_PERMITTED, 409, "Hauler is not PERMITTED")
    for d in STORE["disposals"].values():
        if d["manifest_id"] == manifest_id:
            raise ApiError(ERR_DUPLICATE_DISPOSAL, 409, "A disposal record already exists for this manifest")
    d = {
        "id": str(uuid.uuid4()),
        "hauler_id": hauler_id,
        "manifest_id": manifest_id,
        "disposed_volume_gal": volume,
        "disposal_site_name": site,
        "disposed_at": disposed_at,
        "created_at": now(),
        "_seq": next_seq(),
    }
    STORE["disposals"][d["id"]] = d
    return success(ser_disposal(d), 201)


@bp.get("/disposal-records")
def list_disposals():
    uid, role = auth()
    require_roles(role, READERS)
    hauler_filter = request.args.get("hauler_id")
    manifest_filter = request.args.get("manifest_id")
    items = list(STORE["disposals"].values())
    if role == "HaulerAdmin":
        items = [d for d in items if d["hauler_id"] == uid]
    if hauler_filter is not None:
        items = [d for d in items if d["hauler_id"] == hauler_filter]
    if manifest_filter is not None:
        items = [d for d in items if d["manifest_id"] == manifest_filter]
    page, meta = paginate(by_creation(items))
    return success([ser_disposal(d) for d in page], 200, "array", meta)


@bp.get("/disposal-records/<did>")
def get_disposal(did):
    uid, role = auth()
    require_roles(role, READERS)
    d = get_or_404("disposals", did)
    if role == "HaulerAdmin":
        forbid_unless(d["hauler_id"] == uid)
    return success(ser_disposal(d))
