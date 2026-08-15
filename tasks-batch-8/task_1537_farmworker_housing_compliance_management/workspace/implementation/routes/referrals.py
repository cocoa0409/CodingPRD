"""Service referrals: create (ELIGIBLE + minor gates), list, get, drive lifecycle."""

from flask import Blueprint

import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from validate import (
    get_body, require_string, require_enum, optional_string,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("referrals", __name__)

REFERRAL_TYPES = {"EDUCATION", "HEALTH"}
REFERRAL_TARGETS = {"ACCEPTED_BY_AGENCY", "COMPLETED", "DECLINED"}


def _view(r):
    return {
        "id": r["id"],
        "household_id": r["household_id"],
        "referral_type": r["referral_type"],
        "agency_name": r["agency_name"],
        "notes": r["notes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/service-referrals", methods=["POST"])
def create_referral():
    require_roles("IntakeCoordinator")
    body = get_body()
    household_id = require_string(body, "household_id")
    referral_type = require_enum(body, "referral_type", REFERRAL_TYPES)
    agency_name = require_string(body, "agency_name")
    notes = optional_string(body, "notes")

    h = db.households.get(household_id)
    if h is None:
        raise err("ERR_HOUSEHOLD_NOT_FOUND")
    if h["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_HOUSEHOLD_NOT_ELIGIBLE")
    if referral_type == "EDUCATION" and h.get("minor_count", 0) < 1:
        raise err("ERR_EDUCATION_REFERRAL_REQUIRES_MINOR")

    now = db.now_ts()
    r = {
        "id": db.new_id(),
        "household_id": household_id,
        "referral_type": referral_type,
        "agency_name": agency_name,
        "notes": notes,
        "status": "INITIATED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.service_referrals[r["id"]] = r
    return success_object(_view(r), status=201)


@bp.route("/service-referrals", methods=["GET"])
def list_referrals():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.service_referrals.values())
    hh_f = get_filter("household_id")
    type_f = get_filter("referral_type")
    status_f = get_filter("status")
    if hh_f is not None:
        items = [r for r in items if r["household_id"] == hh_f]
    if type_f is not None:
        items = [r for r in items if r["referral_type"] == type_f]
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(r) for r in page], total, limit, offset)


@bp.route("/service-referrals/<rid>", methods=["GET"])
def get_referral(rid):
    get_auth()
    r = db.service_referrals.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(r))


@bp.route("/service-referrals/<rid>", methods=["PUT"])
def drive_referral(rid):
    require_roles("IntakeCoordinator")
    body = get_body()
    target = require_enum(body, "status", REFERRAL_TARGETS)
    r = db.service_referrals.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND")
    current = r["status"]

    allowed = {
        "INITIATED": {"ACCEPTED_BY_AGENCY", "DECLINED"},
        "ACCEPTED_BY_AGENCY": {"COMPLETED"},
        "COMPLETED": set(),
        "DECLINED": set(),
    }
    if target not in allowed.get(current, set()):
        raise err("ERR_INVALID_STATE", f"Cannot move referral from {current} to {target}")
    r["status"] = target
    r["updated_at"] = db.now_ts()
    return success_object(_view(r))
