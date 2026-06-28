"""Settlement endpoints (PRD §3.6, §4)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role, require_account_owner
from models import settlement_dict
from response import object_response, array_response
from routes.common import get_account, get_settlement, paginate, page_slice
from services.settlement import fail_leg

bp = Blueprint("settlements", __name__)


@bp.get("/accounts/<account_id>/settlements")
def list_settlements(account_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])

    fill_id = request.args.get("fill_id")
    status = request.args.get("status")

    items = [s for s in db.settlements.values() if s["account_id"] == account_id]
    if fill_id is not None:
        items = [s for s in items if s["fill_id"] == fill_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([settlement_dict(s) for s in page], limit, offset, total)


@bp.post("/settlements/<settlement_id>/fail")
def fail_settlement(settlement_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    s = get_settlement(settlement_id)

    if s["status"] != "UNSETTLED":
        raise errors.err(errors.ERR_INVALID_STATE, "Settlement is not UNSETTLED")

    fail_leg(s)
    return object_response(settlement_dict(s), 200)
