"""Borrower endpoints."""
from flask import Blueprint

from db import STORE
from errors import raise_err
from middleware import ALL_ROLES, auth, require_role
from response import ok_list, ok_object
from serialize import list_response, ser_borrower
from services.core import TERMINAL_LOAN_STATES, loans_of_borrower, stamp_new, touch
from util import as_str, body, need, new_id

bp = Blueprint("borrowers", __name__)


@bp.route("/borrowers", methods=["POST"])
def create_borrower():
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    association_id = as_str(need(b, "association_id"), "association_id")
    legal_name = as_str(need(b, "legal_name"), "legal_name")
    tax_id = as_str(need(b, "tax_id"), "tax_id")
    county = as_str(need(b, "county"), "county")
    if STORE.associations.get(association_id) is None:
        raise_err("ERR_NOT_FOUND", "Association not found")
    borrower = stamp_new({
        "id": new_id(),
        "association_id": association_id,
        "legal_name": legal_name,
        "tax_id": tax_id,
        "county": county,
        "status": "ACTIVE",
        "patronage_eligible": True,
        "active_covenant_breach_count": 0,
    })
    STORE.borrowers[borrower["id"]] = borrower
    return ok_object(ser_borrower(borrower), code=201)


@bp.route("/borrowers/<bid>", methods=["GET"])
def get_borrower(bid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    borrower = STORE.borrowers.get(bid)
    if borrower is None:
        raise_err("ERR_NOT_FOUND", "Borrower not found")
    return ok_object(ser_borrower(borrower))


@bp.route("/borrowers", methods=["GET"])
def list_borrowers():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.borrowers.values(), ser_borrower,
        [("association_id", lambda e: e["association_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/borrowers/<bid>/terminate", methods=["POST"])
def terminate_borrower(bid):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    borrower = STORE.borrowers.get(bid)
    if borrower is None:
        raise_err("ERR_NOT_FOUND", "Borrower not found")
    if borrower["status"] == "TERMINATED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Borrower already terminated")
    for loan in loans_of_borrower(bid):
        if loan["status"] not in TERMINAL_LOAN_STATES:
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "All borrower loans must be terminal before termination")
    borrower["status"] = "TERMINATED"
    borrower["patronage_eligible"] = False
    touch(borrower)
    return ok_object(ser_borrower(borrower))
