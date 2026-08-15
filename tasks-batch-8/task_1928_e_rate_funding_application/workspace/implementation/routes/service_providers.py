"""ServiceProvider endpoints (PRD 3.1). spin is unique across the program."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record
from db import db
from validate import get_body, check_allowed, req_str

bp = Blueprint("service_providers", __name__, url_prefix="/erate")


@bp.post("/service-providers")
def create_provider():
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"name", "spin"})
    name = req_str(body, "name")
    spin = req_str(body, "spin")
    for existing in db["service_providers"].values():
        if existing["spin"] == spin:
            raise_error(ERR_INVALID_REQUEST, f"spin already registered: {spin}")
    rec = new_record("service_providers", {
        "name": name,
        "spin": spin,
    })
    return success_object(public(rec), 201)


@bp.get("/service-providers")
def list_providers():
    return list_collection("service_providers")


@bp.get("/service-providers/<rid>")
def get_provider(rid):
    return get_one("service_providers", rid)
