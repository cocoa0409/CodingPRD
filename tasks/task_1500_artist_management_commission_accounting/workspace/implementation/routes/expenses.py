"""Expense endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ARTIST_ARCHIVED,
    ERR_EXPENSE_NOT_REJECTED,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.calculations import expense_required_approvers, create_approval_requests
from services.core import new_record, touch
from validate import (
    get_body, opt_int, opt_str, req_date, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("expenses", __name__)

CATEGORIES = {"TRAVEL", "PRODUCTION", "MARKETING", "LEGAL", "OTHER"}


@bp.post("/expenses")
def create_expense():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["Agent", "BusinessManager", "Publicist"],
                                  body_artist_id=artist_id)
    category = req_enum(body, "category", CATEGORIES)
    amount = req_int(body, "amount_cents", positive=True)
    incurred_date = req_date(body, "incurred_date")
    description = req_str(body, "description")
    engagement_id = opt_str(body, "engagement_id")

    artist = require_ref("artists", artist_id, "artist_id")
    if engagement_id is not None:
        require_ref("engagements", engagement_id, "engagement_id")
    if artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")

    rec = new_record("expenses", {
        "artist_id": artist_id,
        "engagement_id": engagement_id,
        "category": category,
        "amount_cents": amount,
        "incurred_date": incurred_date,
        "description": description,
        "status": "PENDING_APPROVAL",
        "submitted_by_user_id": caller.user_id,
        "rejection_note": None,
        "reimbursed_statement_id": None,
    })
    approvers = expense_required_approvers(amount)
    create_approval_requests(artist_id, "EXPENSE", rec["id"], approvers, caller.user_id)
    return success_object(public(rec), status=201)


@bp.get("/expenses/<rid>")
def get_expense(rid):
    return get_one("expenses", rid)


@bp.get("/expenses")
def list_expenses():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "engagement_id": request.args.get("engagement_id"),
        "reimbursed_statement_id": request.args.get("reimbursed_statement_id"),
        "status": request.args.get("status"),
    }
    return list_response("expenses", filters)


@bp.post("/expenses/<rid>/resubmit")
def resubmit_expense(rid):
    caller = scoped_mutation_auth(["Agent", "BusinessManager", "Publicist"],
                                  "expenses", rid)
    body = get_body()
    exp = require_path_resource("expenses", rid)
    if exp["status"] != "REJECTED":
        raise_error(ERR_EXPENSE_NOT_REJECTED, "expense is not in REJECTED")

    new_amount = opt_int(body, "amount_cents", positive=True)
    new_description = opt_str(body, "description")
    if new_amount is not None:
        exp["amount_cents"] = new_amount
    if new_description is not None:
        exp["description"] = new_description
    exp["status"] = "PENDING_APPROVAL"
    exp["rejection_note"] = None
    exp["submitted_by_user_id"] = caller.user_id
    touch(exp)
    approvers = expense_required_approvers(exp["amount_cents"])
    create_approval_requests(exp["artist_id"], "EXPENSE", exp["id"], approvers, caller.user_id)
    return success_object(public(exp))
