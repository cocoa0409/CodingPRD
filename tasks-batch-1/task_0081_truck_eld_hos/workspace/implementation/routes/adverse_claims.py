"""AdverseConditionsClaim endpoints + adjudication (PRD §3.9)."""
from flask import Blueprint, request

import db
import errors
import model
import response
import serializers as ser
import timeutil
import validation as val
from middleware import get_auth, require_role
from paginate import paginate
from services import hos

bp = Blueprint("adverse_claims", __name__)

REASONS = {"WEATHER", "ROAD_CLOSURE", "TRAFFIC_INCIDENT"}
CLAIM_STATUSES = {"PENDING", "APPROVED", "REJECTED"}


@bp.route("/eld/adverse-claims", methods=["POST"])
def create_claim():
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    body = val.get_body()
    driver_id = val.require_str(body, "driver_id")
    log_date = val.require_str(body, "log_date")
    if not timeutil.is_date_str(log_date):
        raise errors.err(errors.ERR_INVALID_REQUEST, "log_date must be YYYY-MM-DD.")
    reason = val.require_present(body, "reason")
    val.enum_in(reason, REASONS, "reason")
    # narrative required (non-empty) -> ERR_ANNOTATION_REQUIRED when empty/missing

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "driver_id not found.")

    # ownership: entity-backed driver acts on own claim
    if user_id != driver_id:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Driver may only file their own claim.")

    narrative = body.get("narrative")
    if not isinstance(narrative, str) or narrative == "":
        raise errors.err(errors.ERR_ANNOTATION_REQUIRED, "narrative is required.")

    rec = {
        "driver_id": driver_id,
        "log_date": log_date,
        "reason": reason,
        "narrative": narrative,
        "status": "PENDING",
    }
    model.stamp_new(rec)
    db.adverse_claims[rec["id"]] = rec
    return response.object_response(ser.adverse_claim_view(rec), 201)


@bp.route("/eld/adverse-claims/<id>", methods=["GET"])
def get_claim(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.adverse_claims.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Claim not found.")
    return response.object_response(ser.adverse_claim_view(rec), 200)


@bp.route("/eld/adverse-claims", methods=["GET"])
def list_claims():
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    limit, offset = val.get_pagination()
    items = list(db.adverse_claims.values())
    driver_id = request.args.get("driver_id")
    status = request.args.get("status")
    log_date = request.args.get("log_date")
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if log_date is not None:
        items = [r for r in items if r["log_date"] == log_date]
    page, total = paginate(items, limit, offset)
    return response.array_response([ser.adverse_claim_view(r) for r in page], limit, offset, total)


@bp.route("/eld/adverse-claims/<id>/approve", methods=["POST"])
def approve(id):
    _, role = get_auth()
    require_role(role, {"SafetyOfficer"})
    rec = db.adverse_claims.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Claim not found.")
    body = val.get_body()

    # state: must be PENDING
    if rec["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim is not PENDING.")

    # duplicate approved claim for (driver_id, log_date)
    for c in db.adverse_claims.values():
        if (c["id"] != rec["id"] and c["driver_id"] == rec["driver_id"]
                and c["log_date"] == rec["log_date"] and c["status"] == "APPROVED"):
            raise errors.err(errors.ERR_DUPLICATE_ADVERSE_CLAIM,
                             "An APPROVED claim already exists for this driver-day.")

    # OCC: checked before any clock recompute (PRD §2.6)
    if "expected_adverseconditionsclaim_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "expected_adverseconditionsclaim_version is required.")
    if body["expected_adverseconditionsclaim_version"] != rec["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Claim version mismatch.")

    rec["status"] = "APPROVED"
    model.touch(rec)

    driver = db.drivers.get(rec["driver_id"])
    if driver is not None:
        hos.recompute_driver(driver, dismiss_note=hos.NOTE_ADVERSE, adverse_day=rec["log_date"])
    return response.object_response(ser.adverse_claim_view(rec), 200)


@bp.route("/eld/adverse-claims/<id>/reject", methods=["POST"])
def reject(id):
    _, role = get_auth()
    require_role(role, {"SafetyOfficer"})
    rec = db.adverse_claims.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Claim not found.")
    if rec["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim is not PENDING.")
    rec["status"] = "REJECTED"
    model.touch(rec)
    return response.object_response(ser.adverse_claim_view(rec), 200)
