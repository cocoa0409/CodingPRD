"""Climbing Gym Belay API — Flask entry point and all route handlers."""
import os
from datetime import timedelta

from flask import Flask, request

import calc
import models
from cascades import (
    auto_check_out_member,
    serious_incident_cascade,
    withdraw_member_enrollments,
)
from clock import clock, parse_iso8601, to_iso_z
from db import db
from errors import ApiError, err
from helpers import (
    find_certification,
    find_check_in,
    find_clinic,
    find_enrollment,
    find_facility,
    find_incident,
    find_member,
    find_membership,
    find_rental,
    find_route,
    find_waiver,
    get_body,
    member_active_membership,
    member_has_active_belay_or_lead,
    member_has_passed_belay,
    member_has_valid_waiver,
    paginate,
    parse_pagination,
    recompute_clinic_count,
    recompute_facility_occupancy,
)
from middleware import get_caller, require_role
from response import error_response, list_response, success

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))


# ===========================================================================
# Shared field validators
# ===========================================================================
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return value


def expected_version(body, field):
    """Read and validate an OCC token: required integer."""
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return as_int(body[field], field)


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_caller()
    require_role(role, {"GymAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"])
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    clock.set(dt)
    return success({}, status=200)


# ===========================================================================
# Members
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    body = get_body()
    require_fields(body, ["full_name", "email", "date_of_birth"])
    if not isinstance(body["full_name"], str) or not body["full_name"]:
        raise err("ERR_INVALID_REQUEST", "full_name must be a non-empty string")
    if not isinstance(body["email"], str) or not body["email"]:
        raise err("ERR_INVALID_REQUEST", "email must be a non-empty string")
    dob = parse_iso8601(body["date_of_birth"])
    if dob is None:
        raise err("ERR_INVALID_REQUEST", "date_of_birth must be a valid ISO date")

    email = body["email"]
    for existing in db.members.values():
        if existing["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "Email already registered")

    now = clock.now()
    m = {
        "full_name": body["full_name"],
        "email": email,
        "date_of_birth": dob,
        "date_of_birth_raw": body["date_of_birth"],
        "is_youth": calc.is_youth_at(dob, now),
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
        "version": 1,
    }
    models.stamp_create(m, "Member")
    db.members[m["id"]] = m
    return success(models.serialize_member(m), status=201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    m = find_member(mid)
    return success(models.serialize_member(m), status=200)


@app.route("/members", methods=["GET"])
def list_members():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "GymAdmin"})
    limit, offset = parse_pagination()
    email = request.args.get("email")
    items = [m for m in db.members.values() if email is None or m["email"] == email]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_member(m) for m in page], limit, offset, total)


# ===========================================================================
# Waivers
# ===========================================================================
@app.route("/waivers", methods=["POST"])
def create_waiver():
    uid, role = get_caller()
    require_role(role, {"FrontDesk", "Member"})
    body = get_body()
    require_fields(body, ["member_id"])
    member = find_member(body["member_id"])

    if role == "Member" and uid != member["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only sign their own waiver")

    guardian = body.get("minor_guardian_name")
    if member["is_youth"]:
        if guardian is None or (isinstance(guardian, str) and guardian.strip() == ""):
            raise err("ERR_INVALID_REQUEST", "minor_guardian_name required for youth")
    else:
        if guardian is not None:
            raise err("ERR_INVALID_REQUEST", "minor_guardian_name must be omitted for non-youth")

    now = clock.now()
    # Duplicate valid waiver check
    for w in db.waivers.values():
        if w["member_id"] == member["id"] and now < w["expires_at"]:
            raise err("ERR_DUPLICATE_WAIVER", "Member already holds a VALID waiver")

    w = {
        "member_id": member["id"],
        "signed_at": now,
        "expires_at": now + timedelta(days=calc.WAIVER_VALID_DAYS),
        "minor_guardian_name": guardian if member["is_youth"] else None,
    }
    models.stamp_create(w, "Waiver")
    db.waivers[w["id"]] = w
    return success(models.serialize_waiver(w), status=201)


@app.route("/waivers/<wid>", methods=["GET"])
def get_waiver(wid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    w = find_waiver(wid)
    return success(models.serialize_waiver(w), status=200)


@app.route("/waivers", methods=["GET"])
def list_waivers():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    items = [w for w in db.waivers.values() if member_id is None or w["member_id"] == member_id]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_waiver(w) for w in page], limit, offset, total)


