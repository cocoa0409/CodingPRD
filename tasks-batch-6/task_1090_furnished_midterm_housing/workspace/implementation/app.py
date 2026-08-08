"""Furnished & Mid-Term Housing platform API (Flask, in-memory)."""
import os
from flask import Flask, jsonify, request

import core
from core import (
    DB, ApiError, new_record, touch, public,
    success_object, success_array, error_body,
    provisional_rent_cents, final_rent_cents, cleaning_charge_cents,
    platform_fee_cents, occupancy_tax, days_between, clock_reached,
    parse_date, _parse_iso,
    COI_MIN_COVERAGE_CENTS,
)
from helpers import (
    auth_context, require_role, forbid, get_json_body, require_fields,
    as_int, get_or_404, lookup, paginate, filter_records,
)

app = Flask(__name__)

READ_ROLES = {"Host", "Tenant", "ComplianceReviewer", "PlatformAdmin"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    body = error_body(err.error_id, err.message)
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(err):
    return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return jsonify(error_body("ERR_VALIDATION", str(err))), 422


def respond(payload):
    data, status = payload
    return jsonify(data), status


# ---------------------------------------------------------------------------
# Derived-field recompute helpers
# ---------------------------------------------------------------------------
def recompute_host(host):
    hid = host["id"]
    projected = 0
    balance = 0
    for p in DB.tables["payouts"].values():
        if p.get("host_id") != hid:
            continue
        if p["status"] in ("PENDING", "SCHEDULED"):
            projected += p["net_cents"]
        elif p["status"] == "PAID":
            balance += p["net_cents"]
    if host.get("projected_payout_cents") != projected or host.get("payout_balance_cents") != balance:
        host["projected_payout_cents"] = projected
        host["payout_balance_cents"] = balance
        touch(host)


def recompute_tenant_verification(tenant):
    vers = [v for v in DB.tables["verifications"].values() if v["tenant_id"] == tenant["id"]]
    if any(v["status"] == "APPROVED" for v in vers):
        st = "VERIFIED"
    elif any(v["status"] == "PENDING" for v in vers):
        st = "PENDING"
    elif any(v["status"] == "REJECTED" for v in vers):
        st = "REJECTED"
    else:
        st = "UNVERIFIED"
    if tenant.get("verification_status") != st:
        tenant["verification_status"] = st
        touch(tenant)


def payout_for_booking(booking_id):
    for p in DB.tables["payouts"].values():
        if p.get("booking_id") == booking_id:
            return p
    return None


def deposit_for_booking(booking_id):
    for d in DB.tables["deposits"].values():
        if d.get("booking_id") == booking_id:
            return d
    return None


def tax_for_booking(booking_id):
    for t in DB.tables["tax_assessments"].values():
        if t.get("booking_id") == booking_id:
            return t
    return None


def recompute_payout_net(payout):
    payout["net_cents"] = (
        payout["gross_rent_cents"] - payout["platform_fee_cents"] + payout["deposit_adjustment_cents"]
    )


def host_of_unit(unit):
    return lookup("hosts", unit["host_id"])


def unit_of_booking(booking):
    return lookup("units", booking["unit_id"])


def booking_of_deposit(deposit):
    return lookup("bookings", deposit["booking_id"])


# ---------------------------------------------------------------------------
# COI coverage helper
# ---------------------------------------------------------------------------
def has_valid_coi(booking):
    from datetime import timedelta
    start = parse_date(booking["start_date"])
    end = parse_date(booking["end_date"])  # exclusive
    last_night = end - timedelta(days=1)
    for p in DB.tables["coi_policies"].values():
        if p.get("booking_id") != booking["id"]:
            continue
        if p["status"] != "ACTIVE":
            continue
        if p["coverage_cents"] < COI_MIN_COVERAGE_CENTS:
            continue
        try:
            eff_start = parse_date(p["effective_start"])
            eff_end = parse_date(p["effective_end"])
        except Exception:
            continue
        if eff_start <= start and eff_end >= last_night:
            return True
    return False


# ---------------------------------------------------------------------------
# Availability helpers
# ---------------------------------------------------------------------------
def _overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open intervals [a_start, a_end) and [b_start, b_end) overlap?"""
    return a_start < b_end and b_start < a_end


def unit_available(unit, start_str, end_str, buffer_days, exclude_booking_id=None):
    """Requested window widened by turnover buffer must not overlap any
    REQUESTED/CONFIRMED/ACTIVE booking on the unit (half-open)."""
    from datetime import timedelta
    req_start = parse_date(start_str)
    req_end = parse_date(end_str) + timedelta(days=buffer_days)
    for b in DB.tables["bookings"].values():
        if b["unit_id"] != unit["id"]:
            continue
        if exclude_booking_id and b["id"] == exclude_booking_id:
            continue
        if b["status"] not in ("REQUESTED", "CONFIRMED", "ACTIVE"):
            continue
        other_buffer = unit.get("turnover_buffer_days", 0)
        b_start = parse_date(b["start_date"])
        b_end = parse_date(b["end_date"]) + timedelta(days=other_buffer)
        if _overlaps_half_open(req_start, req_end, b_start, b_end):
            return False
    return True


def tenant_double_booked(tenant_id, start_str, end_str, exclude_booking_id=None):
    """Closed-interval intersection with another CONFIRMED/ACTIVE booking of the tenant."""
    req_start = parse_date(start_str)
    req_end = parse_date(end_str)  # closed interval => inclusive comparison
    for b in DB.tables["bookings"].values():
        if b["tenant_id"] != tenant_id:
            continue
        if exclude_booking_id and b["id"] == exclude_booking_id:
            continue
        if b["status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        b_start = parse_date(b["start_date"])
        b_end = parse_date(b["end_date"])
        # closed intervals overlap when a_start <= b_end and b_start <= a_end
        if req_start <= b_end and b_start <= req_end:
            return True
    return False


# ===========================================================================
# Host endpoints
# ===========================================================================
@app.route("/hosts", methods=["POST"])
def create_host():
    body = get_json_body()
    require_fields(body, ["display_name", "email"])
    host = new_record({
        "display_name": body["display_name"],
        "email": body["email"],
        "payout_account_status": "UNVERIFIED",
        "status": "ACTIVE",
        "projected_payout_cents": 0,
        "payout_balance_cents": 0,
    })
    DB.tables["hosts"][host["id"]] = host
    return respond(success_object(public(host), 201))


@app.route("/hosts/<rid>", methods=["GET"])
def get_host(rid):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    host = get_or_404("hosts", rid)
    return respond(success_object(public(host)))


@app.route("/hosts/<rid>/verify-payout", methods=["POST"])
def verify_payout(rid):
    _, role = auth_context()
    require_role(role, {"ComplianceReviewer"})
    host = get_or_404("hosts", rid)
    if host["payout_account_status"] != "VERIFIED":
        host["payout_account_status"] = "VERIFIED"
        touch(host)
    return respond(success_object(public(host)))


# ===========================================================================
# Tenant endpoints
# ===========================================================================
@app.route("/tenants", methods=["POST"])
def create_tenant():
    body = get_json_body()
    require_fields(body, ["full_name", "email", "tenant_type"])
    if body["tenant_type"] not in ("TRAVEL_NURSE", "RELOCATION", "OTHER"):
        raise ApiError("ERR_VALIDATION", 422, "Invalid tenant_type")
    tenant = new_record({
        "full_name": body["full_name"],
        "email": body["email"],
        "tenant_type": body["tenant_type"],
        "verification_status": "UNVERIFIED",
        "status": "ACTIVE",
    })
    DB.tables["tenants"][tenant["id"]] = tenant
    return respond(success_object(public(tenant), 201))


@app.route("/tenants/<rid>", methods=["GET"])
def get_tenant(rid):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    tenant = get_or_404("tenants", rid)
    return respond(success_object(public(tenant)))


# ===========================================================================
# Transition helpers
# ===========================================================================
def start_transition(table, rid, endpoint_roles, valid_statuses):
    uid, role = auth_context()
    require_role(role, endpoint_roles)
    rec = get_or_404(table, rid)
    body = get_json_body()
    to_status = body.get("to_status")
    if to_status is None or not isinstance(to_status, str):
        raise ApiError("ERR_VALIDATION", 422, "Missing or invalid to_status")
    if to_status not in valid_statuses:
        raise ApiError("ERR_VALIDATION", 422, "Invalid to_status value")
    return uid, role, rec, body, to_status


def check_state(rec, to_status, transition_map):
    allowed_from = transition_map.get(to_status)
    if not allowed_from or rec["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not allowed from current state")


def do_list(table, filters):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    recs = filter_records(table, **filters)
    items, limit, offset, total = paginate(recs)
    return respond(success_array(items, limit, offset, total))


def do_get(table, rid):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rec = get_or_404(table, rid)
    return respond(success_object(public(rec)))


# ===========================================================================
# Verification
# ===========================================================================
DOC_TYPES = {"GOVERNMENT_ID", "EMPLOYMENT_LETTER", "ASSIGNMENT_CONTRACT"}


@app.route("/verifications", methods=["POST"])
def create_verification():
    uid, role = auth_context()
    require_role(role, {"Tenant"})
    body = get_json_body()
    tenant_id = body.get("tenant_id")
    if tenant_id is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: tenant_id")
    if tenant_id != uid:
        forbid()
    tenant = get_or_404("tenants", tenant_id)
    require_fields(body, ["doc_type", "document_ref"])
    if body["doc_type"] not in DOC_TYPES:
        raise ApiError("ERR_VALIDATION", 422, "Invalid doc_type")
    ver = new_record({
        "tenant_id": tenant_id,
        "doc_type": body["doc_type"],
        "document_ref": body["document_ref"],
        "status": "PENDING",
        "reviewer_note": None,
    })
    DB.tables["verifications"][ver["id"]] = ver
    recompute_tenant_verification(tenant)
    return respond(success_object(public(ver), 201))


@app.route("/verifications/<rid>", methods=["GET"])
def get_verification(rid):
    return do_get("verifications", rid)


@app.route("/verifications", methods=["GET"])
def list_verifications():
    return do_list("verifications", {
        "tenant_id": request.args.get("tenant_id"),
        "status": request.args.get("status"),
    })


@app.route("/verifications/<rid>/transitions", methods=["POST"])
def transition_verification(rid):
    uid, role, ver, body, to_status = start_transition(
        "verifications", rid, {"ComplianceReviewer", "Tenant"},
        {"PENDING", "APPROVED", "REJECTED"})
    if to_status in ("APPROVED", "REJECTED"):
        if role != "ComplianceReviewer":
            forbid()
    else:  # PENDING resubmit
        if role != "Tenant" or ver["tenant_id"] != uid:
            forbid()
    check_state(ver, to_status, {
        "APPROVED": {"PENDING"},
        "REJECTED": {"PENDING"},
        "PENDING": {"REJECTED"},
    })
    ver["status"] = to_status
    if to_status in ("APPROVED", "REJECTED") and body.get("reviewer_note") is not None:
        ver["reviewer_note"] = body.get("reviewer_note")
    touch(ver)
    tenant = lookup("tenants", ver["tenant_id"])
    if tenant:
        recompute_tenant_verification(tenant)
    return respond(success_object(public(ver)))


# ===========================================================================
# Unit
# ===========================================================================
@app.route("/units", methods=["POST"])
def create_unit():
    uid, role = auth_context()
    require_role(role, {"Host"})
    body = get_json_body()
    host_id = body.get("host_id")
    if host_id is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: host_id")
    if host_id != uid:
        forbid()
    host = get_or_404("hosts", host_id)
    require_fields(body, ["title", "address", "monthly_rate_cents"])
    monthly = as_int(body, "monthly_rate_cents")
    if monthly <= 0:
        raise ApiError("ERR_VALIDATION", 422, "monthly_rate_cents must be > 0")
    unit = new_record({
        "host_id": host_id,
        "title": body["title"],
        "address": body["address"],
        "monthly_rate_cents": monthly,
        "cleaning_fee_cents": as_int(body, "cleaning_fee_cents", required=False) or 0,
        "deposit_cents": as_int(body, "deposit_cents", required=False) or 0,
        "utilities_included": bool(body.get("utilities_included", False)),
        "cleaning_included": bool(body.get("cleaning_included", False)),
        "requires_coi": bool(body.get("requires_coi", False)),
        "min_term_days": as_int(body, "min_term_days", required=False) if body.get("min_term_days") is not None else 30,
        "max_term_days": as_int(body, "max_term_days", required=False) if body.get("max_term_days") is not None else 90,
        "turnover_buffer_days": as_int(body, "turnover_buffer_days", required=False) if body.get("turnover_buffer_days") is not None else 2,
        "status": "DRAFT",
    })
    DB.tables["units"][unit["id"]] = unit
    return respond(success_object(public(unit), 201))


@app.route("/units/<rid>", methods=["GET"])
def get_unit(rid):
    return do_get("units", rid)


@app.route("/units", methods=["GET"])
def list_units():
    return do_list("units", {
        "host_id": request.args.get("host_id"),
        "status": request.args.get("status"),
    })


@app.route("/units/<rid>/transitions", methods=["POST"])
def transition_unit(rid):
    uid, role, unit, body, to_status = start_transition(
        "units", rid, {"Host", "PlatformAdmin"},
        {"DRAFT", "LISTED", "SUSPENDED", "DELISTED"})
    # actor authz
    if to_status == "SUSPENDED":
        if role == "Host":
            if unit["host_id"] != uid:
                forbid()
        elif role != "PlatformAdmin":
            forbid()
    else:  # LISTED, DELISTED, DRAFT
        if role != "Host" or unit["host_id"] != uid:
            forbid()
    check_state(unit, to_status, {
        "LISTED": {"DRAFT", "SUSPENDED"},
        "SUSPENDED": {"LISTED"},
        "DELISTED": {"DRAFT", "LISTED", "SUSPENDED"},
    })
    if to_status == "LISTED" and unit["status"] == "DRAFT":
        if unit["monthly_rate_cents"] <= 0 or unit["min_term_days"] > unit["max_term_days"]:
            raise ApiError("ERR_VALIDATION", 422, "Unit not eligible to list")
    if to_status == "DELISTED":
        for b in DB.tables["bookings"].values():
            if b["unit_id"] == unit["id"] and b["status"] in ("REQUESTED", "CONFIRMED", "ACTIVE"):
                raise ApiError("ERR_UNIT_HAS_ACTIVE_BOOKINGS", 409, "Unit has active bookings")
    unit["status"] = to_status
    touch(unit)
    return respond(success_object(public(unit)))


# ===========================================================================
# Booking
# ===========================================================================
def _compute_booking_derived_provisional(unit, term_days):
    rent = provisional_rent_cents(unit["monthly_rate_cents"], term_days)
    cleaning = cleaning_charge_cents(unit)
    return rent, cleaning, rent + cleaning


@app.route("/bookings", methods=["POST"])
def create_booking():
    uid, role = auth_context()
    require_role(role, {"Tenant"})
    body = get_json_body()
    tenant_id = body.get("tenant_id")
    if tenant_id is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: tenant_id")
    if tenant_id != uid:
        forbid()
    unit_id = body.get("unit_id")
    if unit_id is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: unit_id")
    unit = get_or_404("units", unit_id)
    tenant = get_or_404("tenants", tenant_id)
    # body well-formedness
    require_fields(body, ["start_date", "end_date"])
    try:
        start = parse_date(body["start_date"])
        end = parse_date(body["end_date"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid date format")
    if not (end > start):
        raise ApiError("ERR_VALIDATION", 422, "end_date must be after start_date")
    term_days = (end - start).days
    # term bounds
    if term_days < unit["min_term_days"]:
        raise ApiError("ERR_TERM_TOO_SHORT", 422, "Term shorter than minimum")
    if term_days > unit["max_term_days"]:
        raise ApiError("ERR_TERM_EXCEEDS_MAX", 422, "Term longer than maximum")
    # availability
    if not unit_available(unit, body["start_date"], body["end_date"], unit["turnover_buffer_days"]):
        raise ApiError("ERR_UNIT_UNAVAILABLE", 409, "Unit not available for the window")
    if tenant_double_booked(tenant_id, body["start_date"], body["end_date"]):
        raise ApiError("ERR_TENANT_DOUBLE_BOOKED", 409, "Tenant double-booked")
    rent, cleaning, gross = _compute_booking_derived_provisional(unit, term_days)
    booking = new_record({
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "term_days": term_days,
        "rent_cents": rent,
        "cleaning_charge_cents": cleaning,
        "gross_rent_cents": gross,
        "rent_basis": "PROVISIONAL",
        "status": "REQUESTED",
    })
    DB.tables["bookings"][booking["id"]] = booking
    return respond(success_object(public(booking), 201))


@app.route("/bookings/<rid>", methods=["GET"])
def get_booking(rid):
    return do_get("bookings", rid)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    return do_list("bookings", {
        "unit_id": request.args.get("unit_id"),
        "tenant_id": request.args.get("tenant_id"),
        "status": request.args.get("status"),
    })


def _confirm_booking(booking, unit):
    host = host_of_unit(unit)
    # Deposit
    amount = int(unit.get("deposit_cents") or 0)
    deposit = new_record({
        "booking_id": booking["id"],
        "amount_cents": amount,
        "held_cents": amount,
        "refunded_cents": 0,
        "forfeited_cents": 0,
        "status": "HELD",
    })
    DB.tables["deposits"][deposit["id"]] = deposit
    # Payout (PROVISIONAL)
    gross = booking["gross_rent_cents"]
    fee = platform_fee_cents(gross, booking["term_days"], unit.get("utilities_included", False))
    payout = new_record({
        "booking_id": booking["id"],
        "host_id": unit["host_id"],
        "gross_rent_cents": gross,
        "platform_fee_cents": fee,
        "deposit_adjustment_cents": 0,
        "net_cents": gross - fee,
        "payout_basis": "PROVISIONAL",
        "scheduled_by_user_id": None,
        "status": "PENDING",
    })
    DB.tables["payouts"][payout["id"]] = payout
    if host:
        recompute_host(host)
    # TaxAssessment
    tax = occupancy_tax(booking["term_days"], gross)
    ta = new_record({
        "booking_id": booking["id"],
        "assessed_term_days": booking["term_days"],
        "taxable": tax["taxable"],
        "occupancy_tax_cents": tax["occupancy_tax_cents"],
        "exempt_reason": tax["exempt_reason"],
    })
    DB.tables["tax_assessments"][ta["id"]] = ta


def _complete_booking(booking, unit):
    booking["rent_cents"] = final_rent_cents(unit["monthly_rate_cents"], booking["start_date"], booking["end_date"])
    booking["gross_rent_cents"] = booking["rent_cents"] + booking["cleaning_charge_cents"]
    booking["rent_basis"] = "FINAL"
    touch(booking)
    payout = payout_for_booking(booking["id"])
    if payout:
        payout["gross_rent_cents"] = booking["gross_rent_cents"]
        payout["platform_fee_cents"] = platform_fee_cents(
            booking["gross_rent_cents"], booking["term_days"], unit.get("utilities_included", False))
        recompute_payout_net(payout)
        payout["payout_basis"] = "FINAL"
        touch(payout)
        host = host_of_unit(unit)
        if host:
            recompute_host(host)
    # Turnover
    from datetime import timedelta
    sched_end = (parse_date(booking["end_date"]) + timedelta(days=unit.get("turnover_buffer_days", 0))).isoformat()
    turnover = new_record({
        "unit_id": unit["id"],
        "booking_id": booking["id"],
        "scheduled_start": booking["end_date"],
        "scheduled_end": sched_end,
        "status": "SCHEDULED",
    })
    DB.tables["turnovers"][turnover["id"]] = turnover


def _cancel_confirmed_booking(booking, unit):
    deposit = deposit_for_booking(booking["id"])
    if deposit:
        deposit["refunded_cents"] = deposit["held_cents"]
        deposit["held_cents"] = 0
        deposit["status"] = "REFUNDED"
        touch(deposit)
    payout = payout_for_booking(booking["id"])
    if payout:
        payout["status"] = "VOIDED"
        touch(payout)
        host = host_of_unit(unit)
        if host:
            recompute_host(host)


@app.route("/bookings/<rid>/transitions", methods=["POST"])
def transition_booking(rid):
    uid, role, booking, body, to_status = start_transition(
        "bookings", rid, {"Host", "Tenant", "PlatformAdmin"},
        {"REQUESTED", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED", "DECLINED"})
    unit = unit_of_booking(booking)
    # actor authz
    if to_status in ("CONFIRMED", "DECLINED"):
        if role != "Host" or not unit or unit["host_id"] != uid:
            forbid()
    elif to_status == "CANCELLED":
        if role != "Tenant" or booking["tenant_id"] != uid:
            forbid()
    elif to_status in ("ACTIVE", "COMPLETED"):
        if role != "PlatformAdmin":
            forbid()
    check_state(booking, to_status, {
        "CONFIRMED": {"REQUESTED"},
        "DECLINED": {"REQUESTED"},
        "CANCELLED": {"REQUESTED", "CONFIRMED"},
        "ACTIVE": {"CONFIRMED"},
        "COMPLETED": {"ACTIVE"},
    })
    if to_status == "CONFIRMED":
        tenant = lookup("tenants", booking["tenant_id"])
        if not tenant or tenant["verification_status"] != "VERIFIED":
            raise ApiError("ERR_TENANT_NOT_VERIFIED", 409, "Tenant not verified")
        if unit["status"] != "LISTED":
            raise ApiError("ERR_UNIT_NOT_LISTED", 409, "Unit not listed")
        if unit.get("requires_coi") and not has_valid_coi(booking):
            raise ApiError("ERR_COI_REQUIRED", 409, "Valid COI required")
        host = host_of_unit(unit)
        if not host or host["payout_account_status"] != "VERIFIED":
            raise ApiError("ERR_HOST_PAYOUT_NOT_VERIFIED", 409, "Host payout not verified")
        booking["status"] = "CONFIRMED"
        touch(booking)
        _confirm_booking(booking, unit)
    elif to_status == "DECLINED":
        booking["status"] = "DECLINED"
        touch(booking)
    elif to_status == "CANCELLED":
        if booking["status"] == "CONFIRMED":
            if clock_reached(booking["start_date"]):
                raise ApiError("ERR_INVALID_STATE", 409, "Cannot cancel after move-in date")
            booking["status"] = "CANCELLED"
            touch(booking)
            _cancel_confirmed_booking(booking, unit)
        else:  # REQUESTED
            booking["status"] = "CANCELLED"
            touch(booking)
    elif to_status == "ACTIVE":
        if not clock_reached(booking["start_date"]):
            raise ApiError("ERR_INVALID_STATE", 409, "Move-in date not reached")
        if unit.get("requires_coi") and not has_valid_coi(booking):
            raise ApiError("ERR_COI_REQUIRED", 409, "Valid COI required")
        booking["status"] = "ACTIVE"
        touch(booking)
    elif to_status == "COMPLETED":
        if not clock_reached(booking["end_date"]):
            raise ApiError("ERR_INVALID_STATE", 409, "Move-out date not reached")
        booking["status"] = "COMPLETED"
        _complete_booking(booking, unit)
    return respond(success_object(public(booking)))


# ===========================================================================
# Extension
# ===========================================================================
@app.route("/extensions", methods=["POST"])
def create_extension():
    uid, role = auth_context()
    require_role(role, {"Tenant"})
    body = get_json_body()
    booking_id = body.get("booking_id")
    if booking_id is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: booking_id")
    booking = get_or_404("bookings", booking_id)
    if booking["tenant_id"] != uid:
        forbid()
    require_fields(body, ["expected_booking_version", "new_end_date"])
    expected = as_int(body, "expected_booking_version")
    try:
        new_end = parse_date(body["new_end_date"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid new_end_date")
    # OCC
    if expected != booking["version"]:
        raise ApiError("ERR_STALE_BOOKING_VERSION", 412, "Stale booking version")
    added = (new_end - parse_date(booking["end_date"])).days
    ext = new_record({
        "booking_id": booking_id,
        "expected_booking_version": expected,
        "new_end_date": body["new_end_date"],
        "added_days": added,
        "status": "REQUESTED",
    })
    DB.tables["extensions"][ext["id"]] = ext
    touch(booking)  # advance booking version by 1
    return respond(success_object(public(ext), 201))


@app.route("/extensions/<rid>", methods=["GET"])
def get_extension(rid):
    return do_get("extensions", rid)


@app.route("/extensions", methods=["GET"])
def list_extensions():
    return do_list("extensions", {
        "booking_id": request.args.get("booking_id"),
        "status": request.args.get("status"),
    })


@app.route("/extensions/<rid>/transitions", methods=["POST"])
def transition_extension(rid):
    uid, role, ext, body, to_status = start_transition(
        "extensions", rid, {"Host", "Tenant"},
        {"REQUESTED", "APPROVED", "DECLINED", "WITHDRAWN"})
    booking = lookup("bookings", ext["booking_id"])
    unit = unit_of_booking(booking) if booking else None
    if to_status in ("APPROVED", "DECLINED"):
        if role != "Host" or not unit or unit["host_id"] != uid:
            forbid()
    else:  # WITHDRAWN
        if role != "Tenant" or not booking or booking["tenant_id"] != uid:
            forbid()
    check_state(ext, to_status, {
        "APPROVED": {"REQUESTED"},
        "DECLINED": {"REQUESTED"},
        "WITHDRAWN": {"REQUESTED"},
    })
    if to_status == "APPROVED":
        if booking["status"] not in ("CONFIRMED", "ACTIVE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Booking not extendable")
        new_end = parse_date(ext["new_end_date"])
        if not (new_end > parse_date(booking["end_date"])):
            raise ApiError("ERR_EXTENSION_NOT_LATER", 422, "new_end_date must be later")
        new_term = (new_end - parse_date(booking["start_date"])).days
        if new_term > unit["max_term_days"]:
            raise ApiError("ERR_TERM_EXCEEDS_MAX", 422, "Extended term exceeds maximum")
        if not unit_available(unit, booking["start_date"], ext["new_end_date"],
                              unit["turnover_buffer_days"], exclude_booking_id=booking["id"]):
            raise ApiError("ERR_UNIT_UNAVAILABLE", 409, "Extended window unavailable")
        # cascade
        booking["end_date"] = ext["new_end_date"]
        booking["term_days"] = new_term
        booking["rent_cents"] = provisional_rent_cents(unit["monthly_rate_cents"], new_term)
        booking["gross_rent_cents"] = booking["rent_cents"] + booking["cleaning_charge_cents"]
        touch(booking)
        payout = payout_for_booking(booking["id"])
        if payout:
            payout["gross_rent_cents"] = booking["gross_rent_cents"]
            recompute_payout_net(payout)
            touch(payout)
            host = host_of_unit(unit)
            if host:
                recompute_host(host)
        ta = tax_for_booking(booking["id"])
        if ta:
            res = occupancy_tax(new_term, booking["gross_rent_cents"])
            ta["assessed_term_days"] = new_term
            ta["taxable"] = res["taxable"]
            ta["occupancy_tax_cents"] = res["occupancy_tax_cents"]
            ta["exempt_reason"] = res["exempt_reason"]
            touch(ta)
        ext["status"] = "APPROVED"
        touch(ext)
    else:
        ext["status"] = to_status
        touch(ext)
    return respond(success_object(public(ext)))


# ===========================================================================
# Deposit
# ===========================================================================
@app.route("/deposits/<rid>", methods=["GET"])
def get_deposit(rid):
    return do_get("deposits", rid)


@app.route("/deposits", methods=["GET"])
def list_deposits():
    return do_list("deposits", {
        "booking_id": request.args.get("booking_id"),
        "status": request.args.get("status"),
    })


@app.route("/deposits/<rid>/settle", methods=["POST"])
def settle_deposit(rid):
    _, role = auth_context()
    require_role(role, {"ComplianceReviewer"})
    deposit = get_or_404("deposits", rid)
    if deposit["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Deposit not HELD")
    booking = booking_of_deposit(deposit)
    if not booking or booking["status"] != "COMPLETED":
        raise ApiError("ERR_DEPOSIT_NOT_SETTLEABLE", 409, "Booking not completed")
    for c in DB.tables["damage_claims"].values():
        if c["deposit_id"] == deposit["id"] and c["status"] in ("FILED", "DISPUTED"):
            raise ApiError("ERR_DEPOSIT_NOT_SETTLEABLE", 409, "Open damage claim exists")
    forfeited = deposit["forfeited_cents"]
    amount = deposit["amount_cents"]
    if forfeited == 0:
        deposit["refunded_cents"] = deposit["held_cents"]
        deposit["held_cents"] = 0
        deposit["status"] = "REFUNDED"
    elif forfeited < amount:
        deposit["refunded_cents"] = deposit["held_cents"]
        deposit["held_cents"] = 0
        deposit["status"] = "PARTIALLY_REFUNDED"
    else:  # forfeited == amount
        deposit["status"] = "FORFEITED"
    touch(deposit)
    return respond(success_object(public(deposit)))


# ===========================================================================
# DamageClaim
# ===========================================================================
@app.route("/damage-claims", methods=["POST"])
def create_damage_claim():
    uid, role = auth_context()
    require_role(role, {"Host"})
    body = get_json_body()
    deposit_id = body.get("deposit_id")
    if deposit_id is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: deposit_id")
    deposit = get_or_404("deposits", deposit_id)
    booking = booking_of_deposit(deposit)
    unit = unit_of_booking(booking) if booking else None
    if not unit or unit["host_id"] != uid:
        forbid()
    require_fields(body, ["expected_deposit_version", "claimed_cents", "description"])
    expected = as_int(body, "expected_deposit_version")
    claimed = as_int(body, "claimed_cents")
    if expected != deposit["version"]:
        raise ApiError("ERR_STALE_DEPOSIT_VERSION", 412, "Stale deposit version")
    claim = new_record({
        "deposit_id": deposit_id,
        "expected_deposit_version": expected,
        "claimed_cents": claimed,
        "approved_cents": 0,
        "description": body["description"],
        "tenant_response": None,
        "status": "FILED",
    })
    DB.tables["damage_claims"][claim["id"]] = claim
    touch(deposit)  # advance deposit version by 1
    return respond(success_object(public(claim), 201))


@app.route("/damage-claims/<rid>", methods=["GET"])
def get_damage_claim(rid):
    return do_get("damage_claims", rid)


@app.route("/damage-claims", methods=["GET"])
def list_damage_claims():
    return do_list("damage_claims", {
        "deposit_id": request.args.get("deposit_id"),
        "status": request.args.get("status"),
    })


@app.route("/damage-claims/<rid>/transitions", methods=["POST"])
def transition_damage_claim(rid):
    uid, role, claim, body, to_status = start_transition(
        "damage_claims", rid, {"Host", "Tenant", "ComplianceReviewer"},
        {"FILED", "DISPUTED", "APPROVED", "REJECTED", "WITHDRAWN"})
    deposit = lookup("deposits", claim["deposit_id"])
    booking = booking_of_deposit(deposit) if deposit else None
    unit = unit_of_booking(booking) if booking else None
    if to_status == "DISPUTED":
        if role != "Tenant" or not booking or booking["tenant_id"] != uid:
            forbid()
    elif to_status in ("FILED", "WITHDRAWN"):
        if role != "Host" or not unit or unit["host_id"] != uid:
            forbid()
    elif to_status in ("APPROVED", "REJECTED"):
        if role != "ComplianceReviewer":
            forbid()
    check_state(claim, to_status, {
        "DISPUTED": {"FILED"},
        "FILED": {"DISPUTED"},
        "APPROVED": {"FILED", "DISPUTED"},
        "REJECTED": {"FILED", "DISPUTED"},
        "WITHDRAWN": {"FILED"},
    })
    if to_status == "DISPUTED":
        if body.get("tenant_response") is not None:
            claim["tenant_response"] = body.get("tenant_response")
        claim["status"] = "DISPUTED"
        touch(claim)
    elif to_status == "FILED":
        if body.get("claimed_cents") is not None:
            claim["claimed_cents"] = as_int(body, "claimed_cents")
        claim["status"] = "FILED"
        touch(claim)
    elif to_status == "APPROVED":
        approved = as_int(body, "approved_cents")
        if deposit["status"] != "HELD":
            raise ApiError("ERR_CLAIM_WINDOW_CLOSED", 409, "Deposit not HELD")
        if approved > claim["claimed_cents"]:
            raise ApiError("ERR_APPROVED_EXCEEDS_CLAIMED", 422, "approved exceeds claimed")
        if approved > deposit["held_cents"]:
            raise ApiError("ERR_APPROVED_EXCEEDS_HELD", 409, "approved exceeds held")
        # cascade
        deposit["forfeited_cents"] += approved
        deposit["held_cents"] -= approved
        if deposit["held_cents"] == 0:
            deposit["status"] = "FORFEITED"
        touch(deposit)
        payout = payout_for_booking(deposit["booking_id"])
        if payout:
            payout["deposit_adjustment_cents"] = deposit["forfeited_cents"]
            recompute_payout_net(payout)
            touch(payout)
            host = lookup("hosts", payout["host_id"])
            if host:
                recompute_host(host)
        claim["approved_cents"] = approved
        claim["status"] = "APPROVED"
        touch(claim)
    else:  # REJECTED or WITHDRAWN
        claim["status"] = to_status
        touch(claim)
    return respond(success_object(public(claim)))


# ===========================================================================
# CoiPolicy
# ===========================================================================
@app.route("/coi-policies", methods=["POST"])
def create_coi_policy():
    uid, role = auth_context()
    require_role(role, {"Host", "Tenant"})
    body = get_json_body()
    booking_id = body.get("booking_id")
    if booking_id is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: booking_id")
    booking = get_or_404("bookings", booking_id)
    unit = unit_of_booking(booking)
    if role == "Host":
        if not unit or unit["host_id"] != uid:
            forbid()
    else:  # Tenant
        if booking["tenant_id"] != uid:
            forbid()
    require_fields(body, ["coverage_cents", "effective_start", "effective_end"])
    coverage = as_int(body, "coverage_cents")
    try:
        parse_date(body["effective_start"])
        parse_date(body["effective_end"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid effective date")
    coi = new_record({
        "booking_id": booking_id,
        "coverage_cents": coverage,
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "status": "PENDING",
    })
    DB.tables["coi_policies"][coi["id"]] = coi
    return respond(success_object(public(coi), 201))


@app.route("/coi-policies/<rid>", methods=["GET"])
def get_coi_policy(rid):
    return do_get("coi_policies", rid)


@app.route("/coi-policies", methods=["GET"])
def list_coi_policies():
    return do_list("coi_policies", {
        "booking_id": request.args.get("booking_id"),
        "status": request.args.get("status"),
    })


@app.route("/coi-policies/<rid>/transitions", methods=["POST"])
def transition_coi_policy(rid):
    uid, role, coi, body, to_status = start_transition(
        "coi_policies", rid, {"ComplianceReviewer", "PlatformAdmin"},
        {"PENDING", "ACTIVE", "EXPIRED", "REVOKED"})
    if to_status in ("ACTIVE", "REVOKED"):
        if role != "ComplianceReviewer":
            forbid()
    else:  # EXPIRED
        if role != "PlatformAdmin":
            forbid()
    check_state(coi, to_status, {
        "ACTIVE": {"PENDING"},
        "REVOKED": {"ACTIVE"},
        "EXPIRED": {"ACTIVE"},
    })
    if to_status == "ACTIVE":
        if coi["coverage_cents"] < COI_MIN_COVERAGE_CENTS:
            raise ApiError("ERR_COI_INSUFFICIENT_COVERAGE", 409, "Coverage below minimum")
        if parse_date(coi["effective_start"]) > parse_date(coi["effective_end"]):
            raise ApiError("ERR_DATE_RANGE_INVALID", 422, "effective_start after effective_end")
        coi["status"] = "ACTIVE"
        touch(coi)
    elif to_status == "EXPIRED":
        if not clock_reached(coi["effective_end"]):
            raise ApiError("ERR_INVALID_STATE", 409, "effective_end not reached")
        coi["status"] = "EXPIRED"
        touch(coi)
    else:  # REVOKED
        coi["status"] = "REVOKED"
        touch(coi)
    return respond(success_object(public(coi)))


# ===========================================================================
# Turnover
# ===========================================================================
@app.route("/turnovers/<rid>", methods=["GET"])
def get_turnover(rid):
    return do_get("turnovers", rid)


@app.route("/turnovers", methods=["GET"])
def list_turnovers():
    return do_list("turnovers", {
        "unit_id": request.args.get("unit_id"),
        "booking_id": request.args.get("booking_id"),
        "status": request.args.get("status"),
    })


@app.route("/turnovers/<rid>/transitions", methods=["POST"])
def transition_turnover(rid):
    uid, role, turnover, body, to_status = start_transition(
        "turnovers", rid, {"Host"},
        {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "SKIPPED"})
    unit = lookup("units", turnover["unit_id"])
    if not unit or unit["host_id"] != uid:
        forbid()
    check_state(turnover, to_status, {
        "IN_PROGRESS": {"SCHEDULED"},
        "COMPLETED": {"IN_PROGRESS"},
        "SKIPPED": {"SCHEDULED"},
    })
    if to_status == "IN_PROGRESS":
        booking = lookup("bookings", turnover["booking_id"])
        if not booking or booking["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", 409, "Booking not completed")
    turnover["status"] = to_status
    touch(turnover)
    return respond(success_object(public(turnover)))


# ===========================================================================
# Payout
# ===========================================================================
@app.route("/payouts/<rid>", methods=["GET"])
def get_payout(rid):
    return do_get("payouts", rid)


@app.route("/payouts", methods=["GET"])
def list_payouts():
    return do_list("payouts", {
        "booking_id": request.args.get("booking_id"),
        "host_id": request.args.get("host_id"),
        "status": request.args.get("status"),
    })


@app.route("/payouts/<rid>/transitions", methods=["POST"])
def transition_payout(rid):
    uid, role, payout, body, to_status = start_transition(
        "payouts", rid, {"PlatformAdmin"},
        {"PENDING", "SCHEDULED", "PAID", "REVERSED", "VOIDED"})
    check_state(payout, to_status, {
        "SCHEDULED": {"PENDING"},
        "PAID": {"SCHEDULED"},
        "REVERSED": {"PAID"},
        "VOIDED": {"PENDING"},
    })
    host = lookup("hosts", payout["host_id"])
    if to_status == "SCHEDULED":
        booking = lookup("bookings", payout["booking_id"])
        if not booking or booking["status"] != "COMPLETED":
            raise ApiError("ERR_BOOKING_NOT_COMPLETED", 409, "Booking not completed")
        if not host or host["payout_account_status"] != "VERIFIED":
            raise ApiError("ERR_HOST_PAYOUT_NOT_VERIFIED", 409, "Host payout not verified")
        payout["scheduled_by_user_id"] = uid
        payout["status"] = "SCHEDULED"
        touch(payout)
        if host:
            recompute_host(host)
    elif to_status == "PAID":
        if uid == payout.get("scheduled_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Same operator cannot pay")
        payout["status"] = "PAID"
        touch(payout)
        if host:
            recompute_host(host)
    elif to_status == "REVERSED":
        payout["status"] = "REVERSED"
        touch(payout)
        if host:
            recompute_host(host)
    else:  # VOIDED
        payout["status"] = "VOIDED"
        touch(payout)
        if host:
            recompute_host(host)
    return respond(success_object(public(payout)))


# ===========================================================================
# TaxAssessment
# ===========================================================================
@app.route("/tax-assessments/<rid>", methods=["GET"])
def get_tax_assessment(rid):
    return do_get("tax_assessments", rid)


@app.route("/tax-assessments", methods=["GET"])
def list_tax_assessments():
    return do_list("tax_assessments", {
        "booking_id": request.args.get("booking_id"),
    })


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    if body.get("to_iso8601") is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing to_iso8601")
    try:
        DB.clock = _parse_iso(body["to_iso8601"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid to_iso8601")
    return respond(success_object({}))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
