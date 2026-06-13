"""Families (PRD §3.2)."""
from flask import Blueprint

from db import db
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import get_identity, require_roles, ROLE_FRONTDESK, ROLE_MEMBER
from response import success
from common import get_json_body, require_fields, require_email
from services.serialize import view

bp = Blueprint("families", __name__)


@bp.post("/dojo/families")
def create_family():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    body = get_json_body()
    require_fields(body, ["surname", "billing_email"])
    if not isinstance(body["surname"], str) or not (1 <= len(body["surname"]) <= 80):
        raise err(ERR_INVALID_REQUEST, "surname must be 1..80 chars.")
    require_email(body["billing_email"], "billing_email")

    now = db.now_iso()
    fid = db.new_id()
    fam = {
        "id": fid,
        "surname": body["surname"],
        "billing_email": body["billing_email"],
        "active_member_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.families[fid] = fam
    return success(view(fam), 201)


@bp.get("/dojo/families/<fid>")
def get_family(fid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    fam = db.families.get(fid)
    if fam is None:
        raise err(ERR_NOT_FOUND, "Family not found.")
    return success(view(fam), 200)
