"""PTPackage and PTSession endpoints (PRD §3.6, §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import constants
import errors
import lookups
import models
from middleware import authenticate, require_role, require_owner
from response import success
from services import calc
from util import (require_str, require_int, parse_dt, parse_pagination, paginate)

bp = Blueprint("personal_training", __name__)


# --------------------------------------------------------------------------
# PTPackage
# --------------------------------------------------------------------------

@bp.route("/pt-packages", methods=["POST"])
def create_package():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    body = request.get_json(silent=True) or {}

    member_id = require_str(body, "member_id")
    sessions_purchased = require_int(body, "sessions_purchased", minimum=1)
    list_price = require_int(body, "list_price_cents", minimum=0)

    require_owner(caller, member_id)
    member = lookups.get_member(member_id)
    plan = db.store.membership_plans.get(member["plan_id"])
    discount = plan["pt_discount_pct"] if plan else 0

    price_paid = calc.pt_package_price(list_price, discount)

    rec = models.stamp_new({
        "member_id": member_id,
        "sessions_purchased": sessions_purchased,
        "list_price_cents": list_price,
        "price_paid_cents": price_paid,
        "sessions_remaining": sessions_purchased,
        "status": "ACTIVE",
    })
    db.store.pt_packages[rec["id"]] = rec
    return success(models.serialize_pt_package(rec), status=201)


@bp.route("/pt-packages/<package_id>", methods=["GET"])
def get_package(package_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_pt_package(package_id)
    require_owner(caller, rec["member_id"])
    return success(models.serialize_pt_package(rec), status=200)


@bp.route("/pt-packages", methods=["GET"])
def list_packages():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    items = list(db.store.pt_packages.values())
    if caller.is_member:
        items = [p for p in items if p["member_id"] == caller.user_id]
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_pt_package(p) for p in page], status=200, pagination=pagination)


# --------------------------------------------------------------------------
# PTSession
# --------------------------------------------------------------------------

@bp.route("/pt-sessions", methods=["POST"])
def create_pt_session():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    body = request.get_json(silent=True) or {}

    package_id = require_str(body, "package_id")
    trainer_name = require_str(body, "trainer_name")
    starts_raw = _required(body, "starts_at")
    expected = _required_version(body, "expected_package_version")

    # Existence (priority 3).
    package = lookups.get_pt_package(package_id)
    # Ownership against the package owner (priority 2 — but FK existence first).
    require_owner(caller, package["member_id"])

    starts_at = parse_dt(starts_raw, "starts_at")

    # OCC (priority 7).
    if expected != package["version"]:
        errors.raise_error(errors.ERR_STALE_PACKAGE_VERSION, "Stale package version")

    # Fiscal: package ACTIVE with sessions_remaining >= 1 (priority 18).
    # (No standalone ERR_INVALID_STATE row applies to scheduling; the gate is
    #  ERR_NO_PT_SESSIONS for a non-active or empty package.)
    if package["status"] != "ACTIVE" or package["sessions_remaining"] < 1:
        errors.raise_error(errors.ERR_NO_PT_SESSIONS, "Package not active or no sessions remaining")

    # PT time overlap (priority 16): start within an existing SCHEDULED session's
    # half-open 60-minute busy block for the same member.
    member_id = package["member_id"]
    if _pt_time_overlap(member_id, starts_at):
        errors.raise_error(errors.ERR_PT_TIME_OVERLAP, "PT session overlaps an existing busy block")

    rec = models.stamp_new({
        "package_id": package_id,
        "trainer_name": trainer_name,
        "starts_at": starts_at,
        "status": "SCHEDULED",
        "deducted": True,
    })
    db.store.pt_sessions[rec["id"]] = rec

    package["sessions_remaining"] -= 1
    models.touch(package)
    if package["sessions_remaining"] == 0:
        package["status"] = "EXHAUSTED"
        models.touch(package)

    return success(models.serialize_pt_session(rec), status=201)


@bp.route("/pt-sessions/<session_id>", methods=["GET"])
def get_pt_session(session_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_pt_session(session_id)
    package = db.store.pt_packages.get(rec["package_id"])
    if package is not None:
        require_owner(caller, package["member_id"])
    return success(models.serialize_pt_session(rec), status=200)


@bp.route("/pt-sessions", methods=["GET"])
def list_pt_sessions():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    items = list(db.store.pt_sessions.values())
    if caller.is_member:
        owned_pkg = {p["id"] for p in db.store.pt_packages.values()
                     if p["member_id"] == caller.user_id}
        items = [s for s in items if s["package_id"] in owned_pkg]
    package_id = request.args.get("package_id")
    status = request.args.get("status")
    if package_id is not None:
        items = [s for s in items if s["package_id"] == package_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_pt_session(s) for s in page], status=200, pagination=pagination)


@bp.route("/pt-sessions/<session_id>/complete", methods=["POST"])
def complete_pt_session(session_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    rec = lookups.get_pt_session(session_id)
    if rec["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "PT session is not SCHEDULED")
    if db.now() < rec["starts_at"]:
        errors.raise_error(errors.ERR_INVALID_STATE, "PT session has not started yet")
    rec["status"] = "COMPLETED"
    models.touch(rec)
    return success(models.serialize_pt_session(rec), status=200)


@bp.route("/pt-sessions/<session_id>/no-show", methods=["POST"])
def no_show_pt_session(session_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    rec = lookups.get_pt_session(session_id)
    if rec["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "PT session is not SCHEDULED")
    if db.now() < rec["starts_at"]:
        errors.raise_error(errors.ERR_INVALID_STATE, "PT session has not started yet")
    rec["status"] = "NO_SHOW"
    models.touch(rec)
    return success(models.serialize_pt_session(rec), status=200)


@bp.route("/pt-sessions/<session_id>/cancel", methods=["POST"])
def cancel_pt_session(session_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_pt_session(session_id)
    package = db.store.pt_packages.get(rec["package_id"])
    if package is not None:
        require_owner(caller, package["member_id"])
    body = request.get_json(silent=True) or {}
    expected = _required_version(body, "expected_package_version")

    # OCC (priority 7) against the package.
    if package is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Owning package not found")
    if expected != package["version"]:
        errors.raise_error(errors.ERR_STALE_PACKAGE_VERSION, "Stale package version")

    # State validity (priority 8).
    if rec["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "PT session is not SCHEDULED")

    # Late-cancel cutoff (priority 21): now must be strictly earlier than
    # starts_at - 24h.
    cutoff = rec["starts_at"] - timedelta(hours=constants.PT_CANCEL_CUTOFF_HOURS)
    if db.now() >= cutoff:
        errors.raise_error(errors.ERR_PT_LATE_CANCEL, "Cancel within the cutoff window")

    rec["status"] = "CANCELLED"
    rec["deducted"] = False
    models.touch(rec)
    package["sessions_remaining"] += 1
    if package["status"] == "EXHAUSTED" and package["sessions_remaining"] > 0:
        package["status"] = "ACTIVE"
    models.touch(package)
    return success(models.serialize_pt_session(rec), status=200)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _required(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field '%s'" % field)
    return body[field]


def _required_version(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field '%s'" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    return v


def _pt_time_overlap(member_id, starts_at):
    """A new starts_at may not fall within any existing SCHEDULED PT session's
    half-open [s, s + 60min) busy block for the same member (PRD §3.6)."""
    block = timedelta(minutes=constants.PT_SESSION_MINUTES)
    for s in db.store.pt_sessions.values():
        if s["status"] != "SCHEDULED":
            continue
        pkg = db.store.pt_packages.get(s["package_id"])
        if pkg is None or pkg["member_id"] != member_id:
            continue
        existing_start = s["starts_at"]
        if existing_start <= starts_at < existing_start + block:
            return True
    return False
