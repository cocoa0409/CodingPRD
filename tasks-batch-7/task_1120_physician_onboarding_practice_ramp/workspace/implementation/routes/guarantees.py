"""Income guarantee endpoints (PRD 3.8)."""

from flask import Blueprint, request

import domain as D
from db import store, bump
from errors import (
    ApiError, ERR_GUARANTEE_NOT_FOUND, ERR_GUARANTEE_NOT_DRAFT,
    ERR_GUARANTEE_NOT_ACTIVE, ERR_START_DATE_NOT_REACHED,
    ERR_REPAYMENT_EXCEEDS_OUTSTANDING,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("guarantees", __name__)


def _get_guarantee(gid):
    guarantee = store.guarantees.get(gid)
    if guarantee is None:
        raise ApiError(ERR_GUARANTEE_NOT_FOUND, 404, "IncomeGuarantee not found")
    return guarantee


@bp.route("/onboarding/income-guarantees/<gid>", methods=["GET"])
def get_guarantee(gid):
    get_context()
    return success_object(D.serialize_guarantee(_get_guarantee(gid)))


@bp.route("/onboarding/income-guarantees", methods=["GET"])
def list_guarantees():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    status = request.args.get("status")
    records = sorted(store.guarantees.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_guarantee(r) for r in records], request.args)


@bp.route("/onboarding/income-guarantees/<gid>/activate", methods=["POST"])
def activate_guarantee(gid):
    _uid, role = get_context()
    require_role(role, ["FinanceAnalyst"])
    guarantee = _get_guarantee(gid)
    if guarantee["status"] != "DRAFT":
        raise ApiError(ERR_GUARANTEE_NOT_DRAFT, 409,
                       "Only a DRAFT guarantee can be activated")
    first_day = D.parse_date(guarantee["start_month"] + "-01", "start_month")
    if D.clock_date() < first_day:
        raise ApiError(ERR_START_DATE_NOT_REACHED, 422,
                       "The logical clock has not reached the first day of start_month")
    guarantee["status"] = "ACTIVE"
    bump(guarantee)
    return success_object(D.serialize_guarantee(guarantee))


@bp.route("/onboarding/income-guarantees/<gid>/reconcile", methods=["POST"])
def reconcile_guarantee(gid):
    _uid, role = get_context()
    require_role(role, ["FinanceAnalyst"])
    guarantee = _get_guarantee(gid)
    if guarantee["status"] != "ACTIVE":
        raise ApiError(ERR_GUARANTEE_NOT_ACTIVE, 409,
                       "Reconciliation requires an ACTIVE guarantee")
    derived = D.guarantee_derived(guarantee)
    if derived["months_reconciled"] == guarantee["term_months"]:
        guarantee["status"] = "SETTLED"
    bump(guarantee)
    return success_object(D.serialize_guarantee(guarantee))


@bp.route("/onboarding/income-guarantees/<gid>/repayments", methods=["POST"])
def post_repayment(gid):
    _uid, role = get_context()
    require_role(role, ["FinanceAnalyst"])
    guarantee = _get_guarantee(gid)
    body = D.get_body()
    amount = D.non_negative(D.req_int(body, "amount_cents"), "amount_cents")
    outstanding_before = D.guarantee_derived(guarantee)["outstanding_balance_cents"]
    if amount > outstanding_before:
        raise ApiError(ERR_REPAYMENT_EXCEEDS_OUTSTANDING, 422,
                       "amount_cents exceeds the outstanding balance")
    guarantee["total_repaid_cents"] += amount
    bump(guarantee)
    return success_object(D.serialize_guarantee(guarantee), status=201)
