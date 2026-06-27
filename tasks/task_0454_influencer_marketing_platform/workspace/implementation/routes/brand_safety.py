from flask import Blueprint, request

from db import db, base_fields, bump
from middleware import get_auth, require_role
from validators import get_body, req_enum, opt_str
from errors import err
from response import success
from pagination import paginate
import serializers as S
import services as svc
import derive

bp = Blueprint("brand_safety", __name__)

SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
REASON_CODES = {"HATE_SPEECH", "FRAUD_SIGNAL", "NSFW", "MISINFORMATION", "OTHER"}


@bp.route("/creators/<creator_id>/brand-safety-flags", methods=["POST"])
def open_flag(creator_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    c = svc.get_creator(creator_id)
    body = get_body()
    severity = req_enum(body, "severity", SEVERITIES)
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    note = opt_str(body, "note", default="")

    rec = base_fields()
    rec.update({
        "creator_id": creator_id,
        "severity": severity,
        "reason_code": reason_code,
        "note": note if note is not None else "",
        "status": "OPEN",
    })
    db.brand_safety_flags[rec["id"]] = rec
    derive.recompute_brand_safety_status(c)
    return success(S.brand_safety_flag_view(rec), status=201)


@bp.route("/creators/<creator_id>/brand-safety-flags", methods=["GET"])
def list_flags(creator_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "ComplianceOfficer", "Brand"})
    svc.get_creator(creator_id)
    status = request.args.get("status")
    rows = [f for f in db.brand_safety_flags.values() if f["creator_id"] == creator_id]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    page, meta = paginate(rows)
    return success([S.brand_safety_flag_view(f) for f in page], status=200, pagination=meta)


@bp.route("/brand-safety-flags/<flag_id>/resolve", methods=["POST"])
def resolve_flag(flag_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    f = svc.get_brand_safety_flag(flag_id)
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Flag is not OPEN")
    f["status"] = "RESOLVED"
    bump(f)
    c = db.creators.get(f["creator_id"])
    if c:
        derive.recompute_brand_safety_status(c)
    return success(S.brand_safety_flag_view(f), status=200)