# ===========================================================================
# Memberships
# ===========================================================================
@app.route("/memberships", methods=["POST"])
def create_membership():
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    body = get_body()
    require_fields(body, ["member_id", "plan_tier"])
    member = find_member(body["member_id"])
    plan = body["plan_tier"]
    if plan not in calc.PLAN_FEES:
        raise err("ERR_INVALID_REQUEST", "plan_tier must be BASIC or YOUTH_TEAM")

    now = clock.now()
    m = {
        "member_id": member["id"],
        "plan_tier": plan,
        "monthly_fee_cents": calc.PLAN_FEES[plan],
        "cycle_start": now,
        "cycle_end": now + timedelta(days=calc.CYCLE_DAYS),
        "billing_status": "CURRENT",
        "access_status": "ACTIVE",
        "past_due_since": None,
        "frozen_at": None,
        "version": 1,
    }
    models.stamp_create(m, "Membership")
    db.memberships[m["id"]] = m
    return success(models.serialize_membership(m), status=201)


@app.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    m = find_membership(mid)
    return success(models.serialize_membership(m), status=200)


@app.route("/memberships", methods=["GET"])
def list_memberships():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    items = [m for m in db.memberships.values() if member_id is None or m["member_id"] == member_id]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_membership(m) for m in page], limit, offset, total)


