"""Customer endpoints (PRD §3.7)."""
from flask import Blueprint

import db
from errors import err
from helpers import get_json_body, require_fields, stamp_create
from middleware import require_auth
from response import object_response
from serializers import customer_view

bp = Blueprint("customers", __name__)


def get_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    return c


@bp.route("/compliance/customers", methods=["POST"])
@require_auth(["Budtender", "ComplianceManager"])
def create_customer():
    body = get_json_body()
    require_fields(body, ["birthdate"])
    birthdate = body["birthdate"]

    is_medical = body.get("is_medical", False)
    if is_medical is None:
        is_medical = False
    if not isinstance(is_medical, bool):
        raise err("ERR_INVALID_REQUEST", "is_medical must be a boolean.")

    medical_card_number = body.get("medical_card_number")  # defaults to null

    rec = {
        "id": db.new_id(),
        "medical_card_number": medical_card_number,
        "is_medical": is_medical,
        "birthdate": birthdate,
    }
    stamp_create(rec)
    db.customers[rec["id"]] = rec
    return object_response(customer_view(rec), 201)


@bp.route("/compliance/customers/<customer_id>", methods=["GET"])
@require_auth(["Budtender", "ComplianceManager", "StateRegulator"], open_read=True)
def get_customer(customer_id):
    return object_response(customer_view(get_customer_or_404(customer_id)))
