"""Owner routes."""
from flask import request

from db import db, stamp_create
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response
from services.util import require_str
from services.computed import serialize_owner


def register(app):
    @app.route("/owners", methods=["POST"])
    def create_owner():
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        data = get_json()
        resort_id = require_str(data, "resort_id")
        full_name = require_str(data, "full_name")
        email = require_str(data, "email")
        # resort_id must reference an existing resort.
        get_or_404(db.resorts, resort_id)
        owner = {
            "resort_id": resort_id,
            "full_name": full_name,
            "email": email,
        }
        stamp_create(owner)
        db.owners[owner["id"]] = owner
        return success(serialize_owner(owner), status=201)

    @app.route("/owners/<owner_id>", methods=["GET"])
    def get_owner(owner_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        owner = get_or_404(db.owners, owner_id)
        return success(serialize_owner(owner))

    @app.route("/owners", methods=["GET"])
    def list_owners():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.owners.values())
        resort_id = request.args.get("resort_id")
        if resort_id is not None:
            items = [o for o in items if o["resort_id"] == resort_id]
        return list_response(items, serialize_owner)
