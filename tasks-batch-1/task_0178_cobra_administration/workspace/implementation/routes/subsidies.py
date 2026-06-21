"""Subsidy-grant get/list/revoke endpoints."""
from flask import Blueprint, request

from db import store
from middleware import require_role
from models import serialize, touch, SUBSIDY_FIELDS
from response import object_response, array_response
from timeutil import parse_year_month, year_month_index
from services.ledger import recompute_invoice_subsidy, recompute_account
from services.lookup import get_or_404, paginate, sorted_by_creation

bp = Blueprint("subsidies", __name__)


@bp.get("/subsidies/<sid>")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def get_subsidy(sid):
    sub = get_or_404(store.subsidies, sid)
    return object_response(serialize(sub, SUBSIDY_FIELDS))


@bp.get("/subsidies")
@require_role({"PlanAdministrator", "BillingAgent"})
def list_subsidies():
    enrollment_id = request.args.get("enrollment_id")
    items = list(store.subsidies.values())
    if enrollment_id is not None:
        items = [s for s in items if s["enrollment_id"] == enrollment_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(s, SUBSIDY_FIELDS) for s in page],
                          limit, offset, total)


@bp.post("/subsidies/<sid>/revoke")
@require_role({"PlanAdministrator"})
def revoke_subsidy(sid):
    sub = get_or_404(store.subsidies, sid)
    from errors import ApiError
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Subsidy is not ACTIVE")
    sub["status"] = "REVOKED"
    touch(sub)

    # Recompute subsidy on FUTURE OPEN invoices only (coverage_month later than
    # the current clock month). PAID invoices keep their applied subsidy
    # (chronological lock). PRD §3.7.
    enr = store.enrollments.get(sub["enrollment_id"])
    if enr is not None:
        now = store.now()
        now_idx = year_month_index(now.year, now.month)
        account = None
        for acc in store.accounts.values():
            if acc["enrollment_id"] == enr["id"]:
                account = acc
                break
        if account is not None:
            for inv in store.invoices.values():
                if inv["account_id"] != account["id"]:
                    continue
                if inv["status"] != "OPEN":
                    continue
                iy, im = parse_year_month(inv["coverage_month"])
                if year_month_index(iy, im) > now_idx:
                    recompute_invoice_subsidy(enr, inv)
            recompute_account(account, enr)
    return object_response(serialize(sub, SUBSIDY_FIELDS))
