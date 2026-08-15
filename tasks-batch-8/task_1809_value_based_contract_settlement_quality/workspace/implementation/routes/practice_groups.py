"""PracticeGroup endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE_TIN,
    ERR_GROUP_HAS_OPEN_CONTRACTS,
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

bp = Blueprint("practice_groups", __name__)


@bp.route("/vbc/practice-groups", methods=["POST"])
@require_roles("PayerAdmin")
def create_group(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, {"group_name", "tin"})
    group_name = require_string(body, "group_name")
    tin = require_string(body, "tin")

    # Uniqueness (priority 11): tin globally unique regardless of status.
    for group in db.practice_groups.values():
        if group["tin"] == tin:
            raise_err(ERR_DUPLICATE_TIN, "tin already exists")

    group = {
        "group_name": group_name,
        "tin": tin,
        "group_status": "ACTIVE",
        "suspension_reason": None,
    }
    db.stamp_new(group)
    db.practice_groups[group["id"]] = group
    return success_object(group, 201)


@bp.route("/vbc/practice-groups", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_groups(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.practice_groups.values()))
    items = apply_filters(items, ["group_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/practice-groups/<group_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_group(group_id: str, _user_id: str, _role: str):
    group = db.practice_groups.get(group_id)
    if group is None:
        raise_err(ERR_NOT_FOUND, "PracticeGroup id does not exist")
    return success_object(group)


@bp.route("/vbc/practice-groups/<group_id>/suspend", methods=["POST"])
@require_roles("PayerAdmin")
def suspend_group(group_id: str, _user_id: str, _role: str):
    group = db.practice_groups.get(group_id)
    if group is None:
        raise_err(ERR_NOT_FOUND, "PracticeGroup id does not exist")
    body = get_json_body()
    reject_unknown_fields(body, {"reason"})
    reason = require_string(body, "reason")
    if group["group_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE group can be suspended")
    group["group_status"] = "SUSPENDED"
    group["suspension_reason"] = reason
    db.touch(group)
    return success_object(group)


@bp.route("/vbc/practice-groups/<group_id>/reinstate", methods=["POST"])
@require_roles("PayerAdmin")
def reinstate_group(group_id: str, _user_id: str, _role: str):
    group = db.practice_groups.get(group_id)
    if group is None:
        raise_err(ERR_NOT_FOUND, "PracticeGroup id does not exist")
    if group["group_status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SUSPENDED group can be reinstated")
    group["group_status"] = "ACTIVE"
    group["suspension_reason"] = None
    db.touch(group)
    return success_object(group)


@bp.route("/vbc/practice-groups/<group_id>/terminate", methods=["POST"])
@require_roles("PayerAdmin")
def terminate_group(group_id: str, _user_id: str, _role: str):
    group = db.practice_groups.get(group_id)
    if group is None:
        raise_err(ERR_NOT_FOUND, "PracticeGroup id does not exist")
    if group["group_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE or SUSPENDED group can be terminated")
    for contract in db.contracts.values():
        if contract["practice_group_id"] == group_id and contract["contract_status"] in ("DRAFT", "ACTIVE"):
            raise_err(ERR_GROUP_HAS_OPEN_CONTRACTS, "Group has open contracts")
    group["group_status"] = "TERMINATED"
    db.touch(group)
    return success_object(group)
