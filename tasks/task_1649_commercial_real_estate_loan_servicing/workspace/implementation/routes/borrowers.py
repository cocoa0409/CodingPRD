from flask import Blueprint

import db
import errors
import middleware as mw
from response import success
from services.common import stamp_new
from services.serialize import borrower as ser_borrower
from services.validate import body_json, require_fields, req_str

bp = Blueprint("borrowers", __name__)


@bp.post("/borrowers")
def create_borrower():
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    data = body_json()
    require_fields(data, ["legal_name", "tax_id", "contact_email"])
    legal_name = req_str(data, "legal_name")
    tax_id = req_str(data, "tax_id")
    contact_email = req_str(data, "contact_email")
    for b in db.borrowers.values():
        if b["tax_id"] == tax_id:
            raise errors.invalid_request("tax_id must be unique across borrowers")
    b = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "tax_id": tax_id,
        "contact_email": contact_email,
    }
    stamp_new(b)
    db.borrowers[b["id"]] = b
    return success(ser_borrower(b), status=201)


@bp.get("/borrowers/<bid>")
def get_borrower(bid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    b = db.borrowers.get(bid)
    if b is None:
        raise errors.not_found("Borrower not found")
    if actor["role"] == "Borrower" and actor["user_id"] != bid:
        raise errors.not_found("Borrower not found")
    return success(ser_borrower(b))
