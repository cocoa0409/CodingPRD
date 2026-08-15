"""Registry endpoints: owners and verifiers."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok
from validation import parse_body, require_path_entity

bp = Blueprint("registry", __name__)


@bp.post("/v1/owners")
def create_owner():
    get_context()
    require_roles(["ComplianceOfficer"])
    body = parse_body({
        "name": ("string", True, None),
        "contact_email": ("string", True, None),
    }, allow_empty=False)
    owner = db.new_common({
        "id": db.new_id(),
        "name": body["name"],
        "contact_email": body["contact_email"],
        "standing": "NORMAL",
        "outstanding_fines_cents": 0,
    })
    store.owners[owner["id"]] = owner
    return created(owner)


@bp.get("/v1/owners/<owner_id>")
def get_owner(owner_id):
    get_context()
    owner = require_path_entity(store.owners, owner_id)
    return ok(owner)


@bp.post("/v1/verifiers")
def create_verifier():
    get_context()
    require_roles(["ComplianceOfficer"])
    body = parse_body({
        "name": ("string", True, None),
        "license_number": ("string", True, None),
        "accredited": ("boolean", False, None),
    }, allow_empty=False)
    for v in store.verifiers.values():
        if v["license_number"] == body["license_number"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "license_number must be unique across verifiers")
    verifier = db.new_common({
        "id": db.new_id(),
        "name": body["name"],
        "license_number": body["license_number"],
        "accredited": body.get("accredited", True),
    })
    store.verifiers[verifier["id"]] = verifier
    return created(verifier)


@bp.get("/v1/verifiers/<verifier_id>")
def get_verifier(verifier_id):
    get_context()
    verifier = require_path_entity(store.verifiers, verifier_id)
    return ok(verifier)
