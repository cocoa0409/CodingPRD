"""Account endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import make_record, touch, public_view, sort_by_created
from services import validate

bp = Blueprint("accounts", __name__)


def _ensure_account(account_id):
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    return acct


@bp.route("/accounts", methods=["POST"])
def create_account():
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    body = validate.get_body()

    legal_name = validate.require_str(body, "legal_name")
    service_day = validate.require_enum(body, "service_day", validate.SERVICE_DAYS)
    grace = validate.optional_int(body, "shortage_grace_units", minimum=0, default=2)

    acct = make_record("accounts", {
        "legal_name": legal_name,
        "service_day": service_day,
        "shortage_grace_units": grace,
        "billing_status": "CURRENT",
        "outstanding_cents": 0,
        "active_wearer_count": 0,
    })
    return object_response(public_view(acct), 201)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    acct = _ensure_account(account_id)
    return object_response(public_view(acct), 200)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    limit, offset = parse_pagination()
    from flask import request
    billing_status = request.args.get("billing_status")

    rows = list(db.accounts.values())
    if billing_status is not None:
        rows = [a for a in rows if a["billing_status"] == billing_status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(a) for a in page], limit, offset, total)


@bp.route("/accounts/<account_id>/place-hold", methods=["POST"])
def place_hold(account_id):
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    acct = _ensure_account(account_id)
    # State legality: PAST_DUE -> ON_HOLD only.
    if acct["billing_status"] != "PAST_DUE":
        raise errors.invalid_state("place-hold requires a PAST_DUE account.")
    acct["billing_status"] = "ON_HOLD"
    touch(acct)
    return object_response(public_view(acct), 200)


@bp.route("/accounts/<account_id>/release-hold", methods=["POST"])
def release_hold(account_id):
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    acct = _ensure_account(account_id)
    if acct["billing_status"] != "ON_HOLD":
        raise errors.invalid_state("release-hold requires an ON_HOLD account.")
    # Permitted only while outstanding <= threshold.
    from services.ledger import PAST_DUE_THRESHOLD_CENTS
    if acct["outstanding_cents"] > PAST_DUE_THRESHOLD_CENTS:
        raise errors.invalid_state("release-hold requires outstanding at or below threshold.")
    acct["billing_status"] = "CURRENT"
    touch(acct)
    return object_response(public_view(acct), 200)
