"""Margin call endpoints (PRD §3.9, §4)."""
from flask import Blueprint, request

import constants
import errors
from db import db
from middleware import get_identity, require_role, require_account_owner
from models import _base_full, margin_call_dict, touch
from response import object_response, array_response
from routes.common import (get_account, get_margin_call, paginate, page_slice)
from services.account import recompute_account
from services.margin import liquidate_call
from timeutil import add_business_days, iso, parse_iso

bp = Blueprint("margin", __name__)


@bp.post("/accounts/<account_id>/margin-calls")
def issue_margin_call(account_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    acct = get_account(account_id)
    recompute_account(acct)

    # deficiency precondition (PRD §3.9): maintenance_excess_cents < 0
    if acct["maintenance_excess_cents"] >= 0:
        raise errors.err(errors.ERR_NO_DEFICIENCY, "No maintenance deficiency")

    # single-occupancy cure window: any ISSUED call whose [created_at, cure_by]
    # still contains the clock (cure_by >= clock) collides (PRD §3.9, window_overlap)
    clock = db.clock
    for m in db.margin_calls.values():
        if (m["account_id"] == account_id and m["status"] == "ISSUED"
                and parse_iso(m["cure_by"]) >= clock):
            raise errors.err(errors.ERR_MARGIN_CALL_ACTIVE,
                             "An issued margin call already occupies the cure window")

    rec = _base_full()
    rec.update({
        "account_id": account_id,
        "deficiency_cents": abs(acct["maintenance_excess_cents"]),
        "cure_by": iso(add_business_days(db.clock, constants.MARGIN_CURE_DAYS)),
        "status": "ISSUED",
    })
    db.margin_calls[rec["id"]] = rec

    # trading_status -> MARGIN_CALL (derived); recompute + bump version
    recompute_account(acct)
    touch(acct)
    return object_response(margin_call_dict(rec), 201)


@bp.get("/accounts/<account_id>/margin-calls")
def list_margin_calls(account_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])

    status = request.args.get("status")
    items = [m for m in db.margin_calls.values() if m["account_id"] == account_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([margin_call_dict(m) for m in page], limit, offset, total)


@bp.post("/accounts/<account_id>/margin-calls/<call_id>/liquidate")
def liquidate_margin_call(account_id, call_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    # existence left-to-right: account then call (PRD §2.6)
    acct = get_account(account_id)
    mc = get_margin_call(call_id)
    if mc["account_id"] != account_id:
        raise errors.err(errors.ERR_NOT_FOUND, "Margin call not found for this account")

    # state: must be ISSUED
    if mc["status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Margin call is not ISSUED")

    recompute_account(acct)
    # liquidation requires clock date strictly past cure_by AND excess still < 0
    from timeutil import date_floor
    if not (date_floor(db.clock) > date_floor(parse_iso(mc["cure_by"]))
            and acct["maintenance_excess_cents"] < 0):
        raise errors.err(errors.ERR_MARGIN_CALL_NOT_DUE,
                         "Liquidation not due (before cure_by or excess non-negative)")

    liquidate_call(acct, mc)
    return object_response(margin_call_dict(mc), 200)
