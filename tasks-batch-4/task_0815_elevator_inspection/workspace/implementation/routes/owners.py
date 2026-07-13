from flask import Blueprint

from auth import require
from common import get_body, lookup, require_string
from envelope import object_response
from services.logic import serialize_owner
from store import base_fields, db

bp = Blueprint("owners", __name__)


@bp.route("/owners", methods=["POST"])
@require("Registrar")
def create_owner():
    body = get_body()
    name = require_string(body, "name")
    contact_email = require_string(body, "contact_email")
    owner = base_fields()
    owner.update({"name": name, "contact_email": contact_email})
    db.owners[owner["id"]] = owner
    return object_response(serialize_owner(owner), 201)


@bp.route("/owners/<owner_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_owner(owner_id):
    owner = lookup(db.owners, owner_id, "ERR_OWNER_NOT_FOUND")
    return object_response(serialize_owner(owner), 200)
