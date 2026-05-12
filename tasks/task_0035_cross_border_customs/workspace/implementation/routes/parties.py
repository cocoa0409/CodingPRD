"""Importer + Declarant endpoints."""

from flask import Blueprint

from db import DB, LOCK
from errors import APIError, ERR_INVALID_REQUEST, not_found
from middleware import require_roles
from response import success_object
from services.common import get_body, stamp_create, touch
from services.serializers import serialize_importer, serialize_declarant


bp = Blueprint("parties", __name__)


@bp.route("/importers", methods=["POST"])
@require_roles("CustomsOfficer")
def create_importer():
    body = get_body()
    name = body.get("name")
    license_number = body.get("license_number")
    if not isinstance(name, str) or name.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "name required", 400)
    if not isinstance(license_number, str) or license_number.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "license_number required", 400)

    with LOCK:
        for im in DB.importers.values():
            if im["license_number"] == license_number:
                raise APIError(ERR_INVALID_REQUEST, "license_number must be unique", 400)
        im = {
            "name": name,
            "license_number": license_number,
            "status": "ACTIVE",
        }
        stamp_create(im)
        DB.importers[im["id"]] = im
        return success_object(serialize_importer(im), status=201)


@bp.route("/importers/<importer_id>/suspend", methods=["POST"])
@require_roles("CustomsOfficer")
def suspend_importer(importer_id):
    with LOCK:
        im = DB.importers.get(importer_id)
        if im is None:
            raise not_found("Importer not found")
        im["status"] = "SUSPENDED"
        touch(im)
        return success_object(serialize_importer(im), status=200)


@bp.route("/declarants", methods=["POST"])
@require_roles("CustomsOfficer")
def create_declarant():
    body = get_body()
    name = body.get("name")
    agent_code = body.get("agent_code")
    if not isinstance(name, str) or name.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "name required", 400)
    if not isinstance(agent_code, str) or agent_code.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "agent_code required", 400)

    with LOCK:
        for dc in DB.declarants.values():
            if dc["agent_code"] == agent_code:
                raise APIError(ERR_INVALID_REQUEST, "agent_code must be unique", 400)
        dc = {
            "name": name,
            "agent_code": agent_code,
            "status": "ACTIVE",
        }
        stamp_create(dc)
        DB.declarants[dc["id"]] = dc
        return success_object(serialize_declarant(dc), status=201)
