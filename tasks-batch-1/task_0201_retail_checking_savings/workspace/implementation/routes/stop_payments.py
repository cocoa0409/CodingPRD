"""Stop-payment orders — PRD §3.10."""
from flask import Blueprint, request, g

from db import db, parse_date
from middleware import require_roles
from response import object_response
from models import stamp_new, public
from services.validate import get_body, require_fields
from services.resolve import get_account, require_account_owner
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("stop_payments", __name__)


def serialize_stop(s):
    return public(s)


@bp.route("/accounts/<account_id>/stop-payments", methods=["POST"])
@require_roles("AccountHolder")
def create_stop(account_id):
    a = get_account(account_id)
    require_account_owner(a, g.user_id)
    body = get_body()
    require_fields(body, "check_number", "max_amount_cents", "expires_on")

    max_amount = body["max_amount_cents"]
    if not isinstance(max_amount, int) or isinstance(max_amount, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "max_amount_cents must be an integer")

    check_number = body["check_number"]

    # Duplicate ACTIVE stop on same check_number (priority 16) precedes the
    # expiry-in-past check (priority 17) per validation ordering.
    existing = [
        s for s in db.stop_payments.values()
        if s["account_id"] == account_id and s["status"] == "ACTIVE"
        and s["check_number"] == check_number
    ]
    if existing:
        raise ApiError(errors.ERR_DUPLICATE_STOP_PAYMENT, 409,
                       "An ACTIVE stop already covers this check_number")

    # expires_on must be strictly after the current ledger clock date (priority 17).
    try:
        exp = parse_date(body["expires_on"])
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "expires_on must be an ISO date")
    if exp is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "expires_on must be an ISO date")
    if exp <= db.clock_date():
        raise ApiError(errors.ERR_STOP_EXPIRY_IN_PAST, 422,
                       "expires_on must be strictly after the ledger clock date")

    stop = {
        "account_id": account_id,
        "check_number": check_number,
        "max_amount_cents": max_amount,
        "status": "ACTIVE",
        "expires_on": body["expires_on"],
    }
    stamp_new(stop)
    db.stop_payments[stop["id"]] = stop
    return object_response(serialize_stop(stop), status=201)


@bp.route("/accounts/<account_id>/stop-payments", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def list_stops(account_id):
    get_account(account_id)
    status = request.args.get("status")
    rows = [s for s in db.stop_payments.values() if s["account_id"] == account_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return paged_list(rows, serializer=serialize_stop)
