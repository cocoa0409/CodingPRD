"""Issuer endpoints (PRD 3.1)."""
from flask import Blueprint, request

from clock import clock
from db import db, new_id, now_iso
from derive import touch
from errors import err
from middleware import get_auth, get_auth_optional, require_role
from pagination import paginate
from response import success
from serializers import issuer_out
from validation import require_body, require_str, require_enum, opt_bool

bp = Blueprint("issuers", __name__)

ENTITY_TYPES = {"C_CORP", "LLC", "BENEFIT_CORP"}


@bp.post("/issuers")
def create_issuer():
    # Public registration: Anonymous or ComplianceOfficer.
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, {"Anonymous", "ComplianceOfficer"})

    body = require_body()
    legal_name = require_str(body, "legal_name")
    ein = require_str(body, "ein")
    home_state_code = require_str(body, "home_state_code")
    entity_type = require_enum(body, "entity_type", ENTITY_TYPES)
    bad_actor_flag = opt_bool(body, "bad_actor_flag", False)

    # Uniqueness on ein (PRD 3.1 / validation priority 17).
    for existing in db.issuers.values():
        if existing["ein"] == ein:
            raise err("ERR_DUPLICATE_RESOURCE", "An issuer with this ein already exists")

    ts = now_iso()
    iid = new_id()
    rec = {
        "id": iid,
        "legal_name": legal_name,
        "ein": ein,
        "home_state_code": home_state_code,
        "entity_type": entity_type,
        "bad_actor_flag": bad_actor_flag,
        "status": "ONBOARDING",
        "total_raised_trailing_12mo_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.issuers[iid] = rec
    return success(issuer_out(rec), status=201)


@bp.get("/issuers/<id>")
def get_issuer(id):
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, {"Anonymous", "Issuer", "ComplianceOfficer"})
    rec = db.issuers.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Issuer not found")
    return success(issuer_out(rec))


@bp.get("/issuers")
def list_issuers():
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, {"Anonymous", "ComplianceOfficer"})
    rows = list(db.issuers.values())
    hsc = request.args.get("home_state_code")
    if hsc is not None:
        rows = [r for r in rows if r["home_state_code"] == hsc]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows)
    return success([issuer_out(r) for r in page], pagination=meta)


@bp.post("/issuers/<id>/verify")
def verify_issuer(id):
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    rec = db.issuers.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Issuer not found")
    if rec["status"] != "ONBOARDING":
        raise err("ERR_INVALID_STATE", "Issuer is not in ONBOARDING")
    if rec["bad_actor_flag"]:
        raise err("ERR_BAD_ACTOR_DISQUALIFIED", "A bad-actor-flagged issuer cannot be verified")
    rec["status"] = "VERIFIED"
    touch(rec)
    return success(issuer_out(rec))


@bp.post("/issuers/<id>/bar")
def bar_issuer(id):
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    rec = db.issuers.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Issuer not found")
    if rec["status"] != "ONBOARDING":
        raise err("ERR_INVALID_STATE", "Issuer is not in ONBOARDING")
    rec["status"] = "BARRED"
    touch(rec)
    return success(issuer_out(rec))
