"""Customer onboarding — PRD §3.1."""
from flask import Blueprint

from db import db
from middleware import require_roles
from response import object_response
from models import stamp_new, public
from services.validate import get_body, require_fields
from services.resolve import get_customer
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("customers", __name__)


def serialize_customer(c):
    return public(c)


@bp.route("/customers", methods=["POST"])
@require_roles("Teller", "ComplianceOfficer")
def create_customer():
    body = get_body()
    require_fields(body, "legal_name", "date_of_birth", "tax_id_last4")

    country = body.get("country_of_residence", "US")
    if country is None:
        country = "US"
    if not isinstance(country, str) or len(country) == 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "country_of_residence must be a string")

    customer = {
        "legal_name": body["legal_name"],
        "date_of_birth": body["date_of_birth"],
        "tax_id_last4": body["tax_id_last4"],
        "country_of_residence": country,
        "cip_status": "UNVERIFIED",
    }
    stamp_new(customer)
    db.customers[customer["id"]] = customer
    return object_response(serialize_customer(customer), status=201)


@bp.route("/customers/<customer_id>", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def get_one(customer_id):
    c = get_customer(customer_id)
    return object_response(serialize_customer(c))


@bp.route("/customers/<customer_id>/applications", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def list_customer_applications(customer_id):
    get_customer(customer_id)
    rows = [a for a in db.applications.values() if a["customer_id"] == customer_id]
    return paged_list(rows)
