"""Operator and Station routes."""

from flask import Blueprint, request

import db
from errors import raise_error
from middleware import require_roles
from response import paginated, success
from validators import (
    get_pagination,
    parse_json_body,
    paginate_list,
    require_enum,
    require_int,
    require_number,
    require_str,
)


bp = Blueprint("operators", __name__)


VALID_OPERATOR_KINDS = {"PLATFORM", "STATION_OWNER", "ROAMING_PARTNER"}


@bp.post("/operators")
@require_roles({"PlatformOperator"})
def create_operator():
    body = parse_json_body()
    name = require_str(body, "name", 1, 120)
    role_kind = require_enum(body, "role_kind", VALID_OPERATOR_KINDS)
    tax_id = require_str(body, "tax_id", 1, 40)

    # Uniqueness on name globally.
    for existing in db.operators.values():
        if existing["name"] == name:
            raise_error("ERR_VALIDATION", "operator name already exists")

    record = {
        "name": name,
        "role_kind": role_kind,
        "tax_id": tax_id,
    }
    db.with_common_fields(record)
    db.operators[record["id"]] = record
    return success(db.public(record), status=201)


@bp.get("/operators")
@require_roles({"PlatformOperator", "StationOwner", "CustomerService"})
def list_operators():
    role_kind = request.args.get("role_kind")
    limit, offset = get_pagination()
    items = sorted(db.operators.values(), key=lambda r: r["_seq"])
    if role_kind:
        items = [o for o in items if o["role_kind"] == role_kind]
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)


@bp.get("/operators/<operator_id>")
@require_roles({"PlatformOperator", "StationOwner", "CustomerService"})
def get_operator(operator_id: str):
    record = db.operators.get(operator_id)
    if record is None:
        raise_error("ERR_NOT_FOUND", "operator not found")
    return success(db.public(record))
