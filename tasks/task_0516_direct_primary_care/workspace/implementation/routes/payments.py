"""Payment read endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from middleware import authenticate, require_roles
from routes.helpers import get_or_404, require_member_owns

bp = Blueprint("payments", __name__)


@bp.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Member"})
    p = get_or_404("payment", pid)
    if caller.role == "Member":
        require_member_owns(caller, p["member_id"])
    return response.object_response(serialize.payment(p), 200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Member"})
    limit, offset = validate.pagination()
    member_id = request.args.get("member_id")
    membership_id = request.args.get("membership_id")
    invoice_id = request.args.get("invoice_id")
    charge_kind = request.args.get("charge_kind")

    rows = list(db.payments.values())
    if caller.role == "Member":
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if membership_id is not None:
        rows = [r for r in rows if r.get("membership_id") == membership_id]
    if invoice_id is not None:
        rows = [r for r in rows if r.get("invoice_id") == invoice_id]
    if charge_kind is not None:
        rows = [r for r in rows if r["charge_kind"] == charge_kind]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.payment(r) for r in page], limit, offset, total, 200
    )
