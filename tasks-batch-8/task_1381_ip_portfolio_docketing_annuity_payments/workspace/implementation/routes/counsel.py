"""CounselFirm routes (PRD §3.7)."""

from flask import Blueprint

import db as dbmod
import serialize
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, get_firm, check_allowed_fields, req_str, JURISDICTIONS,
)

bp = Blueprint("counsel", __name__)


@bp.post("/counsel-firms")
def create_firm():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    check_allowed_fields(body, {"display_name", "accredited_jurisdictions"})
    display_name = req_str(body, "display_name")
    accredited = body.get("accredited_jurisdictions")
    if not isinstance(accredited, list) or any(
        not isinstance(code, str) or code not in JURISDICTIONS for code in accredited
    ):
        raise_err(ERR_INVALID_REQUEST, "accredited_jurisdictions must be an array of jurisdiction codes")
    rec = stamp_new({
        "id": new_id(),
        "display_name": display_name,
        "accredited_jurisdictions": list(accredited),
    })
    dbmod.DB["counsel_firms"][rec["id"]] = rec
    return success_object(serialize.counsel_firm(rec), 201)


@bp.get("/counsel-firms/<firm_id>")
def get_firm_route(firm_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.counsel_firm(get_firm(firm_id)))


@bp.get("/counsel-firms/<firm_id>/instructions")
def list_firm_instructions(firm_id):
    require_roles(ALL_ROLES)
    firm = get_firm(firm_id)
    limit, offset = parse_pagination()
    items = [
        ins for ins in dbmod.DB["instructions"].values()
        if ins["counsel_firm_id"] == firm["id"]
    ]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.instruction(r) for r in page], total, limit, offset)
