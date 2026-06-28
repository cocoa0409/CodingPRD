"""Statement read endpoints (PRD §3.6, §3.7)."""
from flask import Blueprint, request

import db
import common
import errors
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import statement_out

bp = Blueprint("statements", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]


@bp.get("/statements/<sid>")
def get_statement(sid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_statement(sid)
    return success_object(statement_out(rec), status=200)


@bp.get("/statements")
def list_statements():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.statements.values())
    membership_id = request.args.get("membership_id")
    club_id = request.args.get("club_id")
    period_index = request.args.get("period_index")
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    if period_index is not None:
        try:
            pi = int(period_index)
        except (ValueError, TypeError):
            raise errors.invalid_request("period_index must be an integer")
        records = [r for r in records if r["period_index"] == pi]
    page, total = common.sort_and_page(records, limit, offset)
    data = [statement_out(r) for r in page]
    return success_array(data, limit, offset, total)
