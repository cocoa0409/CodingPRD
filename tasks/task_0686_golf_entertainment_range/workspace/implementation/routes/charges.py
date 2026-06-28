"""Charge ledger read routes (PRD §3.12; SCAFFOLD §1.5)."""

from flask import Blueprint, request

from db import db
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles
from services.lookup import get_or_404
from services.serialize import charge_out

bp = Blueprint("charges", __name__)


@bp.get("/golf/charges/<charge_id>")
def get_charge(charge_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    c = get_or_404(db.charges, charge_id, "charge")
    return success(charge_out(c))


@bp.get("/golf/charges")
def list_charges():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(request.args)
    records = list(db.charges.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        records = [c for c in records if c["member_id"] == member_id]
    window, total = paginate(records, limit, offset)
    return list_success([charge_out(c) for c in window], limit, offset, total)
