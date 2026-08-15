"""Teacher registry endpoint (PRD 3.2)."""
from flask import Blueprint

from middleware import get_caller, require_roles
from response import success_object
from services.core import new_record
from services.serialize import serialize_teacher
from validate import get_body, reject_unknown_fields, req_str

bp = Blueprint("teachers", __name__)


@bp.post("/teachers")
def create_teacher():
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"full_name", "email"})
    rec = new_record("teachers", {
        "full_name": req_str(body, "full_name"),
        "email": req_str(body, "email"),
    })
    return success_object(serialize_teacher(rec), status=201)
