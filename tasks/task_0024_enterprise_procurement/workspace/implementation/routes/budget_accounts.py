"""BudgetAccount endpoints (PRD §3.1)."""

from __future__ import annotations

import re

from flask import Blueprint, jsonify, request

from db import db, stamp_create, serialize, serialize_list, order_by_created_then_seq
from errors import err
from middleware import enforce_role, require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from services.lookups import find_budget_account
from validate import get_json_body, require_fields, require_int, require_string

bp = Blueprint("budget_accounts", __name__)

# PRD §3.1: code format BA-NNNN-UPPER-UPPER
_BA_CODE_RE = re.compile(r"^BA-[0-9]{4}-[A-Z]+-[A-Z]+$")


@bp.post("/budget-accounts")
@require_roles("FinanceApprover")
def create_budget_account():
    body = get_json_body()
    require_fields(body, ["code", "department", "fiscal_year", "total_amount_cents"])
    code = require_string(body["code"], "code")
    if not _BA_CODE_RE.match(code):
        raise err("ERR_VALIDATION", "code must match BA-NNNN-UPPER-UPPER pattern.")
    if any(b.get("code") == code for b in db.budget_accounts.values()):
        raise err("ERR_VALIDATION", "code already exists.")
    department = require_string(body["department"], "department")
    fiscal_year = require_int(body["fiscal_year"], "fiscal_year")
    total = require_int(body["total_amount_cents"], "total_amount_cents", min_value=0)

    row = {
        "code": code,
        "department": department,
        "fiscal_year": fiscal_year,
        "total_amount_cents": total,
        "committed_amount_cents": 0,
        "spent_amount_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(row, common=True)
    db.budget_accounts[row["id"]] = row
    return jsonify(success_object(serialize(row))), 201


@bp.get("/budget-accounts/<rid>")
@require_roles("FinanceApprover", "Buyer", "Requester", "DepartmentHead", "GeneralManager")
def get_budget_account(rid: str):
    row = find_budget_account(rid)
    enforce_role()
    return jsonify(success_object(serialize(row))), 200


@bp.get("/budget-accounts")
@require_roles("FinanceApprover", "Buyer", "Requester", "DepartmentHead", "GeneralManager")
def list_budget_accounts():
    limit, offset = parse_limit_offset()
    department = request.args.get("department")
    fiscal_year = request.args.get("fiscal_year")
    status = request.args.get("status")
    rows = list(db.budget_accounts.values())
    if department is not None:
        rows = [r for r in rows if r.get("department") == department]
    if fiscal_year is not None:
        try:
            fy = int(fiscal_year)
        except ValueError:
            raise err("ERR_VALIDATION", "fiscal_year must be an integer.")
        rows = [r for r in rows if r.get("fiscal_year") == fy]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows = order_by_created_then_seq(rows)
    page, total = paginate(rows, limit, offset)
    return jsonify(success_array(serialize_list(page), limit, offset, total)), 200