@app.route("/memberships/<mid>/freeze-quote", methods=["GET"])
def freeze_quote(mid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member"})
    m = find_membership(mid)
    if role == "Member":
        _, uid_role = role, None  # noqa
    credit, unused_days = calc.freeze_credit(m["monthly_fee_cents"], clock.now(), m["cycle_end"])
    return success({"freeze_credit_cents": credit, "unused_days": unused_days}, status=200)


def _member_owns(uid, role, member_id):
    if role == "Member" and uid != member_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only act on their own resource")


@app.route("/memberships/<mid>/freeze", methods=["POST"])
def freeze_membership(mid):
    uid, role = get_caller()
    require_role(role, {"Member"})
    m = find_membership(mid)
    _member_owns(uid, role, m["member_id"])
    # state check
    if not (m["access_status"] == "ACTIVE" and m["billing_status"] != "CANCELLED"):
        raise err("ERR_INVALID_STATE", "Membership not freezable")
    body = get_body()
    ev = expected_version(body, "expected_membership_version")
    if ev != m["version"]:
        raise err("ERR_STALE_MEMBERSHIP_VERSION", "Stale membership version")

    credit, _ = calc.freeze_credit(m["monthly_fee_cents"], clock.now(), m["cycle_end"])
    m["access_status"] = "FROZEN"
    m["frozen_at"] = clock.now()
    member = db.members.get(m["member_id"])
    if member is not None:
        member["wallet_credit_cents"] += credit
        member["version"] += 1
        models.touch(member, "Member")
    m["version"] += 1
    models.touch(m, "Membership")
    return success(models.serialize_membership(m), status=200)


@app.route("/memberships/<mid>/resume", methods=["POST"])
def resume_membership(mid):
    uid, role = get_caller()
    require_role(role, {"Member"})
    m = find_membership(mid)
    _member_owns(uid, role, m["member_id"])
    if m["access_status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Membership not frozen")
    body = get_body()
    ev = expected_version(body, "expected_membership_version")
    if ev != m["version"]:
        raise err("ERR_STALE_MEMBERSHIP_VERSION", "Stale membership version")

    now = clock.now()
    m["access_status"] = "ACTIVE"
    m["frozen_at"] = None
    m["cycle_start"] = now
    m["cycle_end"] = now + timedelta(days=calc.CYCLE_DAYS)
    m["version"] += 1
    models.touch(m, "Membership")
    return success(models.serialize_membership(m), status=200)


@app.route("/memberships/<mid>/run-billing", methods=["POST"])
def run_billing(mid):
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    m = find_membership(mid)
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("SUCCEEDED", "FAILED", "SWEEP"):
        raise err("ERR_INVALID_REQUEST", "outcome must be SUCCEEDED, FAILED, or SWEEP")

    now = clock.now()

    if outcome == "FAILED":
        # CURRENT -> PAST_DUE; requires CURRENT and cycle due
        if m["billing_status"] != "CURRENT" or now < m["cycle_end"]:
            raise err("ERR_INVALID_STATE", "FAILED only valid on a CURRENT due cycle")
        m["billing_status"] = "PAST_DUE"
        m["past_due_since"] = now
        m["version"] += 1
        models.touch(m, "Membership")
        return success(models.serialize_membership(m), status=200)

    if outcome == "SUCCEEDED":
        if m["billing_status"] == "PAST_DUE":
            # back-payment recovery
            m["billing_status"] = "CURRENT"
            m["past_due_since"] = None
            m["cycle_start"] = now
            m["cycle_end"] = now + timedelta(days=calc.CYCLE_DAYS)
            if m["access_status"] == "SUSPENDED":
                m["access_status"] = "ACTIVE"
            m["version"] += 1
            models.touch(m, "Membership")
            return success(models.serialize_membership(m), status=200)
        elif m["billing_status"] == "CURRENT":
            if now < m["cycle_end"]:
                raise err("ERR_INVALID_STATE", "Cycle is not yet due")
            if m["access_status"] == "FROZEN":
                raise err("ERR_MEMBERSHIP_FROZEN", "A frozen membership is not billed")
            # on-time renewal: wallet-then-card
            member = db.members.get(m["member_id"])
            if member is not None:
                wallet_applied, _, new_wallet = calc.renewal_charge(m["monthly_fee_cents"], member["wallet_credit_cents"])
                if new_wallet != member["wallet_credit_cents"]:
                    member["wallet_credit_cents"] = new_wallet
                    member["version"] += 1
                    models.touch(member, "Member")
            m["cycle_start"] = now
            m["cycle_end"] = now + timedelta(days=calc.CYCLE_DAYS)
            m["version"] += 1
            models.touch(m, "Membership")
            return success(models.serialize_membership(m), status=200)
        else:
            raise err("ERR_INVALID_STATE", "Cannot run billing on this membership")

    # outcome == SWEEP
    if m["billing_status"] != "PAST_DUE":
        raise err("ERR_INVALID_STATE", "SWEEP only valid on a PAST_DUE membership")
    days_overdue = calc.grace_days_overdue(m["past_due_since"], now)
    if days_overdue >= calc.GRACE_DAYS and m["access_status"] == "ACTIVE":
        m["access_status"] = "SUSPENDED"
        auto_check_out_member(m["member_id"])
        m["version"] += 1
        models.touch(m, "Membership")
    return success(models.serialize_membership(m), status=200)


@app.route("/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    uid, role = get_caller()
    require_role(role, {"Member"})
    m = find_membership(mid)
    _member_owns(uid, role, m["member_id"])
    if m["billing_status"] not in ("CURRENT", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Membership not cancellable")
    body = get_body()
    ev = expected_version(body, "expected_membership_version")
    if ev != m["version"]:
        raise err("ERR_STALE_MEMBERSHIP_VERSION", "Stale membership version")

    m["billing_status"] = "CANCELLED"
    m["access_status"] = "TERMINATED"
    withdraw_member_enrollments(m["member_id"])
    m["version"] += 1
    models.touch(m, "Membership")
    return success(models.serialize_membership(m), status=200)


# ===========================================================================
# Certifications
# ===========================================================================
@app.route("/certifications", methods=["POST"])
def create_certification():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Examiner"})
    body = get_body()
    require_fields(body, ["member_id", "discipline"])
    member = find_member(body["member_id"])
    discipline = body["discipline"]
    if discipline not in ("BELAY", "LEAD"):
        raise err("ERR_INVALID_REQUEST", "discipline must be BELAY or LEAD")

    c = {
        "member_id": member["id"],
        "discipline": discipline,
        "status": "REGISTERED",
        "weighted_score": None,
        "min_station_score": None,
        "passed_at": None,
        "expires_at": None,
        "examiner_user_id": None,
        "version": 1,
    }
    models.stamp_create(c, "Certification")
    db.certifications[c["id"]] = c
    return success(models.serialize_certification(c), status=201)


@app.route("/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "Examiner", "GymAdmin"})
    c = find_certification(cid)
    return success(models.serialize_certification(c), status=200)


@app.route("/certifications", methods=["GET"])
def list_certifications():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "Examiner", "GymAdmin"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    discipline = request.args.get("discipline")
    items = [
        c for c in db.certifications.values()
        if (member_id is None or c["member_id"] == member_id)
        and (discipline is None or c["discipline"] == discipline)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_certification(c) for c in page], limit, offset, total)


@app.route("/certifications/<cid>/grade", methods=["POST"])
def grade_certification(cid):
    uid, role = get_caller()
    require_role(role, {"Examiner"})
    c = find_certification(cid)
    if c["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "Certification not REGISTERED")
    body = get_body()
    require_fields(body, ["knot", "commands", "catch", "lower"])
    scores = {}
    for name in ("knot", "commands", "catch", "lower"):
        v = body[name]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
        if v < 0 or v > 100:
            raise err("ERR_INVALID_REQUEST", "%s must be in [0,100]" % name)
        scores[name] = v

    weighted, min_station = calc.belay_weighted_score(
        scores["knot"], scores["commands"], scores["catch"], scores["lower"]
    )
    passes = weighted >= calc.CERT_PASS_THRESHOLD and min_station >= calc.CERT_STATION_FLOOR

    # Lead prerequisite gate applies only when the test would otherwise pass.
    if passes and c["discipline"] == "LEAD":
        if not member_has_passed_belay(c["member_id"]):
            raise err("ERR_BELAY_PREREQUISITE_MISSING", "LEAD requires a passed non-expired BELAY cert")

    c["weighted_score"] = weighted
    c["min_station_score"] = min_station
    c["examiner_user_id"] = uid
    if passes:
        c["status"] = "PASSED"
        c["passed_at"] = clock.now()
        c["expires_at"] = clock.now() + timedelta(days=calc.CERT_VALID_DAYS)
    else:
        c["status"] = "FAILED"
    c["version"] += 1
    models.touch(c, "Certification")
    return success(models.serialize_certification(c), status=200)


@app.route("/certifications/<cid>/refresh-status", methods=["POST"])
def refresh_certification(cid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Examiner"})
    c = find_certification(cid)
    if c["status"] != "PASSED":
        raise err("ERR_INVALID_STATE", "Certification not PASSED")
    if c["expires_at"] is None or clock.now() < c["expires_at"]:
        raise err("ERR_INVALID_STATE", "Certification not yet expired")
    c["status"] = "EXPIRED"
    c["version"] += 1
    models.touch(c, "Certification")
    return success(models.serialize_certification(c), status=200)


# ===========================================================================
# Facilities
# ===========================================================================
@app.route("/facilities", methods=["POST"])
def create_facility():
    _, role = get_caller()
    require_role(role, {"GymAdmin"})
    body = get_body()
    require_fields(body, ["name", "floor_capacity"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise err("ERR_INVALID_REQUEST", "name must be a non-empty string")
    cap = body["floor_capacity"]
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise err("ERR_INVALID_REQUEST", "floor_capacity must be an integer >= 1")
    requires = body.get("requires_belay_cert", False)
    if not isinstance(requires, bool):
        raise err("ERR_INVALID_REQUEST", "requires_belay_cert must be a boolean")

    f = {
        "name": body["name"],
        "floor_capacity": cap,
        "occupancy": 0,
        "requires_belay_cert": requires,
        "version": 1,
    }
    models.stamp_create(f, "Facility")
    db.facilities[f["id"]] = f
    return success(models.serialize_facility(f), status=201)


@app.route("/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "RouteSetter", "GymAdmin"})
    f = find_facility(fid)
    return success(models.serialize_facility(f), status=200)


@app.route("/facilities", methods=["GET"])
def list_facilities():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "RouteSetter", "GymAdmin"})
    limit, offset = parse_pagination()
    items = list(db.facilities.values())
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_facility(f) for f in page], limit, offset, total)


@app.route("/facilities/<fid>/routes", methods=["GET"])
def list_facility_routes(fid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "RouteSetter", "GymAdmin"})
    find_facility(fid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [
        r for r in db.routes.values()
        if r["facility_id"] == fid and (status is None or r["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_route(r) for r in page], limit, offset, total)


@app.route("/facilities/<fid>/check-ins", methods=["GET"])
def list_facility_check_ins(fid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "GymAdmin"})
    find_facility(fid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    member_id = request.args.get("member_id")
    items = [
        c for c in db.check_ins.values()
        if c["facility_id"] == fid
        and (status is None or c["status"] == status)
        and (member_id is None or c["member_id"] == member_id)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_check_in(c) for c in page], limit, offset, total)


@app.route("/facilities/<fid>/incidents", methods=["GET"])
def list_facility_incidents(fid):
    _, role = get_caller()
    require_role(role, {"GymAdmin"})
    find_facility(fid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [
        i for i in db.incidents.values()
        if i["facility_id"] == fid and (status is None or i["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_incident(i) for i in page], limit, offset, total)


@app.route("/facilities/<fid>/setter-report", methods=["GET"])
def setter_report(fid):
    _, role = get_caller()
    require_role(role, {"RouteSetter", "GymAdmin"})
    find_facility(fid)
    setter_user_id = request.args.get("setter_user_id")
    month = request.args.get("month")
    if not setter_user_id or not month:
        raise err("ERR_INVALID_REQUEST", "setter_user_id and month are required")

    # month is YYYY-MM; build the half-open window [month_start, next_month_start)
    try:
        year_s, mon_s = month.split("-")
        year = int(year_s)
        mon = int(mon_s)
        if mon < 1 or mon > 12:
            raise ValueError()
    except (ValueError, AttributeError):
        raise err("ERR_INVALID_REQUEST", "month must be YYYY-MM")

    from datetime import datetime, timezone
    month_start = datetime(year, mon, 1, tzinfo=timezone.utc)
    if mon == 12:
        next_month_start = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(year, mon + 1, 1, tzinfo=timezone.utc)

    total_points = 0
    route_count = 0
    for r in db.routes.values():
        if r["facility_id"] != fid:
            continue
        if r["setter_user_id"] != setter_user_id:
            continue
        if r["status"] not in ("OPEN", "STRIPPED"):
            continue
        if month_start <= r["set_on"] < next_month_start:
            total_points += r["difficulty_points"]
            route_count += 1

    return success({
        "setter_user_id": setter_user_id,
        "month": month,
        "total_points": total_points,
        "route_count": route_count,
    }, status=200)


# ===========================================================================
# Routes
# ===========================================================================
@app.route("/routes", methods=["POST"])
def create_route():
    uid, role = get_caller()
    require_role(role, {"RouteSetter"})
    body = get_body()
    require_fields(body, ["facility_id", "grade", "style"])
    facility = find_facility(body["facility_id"])
    grade = body["grade"]
    if isinstance(grade, bool) or not isinstance(grade, int) or grade < 0 or grade > 10:
        raise err("ERR_INVALID_REQUEST", "grade must be an integer in [0,10]")
    style = body["style"]
    if style not in calc.STYLE_MULT:
        raise err("ERR_INVALID_REQUEST", "style must be SLAB, OVERHANG, or ROOF")

    now = clock.now()
    r = {
        "facility_id": facility["id"],
        "setter_user_id": uid,
        "grade": grade,
        "style": style,
        "difficulty_points": calc.difficulty_points(grade, style),
        "status": "OPEN",
        "set_on": now,
        "version": 1,
    }
    models.stamp_create(r, "Route")
    db.routes[r["id"]] = r
    return success(models.serialize_route(r), status=201)


@app.route("/routes/<rid>/strip", methods=["POST"])
def strip_route(rid):
    _, role = get_caller()
    require_role(role, {"RouteSetter"})
    r = find_route(rid)
    if r["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Route not OPEN")
    body = get_body()
    ev = expected_version(body, "expected_route_version")
    if ev != r["version"]:
        raise err("ERR_STALE_ROUTE_VERSION", "Stale route version")
    r["status"] = "STRIPPED"
    r["version"] += 1
    models.touch(r, "Route")
    return success(models.serialize_route(r), status=200)


@app.route("/routes", methods=["GET"])
def list_routes():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "RouteSetter", "GymAdmin"})
    limit, offset = parse_pagination()
    setter_user_id = request.args.get("setter_user_id")
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    items = [
        r for r in db.routes.values()
        if (setter_user_id is None or r["setter_user_id"] == setter_user_id)
        and (facility_id is None or r["facility_id"] == facility_id)
        and (status is None or r["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_route(r) for r in page], limit, offset, total)


# ===========================================================================
# Check-Ins
# ===========================================================================
@app.route("/check-ins", methods=["POST"])
def create_check_in():
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    body = get_body()
    require_fields(body, ["member_id", "facility_id", "entry_kind", "expected_facility_version"])
    # existence: body FKs left-to-right (member then facility per input order)
    member = find_member(body["member_id"])
    facility = find_facility(body["facility_id"])

    entry_kind = body["entry_kind"]
    if entry_kind not in ("MEMBERSHIP", "DAY_PASS"):
        raise err("ERR_INVALID_REQUEST", "entry_kind must be MEMBERSHIP or DAY_PASS")
    gear_bundle = body.get("gear_bundle", False)
    if not isinstance(gear_bundle, bool):
        raise err("ERR_INVALID_REQUEST", "gear_bundle must be a boolean")
    ev = expected_version_check_in(body)

    # (7) waiver gate
    if not member_has_valid_waiver(member["id"]):
        raise err("ERR_WAIVER_INVALID", "Member has no VALID waiver")
    # (8) belay gate
    if facility["requires_belay_cert"] and not member_has_active_belay_or_lead(member["id"]):
        raise err("ERR_BELAY_CERT_REQUIRED", "Facility requires a current belay/lead certification")
    # (10) active-membership gate (MEMBERSHIP only)
    if entry_kind == "MEMBERSHIP" and member_active_membership(member["id"]) is None:
        raise err("ERR_MEMBERSHIP_NOT_ACTIVE", "No membership with ACTIVE access")
    # (12) OCC
    if ev != facility["version"]:
        raise err("ERR_STALE_FACILITY_VERSION", "Stale facility version")
    # (13) capacity
    if facility["occupancy"] >= facility["floor_capacity"]:
        raise err("ERR_CAPACITY_FULL", "Facility at capacity")

    if entry_kind == "DAY_PASS":
        price = calc.day_pass_price(member["is_youth"], gear_bundle)
    else:
        price = 0

    now = clock.now()
    c = {
        "member_id": member["id"],
        "facility_id": facility["id"],
        "entry_kind": entry_kind,
        "gear_bundle": gear_bundle,
        "price_cents": price,
        "status": "ON_FLOOR",
        "checked_in_at": now,
        "checked_out_at": None,
    }
    models.stamp_create(c, "CheckIn")
    db.check_ins[c["id"]] = c
    recompute_facility_occupancy(facility["id"])
    facility["version"] += 1
    models.touch(facility, "Facility")
    return success(models.serialize_check_in(c), status=201)


def expected_version_check_in(body):
    return expected_version(body, "expected_facility_version")


@app.route("/check-ins/<cid>", methods=["GET"])
def get_check_in(cid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "GymAdmin"})
    c = find_check_in(cid)
    return success(models.serialize_check_in(c), status=200)


@app.route("/check-ins", methods=["GET"])
def list_check_ins():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "GymAdmin"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    items = [
        c for c in db.check_ins.values()
        if (member_id is None or c["member_id"] == member_id)
        and (facility_id is None or c["facility_id"] == facility_id)
        and (status is None or c["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_check_in(c) for c in page], limit, offset, total)


@app.route("/check-ins/<cid>/check-out", methods=["POST"])
def check_out(cid):
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    c = find_check_in(cid)
    if c["status"] != "ON_FLOOR":
        raise err("ERR_INVALID_STATE", "Check-in not ON_FLOOR")
    c["status"] = "CHECKED_OUT"
    c["checked_out_at"] = clock.now()
    models.touch(c, "CheckIn")
    recompute_facility_occupancy(c["facility_id"])
    f = db.facilities.get(c["facility_id"])
    if f is not None:
        f["version"] += 1
        models.touch(f, "Facility")
    return success(models.serialize_check_in(c), status=200)


# ===========================================================================
# Clinics
# ===========================================================================
@app.route("/clinics", methods=["POST"])
def create_clinic():
    _, role = get_caller()
    require_role(role, {"GymAdmin"})
    body = get_body()
    require_fields(body, ["title", "starts_at", "ends_at", "seat_capacity"])
    if not isinstance(body["title"], str) or not body["title"]:
        raise err("ERR_INVALID_REQUEST", "title must be a non-empty string")
    starts_at = parse_iso8601(body["starts_at"])
    ends_at = parse_iso8601(body["ends_at"])
    if starts_at is None or ends_at is None:
        raise err("ERR_INVALID_REQUEST", "starts_at/ends_at must be valid ISO instants")
    if ends_at <= starts_at:
        raise err("ERR_INVALID_REQUEST", "ends_at must be after starts_at")
    cap = body["seat_capacity"]
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise err("ERR_INVALID_REQUEST", "seat_capacity must be an integer >= 1")

    c = {
        "title": body["title"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "seat_capacity": cap,
        "enrolled_count": 0,
        "status": "SCHEDULED",
        "version": 1,
    }
    models.stamp_create(c, "Clinic")
    db.clinics[c["id"]] = c
    return success(models.serialize_clinic(c), status=201)


@app.route("/clinics/<cid>", methods=["GET"])
def get_clinic(cid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    c = find_clinic(cid)
    return success(models.serialize_clinic(c), status=200)


@app.route("/clinics", methods=["GET"])
def list_clinics():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [c for c in db.clinics.values() if status is None or c["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_clinic(c) for c in page], limit, offset, total)


@app.route("/clinics/<cid>/cancel", methods=["POST"])
def cancel_clinic(cid):
    _, role = get_caller()
    require_role(role, {"GymAdmin"})
    c = find_clinic(cid)
    if c["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Clinic not SCHEDULED")
    body = get_body()
    ev = expected_version(body, "expected_clinic_version")
    if ev != c["version"]:
        raise err("ERR_STALE_CLINIC_VERSION", "Stale clinic version")

    c["status"] = "CANCELLED"
    for e in db.enrollments.values():
        if e["clinic_id"] == c["id"] and e["status"] == "ENROLLED":
            e["status"] = "WITHDRAWN"
    recompute_clinic_count(c["id"])
    c["version"] += 1
    models.touch(c, "Clinic")
    return success(models.serialize_clinic(c), status=200)


@app.route("/clinics/<cid>/enrollments", methods=["GET"])
def list_clinic_enrollments(cid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "GymAdmin"})
    find_clinic(cid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [
        e for e in db.enrollments.values()
        if e["clinic_id"] == cid and (status is None or e["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_enrollment(e) for e in page], limit, offset, total)


# ===========================================================================
# Enrollments
# ===========================================================================
@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    uid, role = get_caller()
    require_role(role, {"FrontDesk", "Member"})
    body = get_body()
    require_fields(body, ["clinic_id", "member_id", "expected_clinic_version"])
    # existence: clinic then member (input order)
    clinic = find_clinic(body["clinic_id"])
    member = find_member(body["member_id"])

    # ownership for Member role
    if role == "Member" and uid != member["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only enroll themselves")

    ev = expected_version(body, "expected_clinic_version")

    # (11) enrollment window: clock strictly before starts_at; also rejects cancelled
    now = clock.now()
    if clinic["status"] != "SCHEDULED" or now >= clinic["starts_at"]:
        raise err("ERR_ENROLLMENT_WINDOW_CLOSED", "Enrollment window closed")
    # (12) OCC
    if ev != clinic["version"]:
        raise err("ERR_STALE_CLINIC_VERSION", "Stale clinic version")
    # (13) capacity
    if clinic["enrolled_count"] >= clinic["seat_capacity"]:
        raise err("ERR_CAPACITY_FULL", "Clinic at capacity")

    e = {
        "clinic_id": clinic["id"],
        "member_id": member["id"],
        "status": "ENROLLED",
    }
    models.stamp_create(e, "Enrollment")
    db.enrollments[e["id"]] = e
    recompute_clinic_count(clinic["id"])
    clinic["version"] += 1
    models.touch(clinic, "Clinic")
    return success(models.serialize_enrollment(e), status=201)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    e = find_enrollment(eid)
    return success(models.serialize_enrollment(e), status=200)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    clinic_id = request.args.get("clinic_id")
    status = request.args.get("status")
    items = [
        e for e in db.enrollments.values()
        if (member_id is None or e["member_id"] == member_id)
        and (clinic_id is None or e["clinic_id"] == clinic_id)
        and (status is None or e["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_enrollment(e) for e in page], limit, offset, total)


@app.route("/enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment(eid):
    uid, role = get_caller()
    require_role(role, {"Member"})
    e = find_enrollment(eid)
    if role == "Member" and uid != e["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only withdraw their own enrollment")
    if e["status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Enrollment not ENROLLED")
    e["status"] = "WITHDRAWN"
    recompute_clinic_count(e["clinic_id"])
    c = db.clinics.get(e["clinic_id"])
    if c is not None:
        c["version"] += 1
        models.touch(c, "Clinic")
    return success(models.serialize_enrollment(e), status=200)


# ===========================================================================
# Rentals
# ===========================================================================
@app.route("/rentals", methods=["POST"])
def create_rental():
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    body = get_body()
    require_fields(body, ["member_id", "item_kind", "deposit_cents"])
    member = find_member(body["member_id"])
    item_kind = body["item_kind"]
    if item_kind not in ("HARNESS", "SHOES", "ROPE"):
        raise err("ERR_INVALID_REQUEST", "item_kind must be HARNESS, SHOES, or ROPE")
    deposit = body["deposit_cents"]
    if isinstance(deposit, bool) or not isinstance(deposit, int) or deposit < 0:
        raise err("ERR_INVALID_REQUEST", "deposit_cents must be an integer >= 0")

    now = clock.now()
    r = {
        "member_id": member["id"],
        "item_kind": item_kind,
        "deposit_cents": deposit,
        "rented_at": now,
        "due_at": now + timedelta(hours=calc.RENTAL_DUE_HOURS),
        "returned_at": None,
        "late_fee_cents": 0,
        "refund_cents": 0,
        "status": "OUT",
        "version": 1,
    }
    models.stamp_create(r, "Rental")
    db.rentals[r["id"]] = r
    return success(models.serialize_rental(r), status=201)


@app.route("/rentals/<rid>", methods=["GET"])
def get_rental(rid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    r = find_rental(rid)
    return success(models.serialize_rental(r), status=200)


@app.route("/rentals", methods=["GET"])
def list_rentals():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "Member", "GymAdmin"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = [
        r for r in db.rentals.values()
        if (member_id is None or r["member_id"] == member_id)
        and (status is None or r["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_rental(r) for r in page], limit, offset, total)


@app.route("/rentals/<rid>/return", methods=["POST"])
def return_rental(rid):
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    r = find_rental(rid)
    if r["status"] != "OUT":
        raise err("ERR_INVALID_STATE", "Rental not OUT")
    body = get_body()
    ev = expected_version(body, "expected_rental_version")
    if ev != r["version"]:
        raise err("ERR_STALE_RENTAL_VERSION", "Stale rental version")

    now = clock.now()
    late_fee, refund = calc.rental_late_fee(r["due_at"], now, r["deposit_cents"])
    r["late_fee_cents"] = late_fee
    r["refund_cents"] = refund
    r["status"] = "RETURNED"
    r["returned_at"] = now
    member = db.members.get(r["member_id"])
    if member is not None and refund > 0:
        member["wallet_credit_cents"] += refund
        member["version"] += 1
        models.touch(member, "Member")
    r["version"] += 1
    models.touch(r, "Rental")
    return success(models.serialize_rental(r), status=200)


@app.route("/rentals/<rid>/report-lost", methods=["POST"])
def report_lost_rental(rid):
    _, role = get_caller()
    require_role(role, {"FrontDesk"})
    r = find_rental(rid)
    if r["status"] != "OUT":
        raise err("ERR_INVALID_STATE", "Rental not OUT")
    body = get_body()
    ev = expected_version(body, "expected_rental_version")
    if ev != r["version"]:
        raise err("ERR_STALE_RENTAL_VERSION", "Stale rental version")

    r["late_fee_cents"] = r["deposit_cents"]
    r["refund_cents"] = 0
    r["status"] = "LOST"
    r["version"] += 1
    models.touch(r, "Rental")
    return success(models.serialize_rental(r), status=200)


# ===========================================================================
# Incidents
# ===========================================================================
@app.route("/incidents", methods=["POST"])
def create_incident():
    _, role = get_caller()
    require_role(role, {"FrontDesk", "GymAdmin"})
    body = get_body()
    require_fields(body, ["member_id", "facility_id", "severity", "description"])
    member = find_member(body["member_id"])
    facility = find_facility(body["facility_id"])
    cert_id = body.get("certification_id")
    if cert_id is not None:
        find_certification(cert_id)
    severity = body["severity"]
    if severity not in ("MINOR", "SERIOUS"):
        raise err("ERR_INVALID_REQUEST", "severity must be MINOR or SERIOUS")
    if not isinstance(body["description"], str):
        raise err("ERR_INVALID_REQUEST", "description must be a string")

    now = clock.now()
    i = {
        "member_id": member["id"],
        "facility_id": facility["id"],
        "certification_id": cert_id,
        "severity": severity,
        "description": body["description"],
        "status": "OPEN",
        "reported_at": now,
        "version": 1,
    }
    models.stamp_create(i, "Incident")
    db.incidents[i["id"]] = i

    if severity == "SERIOUS":
        serious_incident_cascade(member["id"], cert_id)

    return success(models.serialize_incident(i), status=201)


@app.route("/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    _, role = get_caller()
    require_role(role, {"FrontDesk", "GymAdmin"})
    i = find_incident(iid)
    return success(models.serialize_incident(i), status=200)


@app.route("/incidents", methods=["GET"])
def list_incidents():
    _, role = get_caller()
    require_role(role, {"GymAdmin"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    certification_id = request.args.get("certification_id")
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    items = [
        i for i in db.incidents.values()
        if (member_id is None or i["member_id"] == member_id)
        and (certification_id is None or i.get("certification_id") == certification_id)
        and (facility_id is None or i["facility_id"] == facility_id)
        and (status is None or i["status"] == status)
    ]
    page, total = paginate(items, limit, offset)
    return list_response([models.serialize_incident(i) for i in page], limit, offset, total)


@app.route("/incidents/<iid>/resolve", methods=["POST"])
def resolve_incident(iid):
    _, role = get_caller()
    require_role(role, {"GymAdmin"})
    i = find_incident(iid)
    if i["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Incident not OPEN")
    i["status"] = "RESOLVED"
    i["version"] += 1
    models.touch(i, "Incident")
    return success(models.serialize_incident(i), status=200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
