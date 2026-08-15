"""Bin entry permit endpoints (PRD 3.4): request by SiteManager or
SafetyOfficer, segregated approval by SafetyOfficer."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services import core
from util import (as_bool, as_dt, as_str, body, paginate_sorted, query_enum,
                  query_str, required, resolve_body_fk, resolve_path)

bp = Blueprint("permits", __name__)


@bp.route("/grain/entry-permits", methods=["POST"])
def create_permit():
    user_id, _ = require_roles("SiteManager", "SafetyOfficer")
    data = body()
    # existence (4)
    bin_rec = resolve_body_fk(db.bins, data, "bin_id", "bin")
    # shape (6)
    bin_id = as_str(required(data, "bin_id"), "bin_id")
    start = as_dt(required(data, "planned_start"), "planned_start")
    end = as_dt(required(data, "planned_end"), "planned_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400,
                       "planned_end must be strictly after planned_start")
    atmosphere = as_bool(required(data, "atmosphere_test_passed"),
                         "atmosphere_test_passed")
    loto = as_bool(required(data, "loto_confirmed"), "loto_confirmed")

    rec = core.new_common()
    rec.update({
        "bin_id": bin_id,
        "planned_start": start,
        "planned_end": end,
        "atmosphere_test_passed": atmosphere,
        "loto_confirmed": loto,
        "requester_user_id": user_id,
        "approver_user_id": None,
        "status": "REQUESTED",
    })
    db.permits[rec["id"]] = rec
    return ok(core.permit_view(rec), 201)


@bp.route("/grain/entry-permits/<pid>", methods=["GET"])
def get_permit(pid):
    require_roles(*ALL_ROLES)
    return ok(core.permit_view(resolve_path(db.permits, pid, "permit")))


@bp.route("/grain/entry-permits", methods=["GET"])
def list_permits():
    require_roles(*ALL_ROLES)
    f_bin = query_str("bin_id")
    f_status = query_enum("status", core.PERMIT_STATUSES)
    items = list(db.permits.values())
    if f_bin is not None:
        items = [p for p in items if p["bin_id"] == f_bin]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.permit_view(p) for p in page], total, limit, offset)


@bp.route("/grain/entry-permits/<pid>/approve", methods=["POST"])
def approve_permit(pid):
    user_id, _ = require_roles("SafetyOfficer")
    # existence (4)
    rec = resolve_path(db.permits, pid, "permit")
    # segregation (8): approver must differ from requester, before state check
    if user_id == rec["requester_user_id"]:
        raise ApiError("ERR_SOD_PERMIT_SELF_APPROVE", 403,
                       "the permit requester may not approve their own permit")
    # state (11)
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_PERMIT_NOT_REQUESTED", 409, "permit is not REQUESTED")
    # safety (16): no ACTIVE fumigation with application_start <= now on the bin
    if core.active_lockout_fumigation(rec["bin_id"]) is not None:
        raise ApiError("ERR_ACTIVE_FUMIGATION_EXISTS", 409,
                       "an active fumigation lockout exists on the bin")
    # safety (19): atmosphere test and LOTO
    if not (rec["atmosphere_test_passed"] and rec["loto_confirmed"]):
        raise ApiError("ERR_ATMOSPHERE_UNSAFE", 409,
                       "atmosphere test and lockout-tagout must both pass")

    rec["status"] = "APPROVED"
    rec["approver_user_id"] = user_id
    core.touch(rec)
    return ok(core.permit_view(rec))
