"""Per-Diem Healthcare Staffing API — Flask entry point and routes."""
import os

from flask import Flask, request

import store
from store import db, now, parse_iso, render_dt
import logic
from logic import (stamp_new, bump, order_of_shift, facility_of_order,
                   facility_of_shift, shift_of_assignment, order_of_assignment,
                   facility_of_assignment, facility_id_of_assignment,
                   assignment_of_timesheet)
from envelope import (AppError, require, get_identity, get_body, pagination,
                      paginate, object_response, raw_object_response,
                      array_response, error_response)

app = Flask(__name__)


@app.errorhandler(AppError)
def _handle_app_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(AppError("ERR_VALIDATION", "Unknown route."))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(AppError("ERR_VALIDATION", "Method not allowed."))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, AppError):
        return error_response(err)
    return error_response(AppError("ERR_VALIDATION", "Internal error: %s" % err))


# ---------------------------------------------------------------------------
# Validation helpers (raise ERR_VALIDATION)
# ---------------------------------------------------------------------------
def v_required(body, key):
    if key not in body or body[key] is None:
        raise AppError("ERR_VALIDATION", "Missing required field: %s" % key)
    return body[key]


def v_str(body, key, required=True, minlen=None, maxlen=None):
    if key not in body or body[key] is None:
        if required:
            raise AppError("ERR_VALIDATION", "Missing required field: %s" % key)
        return None
    val = body[key]
    if not isinstance(val, str):
        raise AppError("ERR_VALIDATION", "%s must be a string" % key)
    if minlen is not None and len(val) < minlen:
        raise AppError("ERR_VALIDATION", "%s too short" % key)
    if maxlen is not None and len(val) > maxlen:
        raise AppError("ERR_VALIDATION", "%s too long" % key)
    return val


def v_int(body, key, required=True, lo=None, hi=None):
    if key not in body or body[key] is None:
        if required:
            raise AppError("ERR_VALIDATION", "Missing required field: %s" % key)
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise AppError("ERR_VALIDATION", "%s must be an integer" % key)
    if lo is not None and val < lo:
        raise AppError("ERR_VALIDATION", "%s below minimum" % key)
    if hi is not None and val > hi:
        raise AppError("ERR_VALIDATION", "%s above maximum" % key)
    return val


def v_enum(body, key, allowed, required=True):
    if key not in body or body[key] is None:
        if required:
            raise AppError("ERR_VALIDATION", "Missing required field: %s" % key)
        return None
    val = body[key]
    if val not in allowed:
        raise AppError("ERR_VALIDATION", "%s invalid enum member" % key)
    return val


def v_datetime(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise AppError("ERR_VALIDATION", "Missing required field: %s" % key)
        return None
    val = body[key]
    if not isinstance(val, str) or not store.is_iso_datetime(val):
        raise AppError("ERR_VALIDATION", "%s must be an ISO 8601 datetime" % key)
    return val


def resolve(table, entity_id, err_id):
    ent = table.get(entity_id)
    if ent is None:
        raise AppError(err_id, "%s does not resolve" % entity_id)
    return ent


def scope_facility(role, user_id, facility_id):
    """Facility-role ownership check (ERR_ROLE_SCOPE_VIOLATION)."""
    if role in ("FacilityScheduler", "FacilityVerifier"):
        if user_id != facility_id:
            raise AppError("ERR_ROLE_SCOPE_VIOLATION",
                           "Facility principal acting outside its own facility.")


def owner_clinician(role, user_id, clinician_id):
    if role == "Clinician" and user_id != clinician_id:
        raise AppError("ERR_NOT_OWNER", "Clinician acting on another clinician's resource.")


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/staffing/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["PlatformAdmin"])
    body = get_body()
    to_iso = v_datetime(body, "to_iso8601", required=True)
    db.clock = parse_iso(to_iso)
    return raw_object_response({"current_utc": now()}, 200)


# ===========================================================================
# Facilities & rate cards
# ===========================================================================
@app.route("/staffing/facilities", methods=["POST"])
def create_facility():
    require(["PlatformAdmin"])
    body = get_body()
    name = v_str(body, "name", True, 1, 120)
    unit_name = v_str(body, "unit_name", True, 1, 60)
    unit_capacity = v_int(body, "unit_capacity", True, 1, 20)
    req_types = body.get("required_credential_types")
    if not isinstance(req_types, list) or len(req_types) == 0:
        raise AppError("ERR_VALIDATION", "required_credential_types must be a non-empty array")
    for t in req_types:
        if t not in store.CREDENTIAL_TYPES:
            raise AppError("ERR_VALIDATION", "invalid credential type: %s" % t)
    fac = stamp_new({
        "name": name,
        "unit_name": unit_name,
        "unit_capacity": unit_capacity,
        "required_credential_types": list(req_types),
        "pending_pay_cents": 0,
        "outstanding_balance_cents": 0,
        "lifetime_billed_cents": 0,
    })
    db.facilities[fac["id"]] = fac
    return object_response(fac, 201)


