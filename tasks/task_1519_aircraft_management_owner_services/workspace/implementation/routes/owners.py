"""Owner endpoints."""
from flask import Blueprint, request

from db import db
from errors import validation
from middleware import require_roles, require_read
from response import success_object
from serializers import owner_view
from services.core import make_record, require_exists

bp = Blueprint("owners", __name__)


@bp.route("/owners", methods=["POST"])
def create_owner():
    require_roles("AccountExecutive")
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    contact_email = body.get("contact_email")
    if not isinstance(legal_name, str) or not legal_name:
        raise validation("legal_name is required")
    if not isinstance(contact_email, str) or not contact_email:
        raise validation("contact_email is required")
    rec = make_record({
        "legal_name": legal_name,
        "contact_email": contact_email,
    })
    db.owners[rec["id"]] = rec
    return success_object(owner_view(rec), 201)


@bp.route("/owners/<owner_id>", methods=["GET"])
def get_owner(owner_id):
    require_read()
    rec = require_exists(db.owners, owner_id)
    return success_object(owner_view(rec))
