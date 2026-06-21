from flask import Blueprint
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, require_bool, require_enum,
                  paginate, sorted_by_created)
from serialize import public, public_list
from services.common import get_return_or_404, owner_check_return

bp = Blueprint("children", __name__)

EDITORS = {"Taxpayer", "Preparer"}
DOC_TYPES = {"W2", "1099_NEC", "1099_INT", "1099_DIV", "1099_B"}
SCHEDULE_TYPES = {"A", "B", "C", "D", "E"}
CREDIT_TYPES = {"EITC", "CTC", "AOTC"}


def _invalidate_if_ready(ret):
    """Adding a child to a READY return resets it to DRAFT (compute invalidation)."""
    if ret["status"] == "READY":
        ret["status"] = "DRAFT"
    touch(ret)


# --- IncomeDocument --------------------------------------------------------

@bp.post("/tax-returns/<return_id>/income-documents")
def create_income_document(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    body = get_body()

    doc_type = require_enum(body, "doc_type", DOC_TYPES)
    payer_name = require_str(body, "payer_name")
    box_amount = require_int(body, "box_amount_cents", min_value=0)
    withholding = require_int(body, "federal_withholding_cents", required=False,
                              default=0, min_value=0)
    qualified_div = require_int(body, "qualified_dividends_cents", required=False,
                                default=0, min_value=0)
    proceeds = require_int(body, "proceeds_cents", required=False, default=0, min_value=0)
    cost_basis = require_int(body, "cost_basis_cents", required=False, default=0, min_value=0)
    holding_long_term = require_bool(body, "holding_long_term", required=False, default=False)

    if qualified_div > box_amount:
        raise err(errors.ERR_INVALID_REQUEST,
                  "qualified_dividends_cents may not exceed box_amount_cents")

    doc = {
        "return_id": return_id,
        "doc_type": doc_type,
        "payer_name": payer_name,
        "box_amount_cents": box_amount,
        "federal_withholding_cents": withholding,
        "qualified_dividends_cents": qualified_div,
        "proceeds_cents": proceeds,
        "cost_basis_cents": cost_basis,
        "holding_long_term": holding_long_term,
    }
    init_common(doc)
    db.income_documents[doc["id"]] = doc
    _invalidate_if_ready(ret)
    return success(public(doc), status=201)


@bp.get("/tax-returns/<return_id>/income-documents")
def list_income_documents(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    items = [d for d in db.income_documents.values() if d["return_id"] == return_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


# --- Schedule --------------------------------------------------------------

@bp.post("/tax-returns/<return_id>/schedules")
def create_schedule(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    body = get_body()

    schedule_type = require_enum(body, "schedule_type", SCHEDULE_TYPES)
    gross = require_int(body, "gross_amount_cents", required=False, default=0, min_value=0)
    expense = require_int(body, "expense_amount_cents", required=False, default=0, min_value=0)

    for s in db.schedules.values():
        if s["return_id"] == return_id and s["schedule_type"] == schedule_type:
            raise err(errors.ERR_DUPLICATE_CHILD,
                      "Schedule of this type already exists on the return")

    sched = {
        "return_id": return_id,
        "schedule_type": schedule_type,
        "gross_amount_cents": gross,
        "expense_amount_cents": expense,
        "net_amount_cents": 0,
    }
    init_common(sched)
    db.schedules[sched["id"]] = sched
    _invalidate_if_ready(ret)
    return success(public(sched), status=201)


@bp.get("/tax-returns/<return_id>/schedules")
def list_schedules(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    items = [s for s in db.schedules.values() if s["return_id"] == return_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


# --- Dependent -------------------------------------------------------------

@bp.post("/tax-returns/<return_id>/dependents")
def create_dependent(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    body = get_body()

    full_name = require_str(body, "full_name")
    age_years = require_int(body, "age_years", min_value=0)
    is_student = require_bool(body, "is_student", required=False, default=False)

    dep = {
        "return_id": return_id,
        "full_name": full_name,
        "age_years": age_years,
        "is_student": is_student,
        "qualifies_ctc": age_years < 17,
    }
    init_common(dep)
    db.dependents[dep["id"]] = dep
    _invalidate_if_ready(ret)
    return success(public(dep), status=201)


@bp.get("/tax-returns/<return_id>/dependents")
def list_dependents(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    items = [d for d in db.dependents.values() if d["return_id"] == return_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


# --- CreditClaim -----------------------------------------------------------

@bp.post("/tax-returns/<return_id>/credit-claims")
def create_credit_claim(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    body = get_body()

    credit_type = require_enum(body, "credit_type", CREDIT_TYPES)
    claimed = require_int(body, "claimed_amount_cents", required=False, default=0, min_value=0)

    for c in db.credit_claims.values():
        if c["return_id"] == return_id and c["credit_type"] == credit_type:
            raise err(errors.ERR_DUPLICATE_CHILD,
                      "CreditClaim of this type already exists on the return")

    claim = {
        "return_id": return_id,
        "credit_type": credit_type,
        "claimed_amount_cents": claimed,
        "allowed_amount_cents": 0,
        "refundable_cents": 0,
    }
    init_common(claim)
    db.credit_claims[claim["id"]] = claim
    _invalidate_if_ready(ret)
    return success(public(claim), status=201)


@bp.get("/tax-returns/<return_id>/credit-claims")
def list_credit_claims(return_id):
    user_id, role = get_auth()
    require_roles(role, EDITORS)
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    items = [c for c in db.credit_claims.values() if c["return_id"] == return_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)
