"""Performance-rights advisory cases (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_FORBIDDEN_ACCOUNT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RIGHTS_CASE_NOT_FOUND,
    ERR_WORK_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_case
from services import get_or_404
from util import is_str, new_record, touch
from routes.helpers import body, paginate, require_fields

bp = Blueprint("rights", __name__)

ALL_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor", "Customer")
VENUE_KINDS = ("EDUCATIONAL", "CONCERT", "COMPETITION", "RELIGIOUS")
DETERMINATIONS = ("CLEARED", "LICENSE_REQUIRED", "PROHIBITED")


@bp.post("/library/rights-advisory-cases")
def create_case():
    require_auth("Customer", "LibraryClerk", "RightsAdvisor")
    data = body()
    require_fields(data, ["account_id", "work_id", "venue_kind", "question"])
    account = db["customer_accounts"].get(data["account_id"])
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 404, "CustomerAccount not found")
    work = db["works"].get(data["work_id"])
    if work is None:
        raise ApiError(ERR_WORK_NOT_FOUND, 404, "Work not found")
    if data["venue_kind"] not in VENUE_KINDS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid venue_kind")
    if not is_str(data["question"]):
        raise ApiError(ERR_INVALID_REQUEST, 400, "question is required")
    rec = new_record()
    rec.update(
        {
            "account_id": account["id"],
            "work_id": work["id"],
            "venue_kind": data["venue_kind"],
            "question": data["question"],
            "determination": "PENDING",
            "decided_by_user_id": None,
            "status": "OPEN",
        }
    )
    db["rights_cases"][rec["id"]] = rec
    return success_object(ser_case(rec), status=201)


@bp.get("/library/rights-advisory-cases")
def list_cases():
    require_auth(*ALL_ROLES)
    rows = list(db["rights_cases"].values())
    for param in ("account_id", "work_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [c for c in rows if c[param] == v]
    return paginate(rows, ser_case)


@bp.get("/library/rights-advisory-cases/<cid>")
def get_case(cid):
    require_auth(*ALL_ROLES)
    rec = get_or_404("rights_cases", cid, ERR_RIGHTS_CASE_NOT_FOUND)
    return success_object(ser_case(rec))


@bp.post("/library/rights-advisory-cases/<cid>/decide")
def decide_case(cid):
    uid, _ = require_auth("RightsAdvisor")
    rec = get_or_404("rights_cases", cid, ERR_RIGHTS_CASE_NOT_FOUND)
    if rec["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN case may be decided")
    data = body()
    determination = data.get("determination")
    if determination not in DETERMINATIONS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "determination must be CLEARED, LICENSE_REQUIRED, or PROHIBITED")
    rec["determination"] = determination
    rec["decided_by_user_id"] = uid
    rec["status"] = "DECIDED"
    touch(rec)
    return success_object(ser_case(rec))


@bp.post("/library/rights-advisory-cases/<cid>/withdraw")
def withdraw_case(cid):
    uid, _ = require_auth("Customer")
    rec = get_or_404("rights_cases", cid, ERR_RIGHTS_CASE_NOT_FOUND)
    if rec["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN case may be withdrawn")
    if uid != rec["account_id"]:
        raise ApiError(ERR_FORBIDDEN_ACCOUNT, 403, "Customer may act only on its own account's cases")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success_object(ser_case(rec))
