"""Loan endpoints: get loan, list installments."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from errors import err_forbidden_for_role
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_investor_role_resolves,
    get_loan,
    paginate,
    parse_pagination,
    sort_for_list,
)
from services.serializers import serialize_installment, serialize_loan

bp = Blueprint("loans", __name__)


def _check_loan_read_scope(loan: dict):
    if g.role == "Borrower":
        if g.user_id != loan["borrower_id"]:
            raise err_forbidden_for_role("Borrower may only read their own loans.")
    if g.role == "Investor":
        # Investor may read a loan only if they hold a (CONVERTED or LOST)
        # investment in its source listing.
        inv_match = any(
            inv["investor_id"] == g.user_id and inv["status"] in ("CONVERTED", "LOST")
            for inv in store.investments_for_listing(loan["listing_id"])
        )
        if not inv_match:
            raise err_forbidden_for_role("Investor has no investment in this loan.")


@bp.get("/platforms/<platform_id>/loans/<loan_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def get_loan_route(platform_id, loan_id):
    loan = get_loan(platform_id, loan_id)
    _check_loan_read_scope(loan)
    return success(serialize_loan(loan))


@bp.get("/platforms/<platform_id>/loans/<loan_id>/installments")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def list_installments(platform_id, loan_id):
    loan = get_loan(platform_id, loan_id)
    _check_loan_read_scope(loan)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")

    items = store.installments_for_loan(loan_id)
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    # Installments natural sort: sequence_number, then created_at/id.
    items = sorted(items, key=lambda x: (x["sequence_number"], x.get("created_at", ""), x["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize_installment(x) for x in page], limit, offset, total)
