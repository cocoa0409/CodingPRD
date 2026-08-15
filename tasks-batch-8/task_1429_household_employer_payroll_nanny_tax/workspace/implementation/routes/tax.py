"""Tax liability accounts and tax deposit endpoints (PRD 3.9)."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_DEPOSIT_BELOW_REQUIRED,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.employers import get_employer_or_404
from services import tax as tax_svc
from services.serializers import serialize_tax_account, serialize_deposit
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_date,
    require_int,
    sort_by_created_at,
)

bp = Blueprint("tax", __name__)


@bp.route("/household-payroll/employers/<employer_id>/tax-accounts", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_tax_accounts(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)
    limit, offset = parse_pagination()
    items = [a for a in db.tax_accounts.values() if a["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["tax_year"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_tax_account(a) for a in page], limit, offset, total)


@bp.route("/household-payroll/employers/<employer_id>/deposits", methods=["POST"])
@require_roles("PayrollAdmin")
def create_deposit(employer_id: str, _user_id: str, _role: str):
    employer = get_employer_or_404(employer_id)
    body = get_json_body()
    tax_year = require_int(body, "tax_year")
    quarter = require_int(body, "quarter")
    if quarter not in (1, 2, 3, 4):
        raise_err(ERR_INVALID_REQUEST, "quarter must be 1, 2, 3, or 4")
    amount_cents = require_int(body, "amount_cents", 0)
    remitted_on = require_date(body, "remitted_on")

    if remitted_on > db.clock_today():
        raise_err(ERR_INVALID_REQUEST, "remitted_on must not be after the logical-clock current date")

    required = tax_svc.required_amount_for_quarter(employer, tax_year, quarter)
    if amount_cents < required:
        raise_err(ERR_DEPOSIT_BELOW_REQUIRED, "amount_cents is below the safe-harbor requirement")

    due_date = tax_svc.quarter_due_date(tax_year, quarter)
    late_days = max(
        0,
        (datetime.strptime(remitted_on, "%Y-%m-%d") - datetime.strptime(due_date, "%Y-%m-%d")).days,
    )
    penalty = tax_svc.late_penalty(late_days, required)

    deposit = {
        "employer_id": employer_id,
        "tax_year": tax_year,
        "quarter": quarter,
        "amount_cents": amount_cents,
        "remitted_on": remitted_on,
        "required_amount_cents": required,
        "due_date": due_date,
        "late_days": late_days,
        "penalty_cents": penalty,
    }
    db.stamp_new_immutable(deposit)

    # The full penalty of every late deposit lands on the year's FICA_ER account.
    if penalty > 0:
        fica_er = tax_svc.get_or_create_account(employer_id, tax_year, "FICA_ER")
        fica_er["penalty_cents"] += penalty
        db.touch(fica_er)

    deposit["unapplied_cents"] = tax_svc.allocate_deposit(employer_id, tax_year, amount_cents)
    db.deposits[deposit["id"]] = deposit
    return success_object(serialize_deposit(deposit), 201)


@bp.route("/household-payroll/employers/<employer_id>/deposits", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_deposits(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)
    limit, offset = parse_pagination()
    items = [d for d in db.deposits.values() if d["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["tax_year"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_deposit(d) for d in page], limit, offset, total)
