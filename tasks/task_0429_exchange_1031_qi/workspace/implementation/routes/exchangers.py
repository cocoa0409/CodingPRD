"""Exchanger endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import response
import validate
from middleware import require_auth, require_role, QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER
from services import core

bp = Blueprint("exchangers", __name__)


@bp.post("/exchangers")
def create_exchanger():
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    data = validate.body()
    # legal_name non-empty; taxpayer_id and email required strings (PRD §3.1).
    legal_name = validate.require_str(data, "legal_name")
    taxpayer_id = validate.require_str(data, "taxpayer_id")
    email = validate.require_str(data, "email", allow_empty=True)
    # taxpayer_id is a uniqueness key (PRD §3.1) -> ERR_DUPLICATE_TAXPAYER_ID.
    for r in db.exchangers.values():
        if r["taxpayer_id"] == taxpayer_id:
            raise errors.duplicate_taxpayer_id()
    record = core._stamp_new({
        "legal_name": legal_name,
        "taxpayer_id": taxpayer_id,
        "email": email,
    })
    db.exchangers[record["id"]] = record
    return response.success_object(core.serialize_exchanger(record), status=201)


@bp.get("/exchangers/<exchanger_id>")
def get_exchanger(exchanger_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER})
    record = db.exchangers.get(exchanger_id)
    if record is None:
        raise errors.not_found()
    # Exchanger may read only their own record (PRD §2.1 ownership).
    if role == EXCHANGER and user_id != record["id"]:
        raise errors.unauthorized()
    return response.success_object(core.serialize_exchanger(record))
