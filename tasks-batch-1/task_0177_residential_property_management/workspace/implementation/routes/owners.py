"""Owner routes (PRD §3.1)."""
from flask import Blueprint

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response
from services.common import (
    serialize, require_string, require_number, require_enum,
)

bp = Blueprint("owners", __name__)

DISTRIBUTION_METHODS = {"ACH", "CHECK"}


@bp.route("/owners", methods=["POST"])
def create_owner():
    require_role({"PropertyManager"})
    body = get_json_body()
    legal_name = require_string(body, "legal_name")
    email = require_string(body, "email")
    mgmt_fee = require_number(body, "management_fee_pct", minimum=0, maximum=0.5)
    distribution_method = require_enum(body, "distribution_method",
                                       DISTRIBUTION_METHODS, default="ACH")
    with db.LOCK:
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "legal_name": legal_name,
            "email": email,
            "distribution_method": distribution_method,
            "management_fee_pct": mgmt_fee,
        }
        db.owners[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/owners/<id>", methods=["GET"])
def get_owner(id):
    require_role({"PropertyManager", "Owner"})
    with db.LOCK:
        record = db.owners.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Owner not found")
        return object_response(serialize(record), 200)
