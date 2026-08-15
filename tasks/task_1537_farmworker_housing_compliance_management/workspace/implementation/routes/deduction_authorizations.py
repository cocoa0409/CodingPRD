"""Deduction authorizations: create (with supersession + OCC), list, get, revoke."""

from flask import Blueprint

import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from validate import (
    get_body, require_string, require_number, require_enum,
    parse_date_strict, parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("deduction_authorizations", __name__)

PURPOSES = {"RENT", "RENT_AND_UTILITIES"}


def _view(a):
    return {
        "id": a["id"],
        "household_id": a["household_id"],
        "cap_percent": a["cap_percent"],
        "purpose": a["purpose"],
        "effective_date": a["effective_date"],
        "status": a["status"],
        "superseded_by_id": a["superseded_by_id"],
        "created_by": a["created_by"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/deduction-authorizations", methods=["POST"])
def create_authorization():
    user_id, _ = require_roles("IntakeCoordinator")
    body = get_body()
    household_id = require_string(body, "household_id")
    cap_percent = require_number(body, "cap_percent")
    purpose = require_enum(body, "purpose", PURPOSES)
    effective = parse_date_strict(body.get("effective_date"), "effective_date")
    if "expected_household_version" not in body or body["expected_household_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_household_version is required")
    expected_household_version = body["expected_household_version"]
    if isinstance(expected_household_version, bool) or not isinstance(expected_household_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_household_version must be an integer")
    if not (cap_percent > 0 and cap_percent <= 1):
        raise err("ERR_INVALID_REQUEST", "cap_percent must be > 0 and <= 1")

    h = db.households.get(household_id)
    if h is None:
        raise err("ERR_HOUSEHOLD_NOT_FOUND")

    # OCC after existence, before business rules.
    if expected_household_version != h["version"]:
        raise err("ERR_STALE_VERSION")

    # Supersede existing ACTIVE authorization for the household.
    prior_active = None
    for a in db.deduction_authorizations.values():
        if a["household_id"] == household_id and a["status"] == "ACTIVE":
            prior_active = a
            break

    now = db.now_ts()
    a = {
        "id": db.new_id(),
        "household_id": household_id,
        "cap_percent": cap_percent,
        "purpose": purpose,
        "effective_date": effective.isoformat(),
        "status": "ACTIVE",
        "superseded_by_id": None,
        "created_by": user_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.deduction_authorizations[a["id"]] = a
    if prior_active is not None:
        prior_active["status"] = "SUPERSEDED"
        prior_active["superseded_by_id"] = a["id"]
        prior_active["updated_at"] = now
    h["version"] += 1
    h["updated_at"] = now
    return success_object(_view(a), status=201)


@bp.route("/deduction-authorizations", methods=["GET"])
def list_authorizations():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.deduction_authorizations.values())
    hh_f = get_filter("household_id")
    status_f = get_filter("status")
    sup_f = get_filter("superseded_by_id")
    if hh_f is not None:
        items = [a for a in items if a["household_id"] == hh_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if sup_f is not None:
        items = [a for a in items if a.get("superseded_by_id") == sup_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(a) for a in page], total, limit, offset)


@bp.route("/deduction-authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    get_auth()
    a = db.deduction_authorizations.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(a))


@bp.route("/deduction-authorizations/<aid>", methods=["PUT"])
def drive_authorization(aid):
    require_roles("IntakeCoordinator")
    body = get_body()
    target = require_enum(body, "status", {"REVOKED"})
    a = db.deduction_authorizations.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND")
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", f"Cannot revoke an authorization in {a['status']}")
    a["status"] = "REVOKED"
    a["updated_at"] = db.now_ts()
    return success_object(_view(a))
