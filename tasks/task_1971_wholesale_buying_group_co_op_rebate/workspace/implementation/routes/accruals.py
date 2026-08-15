"""RebateAccrual read endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import store, public
from errors import err_not_found, err_invalid_request
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate

bp = Blueprint("accruals", __name__)

READ_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor", "MemberRep")


def get_accrual_or_404(accrual_id):
    accrual = store.accruals.get(accrual_id)
    if accrual is None:
        raise err_not_found("RebateAccrual not found")
    return accrual


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _arg_int(name):
    v = request.args.get(name)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise err_invalid_request("%s must be an integer" % name)


@bp.route("/coop/rebate-accruals/<accrual_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_accrual(uid, role, accrual_id):
    return success_object(public(get_accrual_or_404(accrual_id)), code=200)


@bp.route("/coop/rebate-accruals", methods=["GET"])
@require_roles(*READ_ROLES)
def list_accruals(uid, role):
    limit, offset = parse_pagination()
    items = list(store.accruals.values())
    enrollment_id = _arg("enrollment_id")
    if enrollment_id is not None:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]
    quarter = _arg_int("quarter_index")
    if quarter is not None:
        items = [a for a in items if a["quarter_index"] == quarter]
    status = _arg("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(a) for a in page], limit, offset, total)
