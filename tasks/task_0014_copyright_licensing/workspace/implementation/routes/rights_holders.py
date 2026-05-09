"""RightsHolder routes."""
from flask import Blueprint

from common import get_json_body, stamp_new
from db import db
from errors import api_error
from middleware import require_roles
from response import success

bp = Blueprint("rights_holders", __name__)


VALID_HOLDER_TYPES = {"INDIVIDUAL", "ENTITY"}


@bp.route("/rights-holders", methods=["POST"])
def create_rights_holder():
    require_roles(["PlatformAdmin", "RightsHolder"])
    body = get_json_body()

    legal_name = body.get("legal_name")
    holder_type = body.get("holder_type")
    contact_email = body.get("contact_email")
    jurisdiction = body.get("jurisdiction")

    if not legal_name or not isinstance(legal_name, str):
        raise api_error("ERR_VALIDATION", "legal_name required")
    if holder_type not in VALID_HOLDER_TYPES:
        raise api_error("ERR_VALIDATION", "holder_type must be INDIVIDUAL or ENTITY")
    if not contact_email or not isinstance(contact_email, str):
        raise api_error("ERR_VALIDATION", "contact_email required")
    if not jurisdiction or not isinstance(jurisdiction, str) or len(jurisdiction) != 2:
        raise api_error("ERR_VALIDATION", "jurisdiction must be ISO 3166-1 alpha-2 code")

    holder = {
        "legal_name": legal_name,
        "holder_type": holder_type,
        "contact_email": contact_email,
        "jurisdiction": jurisdiction.upper(),
    }
    stamp_new(holder)
    db.rights_holders[holder["id"]] = holder
    return success(holder, status=201)


@bp.route("/rights-holders/<holder_id>", methods=["GET"])
def get_rights_holder(holder_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    holder = db.rights_holders.get(holder_id)
    if not holder:
        raise api_error("ERR_NOT_FOUND", "rights holder not found")
    return success(holder)
