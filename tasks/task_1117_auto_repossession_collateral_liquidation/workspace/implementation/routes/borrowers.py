from flask import Blueprint

from db import store, base_fields, get_or_404, sorted_all
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import borrower_out, loan_out, complaint_out
from util import validate_body

bp = Blueprint("borrowers", __name__)


@bp.post("/borrowers")
def create_borrower():
    require_roles("RecoveryManager")
    body = validate_body({
        "full_name": ("str", True, None),
        "state_code": ("str", True, None),
        "email": ("str", True, None),
    })
    borrower = base_fields()
    borrower.update({
        "full_name": body["full_name"],
        "state_code": body["state_code"],
        "email": body["email"],
        "_seq": store.next_seq(),
    })
    store.borrowers[borrower["id"]] = borrower
    return object_response(borrower_out(borrower), 201)


@bp.get("/borrowers/<bid>")
def get_borrower(bid):
    require_roles(*ALL_ROLES)
    borrower = get_or_404(store.borrowers, bid, "Borrower")
    return object_response(borrower_out(borrower))


@bp.get("/borrowers/<bid>/loan-accounts")
def list_borrower_loans(bid):
    require_roles(*ALL_ROLES)
    get_or_404(store.borrowers, bid, "Borrower")
    rows = [l for l in sorted_all(store.loan_accounts) if l["borrower_id"] == bid]
    return list_response(rows, loan_out)


@bp.get("/borrowers/<bid>/complaints")
def list_borrower_complaints(bid):
    require_roles(*ALL_ROLES)
    get_or_404(store.borrowers, bid, "Borrower")
    rows = [c for c in sorted_all(store.complaints) if c["borrower_id"] == bid]
    return list_response(rows, complaint_out)
