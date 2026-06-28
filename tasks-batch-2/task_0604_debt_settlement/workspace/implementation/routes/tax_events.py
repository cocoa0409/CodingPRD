from flask import Blueprint, g, request

from db import store
from errors import fail, ERR_NOT_PROGRAM_OWNER
from middleware import require_roles
from response import success
from routes.helpers import lookup, paginate, sort_by_created
from services.serialize import tax_event_out

bp = Blueprint("tax_events", __name__)


@bp.get("/tax-events/<tid>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_tax_event(tid):
    t = lookup(store.tax_events, tid)
    _scope(t["program_id"])
    return success(tax_event_out(t))


@bp.get("/tax-events")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_tax_events():
    items = list(store.tax_events.values())
    program_id = request.args.get("program_id")
    source_settlement_id = request.args.get("source_settlement_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [t for t in items if t["program_id"] == program_id]
    if source_settlement_id is not None:
        items = [t for t in items if t["source_settlement_id"] == source_settlement_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if g.role == "Client":
        items = [t for t in items
                 if store.programs.get(t["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([tax_event_out(t) for t in page], pagination=pagination)


def _scope(program_id):
    if g.role == "Client":
        p = store.programs.get(program_id)
        if p is None or p["client_id"] != g.user_id:
            fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own resources")
