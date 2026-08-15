"""CommissionStatement endpoints."""

import db
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import compute_commission
from util import pagination_params, paginate, apply_filters, require_fk

bp = make_blueprint("commissions")

ADMIN = ["DealerAdmin"]


@bp.get("/commission-statements/<sid>")
def get_statement(sid):
    authenticate(ADMIN)
    return success_obj(db.public(require_fk("commission_statements", sid, "commission statement")), 200)


@bp.get("/commission-statements")
def list_statements():
    authenticate(ADMIN)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("commission_statements"), ["program_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(s) for s in page], limit, offset, total, has_more)


@bp.post("/commission-statements/<sid>/recompute")
def recompute_statement(sid):
    authenticate(ADMIN)
    statement = require_fk("commission_statements", sid, "commission statement")
    if statement["status"] != "ACCRUING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an ACCRUING statement can be recomputed")
    program = db.get("programs", statement["program_id"])
    for k, v in compute_commission(program, final=False).items():
        statement[k] = v
    db.touch(statement)
    return success_obj(db.public(statement), 200)


@bp.post("/commission-statements/<sid>/mark_paid")
def mark_paid(sid):
    authenticate(ADMIN)
    statement = require_fk("commission_statements", sid, "commission statement")
    if statement["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a FINALIZED statement can be marked paid")
    statement["status"] = "PAID"
    statement["paid_at"] = db.fmt_ts(db.now())
    db.touch(statement)
    return success_obj(db.public(statement), 200)
