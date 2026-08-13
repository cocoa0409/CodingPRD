"""Owner endpoints and standing administration (PRD 2.10)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import (
    has_past_due_invoice,
    new_common,
    owner_view,
    touch,
)
from util import as_int, as_str, body, paginate_sorted, required

bp = Blueprint("owners", __name__)


def _get_owner(oid):
    o = db.owners.get(oid)
    if not o:
        raise ApiError("ERR_NOT_FOUND", 404, "Owner not found")
    return o


@bp.route("/owners", methods=["POST"])
def create_owner():
    require_roles("ProgramAdmin")
    data = body()
    program_id = as_str(required(data, "program_id"), "program_id")
    if program_id not in db.programs:
        raise ApiError("ERR_NOT_FOUND", 404, "Program not found")
    legal_name = as_str(required(data, "legal_name"), "legal_name")
    deposit = as_int(
        required(data, "initial_deposit_cents"), "initial_deposit_cents"
    )
    if deposit < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "initial_deposit_cents must be >= 0"
        )

    rec = new_common()
    rec.update({
        "legal_name": legal_name,
        "program_id": program_id,
        "owner_standing": "GOOD",
        "deposit_balance_cents": deposit,
    })
    db.owners[rec["id"]] = rec
    return ok(owner_view(rec), status=201)


@bp.route("/owners/<oid>", methods=["GET"])
def get_owner(oid):
    require_roles(*ALL_ROLES)
    return ok(owner_view(_get_owner(oid)))


@bp.route("/owners", methods=["GET"])
def list_owners():
    require_roles(*ALL_ROLES)
    program_id = request.args.get("program_id")
    standing = request.args.get("owner_standing")
    items = list(db.owners.values())
    if program_id is not None:
        items = [o for o in items if o["program_id"] == program_id]
    if standing is not None:
        items = [o for o in items if o["owner_standing"] == standing]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([owner_view(o) for o in page], total, limit, offset)


@bp.route("/owners/<oid>/suspend", methods=["POST"])
def suspend_owner(oid):
    require_roles("ProgramAdmin")
    o = _get_owner(oid)
    if o["owner_standing"] == "EXITED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Owner is EXITED")
    if o["owner_standing"] not in ("GOOD", "DELINQUENT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Owner must be GOOD or DELINQUENT to suspend")
    o["owner_standing"] = "SUSPENDED"
    touch(o)
    return ok(owner_view(o))


@bp.route("/owners/<oid>/reinstate", methods=["POST"])
def reinstate_owner(oid):
    require_roles("ProgramAdmin")
    o = _get_owner(oid)
    if o["owner_standing"] == "EXITED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Owner is EXITED")
    if o["owner_standing"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Owner must be SUSPENDED to reinstate")
    if has_past_due_invoice(o["id"]):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Owner has PAST_DUE invoices")
    o["owner_standing"] = "GOOD"
    touch(o)
    return ok(owner_view(o))
