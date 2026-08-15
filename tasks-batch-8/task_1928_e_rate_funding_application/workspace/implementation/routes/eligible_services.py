"""EligibleService inventory endpoints (PRD 3.1)."""
from flask import Blueprint, request

from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record
from validate import (
    get_body, check_allowed, req_str, req_enum, require_ref,
)

bp = Blueprint("eligible_services", __name__, url_prefix="/erate")

CATEGORIES = ("CATEGORY_ONE", "CATEGORY_TWO")
SERVICE_TYPES = (
    "INTERNET_ACCESS", "DATA_TRANSMISSION", "VOICE_SERVICE",
    "INTERNAL_CONNECTIONS", "BASIC_MAINTENANCE",
)


@bp.post("/eligible-services")
def create_service():
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"funding_cycle_id", "service_description", "category",
                         "service_type"})
    funding_cycle_id = req_str(body, "funding_cycle_id")
    service_description = req_str(body, "service_description")
    category = req_enum(body, "category", CATEGORIES)
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    require_ref("funding_cycles", funding_cycle_id, "funding_cycle_id")
    rec = new_record("eligible_services", {
        "funding_cycle_id": funding_cycle_id,
        "service_description": service_description,
        "category": category,
        "service_type": service_type,
    })
    return success_object(public(rec), 201)


@bp.get("/eligible-services")
def list_services():
    return list_collection("eligible_services", {
        "funding_cycle_id": request.args.get("funding_cycle_id"),
        "category": request.args.get("category"),
    })


@bp.get("/eligible-services/<rid>")
def get_service(rid):
    return get_one("eligible_services", rid)
