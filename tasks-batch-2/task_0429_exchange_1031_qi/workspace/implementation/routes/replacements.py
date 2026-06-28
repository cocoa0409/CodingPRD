"""Global replacement-property read endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
import response
import pagination
from middleware import (
    require_auth, require_role,
    QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER,
)
from services import core

bp = Blueprint("replacements", __name__)

READ_ROLES = {QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER}


@bp.get("/replacement-properties/<replacement_id>")
def get_replacement(replacement_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    rp = db.replacement_properties.get(replacement_id)
    if rp is None:
        raise errors.not_found()
    if role == EXCHANGER:
        ex = db.exchanges.get(rp["exchange_id"])
        if ex is None or ex["exchanger_id"] != user_id:
            raise errors.unauthorized()
    return response.success_object(core.serialize_replacement(rp))


@bp.get("/replacement-properties")
def list_replacements():
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR, SETTLEMENT_OFFICER})
    limit, offset = pagination.read_params()
    rows = list(db.replacement_properties.values())
    exchange_id = request.args.get("exchange_id")
    identified_property_id = request.args.get("identified_property_id")
    if exchange_id is not None:
        rows = [r for r in rows if r["exchange_id"] == exchange_id]
    if identified_property_id is not None:
        rows = [r for r in rows if r["identified_property_id"] == identified_property_id]
    page, meta = pagination.paginate(rows, limit, offset)
    return response.success_array([core.serialize_replacement(r) for r in page], pagination=meta)
