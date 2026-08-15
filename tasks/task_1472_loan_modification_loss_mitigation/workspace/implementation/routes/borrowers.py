from flask import Blueprint

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import ERR_BORROWER_NOT_FOUND
from services import borrower_out
from util import body_json, get_or_404, new_record, opt_str, req_str, success_object

bp = Blueprint("borrowers", __name__)


@bp.route("/borrowers", methods=["POST"])
def create_borrower():
    _, role = authenticate()
    authorize(role, ["ServicingAdmin"])
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    mailing_address = opt_str(body, "mailing_address")

    rec = new_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "mailing_address": mailing_address,
        "status": "ACTIVE",
    })
    store.borrowers[rec["id"]] = rec
    return success_object(borrower_out(rec), 201)


@bp.route("/borrowers/<rid>", methods=["GET"])
def get_borrower(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.borrowers, rid, ERR_BORROWER_NOT_FOUND, "Borrower")
    return success_object(borrower_out(rec))
