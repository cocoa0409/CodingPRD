"""State permits."""
from flask import Blueprint, request

from common import (ApiError, actor, as_date, as_enum, as_str, bad_request,
                    body_dict, created, invalid_state, not_found, ok, ok_list,
                    paginate, ser)
from logic import (MATERIALS, REGIMES, lazy_expire_permit, new_record,
                   sorted_items, touch)
from store import db

bp = Blueprint("permits", __name__)


def _expire_all():
    for p in db.permits.values():
        lazy_expire_permit(p)


def _duplicate_exists(state_code, material_type, exclude_id=None):
    _expire_all()
    for p in db.permits.values():
        if p["id"] == exclude_id:
            continue
        if (p["state_code"] == state_code
                and p["material_type"] == material_type
                and p["status"] in ("FILED", "ACTIVE")):
            return True
    return False


@bp.post("/api/state-permits")
def create_permit():
    actor({"ComplianceOfficer"})
    body = body_dict()
    state_code = as_str(body, "state_code")
    material = as_enum(body, "material_type", MATERIALS)
    regime = as_enum(body, "regime", REGIMES)
    permit_number = as_str(body, "permit_number")
    issued_on = as_date(body, "issued_on")
    expires_on = as_date(body, "expires_on")
    if expires_on < issued_on:
        bad_request("expires_on must be on or after issued_on")
    if _duplicate_exists(state_code, material):
        raise ApiError("ERR_DUPLICATE_PERMIT", 409,
                       "A FILED or ACTIVE permit already exists for this pair")
    rec = new_record()
    rec.update(state_code=state_code, material_type=material, regime=regime,
               permit_number=permit_number, issued_on=issued_on,
               expires_on=expires_on, status="FILED")
    db.permits[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/state-permits")
def list_permits():
    actor()
    _expire_all()
    items = sorted_items(db.permits.values())
    sc = request.args.get("state_code")
    mt = request.args.get("material_type")
    st = request.args.get("status")
    if sc is not None:
        items = [r for r in items if r["state_code"] == sc]
    if mt is not None:
        items = [r for r in items if r["material_type"] == mt]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.post("/api/state-permits/<pid>/activate")
def activate_permit(pid):
    actor({"ComplianceOfficer"})
    rec = db.permits.get(pid)
    if rec is None:
        not_found("Permit not found")
    lazy_expire_permit(rec)
    if rec["status"] != "FILED":
        invalid_state()
    if _duplicate_exists(rec["state_code"], rec["material_type"],
                         exclude_id=rec["id"]):
        raise ApiError("ERR_DUPLICATE_PERMIT", 409,
                       "A FILED or ACTIVE permit already exists for this pair")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(ser(rec))


@bp.post("/api/state-permits/<pid>/revoke")
def revoke_permit(pid):
    actor({"ComplianceOfficer"})
    rec = db.permits.get(pid)
    if rec is None:
        not_found("Permit not found")
    lazy_expire_permit(rec)
    if rec["status"] != "ACTIVE":
        invalid_state()
    rec["status"] = "REVOKED"
    touch(rec)
    return ok(ser(rec))
