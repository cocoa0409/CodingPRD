"""Bond endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import err
from helpers import (
    get_body, require_int, require_enum, stamp_create, bump_version,
    lookup, list_response,
)
from middleware import require_roles
from response import object_response
from serializers import bond_view

bp = Blueprint("bonds", __name__)


@bp.post("/bonds")
@require_roles("AccountAdmin")
def create_bond():
    body = get_body()
    importer_id = body.get("importer_id")
    if importer_id is None or not isinstance(importer_id, str) or importer_id == "":
        raise err("ERR_VALIDATION", "importer_id is required.")
    bond_type = require_enum(body, "bond_type", {"CONTINUOUS", "SINGLE_ENTRY"})
    limit_cents = require_int(body, "limit_cents")
    if limit_cents < 0:
        raise err("ERR_VALIDATION", "limit_cents must be >= 0.")

    # FK existence (404) checked before creation.
    lookup(db.importers, importer_id)

    rec = {
        "importer_id": importer_id,
        "bond_type": bond_type,
        "limit_cents": limit_cents,
        "outstanding_liability_cents": 0,
        "status": "PENDING",
    }
    stamp_create(rec)
    db.bonds[rec["id"]] = rec
    return object_response(bond_view(rec), status=201)


@bp.get("/bonds/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_bond(id):
    return object_response(bond_view(lookup(db.bonds, id)))


@bp.get("/bonds")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_bonds():
    return list_response(
        db.bonds.values(), bond_view, filters=[("importer_id", "importer_id")]
    )


@bp.post("/bonds/<id>/activate")
@require_roles("AccountAdmin")
def activate_bond(id):
    bond = lookup(db.bonds, id)
    # PENDING -> ACTIVE; permitted only while PENDING and limit_cents >= 0.
    if bond["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Bond is not PENDING.")
    bond["status"] = "ACTIVE"
    if bond["bond_type"] == "CONTINUOUS":
        importer = db.importers.get(bond["importer_id"])
        if importer is not None:
            importer["continuous_bond_id"] = bond["id"]
    bump_version(bond)
    return object_response(bond_view(bond))


@bp.post("/bonds/<id>/terminate")
@require_roles("AccountAdmin")
def terminate_bond(id):
    bond = lookup(db.bonds, id)
    # ACTIVE -> TERMINATED; only while ACTIVE and outstanding_liability == 0.
    if bond["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Bond is not ACTIVE.")
    if bond["outstanding_liability_cents"] != 0:
        raise err("ERR_INVALID_STATE", "Bond has non-zero outstanding liability.")
    bond["status"] = "TERMINATED"
    importer = db.importers.get(bond["importer_id"])
    if importer is not None and importer.get("continuous_bond_id") == bond["id"]:
        importer["continuous_bond_id"] = None
    bump_version(bond)
    return object_response(bond_view(bond))
