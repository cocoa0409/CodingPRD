"""Administrative billing-month clock (PRD §3.10)."""
from flask import Blueprint

import db
from middleware import authenticate, require_role
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance_month", methods=["POST"])
def advance_month():
    _, role = authenticate()
    require_role(role, {"LineManager"})
    # Reset every operator's jeta_month_cumulative_gallons to 0. Each such
    # recompute is a mutation that bumps version + updated_at (PRD §2.8).
    for op in db.operators.values():
        op["jeta_month_cumulative_gallons"] = 0
        db.touch(op)
    # Returns no resource body (null data).
    return success(None, 200)
