"""Practice endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE_NPI,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("practices", __name__)


@bp.route("/vbc/practices", methods=["POST"])
@require_roles("PayerAdmin")
def create_practice(_user_id: str, _role: str):
    body = get_json_body()
    # Priority 3: body FK existence (when present and string-typed).
    raw_group = body.get("practice_group_id")
    if isinstance(raw_group, str) and raw_group != "" and raw_group not in db.practice_groups:
        raise_err(ERR_NOT_FOUND, "practice_group_id does not exist")
    # Priority 5: request shape.
    reject_unknown_fields(body, {"practice_group_id", "practice_name", "npi"})
    practice_group_id = require_string(body, "practice_group_id")
    practice_name = require_string(body, "practice_name")
    npi = require_string(body, "npi")
    if practice_group_id not in db.practice_groups:
        raise_err(ERR_NOT_FOUND, "practice_group_id does not exist")

    # Priority 11: npi globally unique.
    for practice in db.practices.values():
        if practice["npi"] == npi:
            raise_err(ERR_DUPLICATE_NPI, "npi already exists")

    practice = {
        "practice_group_id": practice_group_id,
        "practice_name": practice_name,
        "npi": npi,
        "practice_status": "ACTIVE",
    }
    db.stamp_new(practice)
    db.practices[practice["id"]] = practice
    return success_object(practice, 201)


@bp.route("/vbc/practices", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_practices(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.practices.values()))
    items = apply_filters(items, ["practice_group_id", "practice_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/practices/<practice_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_practice(practice_id: str, _user_id: str, _role: str):
    practice = db.practices.get(practice_id)
    if practice is None:
        raise_err(ERR_NOT_FOUND, "Practice id does not exist")
    return success_object(practice)


@bp.route("/vbc/practices/<practice_id>/deactivate", methods=["POST"])
@require_roles("PayerAdmin")
def deactivate_practice(practice_id: str, _user_id: str, _role: str):
    practice = db.practices.get(practice_id)
    if practice is None:
        raise_err(ERR_NOT_FOUND, "Practice id does not exist")
    if practice["practice_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE practice can be deactivated")
    practice["practice_status"] = "INACTIVE"
    db.touch(practice)
    return success_object(practice)
