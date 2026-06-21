"""ServiceCharge endpoints: list, fetch, settle (PRD §3.11)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import touch, public_view, sort_by_created
from services.ledger import recompute_account

bp = Blueprint("service_charges", __name__)


def _parse_paid(raw):
    if raw is None:
        return None
    if raw.lower() in ("true", "1"):
        return True
    if raw.lower() in ("false", "0"):
        return False
    return None


@bp.route("/service-visits/<visit_id>/charges", methods=["GET"])
def list_visit_charges(visit_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    if visit_id not in db.service_visits:
        raise errors.not_found("Service visit not found.")
    limit, offset = parse_pagination()
    charge_type = request.args.get("charge_type")
    rows = [c for c in db.service_charges.values() if c["service_visit_id"] == visit_id]
    if charge_type is not None:
        rows = [c for c in rows if c["charge_type"] == charge_type]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(c) for c in page], limit, offset, total)


@bp.route("/service-charges/<charge_id>", methods=["GET"])
def get_charge(charge_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    c = db.service_charges.get(charge_id)
    if c is None:
        raise errors.not_found("Service charge not found.")
    return object_response(public_view(c), 200)


@bp.route("/service-charges", methods=["GET"])
def list_charges():
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    charge_type = request.args.get("charge_type")
    paid = _parse_paid(request.args.get("paid"))

    rows = list(db.service_charges.values())
    if account_id is not None:
        rows = [c for c in rows if c["account_id"] == account_id]
    if charge_type is not None:
        rows = [c for c in rows if c["charge_type"] == charge_type]
    if paid is not None:
        rows = [c for c in rows if c["paid"] == paid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(c) for c in page], limit, offset, total)


@bp.route("/service-charges/<charge_id>/settle", methods=["POST"])
def settle_charge(charge_id):
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    c = db.service_charges.get(charge_id)
    if c is None:
        raise errors.not_found("Service charge not found.")
    if c["paid"]:
        raise errors.charge_already_settled()

    c["paid"] = True
    touch(c)

    account = db.accounts.get(c["account_id"])
    if account is not None:
        recompute_account(account)

    return object_response(public_view(c), 200)
