"""Property owner registration (PRD 3.1)."""
from flask import Blueprint

from middleware import get_caller, check_role_allowed
from response import success_object
from routes.helpers import public
from services.core import new_record
from validate import get_body, req_str

bp = Blueprint("owners", __name__, url_prefix="/preservation")


@bp.post("/owners")
def create_owner():
    caller = get_caller()
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    mailing_address = req_str(body, "mailing_address")
    check_role_allowed(caller, ["PreservationStaff"])
    rec = new_record("owners", {
        "full_name": full_name,
        "email": email,
        "mailing_address": mailing_address,
    })
    return success_object(public(rec), status=201)
