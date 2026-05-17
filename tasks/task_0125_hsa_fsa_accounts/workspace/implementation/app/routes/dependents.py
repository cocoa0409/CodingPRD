"""Dependent endpoints."""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..errors import ApiError
from ..helpers import (
    get_json_body, parse_iso_field, require_enum, require_fields, require_string,
    serialize_dependent,
)
from ..responses import build_success_envelope
from ..store import store


bp = Blueprint("dependents", __name__)


RELATIONSHIPS = {"CHILD", "SPOUSE", "QUALIFYING_RELATIVE"}


@bp.route("/account-holders/<account_holder_id>/dependents", methods=["POST"])
@require_auth(["AccountHolder", "PlanAdministrator"])
def create_dependent(account_holder_id: str):
    holder = store.account_holders.get(account_holder_id)
    if holder is None:
        raise ApiError("ERR_NOT_FOUND", "Account holder not found.")

    # AccountHolder may only add to their own.
    if g.role == "AccountHolder" and g.user_id != holder["id"]:
        raise ApiError("ERR_NOT_FOUND", "Account holder not found.")

    body = get_json_body(allow_empty=False)
    require_fields(body, ["full_name", "birth_date", "relationship"])
    full_name = require_string(body["full_name"], "full_name")
    birth_date = parse_iso_field(body["birth_date"], "birth_date")
    relationship = require_enum(body["relationship"], RELATIONSHIPS, "relationship")

    with store.lock:
        now = store.clock.now()
        row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "account_holder_id": holder["id"],
            "full_name": full_name,
            "birth_date": birth_date,
            "relationship": relationship,
            "status": "ACTIVE",
        }
        store.dependents[row["id"]] = row

    return jsonify(build_success_envelope(serialize_dependent(row))), 201


@bp.route("/dependents/<dependent_id>/deactivate", methods=["POST"])
@require_auth(["PlanAdministrator"])
def deactivate_dependent(dependent_id: str):
    dep = store.dependents.get(dependent_id)
    if dep is None:
        raise ApiError("ERR_NOT_FOUND", "Dependent not found.")
    with store.lock:
        if dep["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Dependent is not ACTIVE.")
        dep["status"] = "INACTIVE"
        dep["version"] += 1
        dep["updated_at"] = store.clock.now()
    return jsonify(build_success_envelope(serialize_dependent(dep))), 200
