"""Entry permit lifecycle (PRD sections 3.3 and 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_ATMOSPHERE_OUT_OF_LIMITS, ERR_CLIENT_CREDIT_HOLD,
    ERR_ENTRANTS_STILL_INSIDE, ERR_ISOLATION_NOT_VERIFIED,
    ERR_OPEN_INCIDENTS_EXIST, ERR_OUTSIDE_PLANNED_WINDOW,
    ERR_PERMIT_INVALID_STATE, ERR_PERMIT_NOT_FOUND,
    ERR_PRE_ENTRY_READING_STALE, ERR_RESCUE_PLAN_NOT_APPROVED,
    ERR_RESCUE_TEAM_UNDERSTAFFED, ERR_INVALID_TIME_RANGE,
    ERR_SPACE_NOT_PERMIT_REQUIRED, ERR_SPACE_OCCUPIED,
    ERR_SPACE_OUT_OF_SERVICE, raise_error,
)
from helpers import (
    body, iso_z, list_response, now_dt, now_ts, opt_string, parse_dt,
    reject_unknown, req_datetime, req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.spaces import check_expected_space_version, get_space
import services
from services import (
    PRE_ENTRY_MAX_AGE, VERIFICATION_TTL, approved_plan_for_space,
    cancel_permit_cascade, close_permit_cascade, open_incidents_for_permit,
    on_duty_entries_for_permit,
)

bp = Blueprint("permits", __name__)

REQUIRED_ISOLATION_FLAGS = (("ventilation_required", "VENTILATION"),
                            ("blind_flange_required", "BLIND_FLANGE"))


def get_permit(permit_id):
    permit = db.entry_permits.get(permit_id)
    if permit is None:
        raise_error(ERR_PERMIT_NOT_FOUND, "Entry permit not found")
    return permit


def _latest_pre_entry_reading(permit_id, after_iso=None):
    readings = [r for r in db.atmospheric_readings.values()
                if r["permit_id"] == permit_id and r["reading_kind"] == "PRE_ENTRY"]
    if after_iso is not None:
        after = parse_dt(after_iso)
        readings = [r for r in readings if parse_dt(r["recorded_at"]) > after]
    if not readings:
        return None
    readings.sort(key=lambda r: (r["recorded_at"], r["_seq"]))
    return readings[-1]


def _check_isolations(space, permit_id, now):
    for flag, iso_type in REQUIRED_ISOLATION_FLAGS:
        if not space[flag]:
            continue
        ok = any(
            v["permit_id"] == permit_id and v["isolation_type"] == iso_type
            and v["status"] == "VERIFIED"
            and v["expires_at"] is not None and parse_dt(v["expires_at"]) > now
            for v in db.isolation_verifications.values())
        if not ok:
            raise_error(ERR_ISOLATION_NOT_VERIFIED,
                        f"Required isolation type {iso_type} lacks a VERIFIED, unexpired verification")


def _check_fresh_pre_entry(permit, now, after_iso=None):
    reading = _latest_pre_entry_reading(permit["id"], after_iso)
    if reading is None or not reading["within_limits"]:
        raise_error(ERR_ATMOSPHERE_OUT_OF_LIMITS,
                    "No PRE_ENTRY reading exists or the latest is out of limits")
    if (now - parse_dt(reading["recorded_at"])) > PRE_ENTRY_MAX_AGE:
        raise_error(ERR_PRE_ENTRY_READING_STALE,
                    "Latest PRE_ENTRY reading is older than 30 minutes")


def _standby_coverage(permit_id, now):
    count = 0
    for a in db.standby_assignments.values():
        if a["permit_id"] != permit_id or a["status"] not in ("SCHEDULED", "ON_STANDBY"):
            continue
        if parse_dt(a["standby_start_at"]) <= now < parse_dt(a["standby_end_at"]):
            count += 1
    return count


# ---------------------------------------------------------------------------
# CRUD + lifecycle
# ---------------------------------------------------------------------------

@bp.route("/rescue-ops/confined-spaces/<space_id>/entry-permits", methods=["POST"])
def create_permit(space_id):
    user_id, _, _ = require_auth(("EntrySupervisor",))
    space = get_space(space_id)
    data = body()
    reject_unknown(data, {"purpose", "planned_start_at", "planned_end_at", "expected_space_version"})
    purpose = req_string(data, "purpose")
    planned_start = req_datetime(data, "planned_start_at")
    planned_end = req_datetime(data, "planned_end_at")
    if not planned_end > planned_start:
        raise_error(ERR_INVALID_TIME_RANGE, "planned_end_at must be strictly after planned_start_at")
    check_expected_space_version(data, space)
    # Capacity gates (priority 11)
    if space["status"] != "AVAILABLE":
        raise_error(ERR_SPACE_OUT_OF_SERVICE, "Space is not AVAILABLE")
    occupied = any(p["space_id"] == space["id"]
                   and p["status"] in ("ISSUED", "ACTIVE", "SUSPENDED")
                   for p in db.entry_permits.values())
    if occupied:
        raise_error(ERR_SPACE_OCCUPIED, "Space already has a permit in ISSUED, ACTIVE, or SUSPENDED")
    # Referential gate (priority 13)
    if space["classification"] not in ("PERMIT_REQUIRED", "PERMIT_REQUIRED_HAZARDOUS"):
        raise_error(ERR_SPACE_NOT_PERMIT_REQUIRED, "Space is not PERMIT_REQUIRED*")
    # Fiscal gate (priority 14)
    account = db.client_accounts.get(space["client_account_id"])
    if account is not None and account["on_credit_hold"]:
        raise_error(ERR_CLIENT_CREDIT_HOLD, "Account is on credit hold")
    now = now_dt()
    permit = {
        "space_id": space["id"],
        "client_account_id": space["client_account_id"],
        "purpose": purpose,
        "planned_start_at": iso_z(planned_start),
        "planned_end_at": iso_z(planned_end),
        "issued_by": None,
        "issued_at": None,
        "actual_entry_at": None,
        "last_suspended_at": None,
        "closed_at": None,
        "close_reason": None,
        "suspension_count": 0,
        "reentry_count": 0,
        "event_base_billed": False,
        "cancellation_fee_billed": False,
        "status": "DRAFT",
    }
    stamp_new(permit)
    db.entry_permits[permit["id"]] = permit
    # Supersede semantics: existing DRAFT permits of the space auto-cancel.
    for other in list(db.entry_permits.values()):
        if other["space_id"] == space["id"] and other["id"] != permit["id"] \
                and other["status"] == "DRAFT":
            cancel_permit_cascade(other, now, escalation=False)
    touch(space)
    return success_object(serializers.entry_permit(permit), 201)


@bp.route("/rescue-ops/entry-permits", methods=["GET"])
def list_permits():
    require_auth(ALL_ROLES)
    return list_response(list(db.entry_permits.values()), serializers.entry_permit, {
        "space_id": request.args.get("space_id"),
        "client_account_id": request.args.get("client_account_id"),
        "status": request.args.get("status"),
        "issued_by": request.args.get("issued_by"),
    })


@bp.route("/rescue-ops/entry-permits/<permit_id>", methods=["GET"])
def get_one_permit(permit_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.entry_permit(get_permit(permit_id)))


@bp.route("/rescue-ops/entry-permits/<permit_id>/issue", methods=["POST"])
def issue_permit(permit_id):
    user_id, _, _ = require_auth(("EntrySupervisor",))
    permit = get_permit(permit_id)
    body()  # body optional; no fields defined
    if permit["status"] != "DRAFT":
        raise_error(ERR_PERMIT_INVALID_STATE, "Only a DRAFT permit can be issued")
    permit["status"] = "ISSUED"
    permit["issued_by"] = user_id
    permit["issued_at"] = now_ts()
    touch(permit)
    return success_object(serializers.entry_permit(permit))


@bp.route("/rescue-ops/entry-permits/<permit_id>/activate", methods=["POST"])
def activate_permit(permit_id):
    user_id, _, _ = require_auth(("EntrySupervisor",))
    permit = get_permit(permit_id)
    body()
    if permit["status"] != "ISSUED":
        raise_error(ERR_PERMIT_INVALID_STATE, "Only an ISSUED permit can be activated")
    now = now_dt()
    space = get_space(permit["space_id"])
    # Safety chain in fixed order (PRD 3.3): plan, isolation, atmosphere,
    # staleness, standby coverage, planned window; then space availability.
    plan = approved_plan_for_space(space["id"])
    if plan is None:
        raise_error(ERR_RESCUE_PLAN_NOT_APPROVED, "No APPROVED rescue plan exists for the space")
    _check_isolations(space, permit["id"], now)
    _check_fresh_pre_entry(permit, now)
    if _standby_coverage(permit["id"], now) < plan["required_team_size"]:
        raise_error(ERR_RESCUE_TEAM_UNDERSTAFFED, "Standby coverage below required_team_size")
    if not (parse_dt(permit["planned_start_at"]) <= now <= parse_dt(permit["planned_end_at"])):
        raise_error(ERR_OUTSIDE_PLANNED_WINDOW, "now is outside the planned entry window")
    if space["status"] != "AVAILABLE":
        raise_error(ERR_SPACE_OUT_OF_SERVICE, "Space is not AVAILABLE")
    permit["status"] = "ACTIVE"
    permit["actual_entry_at"] = iso_z(now)
    touch(permit)
    return success_object(serializers.entry_permit(permit))


@bp.route("/rescue-ops/entry-permits/<permit_id>/suspend", methods=["POST"])
def suspend_permit(permit_id):
    require_auth(("EntrySupervisor", "SafetyOfficer"))
    permit = get_permit(permit_id)
    data = body()
    reject_unknown(data, {"reason"})
    opt_string(data, "reason")
    if permit["status"] != "ACTIVE":
        raise_error(ERR_PERMIT_INVALID_STATE, "Only an ACTIVE permit can be suspended")
    if on_duty_entries_for_permit(permit["id"]):
        raise_error(ERR_ENTRANTS_STILL_INSIDE, "Roster entries are still ON_DUTY")
    now = now_dt()
    permit["status"] = "SUSPENDED"
    permit["suspension_count"] += 1
    permit["last_suspended_at"] = iso_z(now)
    touch(permit)
    return success_object(serializers.entry_permit(permit))


@bp.route("/rescue-ops/entry-permits/<permit_id>/resume", methods=["POST"])
def resume_permit(permit_id):
    user_id, _, _ = require_auth(("EntrySupervisor",))
    permit = get_permit(permit_id)
    body()
    if permit["status"] != "SUSPENDED":
        raise_error(ERR_PERMIT_INVALID_STATE, "Only a SUSPENDED permit can be resumed")
    now = now_dt()
    space = get_space(permit["space_id"])
    # Re-entry chain (PRD 3.5): plan, isolation, post-suspension atmosphere,
    # staleness, open incidents.
    plan = approved_plan_for_space(space["id"])
    if plan is None:
        raise_error(ERR_RESCUE_PLAN_NOT_APPROVED, "No APPROVED rescue plan exists for the space")
    _check_isolations(space, permit["id"], now)
    _check_fresh_pre_entry(permit, now, after_iso=permit["last_suspended_at"])
    if open_incidents_for_permit(permit["id"]):
        raise_error(ERR_OPEN_INCIDENTS_EXIST, "Open incidents exist on the permit")
    permit["status"] = "ACTIVE"
    permit["reentry_count"] += 1
    touch(permit)
    return success_object(serializers.entry_permit(permit))


@bp.route("/rescue-ops/entry-permits/<permit_id>/close", methods=["POST"])
def close_permit(permit_id):
    user_id, _, _ = require_auth(("EntrySupervisor",))
    permit = get_permit(permit_id)
    body()
    if permit["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_PERMIT_INVALID_STATE, "Only an ACTIVE or SUSPENDED permit can be closed")
    if on_duty_entries_for_permit(permit["id"]):
        raise_error(ERR_ENTRANTS_STILL_INSIDE, "Roster entries are still ON_DUTY")
    if open_incidents_for_permit(permit["id"]):
        raise_error(ERR_OPEN_INCIDENTS_EXIST, "Open incidents exist on the permit")
    close_permit_cascade(permit, now_dt())
    return success_object(serializers.entry_permit(permit))


@bp.route("/rescue-ops/entry-permits/<permit_id>/cancel", methods=["POST"])
def cancel_permit(permit_id):
    user_id, _, _ = require_auth(("EntrySupervisor",))
    permit = get_permit(permit_id)
    data = body()
    reject_unknown(data, {"reason"})
    opt_string(data, "reason")
    if permit["status"] not in ("DRAFT", "ISSUED", "ACTIVE", "SUSPENDED"):
        raise_error(ERR_PERMIT_INVALID_STATE, "Permit is already terminal")
    if permit["status"] == "ACTIVE" and on_duty_entries_for_permit(permit["id"]):
        raise_error(ERR_ENTRANTS_STILL_INSIDE, "Roster entries are still ON_DUTY")
    cancel_permit_cascade(permit, now_dt(), escalation=False)
    return success_object(serializers.entry_permit(permit))
