"""Demurrage invoice endpoints (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint

from errors import APIError, ERR_INVALID_STATE
from middleware import require
from response import ok_object
from services import serialize
from services.common import touch
from services.lookups import path_invoice

bp = Blueprint("demurrage_invoices", __name__)


@bp.get("/demurrage-invoices/<iid>")
@require("TerminalAdmin", "GateOperator")
def get_invoice(iid):
    rec = path_invoice(iid)
    return ok_object(serialize.demurrage_invoice(rec))


@bp.post("/demurrage-invoices/<iid>/pay")
@require("TerminalAdmin")
def pay_invoice(iid):
    inv = path_invoice(iid)
    if inv["status"] != "ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, "invoice is not ISSUED")
    inv["status"] = "PAID"
    touch(inv)
    return ok_object(serialize.demurrage_invoice(inv))


@bp.post("/demurrage-invoices/<iid>/waive")
@require("TerminalAdmin")
def waive_invoice(iid):
    inv = path_invoice(iid)
    if inv["status"] != "ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, "invoice is not ISSUED")
    inv["status"] = "WAIVED"
    touch(inv)
    return ok_object(serialize.demurrage_invoice(inv))
