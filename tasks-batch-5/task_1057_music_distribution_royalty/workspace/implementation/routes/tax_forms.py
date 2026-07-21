"""Year-end 1099 forms — PRD §3.9."""

from flask import Blueprint, request

from db import db, common_fields, now, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import core
import validation as v

bp = Blueprint("tax_forms", __name__)


def total_paid_cents(collaborator_id, tax_year):
    """PRD §3.9 — PAID payouts whose paid_at falls inside the calendar year (UTC)."""
    total = 0
    for payout in core.payouts_of_collaborator(collaborator_id):
        if payout["status"] != "PAID" or payout["paid_at"] is None:
            continue
        if payout["paid_at"].year == tax_year:
            total += payout["net_cents"]
    return total


def owned_form(user_id, role, form_id):
    form = db.tax_forms.get(form_id)
    if role == "Collaborator" and form is not None:
        require_ownership(user_id == form["collaborator_id"])
    return core.find_tax_form(form_id)


@bp.post("/api/tax-forms")
def create_form():
    auth("FinanceOps")
    data = v.body()
    collaborator_id = v.req_id(data, "collaborator_id")
    tax_year = v.req_int(data, "tax_year", minimum=2020, maximum=2100)

    core.find_collaborator(collaborator_id)

    if any(
        f["collaborator_id"] == collaborator_id
        and f["tax_year"] == tax_year
        and f["status"] in ("DRAFT", "ISSUED")
        for f in db.tax_forms.values()
    ):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "A live form already exists for that year.")

    row = common_fields()
    row.update({
        "collaborator_id": collaborator_id,
        "tax_year": tax_year,
        "total_paid_cents": total_paid_cents(collaborator_id, tax_year),
        "status": "DRAFT",
        "issued_at": None,
    })
    db.tax_forms[row["id"]] = row
    return created(row)


@bp.get("/api/tax-forms/<form_id>")
def read_form(form_id):
    user_id, role = auth("FinanceOps", "Collaborator", "PlatformAdmin")
    return ok(owned_form(user_id, role, form_id))


@bp.get("/api/tax-forms")
def list_forms():
    user_id, role = auth("FinanceOps", "Collaborator", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.tax_forms.values())
    if role == "Collaborator":
        rows = [f for f in rows if f["collaborator_id"] == user_id]
    collaborator_id = request.args.get("collaborator_id")
    if collaborator_id is not None:
        rows = [f for f in rows if f["collaborator_id"] == collaborator_id]
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        try:
            year = int(str(tax_year).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "tax_year must be an integer.")
        rows = [f for f in rows if f["tax_year"] == year]
    status = request.args.get("status")
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/tax-forms/<form_id>/issue")
def issue_form(form_id):
    auth("FinanceOps")
    form = core.find_tax_form(form_id)
    if form["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    recomputed = total_paid_cents(form["collaborator_id"], form["tax_year"])
    if recomputed < core.TAX_1099_THRESHOLD_CENTS:
        raise ApiError("ERR_1099_THRESHOLD_NOT_MET")

    form["total_paid_cents"] = recomputed
    form["status"] = "ISSUED"
    form["issued_at"] = now()
    touch(form)
    return ok(form)


@bp.post("/api/tax-forms/<form_id>/void")
def void_form(form_id):
    auth("FinanceOps")
    data = v.body()
    v.req_string(data, "reason_code")

    form = core.find_tax_form(form_id)
    if form["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    form["status"] = "VOIDED"
    touch(form)
    return ok(form)
