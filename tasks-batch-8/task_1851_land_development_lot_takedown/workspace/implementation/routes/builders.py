"""Builder endpoints (PRD 3.4): homebuilder registration."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_DUPLICATE_BUILDER_LICENSE
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record
from validate import get_body, req_str

bp = Blueprint("builders", __name__)


@bp.post("/builders")
def create_builder():
    authorized(["DeveloperOperator"])
    body = get_body()
    builder_name = req_str(body, "builder_name")
    license_number = req_str(body, "license_number")
    contact_email = req_str(body, "contact_email")
    # Priority 9: license number unique across builders
    for other in db["builders"].values():
        if other["license_number"] == license_number:
            raise_error(ERR_DUPLICATE_BUILDER_LICENSE, "license_number already registered")
    rec = new_record("builders", {
        "builder_name": builder_name,
        "license_number": license_number,
        "contact_email": contact_email,
    })
    return success_object(public(rec), status=201)


@bp.get("/builders")
def list_builders():
    return list_response("builders")


@bp.get("/builders/<rid>")
def get_builder(rid):
    return get_one("builders", rid)
