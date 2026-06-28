from flask import Blueprint, g, request

from db import store
from errors import fail, ERR_NOT_PROGRAM_OWNER
from middleware import require_roles
from response import success
from routes.helpers import lookup, paginate, sort_by_created
from services.serialize import fee_out

bp = Blueprint("fees", __name__)


@bp.get("/fees/<fid>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_fee(fid):
    f = lookup(store.fees, fid)
    _scope(f["program_id"])
    return success(fee_out(f))


@bp.get("/fees")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_fees():
    items = list(store.fees.values())
    program_id = request.args.get("program_id")
    settlement_id = request.args.get("settlement_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [f for f in items if f["program_id"] == program_id]
    if settlement_id is not None:
        items = [f for f in items if f["settlement_id"] == settlement_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if g.role == "Client":
        items = [f for f in items
                 if store.programs.get(f["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([fee_out(f) for f in page], pagination=pagination)


def _scope(program_id):
    if g.role == "Client":
        p = store.programs.get(program_id)
        if p is None or p["client_id"] != g.user_id:
            fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own resources")
