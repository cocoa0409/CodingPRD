"""SpecialRequest acknowledge route (PRD §3.7).

Append-only record: id + created_at, no version. Acknowledging sets
acknowledged true once and it is immutable thereafter.
"""
from flask import Blueprint

import db
from errors import err, ERR_INVALID_STATE
from middleware import require_roles
from response import object_response
from services.lookup import get_or_404

bp = Blueprint("special_requests", __name__)


@bp.post("/special-requests/<sid>/acknowledge")
def acknowledge(sid):
    require_roles({"Host"})
    rec = get_or_404(db.special_requests, sid)
    if rec["acknowledged"]:
        raise err(ERR_INVALID_STATE, "special request already acknowledged")
    rec["acknowledged"] = True
    return object_response(db.serialize(rec), 200)
