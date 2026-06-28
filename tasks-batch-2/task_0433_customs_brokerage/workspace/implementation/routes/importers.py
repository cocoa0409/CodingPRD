"""Importer endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import err
from helpers import (
    get_body, require_str, stamp_create, lookup, list_response,
)
from middleware import require_roles
from response import object_response
from serializers import importer_view

bp = Blueprint("importers", __name__)


@bp.post("/importers")
@require_roles("AccountAdmin")
def create_importer():
    body = get_body()
    name = require_str(body, "name")           # must be non-empty
    ior_number = require_str(body, "ior_number")  # must be non-empty, unique
    owner_user_id = require_str(body, "owner_user_id")

    # ior_number unique across importers -> ERR_DUPLICATE (409).
    for r in db.importers.values():
        if r["ior_number"] == ior_number:
            raise err("ERR_DUPLICATE", "ior_number already in use.")

    rec = {
        "name": name,
        "ior_number": ior_number,
        "owner_user_id": owner_user_id,
        "continuous_bond_id": None,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.importers[rec["id"]] = rec
    return object_response(importer_view(rec), status=201)


@bp.get("/importers/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_importer(id):
    rec = lookup(db.importers, id)
    return object_response(importer_view(rec))


@bp.get("/importers")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_importers():
    return list_response(
        db.importers.values(),
        importer_view,
        filters=[("owner_user_id", "owner_user_id"),
                 ("continuous_bond_id", "continuous_bond_id")],
    )
