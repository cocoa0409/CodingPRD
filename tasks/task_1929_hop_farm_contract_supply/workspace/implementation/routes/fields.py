"""Field endpoints."""

from flask import Blueprint

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_FARM_MANAGER
from response import success_object
from util import get_body, check_unknown_fields, req_str, req_int
from services.core import base_record, public, get_field

bp = Blueprint("fields", __name__)


@bp.route("/api/fields", methods=["POST"])
def create_field():
    require_roles([ROLE_FARM_MANAGER])
    body = get_body()
    check_unknown_fields(body, {"name", "acreage"})
    name = req_str(body, "name")
    acreage = req_int(body, "acreage", min_v=1)

    rec = base_record()
    rec.update({"name": name, "acreage": acreage})
    store.fields[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/api/fields/<field_id>", methods=["GET"])
def get_field_endpoint(field_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_field(field_id)))
