"""Kiln endpoints."""

from flask import Blueprint

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_FARM_MANAGER
from response import success_object
from util import get_body, check_unknown_fields, req_str
from services.core import base_record, public, get_kiln

bp = Blueprint("kilns", __name__)


@bp.route("/api/kilns", methods=["POST"])
def create_kiln():
    require_roles([ROLE_FARM_MANAGER])
    body = get_body()
    check_unknown_fields(body, {"name"})
    name = req_str(body, "name")

    rec = base_record()
    rec.update({"name": name})
    store.kilns[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/api/kilns/<kiln_id>", methods=["GET"])
def get_kiln_endpoint(kiln_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_kiln(kiln_id)))