@app.route("/staffing/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    require(["PlatformAdmin", "ComplianceOfficer", "FacilityScheduler",
             "FacilityVerifier", "BillingAgent"])
    fac = resolve(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    return object_response(fac, 200)


@app.route("/staffing/facilities/<fid>/rate-cards", methods=["POST"])
def create_rate_card(fid):
    user_id, role = require(["PlatformAdmin", "FacilityScheduler"])
    fac = resolve(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    scope_facility(role, user_id, fid)
    body = get_body()
    specialty = v_enum(body, "specialty", store.SPECIALTIES, True)
    rate = v_int(body, "base_pay_rate_cents_per_hour", True, 1000, 50000)
    eff_from = v_datetime(body, "effective_from", True)
    eff_to = v_datetime(body, "effective_to", required=False)
    rc = stamp_new({
        "facility_id": fid,
        "specialty": specialty,
        "base_pay_rate_cents_per_hour": rate,
        "effective_from": eff_from,
        "effective_to": eff_to,
    })
    db.rate_cards[rc["id"]] = rc
    return object_response(rc, 201)


@app.route("/staffing/facilities/<fid>/rate-cards", methods=["GET"])
def list_rate_cards(fid):
    require(["PlatformAdmin", "ComplianceOfficer", "FacilityScheduler",
             "FacilityVerifier", "BillingAgent"])
    resolve(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    specialty = request.args.get("specialty")
    items = [rc for rc in db.rate_cards.values() if rc["facility_id"] == fid]
    if specialty:
        items = [rc for rc in items if rc["specialty"] == specialty]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


# ===========================================================================
# Clinicians & credentials
# ===========================================================================
@app.route("/staffing/clinicians", methods=["POST"])
def create_clinician():
    require(["PlatformAdmin"])
    body = get_body()
    full_name = v_str(body, "full_name", True, 1, 120)
    email = v_str(body, "email", True, 1, None)
    specialty = v_enum(body, "specialty", store.SPECIALTIES, True)
    for c in db.clinicians.values():
        if c["email"] == email:
            raise AppError("ERR_VALIDATION", "email must be unique")
    clin = stamp_new({
        "full_name": full_name,
        "email": email,
        "specialty": specialty,
        "status": "ACTIVE",
        "reliability_score": 100,
        "provisional_reliability_score": 100,
        "no_show_count": 0,
        "completed_shift_count": 0,
    })
    db.clinicians[clin["id"]] = clin
    return object_response(clin, 201)


@app.route("/staffing/clinicians/<cid>", methods=["GET"])
def get_clinician(cid):
    require(["PlatformAdmin", "ComplianceOfficer", "FacilityScheduler",
             "FacilityVerifier", "Clinician"])
    clin = resolve(db.clinicians, cid, "ERR_CLINICIAN_NOT_FOUND")
    return object_response(clin, 200)


@app.route("/staffing/clinicians/<cid>/credentials", methods=["POST"])
def create_credential(cid):
    user_id, role = require(["PlatformAdmin", "Clinician"])
    resolve(db.clinicians, cid, "ERR_CLINICIAN_NOT_FOUND")
    owner_clinician(role, user_id, cid)
    body = get_body()
    ctype = v_enum(body, "credential_type", store.CREDENTIAL_TYPES, True)
    license_number = v_str(body, "license_number", True, 1, 40)
    issued_on = v_datetime(body, "issued_on", True)
    expires_on = v_datetime(body, "expires_on", True)
    if not (parse_iso(expires_on) > parse_iso(issued_on)):
        raise AppError("ERR_VALIDATION", "expires_on must be strictly after issued_on")
    for c in db.credentials.values():
        if (c["clinician_id"] == cid and c["credential_type"] == ctype
                and c["status"] != "REVOKED"):
            raise AppError("ERR_VALIDATION", "duplicate (clinician, credential_type)")
    cred = stamp_new({
        "clinician_id": cid,
        "credential_type": ctype,
        "license_number": license_number,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "PENDING_VERIFICATION",
        "verified_at": None,
        "verified_by_user_id": None,
        "decision_note": None,
    })
    db.credentials[cred["id"]] = cred
    return object_response(cred, 201)


@app.route("/staffing/clinicians/<cid>/credentials", methods=["GET"])
def list_credentials(cid):
    require(["PlatformAdmin", "ComplianceOfficer", "FacilityScheduler", "Clinician"])
    resolve(db.clinicians, cid, "ERR_CLINICIAN_NOT_FOUND")
    items = [c for c in db.credentials.values() if c["clinician_id"] == cid]
    for c in items:
        logic.materialize_expiry(c)
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/credentials/<crid>/verify", methods=["POST"])
def verify_credential(crid):
    user_id, role = require(["ComplianceOfficer"])
    cred = resolve(db.credentials, crid, "ERR_CREDENTIAL_NOT_FOUND")
    body = get_body()
    decision = v_enum(body, "decision", {"VERIFIED", "REJECTED"}, True)
    supplied_expires = v_datetime(body, "expires_on", required=False)
    note = v_str(body, "note", required=False, maxlen=None)
    logic.materialize_expiry(cred)
    if cred["status"] not in ("PENDING_VERIFICATION", "EXPIRED"):
        raise AppError("ERR_CREDENTIAL_NOT_PENDING", "credential not pending or expired")
    if cred["status"] == "EXPIRED":
        if decision != "VERIFIED":
            raise AppError("ERR_CREDENTIAL_NOT_PENDING", "expired credential can only be renewed")
        if supplied_expires is None or not (parse_iso(supplied_expires) > now()):
            raise AppError("ERR_VALIDATION", "renewal requires a future expires_on")
        cred["status"] = "VERIFIED"
        cred["expires_on"] = supplied_expires
        cred["verified_at"] = now()
        cred["verified_by_user_id"] = user_id
        bump(cred)
    else:  # PENDING_VERIFICATION
        if decision == "VERIFIED":
            effective_expires = supplied_expires if supplied_expires is not None else cred["expires_on"]
            if effective_expires is None or not (parse_iso(effective_expires) > now()):
                raise AppError("ERR_VALIDATION", "expires_on must be in the future to verify")
            cred["status"] = "VERIFIED"
            if supplied_expires is not None:
                cred["expires_on"] = supplied_expires
            cred["verified_at"] = now()
            cred["verified_by_user_id"] = user_id
            bump(cred)
        else:  # REJECTED
            cred["status"] = "REJECTED"
            cred["decision_note"] = note
            bump(cred)
    return object_response(cred, 200)


@app.route("/staffing/credentials/<crid>/revoke", methods=["POST"])
def revoke_credential(crid):
    require(["ComplianceOfficer"])
    cred = resolve(db.credentials, crid, "ERR_CREDENTIAL_NOT_FOUND")
    body = get_body()
    reason = v_str(body, "reason", True, 1, None)
    logic.materialize_expiry(cred)
    if cred["status"] not in ("VERIFIED", "EXPIRED"):
        raise AppError("ERR_CREDENTIAL_NOT_PENDING", "credential not revocable")
    cred["status"] = "REVOKED"
    cred["decision_note"] = reason
    bump(cred)
    return object_response(cred, 200)


# ===========================================================================
# Orders & shifts
# ===========================================================================
@app.route("/staffing/orders", methods=["POST"])
def create_order():
    user_id, role = require(["FacilityScheduler"])
    body = get_body()
    fid = body.get("facility_id")
    if not isinstance(fid, str):
        raise AppError("ERR_VALIDATION", "facility_id is required")
    resolve(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    scope_facility(role, user_id, fid)
    specialty = v_enum(body, "specialty", store.SPECIALTIES, True)
    headcount = v_int(body, "headcount", True, 1, store.MAX_ORDER_HEADCOUNT)
    urgency = v_enum(body, "urgency", {"STANDARD", "CRISIS"}, True)
    window_start = v_datetime(body, "window_start", True)
    window_end = v_datetime(body, "window_end", True)
    order = stamp_new({
        "facility_id": fid,
        "specialty": specialty,
        "headcount": headcount,
        "urgency": urgency,
        "window_start": window_start,
        "window_end": window_end,
        "status": "OPEN",
        "shift_count": 0,
        "open_count": 0,
        "filled_count": 0,
        "completed_count": 0,
        "cancelled_count": 0,
    })
    db.orders[order["id"]] = order
    return object_response(order, 201)


@app.route("/staffing/orders/<oid>", methods=["GET"])
def get_order(oid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier",
             "Clinician", "BillingAgent"])
    order = resolve(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    return object_response(order, 200)


@app.route("/staffing/facilities/<fid>/orders", methods=["GET"])
def list_facility_orders(fid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier", "BillingAgent"])
    resolve(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    items = [o for o in db.orders.values() if o["facility_id"] == fid]
    status = request.args.get("status")
    if status:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/orders/<oid>/shifts", methods=["POST"])
def create_shift(oid):
    user_id, role = require(["FacilityScheduler"])
    order = resolve(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    facility = facility_of_order(order)
    scope_facility(role, user_id, order["facility_id"])
    body = get_body()
    sched_start = v_datetime(body, "scheduled_start", True)
    sched_end = v_datetime(body, "scheduled_end", True)
    start = parse_iso(sched_start)
    end = parse_iso(sched_end)

    # duration (priority 56)
    from decimal import Decimal as _D
    dur_hours = _D(str((end - start).total_seconds())) / _D(3600)
    if not (end > start) or dur_hours < _D(str(store.MIN_SHIFT_DURATION_HOURS)) \
            or dur_hours > _D(str(store.MAX_SHIFT_DURATION_HOURS)):
        raise AppError("ERR_SHIFT_DURATION_INVALID", "shift duration invalid")

    # within order window (priority 57)
    w_start = parse_iso(order["window_start"])
    w_end = parse_iso(order["window_end"])
    if start < w_start or end > w_end:
        raise AppError("ERR_SHIFT_OUTSIDE_ORDER_WINDOW", "shift outside order window")

    # order-open state (priority 60)
    if order["status"] in ("CLOSED", "CANCELLED"):
        raise AppError("ERR_ORDER_NOT_OPEN", "order not open")

    # unit capacity (priority 88)
    fid = order["facility_id"]
    concurrent = 1  # counting the shift being created
    for s in db.shifts.values():
        if s["status"] not in ("OPEN", "ASSIGNED", "COMPLETED"):
            continue
        if facility_of_shift(s)["id"] != fid:
            continue
        os = parse_iso(s["scheduled_start"])
        oe = parse_iso(s["scheduled_end"])
        # closed-interval intersection (touching counts)
        if start <= oe and os <= end:
            concurrent += 1
    if concurrent > facility["unit_capacity"]:
        raise AppError("ERR_UNIT_CAPACITY_EXCEEDED", "unit capacity exceeded")

    # headcount (priority 89)
    active_shifts = sum(1 for s in logic.order_shifts(oid) if s["status"] != "CANCELLED")
    if active_shifts + 1 > order["headcount"]:
        raise AppError("ERR_HEADCOUNT_EXCEEDED", "headcount exceeded")

    # rate card (priority 95)
    card = logic.select_rate_card(fid, order["specialty"], start)
    if card is None:
        raise AppError("ERR_RATE_CARD_NOT_FOUND", "no selectable rate card")

    base_rate = card["base_pay_rate_cents_per_hour"]
    if order["urgency"] == "CRISIS":
        effective_rate = store.rhu_cents(_D(base_rate) * store.CRISIS_RATE_MULTIPLIER)
    else:
        effective_rate = base_rate

    shift = stamp_new({
        "order_id": oid,
        "scheduled_start": sched_start,
        "scheduled_end": sched_end,
        "status": "OPEN",
        "claim_count": 0,
        "scheduled_hours": float(logic.scheduled_hours(start, end)),
        "estimated_hours": None,
        "estimated_pay_cents": None,
        "base_pay_rate_cents_per_hour": base_rate,
        "effective_rate_cents_per_hour": effective_rate,
    })
    logic.compute_estimated(shift)
    db.shifts[shift["id"]] = shift
    logic.order_fill_posture(order)
    return object_response(shift, 201)


@app.route("/staffing/orders/<oid>/shifts", methods=["GET"])
def list_order_shifts(oid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier", "Clinician"])
    resolve(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    items = [s for s in db.shifts.values() if s["order_id"] == oid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = require(["FacilityScheduler"])
    order = resolve(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    scope_facility(role, user_id, order["facility_id"])
    body = get_body()
    reason = v_str(body, "reason", True, 1, None)
    if order["status"] not in ("OPEN", "PARTIALLY_FILLED", "FILLED"):
        raise AppError("ERR_ORDER_NOT_OPEN", "order not cancellable")

    affected_clinicians = set()
    for shift in logic.order_shifts(oid):
        if shift["status"] not in ("OPEN", "ASSIGNED"):
            continue
        # LINK 1 — cancel the shift
        shift["status"] = "CANCELLED"
        bump(shift)
        # LINK 2 — cancel live assignments on this shift
        for a in db.assignments.values():
            if a["shift_id"] != shift["id"]:
                continue
            if a["work_status"] in ("PENDING_CONFIRMATION", "CONFIRMED"):
                a["work_status"] = "CANCELLED_BY_FACILITY"
                a["pay_status"] = "WAIVED"
                a["cancellation_reason"] = reason
                lead = logic.hours_2dp(
                    (parse_iso(shift["scheduled_start"]) - now()).total_seconds() / 3600)
                a["cancellation_lead_hours"] = float(lead)
                clin = db.clinicians[a["clinician_id"]]
                # LINK 3 — facility cancellation credit
                logic.append_reliability_event(
                    clin, a["id"], "FACILITY_CANCELLATION_CREDIT", 0,
                    store.FACILITY_CANCELLATION_CREDIT_POINTS, "CONFIRMED",
                    "Order cancelled by facility")
                bump(a)
                affected_clinicians.add(clin["id"])
        # decline remaining PENDING claims on this shift
        for c in db.claims.values():
            if c["shift_id"] == shift["id"] and c["status"] == "PENDING":
                c["status"] = "DECLINED"
                bump(c)
        logic.recompute_claim_count(shift)

    # LINK 4 — reliability recompute for each affected clinician
    for cid in affected_clinicians:
        logic.reliability_recompute(db.clinicians[cid])

    order["status"] = "CANCELLED"
    # refresh counters without flipping status back
    shifts = logic.order_shifts(oid)
    order["shift_count"] = len(shifts)
    order["open_count"] = sum(1 for s in shifts if s["status"] == "OPEN")
    order["filled_count"] = sum(1 for s in shifts if s["status"] in ("ASSIGNED", "COMPLETED"))
    order["completed_count"] = sum(1 for s in shifts if s["status"] == "COMPLETED")
    order["cancelled_count"] = sum(1 for s in shifts if s["status"] == "CANCELLED")
    bump(order)
    return object_response(order, 200)


@app.route("/staffing/shifts/<sid>", methods=["GET"])
def get_shift(sid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier", "Clinician"])
    shift = resolve(db.shifts, sid, "ERR_SHIFT_NOT_FOUND")
    return object_response(shift, 200)


# ===========================================================================
# Claims
# ===========================================================================
@app.route("/staffing/shifts/<sid>/claims", methods=["POST"])
def create_claim(sid):
    user_id, role = require(["Clinician"])
    shift = resolve(db.shifts, sid, "ERR_SHIFT_NOT_FOUND")
    body = get_body()
    cid = body.get("clinician_id")
    if not isinstance(cid, str):
        raise AppError("ERR_VALIDATION", "clinician_id is required")
    clin = resolve(db.clinicians, cid, "ERR_CLINICIAN_NOT_FOUND")
    owner_clinician(role, user_id, cid)
    note = v_str(body, "note", required=False, maxlen=None)

    # state (priority 60)
    if shift["status"] != "OPEN":
        raise AppError("ERR_SHIFT_NOT_OPEN", "shift not open")
    # suspended (priority 65)
    if clin["status"] != "ACTIVE":
        raise AppError("ERR_CLINICIAN_SUSPENDED", "clinician suspended")

    # credential gate (priority 75/76)
    err = logic.credential_gate(cid, shift)
    if err:
        raise AppError(err)
    # claim window (priority 80)
    lock_instant = parse_iso(shift["scheduled_start"]) - \
        logic.timedelta(hours=store.SHIFT_CLAIM_LOCK_HOURS)
    if now() > lock_instant:
        raise AppError("ERR_CLAIM_WINDOW_CLOSED", "claim window closed")
    # duplicate claim (priority 85)
    for c in db.claims.values():
        if c["shift_id"] == sid and c["clinician_id"] == cid \
                and c["status"] in ("PENDING", "AWARDED"):
            raise AppError("ERR_DUPLICATE_CLAIM", "duplicate claim")
    # overlap (86)
    err = logic.overlap_gate(cid, shift)
    if err:
        raise AppError(err)
    # rest (87)
    err = logic.rest_gate(cid, shift)
    if err:
        raise AppError(err)
    # weekly hours (90)
    err = logic.weekly_hours_gate(cid, shift)
    if err:
        raise AppError(err)
    # claim limit (91)
    pending = sum(1 for c in db.claims.values()
                  if c["clinician_id"] == cid and c["status"] == "PENDING")
    if pending >= store.MAX_OPEN_CLAIMS_PER_CLINICIAN:
        raise AppError("ERR_CLAIM_LIMIT_EXCEEDED", "claim limit exceeded")

    claim = stamp_new({
        "shift_id": sid,
        "clinician_id": cid,
        "status": "PENDING",
        "note": note,
        "claimed_at": now(),
        "reliability_snapshot": clin["reliability_score"],
    })
    db.claims[claim["id"]] = claim
    logic.recompute_claim_count(shift)
    return object_response(claim, 201)


@app.route("/staffing/claims/<clid>", methods=["GET"])
def get_claim(clid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier", "Clinician"])
    claim = resolve(db.claims, clid, "ERR_CLAIM_NOT_FOUND")
    return object_response(claim, 200)


@app.route("/staffing/claims", methods=["GET"])
def list_claims():
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier", "Clinician"])
    items = list(db.claims.values())
    shift_id = request.args.get("shift_id")
    clinician_id = request.args.get("clinician_id")
    status = request.args.get("status")
    if shift_id:
        items = [c for c in items if c["shift_id"] == shift_id]
    if clinician_id:
        items = [c for c in items if c["clinician_id"] == clinician_id]
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/claims/<clid>/withdraw", methods=["POST"])
def withdraw_claim(clid):
    user_id, role = require(["Clinician"])
    claim = resolve(db.claims, clid, "ERR_CLAIM_NOT_FOUND")
    owner_clinician(role, user_id, claim["clinician_id"])
    if claim["status"] != "PENDING":
        raise AppError("ERR_CLAIM_NOT_PENDING", "claim not pending")
    claim["status"] = "WITHDRAWN"
    bump(claim)
    logic.recompute_claim_count(db.shifts[claim["shift_id"]])
    return object_response(claim, 200)


@app.route("/staffing/shifts/<sid>/award", methods=["POST"])
def award_shift(sid):
    user_id, role = require(["FacilityScheduler"])
    shift = resolve(db.shifts, sid, "ERR_SHIFT_NOT_FOUND")
    body = get_body()
    claim_id = body.get("claim_id")
    named_claim = None
    if claim_id is not None:
        if not isinstance(claim_id, str):
            raise AppError("ERR_VALIDATION", "claim_id must be a string")
        named_claim = db.claims.get(claim_id)
        if named_claim is None or named_claim["shift_id"] != sid:
            raise AppError("ERR_CLAIM_NOT_FOUND", "claim not found on this shift")
    # scope (40)
    scope_facility(role, user_id, facility_of_shift(shift)["id"])
    # schema (50)
    expected = v_int(body, "expected_shift_version", True)
    # state (60): shift open
    if shift["status"] != "OPEN":
        raise AppError("ERR_SHIFT_NOT_OPEN", "shift not open")

    if named_claim is not None:
        # claim-pending (60)
        if named_claim["status"] != "PENDING":
            raise AppError("ERR_CLAIM_NOT_PENDING", "claim not pending")
        target_clin = db.clinicians[named_claim["clinician_id"]]
        # suspended (65)
        if target_clin["status"] != "ACTIVE":
            raise AppError("ERR_CLINICIAN_SUSPENDED", "clinician suspended")
        # OCC (70)
        if expected != shift["version"]:
            raise AppError("ERR_STALE_SHIFT_VERSION", "stale shift version")
        # eligibility gates (75/76/86/87/90)
        err = logic.eligibility_gates(target_clin["id"], shift)
        if err:
            raise AppError(err)
        winner = named_claim
    else:
        # OCC (70)
        if expected != shift["version"]:
            raise AppError("ERR_STALE_SHIFT_VERSION", "stale shift version")
        winner = _select_winner(shift)
        if winner is None:
            raise AppError("ERR_NO_ELIGIBLE_CLAIM", "no eligible claim")

    # backfill link
    replaces = None
    prior = [a for a in db.assignments.values()
             if a["shift_id"] == sid
             and a["work_status"] in ("CANCELLED_BY_CLINICIAN",
                                      "CANCELLED_BY_FACILITY", "NO_SHOW")]
    if prior:
        prior.sort(key=lambda a: (a["created_at"], a["_seq"]))
        replaces = prior[-1]["id"]

    assignment = stamp_new({
        "shift_id": sid,
        "clinician_id": winner["clinician_id"],
        "claim_id": winner["id"],
        "replaces_assignment_id": replaces,
        "work_status": "PENDING_CONFIRMATION",
        "pay_status": "UNBILLED",
        "awarded_at": now(),
        "confirmed_at": None,
        "estimated_pay_cents": shift["estimated_pay_cents"],
        "final_pay_cents": None,
        "cancellation_lead_hours": None,
        "cancellation_reason": None,
    })
    db.assignments[assignment["id"]] = assignment

    winner["status"] = "AWARDED"
    bump(winner)
    for c in db.claims.values():
        if c["shift_id"] == sid and c["status"] == "PENDING" and c["id"] != winner["id"]:
            c["status"] = "DECLINED"
            bump(c)
    shift["status"] = "ASSIGNED"
    shift["claim_count"] = sum(1 for c in db.claims.values()
                               if c["shift_id"] == sid and c["status"] == "PENDING")
    bump(shift)
    logic.order_fill_posture(order_of_shift(shift))
    return object_response(assignment, 201)


def _select_winner(shift):
    candidates = []
    for c in db.claims.values():
        if c["shift_id"] != shift["id"] or c["status"] != "PENDING":
            continue
        clin = db.clinicians[c["clinician_id"]]
        if clin["status"] != "ACTIVE":
            continue
        if logic.eligibility_gates(clin["id"], shift):
            continue
        candidates.append((c, clin))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (
        -pair[1]["reliability_score"],
        pair[0]["claimed_at"],
        pair[0]["created_at"],
        pair[0]["_seq"],
    ))
    return candidates[0][0]


# ===========================================================================
# Assignments & attendance
# ===========================================================================
@app.route("/staffing/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier",
             "Clinician", "BillingAgent"])
    a = resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    return object_response(a, 200)


@app.route("/staffing/assignments", methods=["GET"])
def list_assignments():
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier",
             "Clinician", "BillingAgent"])
    items = list(db.assignments.values())
    for key in ("shift_id", "clinician_id", "claim_id", "replaces_assignment_id",
                "work_status", "pay_status"):
        val = request.args.get(key)
        if val:
            items = [a for a in items if a[key] == val]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/assignments/<aid>/confirm", methods=["POST"])
def confirm_assignment(aid):
    user_id, role = require(["Clinician"])
    a = resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    owner_clinician(role, user_id, a["clinician_id"])
    if a["work_status"] != "PENDING_CONFIRMATION":
        raise AppError("ERR_ASSIGNMENT_NOT_CANCELLABLE", "assignment not confirmable")
    clin = db.clinicians[a["clinician_id"]]
    if clin["status"] != "ACTIVE":
        raise AppError("ERR_CLINICIAN_SUSPENDED", "clinician suspended")
    a["work_status"] = "CONFIRMED"
    a["confirmed_at"] = now()
    bump(a)
    return object_response(a, 200)


def _release_shift(shift):
    """Return an ASSIGNED shift to OPEN and recompute the order posture."""
    if shift["status"] == "ASSIGNED":
        shift["status"] = "OPEN"
        bump(shift)
        logic.order_fill_posture(order_of_shift(shift))


@app.route("/staffing/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    user_id, role = require(["Clinician", "FacilityScheduler"])
    a = resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    if role == "FacilityScheduler":
        scope_facility(role, user_id, facility_id_of_assignment(a))
    else:
        owner_clinician(role, user_id, a["clinician_id"])
    body = get_body()
    reason = v_str(body, "reason", True, 1, None)
    if a["work_status"] not in ("PENDING_CONFIRMATION", "CONFIRMED"):
        raise AppError("ERR_ASSIGNMENT_NOT_CANCELLABLE", "assignment not cancellable")

    shift = shift_of_assignment(a)
    lead = logic.hours_2dp(
        (parse_iso(shift["scheduled_start"]) - now()).total_seconds() / 3600)
    a["pay_status"] = "WAIVED"
    a["cancellation_reason"] = reason
    a["cancellation_lead_hours"] = float(lead)
    clin = db.clinicians[a["clinician_id"]]

    if role == "FacilityScheduler":
        a["work_status"] = "CANCELLED_BY_FACILITY"
        logic.append_reliability_event(
            clin, a["id"], "FACILITY_CANCELLATION_CREDIT", 0,
            store.FACILITY_CANCELLATION_CREDIT_POINTS, "CONFIRMED",
            "Assignment cancelled by facility")
    else:
        a["work_status"] = "CANCELLED_BY_CLINICIAN"
        from decimal import Decimal as _D
        if lead >= store.CANCELLATION_FREE_HOURS:
            pass  # no reliability event
        elif lead >= store.CANCELLATION_LATE_HOURS:
            logic.append_reliability_event(
                clin, a["id"], "LATE_CANCELLATION",
                store.CANCEL_PENALTY_POINTS_LATE, 0, "PENDING",
                "Late cancellation by clinician")
        else:
            logic.append_reliability_event(
                clin, a["id"], "VERY_LATE_CANCELLATION",
                store.CANCEL_PENALTY_POINTS_VERY_LATE, 0, "PENDING",
                "Very late cancellation by clinician")
    bump(a)
    logic.reliability_recompute(clin)
    _release_shift(shift)
    return object_response(a, 200)


@app.route("/staffing/assignments/<aid>/no-show", methods=["POST"])
def no_show_assignment(aid):
    user_id, role = require(["FacilityVerifier"])
    a = resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    scope_facility(role, user_id, facility_id_of_assignment(a))
    get_body()  # optional note; not persisted
    if a["work_status"] != "CONFIRMED":
        raise AppError("ERR_ASSIGNMENT_NOT_CONFIRMED", "assignment not confirmed")
    shift = shift_of_assignment(a)
    lead = logic.hours_2dp(
        (parse_iso(shift["scheduled_start"]) - now()).total_seconds() / 3600)
    a["work_status"] = "NO_SHOW"
    a["pay_status"] = "WAIVED"
    a["cancellation_lead_hours"] = float(lead)
    clin = db.clinicians[a["clinician_id"]]
    logic.append_reliability_event(
        clin, a["id"], "NO_SHOW", store.NO_SHOW_PENALTY_POINTS, 0, "PENDING",
        "No-show recorded by facility")
    bump(a)
    logic.reliability_recompute(clin)
    _release_shift(shift)
    return object_response(a, 200)


@app.route("/staffing/assignments/<aid>/timesheets", methods=["POST"])
def submit_timesheet(aid):
    user_id, role = require(["Clinician"])
    a = resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    owner_clinician(role, user_id, a["clinician_id"])
    body = get_body()
    clock_in = v_datetime(body, "clock_in", True)
    clock_out = v_datetime(body, "clock_out", True)
    break_minutes = v_int(body, "break_minutes", True, 0, 240)
    ci = parse_iso(clock_in)
    co = parse_iso(clock_out)
    shift = shift_of_assignment(a)
    start = parse_iso(shift["scheduled_start"])
    end = parse_iso(shift["scheduled_end"])
    # punch interval (55)
    lo = start - logic.timedelta(hours=4)
    hi = end + logic.timedelta(hours=4)
    if not (co > ci) or ci < lo or co > hi:
        raise AppError("ERR_INVALID_PUNCH_INTERVAL", "invalid punch interval")
    # state / single-submission (60/61)
    if a["work_status"] != "CONFIRMED" or a["pay_status"] != "UNBILLED":
        raise AppError("ERR_ASSIGNMENT_NOT_CONFIRMED", "assignment not confirmed")
    # shift-ended (81)
    if now() < end:
        raise AppError("ERR_SHIFT_NOT_ENDED", "shift has not ended")
    # timesheet window (82)
    if now() > end + logic.timedelta(days=store.TIMESHEET_SUBMISSION_WINDOW_DAYS):
        raise AppError("ERR_TIMESHEET_WINDOW_CLOSED", "timesheet window closed")

    raw = logic.whole_minutes(ci, co)
    unpaid = logic.deemed_unpaid_break(raw, break_minutes)
    worked = logic.worked_hours_from(raw, unpaid)
    night, weekend = logic.differential_hours(ci, co)

    ts = stamp_new({
        "assignment_id": aid,
        "invoice_id": None,
        "clock_in": clock_in,
        "clock_out": clock_out,
        "break_minutes": break_minutes,
        "raw_minutes": raw,
        "unpaid_break_minutes": unpaid,
        "worked_hours": float(worked),
        "night_hours": float(night),
        "weekend_hours": float(weekend),
        "regular_hours": None,
        "overtime_hours": None,
        "gross_pay_cents": None,
        "status": "SUBMITTED",
        "dispute_count": 0,
        "dispute_reason": None,
        "verified_at": None,
    })
    db.timesheets[ts["id"]] = ts
    # work axis CONFIRMED -> WORKED
    a["work_status"] = "WORKED"
    bump(a)
    db.clinicians[a["clinician_id"]]["completed_shift_count"] += 1
    # pay axis UNBILLED -> TIMESHEET_PENDING
    a["pay_status"] = "TIMESHEET_PENDING"
    bump(a)
    return object_response(ts, 201)


@app.route("/staffing/assignments/<aid>/timesheets", methods=["GET"])
def list_assignment_timesheets(aid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier",
             "Clinician", "BillingAgent"])
    resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    items = [t for t in db.timesheets.values() if t["assignment_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


# ===========================================================================
# Timesheets: read, dispute, resubmit, verify
# ===========================================================================
@app.route("/staffing/timesheets/<tid>", methods=["GET"])
def get_timesheet(tid):
    require(["PlatformAdmin", "FacilityScheduler", "FacilityVerifier",
             "Clinician", "BillingAgent"])
    ts = resolve(db.timesheets, tid, "ERR_TIMESHEET_NOT_FOUND")
    return object_response(ts, 200)


@app.route("/staffing/timesheets/<tid>/dispute", methods=["POST"])
def dispute_timesheet(tid):
    user_id, role = require(["FacilityVerifier"])
    ts = resolve(db.timesheets, tid, "ERR_TIMESHEET_NOT_FOUND")
    a = assignment_of_timesheet(ts)
    scope_facility(role, user_id, facility_id_of_assignment(a))
    body = get_body()
    reason = v_str(body, "reason", True, 1, None)
    if ts["status"] != "SUBMITTED":
        raise AppError("ERR_TIMESHEET_NOT_DISPUTABLE", "timesheet not disputable")
    if ts["dispute_count"] >= store.TIMESHEET_MAX_DISPUTE_ROUNDS:
        raise AppError("ERR_DISPUTE_LIMIT_REACHED", "dispute limit reached")
    ts["status"] = "DISPUTED"
    ts["dispute_reason"] = reason
    ts["dispute_count"] += 1
    bump(ts)
    return object_response(ts, 200)


@app.route("/staffing/timesheets/<tid>/resubmit", methods=["POST"])
def resubmit_timesheet(tid):
    user_id, role = require(["Clinician"])
    ts = resolve(db.timesheets, tid, "ERR_TIMESHEET_NOT_FOUND")
    a = assignment_of_timesheet(ts)
    owner_clinician(role, user_id, a["clinician_id"])
    body = get_body()
    clock_in = v_datetime(body, "clock_in", True)
    clock_out = v_datetime(body, "clock_out", True)
    break_minutes = v_int(body, "break_minutes", True, 0, 240)
    ci = parse_iso(clock_in)
    co = parse_iso(clock_out)
    shift = shift_of_assignment(a)
    start = parse_iso(shift["scheduled_start"])
    end = parse_iso(shift["scheduled_end"])
    lo = start - logic.timedelta(hours=4)
    hi = end + logic.timedelta(hours=4)
    if not (co > ci) or ci < lo or co > hi:
        raise AppError("ERR_INVALID_PUNCH_INTERVAL", "invalid punch interval")
    if ts["status"] != "DISPUTED":
        raise AppError("ERR_TIMESHEET_NOT_RESUBMITTABLE", "timesheet not resubmittable")

    raw = logic.whole_minutes(ci, co)
    unpaid = logic.deemed_unpaid_break(raw, break_minutes)
    worked = logic.worked_hours_from(raw, unpaid)
    night, weekend = logic.differential_hours(ci, co)
    ts["clock_in"] = clock_in
    ts["clock_out"] = clock_out
    ts["break_minutes"] = break_minutes
    ts["raw_minutes"] = raw
    ts["unpaid_break_minutes"] = unpaid
    ts["worked_hours"] = float(worked)
    ts["night_hours"] = float(night)
    ts["weekend_hours"] = float(weekend)
    ts["status"] = "SUBMITTED"
    bump(ts)
    return object_response(ts, 200)


def _weekly_overtime(ts, assignment):
    from decimal import Decimal as _D
    shift = shift_of_assignment(assignment)
    start = parse_iso(shift["scheduled_start"])
    wk_start, wk_end = logic.week_bounds(start)
    clinician_id = assignment["clinician_id"]
    worked = _D(str(ts["worked_hours"]))
    cumulative = _D("0")
    for other in db.timesheets.values():
        if other["id"] == ts["id"]:
            continue
        if other["status"] not in ("VERIFIED", "INVOICED", "PAID"):
            continue
        oa = assignment_of_timesheet(other)
        if oa["clinician_id"] != clinician_id:
            continue
        oshift = shift_of_assignment(oa)
        ostart = parse_iso(oshift["scheduled_start"])
        if wk_start <= ostart < wk_end:
            cumulative += _D(str(other["worked_hours"]))
    overtime = logic.rhu(max(_D("0.0"), min(worked, cumulative + worked - store.OVERTIME_THRESHOLD_HOURS)), 2)
    regular = logic.rhu(worked - overtime, 2)
    return regular, overtime


@app.route("/staffing/timesheets/<tid>/verify", methods=["POST"])
def verify_timesheet(tid):
    user_id, role = require(["FacilityVerifier"])
    ts = resolve(db.timesheets, tid, "ERR_TIMESHEET_NOT_FOUND")
    a = assignment_of_timesheet(ts)
    scope_facility(role, user_id, facility_id_of_assignment(a))
    if ts["status"] != "SUBMITTED":
        raise AppError("ERR_TIMESHEET_NOT_VERIFIABLE", "timesheet not verifiable")
    if a["work_status"] != "WORKED":
        raise AppError("ERR_TIMESHEET_NOT_VERIFIABLE", "assignment not worked")

    shift = shift_of_assignment(a)
    regular, overtime = _weekly_overtime(ts, a)
    from decimal import Decimal as _D
    night = _D(str(ts["night_hours"]))
    weekend = _D(str(ts["weekend_hours"]))
    gross = logic.pay_amount(shift["effective_rate_cents_per_hour"], regular, overtime, night, weekend)
    ts["regular_hours"] = float(regular)
    ts["overtime_hours"] = float(overtime)
    ts["gross_pay_cents"] = gross
    ts["status"] = "VERIFIED"
    ts["verified_at"] = now()
    bump(ts)

    # pay axis TIMESHEET_PENDING -> PAYABLE
    a["pay_status"] = "PAYABLE"
    a["final_pay_cents"] = gross
    bump(a)
    facility = facility_of_assignment(a)
    facility["pending_pay_cents"] += gross
    bump(facility)
    # shift ASSIGNED -> COMPLETED
    if shift["status"] == "ASSIGNED":
        shift["status"] = "COMPLETED"
        bump(shift)
        logic.order_fill_posture(order_of_shift(shift))
    # SHIFT_COMPLETED credit event
    clin = db.clinicians[a["clinician_id"]]
    logic.append_reliability_event(
        clin, a["id"], "SHIFT_COMPLETED", 0, store.SHIFT_COMPLETION_CREDIT_POINTS,
        "CONFIRMED", "Shift completed")
    logic.reliability_recompute(clin)
    return object_response(ts, 200)


# ===========================================================================
# Reliability events
# ===========================================================================
@app.route("/staffing/clinicians/<cid>/reliability-events", methods=["GET"])
def list_clinician_events(cid):
    require(["PlatformAdmin", "ComplianceOfficer", "Clinician"])
    resolve(db.clinicians, cid, "ERR_CLINICIAN_NOT_FOUND")
    items = [e for e in db.reliability_events.values() if e["clinician_id"] == cid]
    et = request.args.get("event_type")
    adj = request.args.get("adjudication_status")
    if et:
        items = [e for e in items if e["event_type"] == et]
    if adj:
        items = [e for e in items if e["adjudication_status"] == adj]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/assignments/<aid>/reliability-events", methods=["GET"])
def list_assignment_events(aid):
    require(["PlatformAdmin", "ComplianceOfficer", "FacilityScheduler",
             "FacilityVerifier", "Clinician"])
    resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    items = [e for e in db.reliability_events.values() if e["assignment_id"] == aid]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/reliability-events/<eid>/adjudicate", methods=["POST"])
def adjudicate_event(eid):
    require(["ComplianceOfficer"])
    event = resolve(db.reliability_events, eid, "ERR_RELIABILITY_EVENT_NOT_FOUND")
    body = get_body()
    decision = v_enum(body, "decision", {"CONFIRMED", "OVERTURNED"}, True)
    if event["adjudication_status"] != "PENDING":
        raise AppError("ERR_EVENT_ALREADY_ADJUDICATED", "event already adjudicated")
    event["adjudication_status"] = decision
    event["adjudicated_at"] = now()
    bump(event)
    logic.reliability_recompute(db.clinicians[event["clinician_id"]])
    return object_response(event, 200)


# ===========================================================================
# Billing
# ===========================================================================
def _facility_id_of_timesheet(ts):
    return facility_id_of_assignment(assignment_of_timesheet(ts))


def _markup_tier(basis):
    if basis < store.MARKUP_TIER1_MAX_CENTS:
        return "TIER_1", store.MARKUP_TIER1_MULTIPLIER
    if basis < store.MARKUP_TIER2_MAX_CENTS:
        return "TIER_2", store.MARKUP_TIER2_MULTIPLIER
    return "TIER_3", store.MARKUP_TIER3_MULTIPLIER


@app.route("/staffing/invoices", methods=["POST"])
def create_invoice():
    require(["BillingAgent"])
    body = get_body()
    fid = body.get("facility_id")
    if not isinstance(fid, str):
        raise AppError("ERR_VALIDATION", "facility_id is required")
    facility = resolve(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    period_start = v_datetime(body, "period_start", True)
    period_end = v_datetime(body, "period_end", True)
    expected = v_int(body, "expected_facility_version", True)
    ps = parse_iso(period_start)
    pe = parse_iso(period_end)
    # invoice-period-invalid (58)
    if not (pe > ps) or (pe - ps) > logic.timedelta(days=store.INVOICE_MAX_PERIOD_DAYS):
        raise AppError("ERR_INVOICE_PERIOD_INVALID", "invalid invoice period")
    # OCC (70)
    if expected != facility["version"]:
        raise AppError("ERR_STALE_FACILITY_VERSION", "stale facility version")

    # billable timesheets (96)
    billable = []
    for ts in db.timesheets.values():
        if ts["status"] != "VERIFIED":
            continue
        if _facility_id_of_timesheet(ts) != fid:
            continue
        sstart = parse_iso(shift_of_assignment(assignment_of_timesheet(ts))["scheduled_start"])
        if ps <= sstart < pe:
            billable.append(ts)
    if not billable:
        raise AppError("ERR_NO_BILLABLE_TIMESHEETS", "no billable timesheets")
    # period overlap (97)
    for inv in db.invoices.values():
        if inv["facility_id"] != fid or inv["status"] not in ("DRAFT", "ISSUED", "SETTLED"):
            continue
        i_ps = parse_iso(inv["period_start"])
        i_pe = parse_iso(inv["period_end"])
        if ps < i_pe and i_ps < pe:
            raise AppError("ERR_INVOICE_PERIOD_OVERLAP", "invoice period overlap")

    # markup tier from lifetime_billed_cents before this invoice
    tier, multiplier = _markup_tier(facility["lifetime_billed_cents"])

    def _sort_key(ts):
        sstart = parse_iso(shift_of_assignment(assignment_of_timesheet(ts))["scheduled_start"])
        return (sstart, ts["created_at"], ts["_seq"])
    billable.sort(key=_sort_key)

    lines = []
    from decimal import Decimal as _D
    for ts in billable:
        pay_cents = ts["gross_pay_cents"]
        bill_cents = store.rhu_cents(_D(pay_cents) * multiplier)
        lines.append({
            "timesheet_id": ts["id"],
            "worked_hours": ts["worked_hours"],
            "pay_cents": pay_cents,
            "bill_cents": bill_cents,
        })
    pay_total = sum(l["pay_cents"] for l in lines)
    bill_total = sum(l["bill_cents"] for l in lines)

    invoice = stamp_new({
        "facility_id": fid,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "markup_tier": tier,
        "markup_multiplier": float(multiplier),
        "lines": lines,
        "line_count": len(lines),
        "pay_total_cents": pay_total,
        "bill_total_cents": bill_total,
        "margin_cents": bill_total - pay_total,
        "issued_by_user_id": None,
        "issued_at": None,
        "due_at": None,
        "settled_by_user_id": None,
        "paid_amount_cents": None,
        "void_reason": None,
    })
    db.invoices[invoice["id"]] = invoice

    for ts in billable:
        ts["status"] = "INVOICED"
        ts["invoice_id"] = invoice["id"]
        bump(ts)
        a = assignment_of_timesheet(ts)
        a["pay_status"] = "INVOICED"
        bump(a)
    facility["pending_pay_cents"] -= pay_total
    bump(facility)
    return object_response(invoice, 201)


@app.route("/staffing/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require(["PlatformAdmin", "BillingAgent", "FacilityScheduler", "FacilityVerifier"])
    inv = resolve(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    return object_response(inv, 200)


@app.route("/staffing/facilities/<fid>/invoices", methods=["GET"])
def list_facility_invoices(fid):
    require(["PlatformAdmin", "BillingAgent", "FacilityScheduler", "FacilityVerifier"])
    resolve(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    items = [i for i in db.invoices.values() if i["facility_id"] == fid]
    status = request.args.get("status")
    if status:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/invoices/<iid>/timesheets", methods=["GET"])
def list_invoice_timesheets(iid):
    require(["PlatformAdmin", "BillingAgent", "FacilityScheduler", "FacilityVerifier"])
    resolve(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    items = [t for t in db.timesheets.values() if t["invoice_id"] == iid]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@app.route("/staffing/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    user_id, role = require(["BillingAgent"])
    inv = resolve(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    get_body()
    if inv["status"] != "DRAFT" or inv["line_count"] < 1:
        raise AppError("ERR_INVOICE_NOT_DRAFT", "invoice not a draft with lines")
    inv["status"] = "ISSUED"
    inv["issued_at"] = now()
    inv["issued_by_user_id"] = user_id
    inv["due_at"] = now() + logic.timedelta(days=store.INVOICE_NET_TERMS_DAYS)
    facility = db.facilities[inv["facility_id"]]
    facility["outstanding_balance_cents"] += inv["bill_total_cents"]
    facility["lifetime_billed_cents"] += inv["bill_total_cents"]
    bump(facility)
    bump(inv)
    return object_response(inv, 200)


@app.route("/staffing/invoices/<iid>/settle", methods=["POST"])
def settle_invoice(iid):
    user_id, role = require(["BillingAgent"])
    inv = resolve(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    # segregation of duties (45)
    if inv["issued_by_user_id"] is not None and user_id == inv["issued_by_user_id"]:
        raise AppError("ERR_SEGREGATION_OF_DUTIES", "settling agent must differ from issuer")
    body = get_body()
    paid = v_int(body, "paid_amount_cents", True)
    if inv["status"] != "ISSUED":
        raise AppError("ERR_INVOICE_NOT_ISSUED", "invoice not issued")
    if paid != inv["bill_total_cents"]:
        raise AppError("ERR_PAYMENT_AMOUNT_MISMATCH", "payment amount mismatch")
    inv["status"] = "SETTLED"
    inv["settled_by_user_id"] = user_id
    inv["paid_amount_cents"] = paid
    facility = db.facilities[inv["facility_id"]]
    facility["outstanding_balance_cents"] -= inv["bill_total_cents"]
    bump(facility)
    for line in inv["lines"]:
        ts = db.timesheets[line["timesheet_id"]]
        ts["status"] = "PAID"
        bump(ts)
        a = assignment_of_timesheet(ts)
        a["pay_status"] = "PAID"
        bump(a)
    bump(inv)
    return object_response(inv, 200)


@app.route("/staffing/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    user_id, role = require(["BillingAgent"])
    inv = resolve(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    body = get_body()
    reason = v_str(body, "reason", True, 1, None)
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise AppError("ERR_INVOICE_NOT_VOIDABLE", "invoice not voidable")
    was_issued = inv["status"] == "ISSUED"
    inv["status"] = "VOID"
    inv["void_reason"] = reason
    facility = db.facilities[inv["facility_id"]]
    for line in inv["lines"]:
        ts = db.timesheets[line["timesheet_id"]]
        ts["status"] = "VERIFIED"
        ts["invoice_id"] = None
        bump(ts)
        a = assignment_of_timesheet(ts)
        a["pay_status"] = "PAYABLE"
        bump(a)
    facility["pending_pay_cents"] += inv["pay_total_cents"]
    if was_issued:
        facility["outstanding_balance_cents"] -= inv["bill_total_cents"]
        facility["lifetime_billed_cents"] -= inv["bill_total_cents"]
    bump(facility)
    bump(inv)
    return object_response(inv, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
