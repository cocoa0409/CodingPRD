"""Tanning & Spray-Tan Salon API — Flask entry point.

In-memory only. No seeding at startup. All state is built via the API.
Boots clean on every process start (per-test-server isolation).
"""
import os
from datetime import timedelta

from flask import Flask, request

import errors
from errors import ApiError, err
import auth
import response as resp
import repo
import calc
import serialize as ser
from clock import clock
from db import store
from money import line_total
from pagination import get_pagination, paginate
from repo import (
    _stamp_create_audited,
    _stamp_create_writeonce,
    touch,
    get_member,
    get_plan,
    get_equipment,
    get_room,
    get_session,
    get_product,
    get_order,
    get_or_create_ledger,
    sorted_by_created,
)
from timeutil import parse_iso

app = Flask(__name__)

SKIN_TYPES = {"I", "II", "III", "IV", "V", "VI"}
TIER_CODES = {"BASIC", "PREMIUM", "UNLIMITED"}
EQUIP_KINDS = {"BED", "BOOTH"}
SESSION_KINDS = {"UV", "SPRAY"}
BOOKING_MODES = {"RESERVATION", "WALK_IN"}
OUTCOMES = {"SUCCEEDED", "DECLINED"}
SERVICE_REASONS = {"SCHEDULED_THRESHOLD", "MANUAL"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(e):
    return resp.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(_e):
    return resp.error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(_e):
    return resp.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    return resp.error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be an integer")
    return value


def list_response(records, serializer):
    limit, offset = get_pagination()
    ordered = sorted_by_created(records)
    page, total = paginate(ordered, limit, offset)
    return resp.array_response([serializer(r) for r in page], limit, offset, total)


# ===========================================================================
# MembershipPlan
# ===========================================================================
@app.route("/membership-plans", methods=["POST"])
def create_plan():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager"})
    data = body()
    require_fields(data, ["tier_code", "monthly_fee_cents"])
    tier_code = data["tier_code"]
    if tier_code not in TIER_CODES:
        raise err(errors.ERR_INVALID_REQUEST, "tier_code out of range")
    monthly_fee = as_int(data["monthly_fee_cents"], "monthly_fee_cents")
    if monthly_fee < 0:
        raise err(errors.ERR_INVALID_REQUEST, "monthly_fee_cents must be >= 0")
    # tier_code unique across plans
    for p in store.membership_plans.values():
        if p["tier_code"] == tier_code:
            raise err(errors.ERR_INVALID_REQUEST, "tier_code must be unique")

    retail_discount = data.get("retail_discount_pct", 0)
    if retail_discount is None:
        retail_discount = 0
    if not isinstance(retail_discount, (int, float)) or isinstance(retail_discount, bool):
        raise err(errors.ERR_INVALID_REQUEST, "retail_discount_pct must be a number")
    if retail_discount < 0 or retail_discount > 0.5:
        raise err(errors.ERR_INVALID_REQUEST, "retail_discount_pct must be between 0 and 0.5")

    weekly_cap = data.get("weekly_uv_session_cap", 0)
    if weekly_cap is None:
        weekly_cap = 0
    weekly_cap = as_int(weekly_cap, "weekly_uv_session_cap")
    if weekly_cap < 0:
        raise err(errors.ERR_INVALID_REQUEST, "weekly_uv_session_cap must be >= 0")

    includes_spray = data.get("includes_spray", True)
    if includes_spray is None:
        includes_spray = True
    if not isinstance(includes_spray, bool):
        raise err(errors.ERR_INVALID_REQUEST, "includes_spray must be a boolean")

    plan = {
        "tier_code": tier_code,
        "monthly_fee_cents": monthly_fee,
        "retail_discount_pct": retail_discount,
        "weekly_uv_session_cap": weekly_cap,
        "includes_spray": includes_spray,
    }
    _stamp_create_writeonce(plan)
    store.membership_plans[plan["id"]] = plan
    return resp.object_response(ser.plan_out(plan), 201)


@app.route("/membership-plans", methods=["GET"])
def list_plans():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    return list_response(list(store.membership_plans.values()), ser.plan_out)


@app.route("/membership-plans/<plan_id>", methods=["GET"])
def get_plan_route(plan_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    plan = get_plan(plan_id)
    return resp.object_response(ser.plan_out(plan))


# ===========================================================================
# Member
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff"})
    data = body()
    require_fields(data, ["full_name", "date_of_birth", "skin_type", "plan_id"])
    if not isinstance(data["full_name"], str) or not data["full_name"].strip():
        raise err(errors.ERR_INVALID_REQUEST, "full_name required")
    dob = parse_iso(data["date_of_birth"])
    if dob is None:
        raise err(errors.ERR_INVALID_REQUEST, "date_of_birth must be a valid datetime")
    if data["skin_type"] not in SKIN_TYPES:
        raise err(errors.ERR_INVALID_REQUEST, "skin_type out of range")
    plan_id = data["plan_id"]
    # plan existence (left-to-right existence ordering; member then plan)
    get_plan(plan_id)

    member = {
        "full_name": data["full_name"],
        "date_of_birth": dob,
        "skin_type": data["skin_type"],
        "plan_id": plan_id,
        "completed_uv_session_count": 0,
        "account_credit_cents": 0,
        "status": "PENDING",
        "billing_status": "CURRENT",
        "cycle_anchor_at": None,
        "frozen_at": None,
        # internal: records the freeze credit issued, for the cancel reversal.
        "_freeze_credit": 0,
    }
    _stamp_create_audited(member)
    store.members[member["id"]] = member
    return resp.object_response(ser.member_out(member), 201)


@app.route("/members", methods=["GET"])
def list_members():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff"})
    members = list(store.members.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        members = [m for m in members if m["plan_id"] == plan_id]
    return list_response(members, ser.member_out)


@app.route("/members/<member_id>", methods=["GET"])
def get_member_route(member_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    # Member-ownership is an authorization check (§2.8 priority 2) and runs
    # before existence (priority 3).
    auth.require_self(role, uid, member_id)
    member = get_member(member_id)
    return resp.object_response(ser.member_out(member))


def _completed_uv_count(member_id):
    return sum(
        1 for s in store.sessions.values()
        if s["member_id"] == member_id and s["kind"] == "UV" and s["status"] == "COMPLETED"
    )


def _has_open_session(member_id):
    return any(
        s["member_id"] == member_id and s["status"] in ("RESERVED", "IN_PROGRESS")
        for s in store.sessions.values()
    )


@app.route("/members/<member_id>/activate", methods=["POST"])
def activate_member(member_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"BillingSystem"})
    member = get_member(member_id)
    # state: must be PENDING to be activated (state-machine precondition).
    if member["status"] != "PENDING":
        raise err(errors.ERR_MEMBER_NOT_ACTIVE, "Member is not PENDING")
    # precondition: SUCCEEDED EFT_DUES Payment exists for the first cycle
    has_dues = any(
        p["member_id"] == member_id and p["kind"] == "EFT_DUES" and p["outcome"] == "SUCCEEDED"
        for p in store.payments.values()
    )
    if not has_dues:
        raise err(errors.ERR_DUES_NOT_PAID, "First dues not paid")
    # precondition: plan resolves
    get_plan(member["plan_id"])

    member["status"] = "ACTIVE"
    member["billing_status"] = "CURRENT"
    member["cycle_anchor_at"] = clock.now()
    touch(member)
    return resp.object_response(ser.member_out(member))


def _check_member_version(member, data):
    require_fields(data, ["expected_member_version"])
    expected = data["expected_member_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(errors.ERR_INVALID_REQUEST, "expected_member_version must be an integer")
    if expected != member["version"]:
        raise err(errors.ERR_STALE_MEMBER_VERSION, "Stale member version")


@app.route("/members/<member_id>/freeze", methods=["POST"])
def freeze_member(member_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"Member"})
    auth.require_self(role, uid, member_id)
    member = get_member(member_id)
    data = body()
    # state precondition before OCC (state precedence per §2.8 priority 5)
    if member["status"] != "ACTIVE":
        raise err(errors.ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")
    if _has_open_session(member_id):
        raise err(errors.ERR_OPEN_SESSION_EXISTS, "Open session exists")
    _check_member_version(member, data)

    plan = get_plan(member["plan_id"])
    credit = calc.freeze_proration_credit(plan["monthly_fee_cents"], member["cycle_anchor_at"], clock.now())
    member["frozen_at"] = clock.now()
    member["account_credit_cents"] += credit
    member["_freeze_credit"] = credit
    member["status"] = "FROZEN"
    touch(member)

    ledger = get_or_create_ledger()
    ledger["deferred_revenue_cents"] += credit
    touch(ledger)
    return resp.object_response(ser.member_out(member))


@app.route("/members/<member_id>/unfreeze", methods=["POST"])
def unfreeze_member(member_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"Member"})
    auth.require_self(role, uid, member_id)
    member = get_member(member_id)
    data = body()
    if member["status"] != "FROZEN":
        raise err(errors.ERR_MEMBER_NOT_FROZEN, "Member is not FROZEN")
    _check_member_version(member, data)

    frozen_duration = clock.now() - member["frozen_at"]
    member["cycle_anchor_at"] = member["cycle_anchor_at"] + frozen_duration
    member["frozen_at"] = None
    member["status"] = "ACTIVE"
    touch(member)
    return resp.object_response(ser.member_out(member))


@app.route("/members/<member_id>/upgrade", methods=["POST"])
def upgrade_member(member_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"Member"})
    auth.require_self(role, uid, member_id)
    member = get_member(member_id)
    data = body()
    require_fields(data, ["new_plan_id", "expected_member_version"])
    new_plan = get_plan(data["new_plan_id"])
    if member["status"] != "ACTIVE":
        raise err(errors.ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")
    _check_member_version(member, data)

    current_plan = get_plan(member["plan_id"])
    if new_plan["monthly_fee_cents"] <= current_plan["monthly_fee_cents"]:
        raise err(errors.ERR_NOT_AN_UPGRADE, "Target plan fee not greater than current")

    charge = calc.upgrade_proration_charge(
        current_plan["monthly_fee_cents"], new_plan["monthly_fee_cents"],
        member["cycle_anchor_at"], clock.now(),
    )
    outcome = store.upgrade_outcomes.pop(member_id, "SUCCEEDED")

    payment = {
        "member_id": member_id,
        "kind": "UPGRADE",
        "amount_cents": charge,
        "outcome": outcome,
        "retail_order_id": None,
    }
    _stamp_create_writeonce(payment)
    store.payments[payment["id"]] = payment

    if outcome == "SUCCEEDED":
        member["plan_id"] = new_plan["id"]
    touch(member)
    return resp.object_response(ser.member_out(member))


@app.route("/members/<member_id>/cancel", methods=["POST"])
def cancel_member(member_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"Member"})
    auth.require_self(role, uid, member_id)
    member = get_member(member_id)
    data = body()
    if member["status"] not in ("PENDING", "ACTIVE", "FROZEN"):
        raise err(errors.ERR_MEMBER_ALREADY_CANCELLED, "Member already CANCELLED")
    if _has_open_session(member_id):
        raise err(errors.ERR_OPEN_SESSION_EXISTS, "Open session exists")
    _check_member_version(member, data)

    if member["status"] == "FROZEN":
        credit = member["_freeze_credit"]
        member["account_credit_cents"] -= credit
        ledger = get_or_create_ledger()
        ledger["deferred_revenue_cents"] -= credit
        touch(ledger)

    member["status"] = "CANCELLED"
    touch(member)
    return resp.object_response(ser.member_out(member))


# ===========================================================================
# ConsentRecord
# ===========================================================================
@app.route("/members/<member_id>/consents", methods=["POST"])
def create_consent(member_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff"})
    get_member(member_id)
    data = body()
    require_fields(data, ["guardian_name", "expires_at"])
    if not isinstance(data["guardian_name"], str) or not data["guardian_name"].strip():
        raise err(errors.ERR_INVALID_REQUEST, "guardian_name required")
    expires_at = parse_iso(data["expires_at"])
    if expires_at is None:
        raise err(errors.ERR_INVALID_REQUEST, "expires_at must be a valid datetime")

    consent = {
        "member_id": member_id,
        "guardian_name": data["guardian_name"],
        "expires_at": expires_at,
    }
    _stamp_create_writeonce(consent)
    store.consents[consent["id"]] = consent
    return resp.object_response(ser.consent_out(consent), 201)


@app.route("/members/<member_id>/consents", methods=["GET"])
def list_consents(member_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    auth.require_self(role, uid, member_id)
    get_member(member_id)
    records = [c for c in store.consents.values() if c["member_id"] == member_id]
    return list_response(records, ser.consent_out)


# ===========================================================================
# Equipment
# ===========================================================================
@app.route("/equipment", methods=["POST"])
def create_equipment():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager"})
    data = body()
    require_fields(data, ["name", "kind", "max_exposure_seconds"])
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise err(errors.ERR_INVALID_REQUEST, "name required")
    if data["kind"] not in EQUIP_KINDS:
        raise err(errors.ERR_INVALID_REQUEST, "kind out of range")
    max_exp = as_int(data["max_exposure_seconds"], "max_exposure_seconds")
    if max_exp < 1:
        raise err(errors.ERR_INVALID_REQUEST, "max_exposure_seconds must be >= 1")
    turnaround = data.get("turnaround_seconds", 600)
    if turnaround is None:
        turnaround = 600
    turnaround = as_int(turnaround, "turnaround_seconds")
    if turnaround < 0:
        raise err(errors.ERR_INVALID_REQUEST, "turnaround_seconds must be >= 0")

    eq = {
        "name": data["name"],
        "kind": data["kind"],
        "max_exposure_seconds": max_exp,
        "turnaround_seconds": turnaround,
        "status": "AVAILABLE",
        "sessions_since_service": 0,
    }
    _stamp_create_audited(eq)
    store.equipment[eq["id"]] = eq
    return resp.object_response(ser.equipment_out(eq), 201)


@app.route("/equipment", methods=["GET"])
def list_equipment():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    return list_response(list(store.equipment.values()), ser.equipment_out)


@app.route("/equipment/<equipment_id>", methods=["GET"])
def get_equipment_route(equipment_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    eq = get_equipment(equipment_id)
    return resp.object_response(ser.equipment_out(eq))


@app.route("/equipment/<equipment_id>/service", methods=["POST"])
def service_equipment(equipment_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager"})
    eq = get_equipment(equipment_id)
    data = body()
    require_fields(data, ["reason"])
    if data["reason"] not in SERVICE_REASONS:
        raise err(errors.ERR_INVALID_REQUEST, "reason out of range")
    if eq["status"] != "MAINTENANCE":
        raise err(errors.ERR_EQUIPMENT_NOT_IN_MAINTENANCE, "Equipment is not in MAINTENANCE")

    sessions_at_service = eq["sessions_since_service"]
    log = {
        "equipment_id": equipment_id,
        "reason": data["reason"],
        "sessions_at_service": sessions_at_service,
    }
    _stamp_create_writeonce(log)
    store.maintenance_logs[log["id"]] = log

    eq["sessions_since_service"] = 0
    eq["status"] = "AVAILABLE"
    touch(eq)
    return resp.object_response(ser.equipment_out(eq))


@app.route("/equipment/<equipment_id>/retire", methods=["POST"])
def retire_equipment(equipment_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager"})
    eq = get_equipment(equipment_id)
    if eq["status"] not in ("AVAILABLE", "MAINTENANCE"):
        raise err(errors.ERR_EQUIPMENT_IN_USE, "Equipment cannot be retired in its current state")
    eq["status"] = "RETIRED"
    touch(eq)
    return resp.object_response(ser.equipment_out(eq))


@app.route("/equipment/<equipment_id>/maintenance-logs", methods=["GET"])
def list_maintenance_logs(equipment_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff"})
    get_equipment(equipment_id)
    records = [m for m in store.maintenance_logs.values() if m["equipment_id"] == equipment_id]
    return list_response(records, ser.maintenance_log_out)


# ===========================================================================
# SprayRoom
# ===========================================================================
@app.route("/spray-rooms", methods=["POST"])
def create_spray_room():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager"})
    data = body()
    require_fields(data, ["name"])
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise err(errors.ERR_INVALID_REQUEST, "name required")
    vent = data.get("ventilation_buffer_seconds", 300)
    if vent is None:
        vent = 300
    vent = as_int(vent, "ventilation_buffer_seconds")
    if vent < 0:
        raise err(errors.ERR_INVALID_REQUEST, "ventilation_buffer_seconds must be >= 0")

    room = {
        "name": data["name"],
        "ventilation_buffer_seconds": vent,
        "status": "AVAILABLE",
    }
    _stamp_create_audited(room)
    store.spray_rooms[room["id"]] = room
    return resp.object_response(ser.spray_room_out(room), 201)


@app.route("/spray-rooms", methods=["GET"])
def list_spray_rooms():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    return list_response(list(store.spray_rooms.values()), ser.spray_room_out)


@app.route("/spray-rooms/<room_id>", methods=["GET"])
def get_spray_room_route(room_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    room = get_room(room_id)
    return resp.object_response(ser.spray_room_out(room))


# ===========================================================================
# Session
# ===========================================================================
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


def _uv_week_count(member_id, week_start, week_end):
    n = 0
    for s in store.sessions.values():
        if s["member_id"] != member_id or s["kind"] != "UV":
            continue
        if s["status"] not in ("RESERVED", "IN_PROGRESS", "COMPLETED"):
            continue
        if week_start <= s["start_at"] < week_end:
            n += 1
    return n


def _latest_prior_uv(member_id):
    """Latest UV session in IN_PROGRESS/COMPLETED by start_at, tie created_at ASC."""
    candidates = [
        s for s in store.sessions.values()
        if s["member_id"] == member_id and s["kind"] == "UV"
        and s["status"] in ("IN_PROGRESS", "COMPLETED")
    ]
    if not candidates:
        return None
    # greatest start_at; on a tie, earliest created_at
    return max(candidates, key=lambda s: (s["start_at"], -s["_seq"]))


@app.route("/sessions", methods=["POST"])
def create_session():
    uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff", "Member"})
    data = body()
    # required fields
    require_fields(data, ["member_id", "kind", "booking_mode", "start_at", "requested_seconds"])
    member_id = data["member_id"]
    # Member ownership for Member role applies to the booking member_id (§2.1)
    auth.require_self(role, uid, member_id)
    # existence: member first (left-to-right §2.7)
    member = get_member(member_id)

    kind = data["kind"]
    booking_mode = data["booking_mode"]
    # shape validation (priority 4) — enums in range
    if kind not in SESSION_KINDS:
        raise err(errors.ERR_INVALID_REQUEST, "kind out of range")
    if booking_mode not in BOOKING_MODES:
        raise err(errors.ERR_INVALID_REQUEST, "booking_mode out of range")
    start_at = parse_iso(data["start_at"])
    if start_at is None:
        raise err(errors.ERR_INVALID_REQUEST, "start_at must be a valid datetime")
    requested_seconds = data["requested_seconds"]
    if isinstance(requested_seconds, bool) or not isinstance(requested_seconds, int):
        raise err(errors.ERR_INVALID_REQUEST, "requested_seconds must be an integer")
    if requested_seconds < 1:
        raise err(errors.ERR_INVALID_REQUEST, "requested_seconds must be >= 1")

    equipment_id = data.get("equipment_id")
    spray_room_id = data.get("spray_room_id")

    # UV/SPRAY consistency (priority 4). Resolve referenced unit existence
    # before deeper validation, but only after shape consistency is satisfied.
    if kind == "UV":
        if not equipment_id or spray_room_id:
            raise err(errors.ERR_INVALID_REQUEST, "UV requires equipment_id and no spray_room_id")
    else:  # SPRAY
        if not spray_room_id or equipment_id:
            raise err(errors.ERR_INVALID_REQUEST, "SPRAY requires spray_room_id and no equipment_id")

    # existence of the referenced unit
    equipment = None
    room = None
    if kind == "UV":
        equipment = get_equipment(equipment_id)
    else:
        room = get_room(spray_room_id)

    # priority 6: booking eligibility (member ACTIVE and not SUSPENDED)
    if member["status"] != "ACTIVE" or member["billing_status"] == "SUSPENDED":
        raise err(errors.ERR_MEMBER_NOT_BOOKABLE, "Member is not bookable")

    end_at = start_at + timedelta(seconds=requested_seconds)
    allowed_seconds = None

    if kind == "UV":
        # priority 7: skin type I prohibited
        if member["skin_type"] == "I":
            raise err(errors.ERR_SKIN_TYPE_UV_PROHIBITED, "Skin type I cannot use UV")

        is_minor = ser._is_minor(member)
        week_start, week_end = calc.iso_week_bounds(start_at)

        # priority 8: minor consent
        if is_minor:
            now = clock.now()
            has_consent = any(
                c["member_id"] == member_id and now < c["expires_at"]
                for c in store.consents.values()
            )
            if not has_consent:
                raise err(errors.ERR_MINOR_CONSENT_REQUIRED, "Minor consent required")

        # priority 9: minor frequency
        if is_minor:
            week_count = _uv_week_count(member_id, week_start, week_end)
            if week_count >= calc.MINOR_WEEKLY_UV_CAP:
                raise err(errors.ERR_MINOR_FREQUENCY_EXCEEDED, "Minor weekly UV cap exceeded")
        else:
            # priority 12: adult plan frequency cap (checked after cooldown/dose
            # per §3.4 order: ... adult frequency, cooldown, dose ...).
            pass

        # NOTE on ordering (§3.4): skin, minor consent, minor frequency, adult
        # frequency, cool-down, dose ceiling, slot conflict.
        plan = get_plan(member["plan_id"])
        if not is_minor:
            cap = plan["weekly_uv_session_cap"]
            if cap != 0:
                week_count = _uv_week_count(member_id, week_start, week_end)
                if week_count >= cap:
                    raise err(errors.ERR_FREQUENCY_CAP_EXCEEDED, "Plan weekly UV cap exceeded")

        # priority 10: cooldown >= 24h since last IN_PROGRESS/COMPLETED UV start_at
        last = _latest_prior_uv(member_id)
        if last is not None:
            gap = (start_at - last["start_at"]).total_seconds()
            if gap < calc.COOLDOWN_SECONDS:
                raise err(errors.ERR_UV_COOLDOWN_NOT_ELAPSED, "UV cooldown not elapsed")

        # priority 11: dose ceiling (reservation estimate)
        completed = _completed_uv_count(member_id)
        allowed_seconds = calc.uv_dose_allowed_seconds(
            member["skin_type"], completed, equipment["max_exposure_seconds"]
        )
        if requested_seconds > allowed_seconds:
            raise err(errors.ERR_DOSE_EXCEEDS_LIMIT, "Requested seconds exceed dose limit")

        # priority 13: equipment slot conflict (interval + turnaround buffer)
        buffer = equipment["turnaround_seconds"]
        new_end_with_buffer = end_at + timedelta(seconds=buffer)
        for s in store.sessions.values():
            if s["equipment_id"] != equipment_id or s["status"] not in ("RESERVED", "IN_PROGRESS"):
                continue
            existing_end_with_buffer = s["end_at"] + timedelta(seconds=equipment["turnaround_seconds"])
            if _intervals_overlap(start_at, new_end_with_buffer, s["start_at"], existing_end_with_buffer):
                raise err(errors.ERR_EQUIPMENT_SLOT_CONFLICT, "Equipment slot conflict")
    else:
        # priority 14: spray room slot conflict (interval + ventilation buffer)
        new_end_with_buffer = end_at + timedelta(seconds=room["ventilation_buffer_seconds"])
        for s in store.sessions.values():
            if s["spray_room_id"] != spray_room_id or s["status"] not in ("RESERVED", "IN_PROGRESS"):
                continue
            existing_end_with_buffer = s["end_at"] + timedelta(seconds=room["ventilation_buffer_seconds"])
            if _intervals_overlap(start_at, new_end_with_buffer, s["start_at"], existing_end_with_buffer):
                raise err(errors.ERR_ROOM_SLOT_CONFLICT, "Spray room slot conflict")

    session = {
        "member_id": member_id,
        "kind": kind,
        "booking_mode": booking_mode,
        "equipment_id": equipment_id if kind == "UV" else None,
        "spray_room_id": spray_room_id if kind == "SPRAY" else None,
        "start_at": start_at,
        "requested_seconds": requested_seconds,
        "end_at": end_at,
        "allowed_seconds": allowed_seconds,
        "status": "RESERVED",
    }
    _stamp_create_audited(session)
    store.sessions[session["id"]] = session
    return resp.object_response(ser.session_out(session), 201)


@app.route("/sessions", methods=["GET"])
def list_sessions():
    uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    sessions = list(store.sessions.values())
    member_id = request.args.get("member_id")
    equipment_id = request.args.get("equipment_id")
    spray_room_id = request.args.get("spray_room_id")
    if role == "Member":
        # Member may only see its own sessions.
        sessions = [s for s in sessions if s["member_id"] == uid]
    if member_id is not None:
        sessions = [s for s in sessions if s["member_id"] == member_id]
    if equipment_id is not None:
        sessions = [s for s in sessions if s["equipment_id"] == equipment_id]
    if spray_room_id is not None:
        sessions = [s for s in sessions if s["spray_room_id"] == spray_room_id]
    return list_response(sessions, ser.session_out)


@app.route("/sessions/<session_id>", methods=["GET"])
def get_session_route(session_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    s = get_session(session_id)
    if role == "Member" and s["member_id"] != uid:
        raise err(errors.ERR_FORBIDDEN, "Member may only view its own sessions")
    return resp.object_response(ser.session_out(s))


@app.route("/sessions/<session_id>/start", methods=["POST"])
def start_session(session_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff"})
    s = get_session(session_id)
    if s["status"] != "RESERVED":
        raise err(errors.ERR_SESSION_NOT_RESERVED, "Session is not RESERVED")
    if s["kind"] == "UV":
        eq = get_equipment(s["equipment_id"])
        if eq["status"] != "AVAILABLE":
            raise err(errors.ERR_EQUIPMENT_UNAVAILABLE, "Equipment is not AVAILABLE")
        # Dose re-check at start (PRD §3.8): the dose CHECK is re-evaluated with
        # completed_uv_session_count as-of the start instant. Because intervening
        # sessions may have completed, the actual escalated allowance is >= the
        # reservation-time estimate, so a borderline reservation stays valid. The
        # persisted session.allowed_seconds is the reservation-time value (PRD §3.4
        # populates it at creation; nothing at start overwrites it).
        member = get_member(s["member_id"])
        completed = _completed_uv_count(s["member_id"])
        allowed = calc.uv_dose_allowed_seconds(member["skin_type"], completed, eq["max_exposure_seconds"])
        if s["requested_seconds"] > allowed:
            raise err(errors.ERR_DOSE_EXCEEDS_LIMIT, "Requested seconds exceed dose limit at start")
        eq["status"] = "IN_USE"
        touch(eq)
    else:
        room = get_room(s["spray_room_id"])
        if room["status"] != "AVAILABLE":
            raise err(errors.ERR_ROOM_UNAVAILABLE, "Room is not AVAILABLE")
        room["status"] = "IN_USE"
        touch(room)

    s["status"] = "IN_PROGRESS"
    touch(s)
    return resp.object_response(ser.session_out(s))


@app.route("/sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff"})
    s = get_session(session_id)
    if s["status"] != "IN_PROGRESS":
        raise err(errors.ERR_SESSION_NOT_IN_PROGRESS, "Session is not IN_PROGRESS")

    if s["kind"] == "UV":
        eq = get_equipment(s["equipment_id"])
        member = get_member(s["member_id"])
        eq["sessions_since_service"] += 1
        member["completed_uv_session_count"] += 1
        # threshold trip overrides the AVAILABLE set (PRD §3.7 / §3.8)
        if eq["sessions_since_service"] >= calc.SERVICE_THRESHOLD:
            eq["status"] = "MAINTENANCE"
        else:
            eq["status"] = "AVAILABLE"
        touch(eq)
        touch(member)
    else:
        room = get_room(s["spray_room_id"])
        room["status"] = "AVAILABLE"
        touch(room)

    s["status"] = "COMPLETED"
    touch(s)
    return resp.object_response(ser.session_out(s))


@app.route("/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff", "Member"})
    s = get_session(session_id)
    if role == "Member" and s["member_id"] != uid:
        raise err(errors.ERR_FORBIDDEN, "Member may only cancel its own sessions")
    if s["status"] != "RESERVED":
        raise err(errors.ERR_SESSION_NOT_RESERVED, "Session is not RESERVED")
    s["status"] = "CANCELLED"
    touch(s)
    return resp.object_response(ser.session_out(s))


@app.route("/sessions/<session_id>/no-show", methods=["POST"])
def no_show_session(session_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff"})
    s = get_session(session_id)
    if s["status"] != "RESERVED":
        raise err(errors.ERR_SESSION_NOT_RESERVED, "Session is not RESERVED")
    if clock.now() < s["start_at"]:
        raise err(errors.ERR_TOO_EARLY_FOR_NO_SHOW, "Too early for no-show")
    s["status"] = "NO_SHOW"
    touch(s)
    return resp.object_response(ser.session_out(s))


# ===========================================================================
# Product
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager"})
    data = body()
    require_fields(data, ["sku", "name", "unit_price_cents", "initial_stock"])
    if not isinstance(data["sku"], str) or not data["sku"].strip():
        raise err(errors.ERR_INVALID_REQUEST, "sku required")
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise err(errors.ERR_INVALID_REQUEST, "name required")
    unit_price = as_int(data["unit_price_cents"], "unit_price_cents")
    if unit_price < 0:
        raise err(errors.ERR_INVALID_REQUEST, "unit_price_cents must be >= 0")
    initial_stock = as_int(data["initial_stock"], "initial_stock")
    if initial_stock < 0:
        raise err(errors.ERR_INVALID_REQUEST, "initial_stock must be >= 0")
    for p in store.products.values():
        if p["sku"] == data["sku"]:
            raise err(errors.ERR_INVALID_REQUEST, "sku must be unique")

    product = {
        "sku": data["sku"],
        "name": data["name"],
        "unit_price_cents": unit_price,
        "initial_stock": initial_stock,
        "stock_on_hand": initial_stock,
        "units_sold": 0,
    }
    _stamp_create_audited(product)
    store.products[product["id"]] = product
    return resp.object_response(ser.product_out(product), 201)


@app.route("/products", methods=["GET"])
def list_products():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    return list_response(list(store.products.values()), ser.product_out)


@app.route("/products/<product_id>", methods=["GET"])
def get_product_route(product_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    p = get_product(product_id)
    return resp.object_response(ser.product_out(p))


# ===========================================================================
# RetailOrder
# ===========================================================================
@app.route("/retail-orders", methods=["POST"])
def create_retail_order():
    uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff", "Member"})
    data = body()
    require_fields(data, ["member_id", "lines"])
    member_id = data["member_id"]
    auth.require_self(role, uid, member_id)
    member = get_member(member_id)

    lines = data["lines"]
    if not isinstance(lines, list) or len(lines) == 0:
        raise err(errors.ERR_INVALID_REQUEST, "lines must be a non-empty array")
    parsed_lines = []
    for ln in lines:
        if not isinstance(ln, dict) or "product_id" not in ln or "quantity" not in ln:
            raise err(errors.ERR_INVALID_REQUEST, "each line needs product_id and quantity")
        qty = ln["quantity"]
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise err(errors.ERR_INVALID_REQUEST, "quantity must be an integer >= 1")
        parsed_lines.append({"product_id": ln["product_id"], "quantity": qty})

    # existence: each line product (§2.7 — product reference yields PRODUCT_NOT_FOUND)
    products_in_order = []
    for ln in parsed_lines:
        products_in_order.append(get_product(ln["product_id"]))

    # discount sourced from member's plan; 0 if member has no plan
    disc = 0
    if member["plan_id"]:
        plan = store.membership_plans.get(member["plan_id"])
        if plan is not None:
            disc = plan["retail_discount_pct"]

    # per-line discount + round, then sum (PRD §3.8)
    subtotal = 0
    for ln, product in zip(parsed_lines, products_in_order):
        subtotal += line_total(product["unit_price_cents"], ln["quantity"], disc)

    credit_applied = min(member["account_credit_cents"], subtotal)
    charged = subtotal - credit_applied

    order = {
        "member_id": member_id,
        "lines": parsed_lines,
        "subtotal_cents": subtotal,
        "credit_applied_cents": credit_applied,
        "charged_cents": charged,
        "status": "PAID",
    }
    _stamp_create_audited(order)
    store.retail_orders[order["id"]] = order

    # side effects: stock down, units_sold up
    for ln, product in zip(parsed_lines, products_in_order):
        product["stock_on_hand"] -= ln["quantity"]
        product["units_sold"] += ln["quantity"]
        touch(product)

    # member credit drawn down
    member["account_credit_cents"] -= credit_applied
    touch(member)

    # ledger: collected_retail rises by charged; deferred falls by credit drawn
    ledger = get_or_create_ledger()
    ledger["collected_retail_cents"] += charged
    ledger["deferred_revenue_cents"] -= credit_applied
    touch(ledger)

    # record a RETAIL Payment for the charged amount (audit trail §3.10)
    payment = {
        "member_id": member_id,
        "kind": "RETAIL",
        "amount_cents": charged,
        "outcome": "SUCCEEDED",
        "retail_order_id": order["id"],
    }
    _stamp_create_writeonce(payment)
    store.payments[payment["id"]] = payment

    return resp.object_response(ser.retail_order_out(order), 201)


@app.route("/retail-orders", methods=["GET"])
def list_retail_orders():
    uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    orders = list(store.retail_orders.values())
    if role == "Member":
        orders = [o for o in orders if o["member_id"] == uid]
    member_id = request.args.get("member_id")
    if member_id is not None:
        orders = [o for o in orders if o["member_id"] == member_id]
    return list_response(orders, ser.retail_order_out)


@app.route("/retail-orders/<order_id>", methods=["GET"])
def get_retail_order_route(order_id):
    uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "Member"})
    o = get_order(order_id)
    if role == "Member" and o["member_id"] != uid:
        raise err(errors.ERR_FORBIDDEN, "Member may only view its own orders")
    return resp.object_response(ser.retail_order_out(o))


@app.route("/retail-orders/<order_id>/refund", methods=["POST"])
def refund_retail_order(order_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"FrontDeskStaff"})
    o = get_order(order_id)
    if o["status"] != "PAID":
        raise err(errors.ERR_ORDER_ALREADY_REFUNDED, "Order is not PAID")

    # compensating reversal: restore stock
    for ln in o["lines"]:
        product = store.products.get(ln["product_id"])
        if product is not None:
            product["stock_on_hand"] += ln["quantity"]
            product["units_sold"] -= ln["quantity"]
            touch(product)

    member = store.members.get(o["member_id"])
    if member is not None:
        member["account_credit_cents"] += o["credit_applied_cents"]
        touch(member)

    ledger = get_or_create_ledger()
    ledger["collected_retail_cents"] -= o["charged_cents"]
    ledger["deferred_revenue_cents"] += o["credit_applied_cents"]
    touch(ledger)

    o["status"] = "REFUNDED"
    touch(o)
    return resp.object_response(ser.retail_order_out(o))


# ===========================================================================
# Payment
# ===========================================================================
@app.route("/payments", methods=["GET"])
def list_payments():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "BillingSystem"})
    payments = list(store.payments.values())
    member_id = request.args.get("member_id")
    retail_order_id = request.args.get("retail_order_id")
    if member_id is not None:
        payments = [p for p in payments if p["member_id"] == member_id]
    if retail_order_id is not None:
        payments = [p for p in payments if p["retail_order_id"] == retail_order_id]
    return list_response(payments, ser.payment_out)


@app.route("/payments/<payment_id>", methods=["GET"])
def get_payment_route(payment_id):
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "FrontDeskStaff", "BillingSystem"})
    p = store.payments.get(payment_id)
    if p is None:
        # No dedicated payment-not-found error in the catalog; use generic 404.
        return resp.error_response("ERR_NOT_FOUND", "Payment not found", 404)
    return resp.object_response(ser.payment_out(p))


# ===========================================================================
# SalonLedger
# ===========================================================================
@app.route("/salon-ledger", methods=["GET"])
def get_salon_ledger():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager"})
    ledger = get_or_create_ledger()
    return resp.object_response(ser.ledger_out(ledger))


# ===========================================================================
# Test-driving endpoints (/_ namespace)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"SalonManager", "BillingSystem"})
    data = body()
    require_fields(data, ["to_iso8601"])
    dt = parse_iso(data["to_iso8601"])
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid datetime")
    clock.set(dt)
    from timeutil import to_iso
    return resp.object_response({"now": to_iso(clock.now())})


@app.route("/_billing/charge-first-dues", methods=["POST"])
def charge_first_dues():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"BillingSystem"})
    data = body()
    require_fields(data, ["member_id", "outcome"])
    member = get_member(data["member_id"])
    outcome = data["outcome"]
    if outcome not in OUTCOMES:
        raise err(errors.ERR_INVALID_REQUEST, "outcome out of range")
    plan = get_plan(member["plan_id"])

    payment = {
        "member_id": member["id"],
        "kind": "EFT_DUES",
        "amount_cents": plan["monthly_fee_cents"],
        "outcome": outcome,
        "retail_order_id": None,
    }
    _stamp_create_writeonce(payment)
    store.payments[payment["id"]] = payment

    if outcome == "SUCCEEDED":
        ledger = get_or_create_ledger()
        ledger["collected_dues_cents"] += plan["monthly_fee_cents"]
        touch(ledger)

    return resp.object_response(ser.payment_out(payment), 201)


@app.route("/_billing/run-eft", methods=["POST"])
def run_eft():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"BillingSystem"})
    data = body()
    require_fields(data, ["member_id", "outcome"])
    member = get_member(data["member_id"])
    outcome = data["outcome"]
    if outcome not in OUTCOMES:
        raise err(errors.ERR_INVALID_REQUEST, "outcome out of range")
    plan = get_plan(member["plan_id"])
    now = clock.now()

    # A run is permitted only while ACTIVE (frozen/other are skipped).
    if member["status"] != "ACTIVE":
        raise err(errors.ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")

    cycle_due_at = member["cycle_anchor_at"] + timedelta(days=30)
    grace_at = member["cycle_anchor_at"] + timedelta(days=37)

    billing = member["billing_status"]

    if billing == "CURRENT":
        # Normal due-date run requires the cycle to be due.
        if now < cycle_due_at:
            raise err(errors.ERR_CYCLE_NOT_DUE, "Cycle not yet due")
        payment = {
            "member_id": member["id"],
            "kind": "EFT_DUES",
            "amount_cents": plan["monthly_fee_cents"],
            "outcome": outcome,
            "retail_order_id": None,
        }
        _stamp_create_writeonce(payment)
        store.payments[payment["id"]] = payment
        if outcome == "SUCCEEDED":
            member["cycle_anchor_at"] = member["cycle_anchor_at"] + timedelta(days=30)
            touch(member)
            ledger = get_or_create_ledger()
            ledger["collected_dues_cents"] += plan["monthly_fee_cents"]
            touch(ledger)
        else:
            # DECLINED: CURRENT -> PAST_DUE, cycle_anchor_at not advanced
            member["billing_status"] = "PAST_DUE"
            touch(member)
        return resp.object_response(ser.member_out(member))

    if billing == "PAST_DUE":
        # Grace lapse -> SUSPENDED (no payment) takes precedence when elapsed.
        if now >= grace_at:
            member["billing_status"] = "SUSPENDED"
            touch(member)
            return resp.object_response(ser.member_out(member))
        # Otherwise a retry: SUCCEEDED -> CURRENT (advance), DECLINED stays PAST_DUE.
        payment = {
            "member_id": member["id"],
            "kind": "EFT_DUES",
            "amount_cents": plan["monthly_fee_cents"],
            "outcome": outcome,
            "retail_order_id": None,
        }
        _stamp_create_writeonce(payment)
        store.payments[payment["id"]] = payment
        if outcome == "SUCCEEDED":
            member["billing_status"] = "CURRENT"
            member["cycle_anchor_at"] = member["cycle_anchor_at"] + timedelta(days=30)
            touch(member)
            ledger = get_or_create_ledger()
            ledger["collected_dues_cents"] += plan["monthly_fee_cents"]
            touch(ledger)
        else:
            touch(member)
        return resp.object_response(ser.member_out(member))

    # SUSPENDED: not a billing-advance source here.
    raise err(errors.ERR_NOT_PAST_DUE, "Member is not in a billable billing state")


@app.route("/_billing/set-upgrade-outcome", methods=["POST"])
def set_upgrade_outcome():
    _uid, role = auth.get_principal()
    auth.require_role(role, {"BillingSystem"})
    data = body()
    require_fields(data, ["member_id", "outcome"])
    member = get_member(data["member_id"])
    outcome = data["outcome"]
    if outcome not in OUTCOMES:
        raise err(errors.ERR_INVALID_REQUEST, "outcome out of range")
    store.upgrade_outcomes[member["id"]] = outcome
    return resp.object_response({"member_id": member["id"], "outcome": outcome})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
