"""Permit routes: confirm, cancel, check-in, mark-no-show, reschedule, revoke,
settle (PRD 3.6-3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import errors
import util
import clock
import db
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core
from util import prime_hours, ceil_div, slot_datetime, BLOCK_MINUTES

bp = Blueprint("permits", __name__)


def _get_owned_permit(user_id, role, pid):
    """Priority 5 (existence) then priority 4-style ownership for OrgCoordinator.

    NOTE: per PRD 2.8 the ownership gate (priority 4) precedes path existence
    (priority 5); but ownership cannot be evaluated before the resource exists,
    so existence is necessarily resolved first. Tests exercise ownership only
    against existing resources."""
    permit = core.get_permit(pid)
    if role == "OrgCoordinator" and user_id != permit["organization_id"]:
        raise errors.forbidden_org()
    return permit


@bp.get("/permits")
def list_permits():
    require_roles(*ANY_ROLE)
    items = list(store.permits.values())
    for param in ("organization_id", "facility_id", "application_id",
                  "fee_schedule_id", "original_permit_id", "permit_date", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if p.get(param) == val]
    return util.paginate(items)


@bp.get("/permits/<pid>")
def get_permit(pid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_permit(pid))


@bp.post("/permits/<pid>/confirm")
def confirm_permit(pid):
    user_id, role = require_roles("OrgCoordinator")
    permit = _get_owned_permit(user_id, role, pid)
    if permit["status"] != "RESERVED":
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be RESERVED to confirm", 409)
    org = core.get_organization(permit["organization_id"])
    if org["standing"] == "SUSPENDED":
        raise errors.ApiError(errors.ERR_ORG_SUSPENDED,
                              "Organization standing is SUSPENDED", 409)
    inv = core.find_invoice_for_permit(permit["id"])
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "PAID"):
        raise errors.ApiError(errors.ERR_INVALID_INVOICE_STATE,
                              "Invoice must be ISSUED, PARTIALLY_PAID, or PAID to confirm", 409)
    if inv["paid_cents"] < inv["deposit_cents"]:
        raise errors.ApiError(errors.ERR_DEPOSIT_NOT_PAID,
                              "Cleared payments do not cover the deposit", 422)
    permit["status"] = "CONFIRMED"
    util.touch(permit)
    return success_object(permit)


@bp.post("/permits/<pid>/cancel")
def cancel_permit(pid):
    user_id, role = require_roles("OrgCoordinator", "AthleticsAdmin")
    permit = core.get_permit(pid)
    if role == "OrgCoordinator" and user_id != permit["organization_id"]:
        raise errors.forbidden_org()
    if permit["status"] not in ("RESERVED", "CONFIRMED", "RAINED_OUT"):
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit cannot be cancelled from its current state", 409)
    if permit["status"] == "CONFIRMED":
        start_dt = slot_datetime(util.parse_date(permit["permit_date"], "permit_date"),
                                 permit["start_minute"])
        if clock.now() >= start_dt:
            raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                                  "Cannot cancel at or after the slot start", 409)
    core.cancel_permit(permit, initiated_by=user_id)
    return success_object(permit)


@bp.post("/permits/<pid>/check-in")
def check_in(pid):
    require_roles("FieldSupervisor")
    body = util.get_json_body()
    attended = util.require_int(body, "attended_minutes")
    permit = core.get_permit(pid)
    if permit["status"] != "CONFIRMED":
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be CONFIRMED to check in", 409)
    duration = permit["end_minute"] - permit["start_minute"]
    if attended < 15 or attended > duration:
        raise errors.invalid_request(
            "attended_minutes must be between 15 and the slot duration")
    now = clock.now()
    start_dt = slot_datetime(util.parse_date(permit["permit_date"], "permit_date"),
                             permit["start_minute"])
    end_dt = slot_datetime(util.parse_date(permit["permit_date"], "permit_date"),
                           permit["end_minute"])
    if now < start_dt - timedelta(minutes=30) or now > end_dt:
        raise errors.ApiError(errors.ERR_CHECKIN_WINDOW_CLOSED,
                              "Check-in is outside [start-30min, end]", 409)
    permit["attendance_minutes"] = attended
    util.touch(permit)
    return success_object(permit)


@bp.post("/permits/<pid>/mark-no-show")
def mark_no_show(pid):
    require_roles("FieldSupervisor")
    permit = core.get_permit(pid)
    if permit["status"] != "CONFIRMED":
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be CONFIRMED to mark no-show", 409)
    end_dt = slot_datetime(util.parse_date(permit["permit_date"], "permit_date"),
                           permit["end_minute"])
    if clock.now() <= end_dt:
        raise errors.ApiError(errors.ERR_NO_SHOW_NOT_YET,
                              "Slot end has not passed yet", 409)
    if permit["attendance_minutes"] is not None:
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit already has a check-in", 409)

    org = core.get_organization(permit["organization_id"])

    # StrikeRecord: points = 10 * new active count including this one.
    new_count = core.active_strike_count(org["id"]) + 1
    strike = {
        "id": db.new_id(),
        "created_at": util.logical_now_iso(),
        "organization_id": org["id"],
        "permit_id": permit["id"],
        "strike_points": 10 * new_count,
        "status": "ACTIVE",
    }
    store.strike_records[strike["id"]] = strike

    # Invoice: penalty = full deposit; deposit waterfall; remainder stays owed.
    inv = core.find_invoice_for_permit(permit["id"])
    inv["penalty_cents"] = inv["deposit_cents"]
    core.run_deposit_waterfall(inv, initiated_by="system")

    permit["status"] = "NO_SHOW"
    util.touch(permit)

    # Ledger: release awarded hours, increment no_show_count.
    core.ledger_release(org["id"], permit.get("season_code", ""), permit)
    ledger = core.find_ledger(org["id"], permit.get("season_code", ""))
    if ledger is not None:
        ledger["no_show_count"] += 1
        util.touch(ledger)
    facility = store.facilities.get(permit["facility_id"])
    if facility is not None:
        core.recompute_facility_weekly_prime(facility)

    # Standing re-evaluation with the full cascade.
    core.recompute_org_strikes(org)
    core.reevaluate_standing(org)
    return success_object(permit)


@bp.post("/permits/<pid>/reschedule")
def reschedule_permit(pid):
    user_id, role = require_roles("OrgCoordinator", "AthleticsAdmin")
    body = util.get_json_body()
    new_date = util.require_date(body, "new_date")
    new_start = util.require_int(body, "new_start_minute", min_v=0, max_v=1439)
    new_end = util.require_int(body, "new_end_minute", min_v=1, max_v=1440)
    expected_version = util.require_int(body, "expected_permit_version")

    permit = core.get_permit(pid)
    if role == "OrgCoordinator" and user_id != permit["organization_id"]:
        raise errors.forbidden_org()

    # State legality.
    if permit["status"] != "RAINED_OUT":
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be RAINED_OUT to reschedule", 409)

    # OCC (PRD 2.7).
    if expected_version != permit["version"]:
        raise errors.stale_version(
            "expected_permit_version does not match the permit's current version")

    # Reschedule hard cap.
    if permit["rain_reschedule_count"] >= core.RESCHEDULE_HARD_CAP:
        raise errors.ApiError(errors.ERR_RESCHEDULE_LIMIT_REACHED,
                              "rain_reschedule_count is already 2", 409)

    # Facility safety gate.
    facility = core.get_facility(permit["facility_id"])
    if facility["condition_status"] == "CLOSED":
        raise errors.ApiError(errors.ERR_FACILITY_CLOSED,
                              "Facility condition_status is CLOSED", 409)

    # Temporal gates: horizon then slot-in-past.
    orig_date = util.parse_date(permit["permit_date"], "permit_date")
    if new_date < orig_date or new_date > orig_date + timedelta(days=core.RESCHEDULE_HORIZON_DAYS):
        raise errors.ApiError(errors.ERR_RESCHEDULE_HORIZON_EXCEEDED,
                              "new_date is outside [permit_date, permit_date + 10 days]", 409)
    if slot_datetime(new_date, new_start) <= clock.now():
        raise errors.ApiError(errors.ERR_SLOT_IN_PAST,
                              "New slot starts at or before the current logical clock", 409)

    # Constraint gates: duration bounds, slot overlap, lights, caps.
    duration = new_end - new_start
    if new_end <= new_start or duration < 30 or duration > 480:
        raise errors.ApiError(errors.ERR_INVALID_TIME_RANGE,
                              "new_end_minute must exceed new_start_minute with duration 30..480", 409)
    new_date_str = new_date.strftime("%Y-%m-%d")
    if core.slot_conflicts(permit["facility_id"], new_date_str, new_start, new_end,
                           exclude_permit_id=permit["id"]):
        raise errors.ApiError(errors.ERR_SLOT_OVERLAP,
                              "New slot overlaps an existing RESERVED/CONFIRMED permit", 409)

    if permit["lights_approved"]:
        if core.lights_conflict_or_cap(facility, new_date_str, new_start, new_end,
                                       exclude_permit_id=permit["id"]):
            raise errors.ApiError(errors.ERR_LIGHTS_BUFFER_OVERLAP,
                                  "Lights buffer or nightly block cap breached", 409)

    # Season prime cap (inclusive).
    window = core._window_for_permit(permit)
    season_code = permit.get("season_code", "")
    ph = prime_hours(new_start, new_end)
    ledger = core.find_ledger(permit["organization_id"], season_code)
    current_prime = ledger["awarded_prime_hours"] if ledger else 0
    if window is not None and current_prime + ph > window["prime_cap_hours_per_org"]:
        raise errors.ApiError(errors.ERR_PRIME_CAP_EXCEEDED,
                              "Reschedule would exceed prime_cap_hours_per_org", 409)

    # Turf-rest weekly cap for the candidate slot's week (inclusive).
    if core.weekly_load_for(facility["id"], new_date) + ph > facility["weekly_prime_hour_cap"]:
        raise errors.ApiError(errors.ERR_TURF_REST_CAP_EXCEEDED,
                              "Reschedule would exceed weekly_prime_hour_cap", 409)

    # --- Apply the reschedule ---
    if permit["original_permit_id"] is None:
        permit["original_permit_id"] = permit["id"]
    permit["permit_date"] = new_date_str
    permit["start_minute"] = new_start
    permit["end_minute"] = new_end
    permit["rain_reschedule_count"] += 1

    # Fee re-quote: new provisional lines REPLACE the invoice lines; rain credit
    # and adjustments reset to 0 (consumed by the replacement slot).
    schedule = core.get_fee_schedule(permit["fee_schedule_id"])
    org = core.get_organization(permit["organization_id"])
    lights_minutes = duration if permit["lights_approved"] else 0
    field_fee, lights_fee, surcharge, total, deposit, _r = core.quote_fees(
        schedule, org["classification"], permit["event_type"], duration, lights_minutes)
    permit["quoted_field_fee_cents"] = field_fee
    permit["quoted_lights_fee_cents"] = lights_fee
    permit["quoted_surcharge_cents"] = surcharge
    permit["quoted_total_cents"] = total
    permit["deposit_required_cents"] = deposit
    permit["lights_minutes_quoted"] = lights_minutes

    inv = core.find_invoice_for_permit(permit["id"])
    inv["field_fee_cents"] = field_fee
    inv["lights_fee_cents"] = lights_fee
    inv["surcharge_cents"] = surcharge
    inv["credit_cents"] = 0
    inv["adjustment_cents"] = 0
    inv["total_cents"] = total
    core.recompute_invoice_totals(inv)
    util.touch(inv)

    permit["status"] = "CONFIRMED"
    util.touch(permit)

    core.ledger_readd(permit["organization_id"], season_code, permit)
    core.recompute_facility_weekly_prime(facility)

    # Immediate re-rain: an ACTIVE closure already intersecting the new slot
    # fires the rain-out cascade within the same request.
    for c in sorted(store.field_closures.values(), key=util.sort_key):
        if c["status"] != "ACTIVE":
            continue
        if c["facility_id"] != permit["facility_id"]:
            continue
        if c["closure_date"] != new_date_str:
            continue
        if c["start_minute"] is None or c["end_minute"] is None:
            core.rain_out_permit(permit)
            break
        if util.half_open_overlap(c["start_minute"], c["end_minute"], new_start, new_end):
            core.rain_out_permit(permit)
            break

    return success_object(permit)


@bp.post("/permits/<pid>/revoke")
def revoke_permit(pid):
    require_roles("AthleticsAdmin")
    body = util.get_json_body()
    fault = util.require_enum(body, "fault", ("ORG_FAULT", "ADMIN_DISCRETION"))
    permit = core.get_permit(pid)
    if permit["status"] not in ("RESERVED", "CONFIRMED"):
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be RESERVED or CONFIRMED to revoke", 409)
    core.revoke_permit(permit, fault)
    return success_object(permit)


@bp.post("/permits/<pid>/settle")
def settle_permit(pid):
    require_roles("FieldSupervisor")
    body = util.get_json_body()
    actual_lights = util.optional_int(body, "actual_lights_minutes", min_v=0, default=None)
    permit = core.get_permit(pid)
    if permit["status"] != "CONFIRMED":
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be CONFIRMED to settle", 409)
    if permit["attendance_minutes"] is None:
        raise errors.ApiError(errors.ERR_CHECKIN_REQUIRED,
                              "Settlement requires a recorded check-in", 409)
    end_dt = slot_datetime(util.parse_date(permit["permit_date"], "permit_date"),
                           permit["end_minute"])
    if clock.now() <= end_dt:
        raise errors.ApiError(errors.ERR_INVALID_PERMIT_STATE,
                              "Slot end has not passed yet", 409)

    org = core.get_organization(permit["organization_id"])
    schedule = core.get_fee_schedule(permit["fee_schedule_id"])
    attendance = permit["attendance_minutes"]

    # Final-variant field fee: min(quoted, round_half_up(attendance * rate / 60)).
    if permit["event_type"] == "TOURNAMENT" and (
            permit["end_minute"] - permit["start_minute"]) >= schedule["tournament_day_min_minutes"]:
        final_field = permit["quoted_field_fee_cents"]
    else:
        if org["classification"] == "RESIDENT":
            rate = schedule["hourly_resident_cents"]
        elif org["classification"] == "NONRESIDENT":
            rate = schedule["hourly_nonresident_cents"]
        else:
            rate = schedule["hourly_commercial_cents"]
        from decimal import Decimal
        actual_field = core.round_half_up_cents(Decimal(attendance) * Decimal(rate) / Decimal(60))
        final_field = min(permit["quoted_field_fee_cents"], actual_field)

    # Final lights fee: min(quoted, ceil(actual/15) * block rate). Zero when
    # lights were never approved.
    if permit["lights_approved"]:
        actual_minutes = actual_lights if actual_lights is not None else attendance
        actual_blocks = ceil_div(actual_minutes, BLOCK_MINUTES)
        final_lights = min(permit["quoted_lights_fee_cents"],
                           actual_blocks * schedule["lights_block_cents"])
    else:
        final_lights = 0

    # Surcharge carries over unchanged; final total can only diverge downward.
    final_total = final_field + final_lights + permit["quoted_surcharge_cents"]
    permit["final_total_cents"] = final_total
    permit["status"] = "COMPLETED"
    util.touch(permit)

    inv = core.find_invoice_for_permit(permit["id"])
    inv["field_fee_cents"] = final_field
    inv["lights_fee_cents"] = final_lights
    inv["surcharge_cents"] = permit["quoted_surcharge_cents"]
    inv["total_cents"] = (final_field + final_lights + permit["quoted_surcharge_cents"]
                          + inv["adjustment_cents"] - inv["credit_cents"])
    core.recompute_invoice_totals(inv)
    util.touch(inv)

    # Ledger: release awarded hours, add attended hours (integer division).
    season_code = permit.get("season_code", "")
    core.ledger_release(org["id"], season_code, permit)
    ledger = core.find_ledger(org["id"], season_code)
    if ledger is not None:
        ledger["attended_hours"] += attendance // 60
        util.touch(ledger)
    facility = store.facilities.get(permit["facility_id"])
    if facility is not None:
        core.recompute_facility_weekly_prime(facility)

    return success_object(permit)
