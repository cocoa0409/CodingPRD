from flask import Blueprint, g, request

from db import store, stamp_new, touch
from errors import (
    fail,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_PROGRAM_OWNER,
)
from middleware import require_roles
from response import success
from clock import parse_iso8601
from routes.helpers import get_body, require_fields, require_string, lookup, paginate, sort_by_created
from services import core
from services.serialize import lawsuit_out

bp = Blueprint("lawsuits", __name__)


@bp.post("/lawsuits")
@require_roles("ProgramAdmin")
def create_lawsuit():
    body = get_body()
    require_fields(body, ["program_id", "debt_id", "court_reference", "filed_at"])
    program_id = body["program_id"]
    lookup(store.programs, program_id)
    debt = lookup(store.debts, body["debt_id"])
    if debt["program_id"] != program_id:
        fail(ERR_NOT_FOUND, "debt does not belong to the named program")

    court_reference = require_string(body["court_reference"], "court_reference")
    filed_raw = body["filed_at"]
    if parse_iso8601(filed_raw) is None:
        fail(ERR_INVALID_REQUEST, "filed_at must be a valid ISO8601 instant")

    # Debt may be referred from ENROLLED or IN_NEGOTIATION
    if debt["status"] not in ("ENROLLED", "IN_NEGOTIATION"):
        fail(ERR_INVALID_STATE, "Debt cannot be referred from its current state")

    lw = stamp_new({
        "program_id": program_id,
        "debt_id": debt["id"],
        "court_reference": court_reference,
        "filed_at": filed_raw,
        "status": "REFERRED",
    })
    store.lawsuits[lw["id"]] = lw

    debt["status"] = "LAWSUIT"
    touch(debt)

    return success(lawsuit_out(lw), status=201)


@bp.get("/lawsuits/<lid>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_lawsuit(lid):
    lw = lookup(store.lawsuits, lid)
    _scope(lw["program_id"])
    return success(lawsuit_out(lw))


@bp.get("/lawsuits")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_lawsuits():
    items = list(store.lawsuits.values())
    program_id = request.args.get("program_id")
    debt_id = request.args.get("debt_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [lw for lw in items if lw["program_id"] == program_id]
    if debt_id is not None:
        items = [lw for lw in items if lw["debt_id"] == debt_id]
    if status is not None:
        items = [lw for lw in items if lw["status"] == status]
    if g.role == "Client":
        items = [lw for lw in items
                 if store.programs.get(lw["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([lawsuit_out(lw) for lw in page], pagination=pagination)


@bp.post("/lawsuits/<lid>/dismiss")
@require_roles("ProgramAdmin")
def dismiss_lawsuit(lid):
    lw = lookup(store.lawsuits, lid)
    if lw["status"] != "REFERRED":
        fail(ERR_INVALID_STATE, "Lawsuit is not REFERRED")
    lw["status"] = "RESOLVED_DISMISSED"
    touch(lw)
    debt = store.debts.get(lw["debt_id"])
    if debt is not None and debt["status"] == "LAWSUIT":
        # Revert to IN_NEGOTIATION if it had a prior offer, else ENROLLED
        had_offer = any(o["debt_id"] == debt["id"] for o in store.offers.values())
        debt["status"] = "IN_NEGOTIATION" if had_offer else "ENROLLED"
        touch(debt)
    return success(lawsuit_out(lw))


def _scope(program_id):
    if g.role == "Client":
        p = store.programs.get(program_id)
        if p is None or p["client_id"] != g.user_id:
            fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own resources")
