"""MatchingGift read endpoints (PRD §3.6). Gifts are created/transitioned
only as side effects of donation workflows."""
from flask import Blueprint, request

from db import db
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import serialize, find_or_404, paginate

bp = Blueprint("matching_gifts", __name__)


@bp.route("/matching-gifts/<match_id>", methods=["GET"])
def get_matching_gift(match_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.matching_gifts, match_id)
    return object_response(serialize(rec), 200)


@bp.route("/matching-gifts", methods=["GET"])
def list_matching_gifts():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    program_id = request.args.get("program_id")
    donation_id = request.args.get("donation_id")
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    items = []
    for m in db.matching_gifts.values():
        if program_id is not None and m["program_id"] != program_id:
            continue
        if donation_id is not None and m["donation_id"] != donation_id:
            continue
        if employee_id is not None and m["employee_id"] != employee_id:
            continue
        if status is not None and m["status"] != status:
            continue
        items.append(m)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(m) for m in page], limit, offset, total, 200)
