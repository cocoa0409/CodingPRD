"""Pump manifest endpoints: submit, list, read, verify, reject."""
import uuid

from flask import Blueprint, request

from db import STORE, now, next_seq
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INTERCEPTOR_NOT_ACTIVE,
    ERR_DUPLICATE_MANIFEST,
    ERR_HAULER_NOT_PERMITTED,
    ERR_INTERCEPTOR_MISMATCH,
    ERR_DISPOSAL_RECORD_MISSING,
    ERR_DISPOSAL_DISCREPANCY,
)
from middleware import (
    auth,
    require_roles,
    forbid_unless,
    get_or_404,
    paginate,
    by_creation,
    filter_enum,
)
from response import success
from services.calculations import disposal_exceeds_tolerance
from services.posture import touch_establishment, suspend_hauler
from services.serializers import ser_manifest
from validation import body_json, v_str, v_num, v_dt, v_enum

bp = Blueprint("manifests", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "FseContact", "HaulerAdmin"]
STATUSES = ("SUBMITTED", "VERIFIED", "REJECTED")
REJECT_REASONS = ("DISPOSAL_MISMATCH", "MISSING_DISPOSAL_RECORD", "HAULER_SUSPENDED", "OTHER")


@bp.post("/pump-manifests")
def create_manifest():
    uid, role = auth()
    body = body_json()
    est_id = v_str(body, "establishment_id")
    ic_id = v_str(body, "interceptor_id")
    h_id = v_str(body, "hauler_id")
    pump_date = v_dt(body, "pump_date")
    volume = v_num(body, "pumped_volume_gal", gt=0)
    require_roles(role, ["FseContact"])
    forbid_unless(uid == est_id)
    get_or_404("establishments", est_id)
    ic = get_or_404("interceptors", ic_id)
    get_or_404("haulers", h_id)
    if ic["status"] != "ACTIVE":
        raise ApiError(ERR_INTERCEPTOR_NOT_ACTIVE, 409, "Interceptor is not ACTIVE")
    for m in STORE["manifests"].values():
        if m["interceptor_id"] == ic_id and m["pump_date"] == pump_date:
            raise ApiError(ERR_DUPLICATE_MANIFEST, 409, "A manifest already exists for this interceptor and pump_date")
    current = now()
    m = {
        "id": str(uuid.uuid4()),
        "establishment_id": est_id,
        "interceptor_id": ic_id,
        "hauler_id": h_id,
        "pump_date": pump_date,
        "pumped_volume_gal": volume,
        "status": "SUBMITTED",
        "submitted_by_user_id": uid,
        "reject_reason": None,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["manifests"][m["id"]] = m
    return success(ser_manifest(m), 201)


@bp.get("/pump-manifests")
def list_manifests():
    uid, role = auth()
    require_roles(role, READERS)
    est_filter = request.args.get("establishment_id")
    hauler_filter = request.args.get("hauler_id")
    ic_filter = request.args.get("interceptor_id")
    status_filter = filter_enum(request.args, "status", STATUSES)
    items = list(STORE["manifests"].values())
    if role == "FseContact":
        items = [m for m in items if m["establishment_id"] == uid]
    elif role == "HaulerAdmin":
        items = [m for m in items if m["hauler_id"] == uid]
    if est_filter is not None:
        items = [m for m in items if m["establishment_id"] == est_filter]
    if hauler_filter is not None:
        items = [m for m in items if m["hauler_id"] == hauler_filter]
    if ic_filter is not None:
        items = [m for m in items if m["interceptor_id"] == ic_filter]
    if status_filter is not None:
        items = [m for m in items if m["status"] == status_filter]
    page, meta = paginate(by_creation(items))
    return success([ser_manifest(m) for m in page], 200, "array", meta)


@bp.get("/pump-manifests/<mid>")
def get_manifest(mid):
    uid, role = auth()
    require_roles(role, READERS)
    m = get_or_404("manifests", mid)
    if role == "FseContact":
        forbid_unless(m["establishment_id"] == uid)
    elif role == "HaulerAdmin":
        forbid_unless(m["hauler_id"] == uid)
    return success(ser_manifest(m))


@bp.post("/pump-manifests/<mid>/verify")
def verify_manifest(mid):
    uid, role = auth()
    require_roles(role, ["Inspector"])
    m = get_or_404("manifests", mid)
    if m["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Manifest is not in SUBMITTED status")
    hauler = STORE["haulers"].get(m["hauler_id"])
    if hauler is None or hauler["status"] != "PERMITTED":
        raise ApiError(ERR_HAULER_NOT_PERMITTED, 409, "Hauler is not PERMITTED")
    ic = STORE["interceptors"].get(m["interceptor_id"])
    if ic is None or ic["establishment_id"] != m["establishment_id"]:
        raise ApiError(ERR_INTERCEPTOR_MISMATCH, 422, "Interceptor does not belong to the manifest's establishment")
    disposal = next((d for d in STORE["disposals"].values() if d["manifest_id"] == mid), None)
    if disposal is None:
        raise ApiError(ERR_DISPOSAL_RECORD_MISSING, 422, "No disposal record exists for this manifest")
    if disposal_exceeds_tolerance(disposal["disposed_volume_gal"], m["pumped_volume_gal"]):
        raise ApiError(ERR_DISPOSAL_DISCREPANCY, 422, "Disposed volume deviates from pumped volume by more than 5%")
    current = now()
    m["status"] = "VERIFIED"
    m["updated_at"] = current
    m["version"] += 1
    est = STORE["establishments"].get(m["establishment_id"])
    if est is not None:
        est["last_verified_pump_at"] = m["pump_date"]
        touch_establishment(est, current, bump=True)
    return success(ser_manifest(m))


@bp.post("/pump-manifests/<mid>/reject")
def reject_manifest(mid):
    uid, role = auth()
    body = body_json()
    reason = v_enum(body, "reason_code", REJECT_REASONS)
    require_roles(role, ["Inspector"])
    m = get_or_404("manifests", mid)
    if m["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Manifest is not in SUBMITTED status")
    current = now()
    m["status"] = "REJECTED"
    m["reject_reason"] = reason
    m["updated_at"] = current
    m["version"] += 1
    if reason == "DISPOSAL_MISMATCH":
        hauler = STORE["haulers"].get(m["hauler_id"])
        if hauler is not None:
            hauler["mismatch_count"] += 1
            hauler["updated_at"] = current
            hauler["version"] += 1
            if hauler["mismatch_count"] >= 3 and hauler["status"] == "PERMITTED":
                suspend_hauler(hauler, current)
    return success(ser_manifest(m))
