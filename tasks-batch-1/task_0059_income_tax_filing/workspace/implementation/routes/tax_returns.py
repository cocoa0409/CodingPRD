from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, require_enum, require_bool,
                  paginate, sorted_by_created)
from serialize import public, public_list
from services.common import (get_taxpayer_or_fk, get_return_or_404, owner_check_return)
from services import compute

bp = Blueprint("tax_returns", __name__)

FILING_STATUSES = {"SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"}
DEDUCTION_METHODS = {"STANDARD", "ITEMIZED"}

COMPUTED_FIELDS = [
    "total_income_cents", "agi_cents", "taxable_income_cents",
    "tax_before_credits_cents", "total_credits_cents", "tax_after_credits_cents",
    "total_payments_cents", "balance_due_cents",
]


@bp.post("/tax-returns")
def create_return():
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    body = get_body()

    taxpayer_id = require_str(body, "taxpayer_id")
    tax_year = require_int(body, "tax_year", min_value=2020)
    filing_status = require_enum(body, "filing_status", FILING_STATUSES)
    deduction_method = require_enum(body, "deduction_method", DEDUCTION_METHODS,
                                    required=False, default="STANDARD")

    # FK existence
    get_taxpayer_or_fk(taxpayer_id)
    # ownership: the created return's taxpayer must match the caller
    if taxpayer_id != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER,
                  "Caller may only create returns for themselves")

    ret = {
        "taxpayer_id": taxpayer_id,
        "tax_year": tax_year,
        "filing_status": filing_status,
        "status": "DRAFT",
        "deduction_method": deduction_method,
        "total_income_cents": 0,
        "agi_cents": 0,
        "taxable_income_cents": 0,
        "tax_before_credits_cents": 0,
        "total_credits_cents": 0,
        "tax_after_credits_cents": 0,
        "total_payments_cents": 0,
        "balance_due_cents": 0,
        "computed_at": None,
    }
    init_common(ret)
    db.tax_returns[ret["id"]] = ret
    return success(public(ret), status=201)


@bp.get("/tax-returns/<return_id>")
def get_return(return_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    return success(public(ret))


@bp.get("/tax-returns")
def list_returns():
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    items = list(db.tax_returns.values())
    # Taxpayer/Preparer only see their own returns
    items = [r for r in items if r["taxpayer_id"] == user_id]
    tp_filter = request.args.get("taxpayer_id")
    if tp_filter is not None:
        items = [r for r in items if r["taxpayer_id"] == tp_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


@bp.patch("/tax-returns/<return_id>")
def patch_return(return_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    body = get_body()

    deduction_method = require_enum(body, "deduction_method", DEDUCTION_METHODS,
                                    required=False, default=None)
    filing_status = require_enum(body, "filing_status", FILING_STATUSES,
                                 required=False, default=None)
    reopen = require_bool(body, "reopen", required=False, default=None)

    reopening = reopen is True
    if reopening:
        if ret["status"] != "REJECTED":
            raise err(errors.ERR_INVALID_STATE,
                      "reopen only valid from REJECTED status")

    if deduction_method is not None:
        ret["deduction_method"] = deduction_method
    if filing_status is not None:
        ret["filing_status"] = filing_status

    if reopening:
        ret["status"] = "DRAFT"

    touch(ret)
    return success(public(ret))


@bp.post("/tax-returns/<return_id>/compute")
def compute_return(return_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)

    # state legality: compute defined from DRAFT and READY
    if ret["status"] not in ("DRAFT", "READY"):
        raise err(errors.ERR_INVALID_STATE,
                  "compute not defined from current state")

    # >= 1 IncomeDocument
    docs = [d for d in db.income_documents.values() if d["return_id"] == return_id]
    if len(docs) < 1:
        raise err(errors.ERR_NO_INCOME_DOCUMENTS,
                  "compute requires at least one income document")

    # ITEMIZED requires Schedule A
    if ret["deduction_method"] == "ITEMIZED":
        has_a = any(s["return_id"] == return_id and s["schedule_type"] == "A"
                    for s in db.schedules.values())
        if not has_a:
            raise err(errors.ERR_ITEMIZED_REQUIRES_SCHEDULE_A,
                      "ITEMIZED deduction requires a Schedule A")

    compute.compute_return_tax(ret)
    ret["status"] = "READY"
    touch(ret)
    return success(public(ret))


@bp.get("/tax-returns/<return_id>/estimated-tax-status")
def estimated_tax_status(return_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    result = compute.compute_underpayment_penalty(ret)
    return success(result)
