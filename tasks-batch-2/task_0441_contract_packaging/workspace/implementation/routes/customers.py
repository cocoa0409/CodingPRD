"""Customer endpoints (PRD §3.1)."""
import re

from flask import Blueprint

import db
import errors
import response
import serializers
import util
from middleware import require_role, ALL_ROLES

bp = Blueprint("customers", __name__)

CODE_RE = re.compile(r"^[A-Z0-9]{2,6}$")


@bp.route("/copack/customers", methods=["POST"])
@require_role("Receiver")
def create_customer():
    body = util.get_json_body()
    util.require_fields(body, "name", "code")
    name = body["name"]
    code = body["code"]
    owns = body.get("owns_components", False)

    if not isinstance(name, str) or not isinstance(code, str):
        raise errors.invalid_request("name and code must be strings")
    if not isinstance(owns, bool):
        raise errors.invalid_request("owns_components must be a boolean")

    # priority 5: Customer.code unique (also enforce format constraint).
    # The code constraint (2-6 uppercase alphanumerics) is a well-formedness
    # check; a violation is a malformed value -> ERR_INVALID_REQUEST.
    if not CODE_RE.match(code):
        raise errors.invalid_request("code must be 2-6 uppercase alphanumeric characters")
    for c in db.customers.values():
        if c["code"] == code:
            raise errors.duplicate_code()

    rec = db.new_full_record({
        "name": name,
        "code": code,
        "owns_components": owns,
    })
    db.customers[rec["id"]] = rec
    return response.success(serializers.customer(rec), status=201)


@bp.route("/copack/customers/<cid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_customer(cid):
    rec = db.customers.get(cid)
    if rec is None:
        raise errors.not_found("Customer not found")
    return response.success(serializers.customer(rec), status=200)


@bp.route("/copack/customers", methods=["GET"])
@require_role(*ALL_ROLES)
def list_customers():
    limit, offset = util.parse_pagination()
    items = util.sort_by_creation(list(db.customers.values()))
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.customer(r) for r in window], status=200, pagination=meta)
