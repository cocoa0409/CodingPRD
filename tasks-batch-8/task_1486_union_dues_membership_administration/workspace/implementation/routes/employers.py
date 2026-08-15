"""Employer registration and read."""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles, ALL_ROLES
from response import ok

bp = Blueprint("employers", __name__, url_prefix="/api/employers")


@bp.route("", methods=["POST"])
@require_roles("OfficeClerk")
def create_employer(user_id, role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    name = utils.require_field(body, "name")
    if not isinstance(name, str):
        raise errors.invalid_request("name must be a string")
    ts = db.fmt_ts(db.now())
    employer = {
        "id": utils.new_id(),
        "name": name,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.employers[employer["id"]] = employer
    return ok(serializers.employer(employer), 201)


@bp.route("/<employer_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_employer(user_id, role, employer_id):
    employer = db.store.employers.get(employer_id)
    if employer is None:
        raise errors.employer_not_found()
    return ok(serializers.employer(employer), 200)
