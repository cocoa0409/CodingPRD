"""Appointments, eligibility checks, estimates, payments, queue, day close."""
from datetime import timedelta

from flask import Blueprint

from store import db
from core import (
    ApiError, authed, body, ok_object, ok_list, paginate, serialize,
    new_record, touch, get_or_404, now, iso, parse_d,
    v_str, v_enum, v_int, v_bool, v_date, v_datetime,
)
from domain import (
    LATE_ARRIVAL_CUTOFF_MINUTES, NO_SHOW_GRACE_MINUTES, PRE_ARRIVAL_STATES,
    strike_count, propagate_strikes, refresh_staleness, latest_fresh_check,
    latest_estimate, latest_provisional_estimate, satisfying_auth,
    compute_clearance, recompute_clearance, run_matching,
    recompute_collected, estimate_amounts, repin_cached_estimate, double_booked,
)
from routes import request_arg, REG_FC_SUP, COVERAGE_STATUSES, VISIT_TYPES, PAYMENT_METHODS, PAYMENT_KINDS

bp2 = Blueprint("patient_access_2", __name__, url_prefix="/patient-access")

ALL4 = ("Registrar", "FinancialCounselor", "FrontDeskAgent", "AccessSupervisor")


# ================================================================== appointments
def _appt_record(patient_id, npi, dept, proc, start_dt, duration, visit_type, provider):
    rec = new_record()
    rec.update({
        "patient_id": patient_id,
        "referring_provider_npi": npi,
        "department_code": dept,
        "procedure_code": proc,
        "scheduled_start": iso(start_dt),
        "_start_dt": start_dt,
        "duration_minutes": duration,
        "visit_type": visit_type,
        "provider_code": provider,
        "status": "SCHEDULED",
        "registration_gate": "BLOCKED",
        "estimated_patient_responsibility_cents": 0,
        "amount_collected_cents": 0,
        "auth_satisfied": False,
        "referral_id": None,
        "late_minutes": 0,
        "no_show_risk_strikes": strike_count(patient_id, now()),
        "cancel_reason": None,
    })
    return rec


@bp2.post("/appointments")
@authed("Registrar")
def create_appointment():
    b = body()
    patient_id = v_str(b, "patient_id")
    npi = v_str(b, "referring_provider_npi", required=False)
    dept = v_str(b, "department_code")
    proc = v_str(b, "procedure_code")
    start_dt = v_datetime(b, "scheduled_start")
    duration = v_int(b, "duration_minutes", minv=5)
    visit_type = v_enum(b, "visit_type", VISIT_TYPES)
    provider = v_str(b, "provider_code")
    get_or_404("patients", patient_id, "patient")
    # overlap check is evaluated before temporal sanity (PRD section 3.4)
    if double_booked(provider, start_dt, duration):
        raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409,
                       "requested slot overlaps another live appointment of this provider")
    if start_dt.date() < now().date():
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "scheduled_start must not be in the past")
    rec = _appt_record(patient_id, npi, dept, proc, start_dt, duration, visit_type, provider)
    db.appointments[rec["id"]] = rec
    run_matching(rec)
    gate, sat = compute_clearance(rec)
    rec["registration_gate"] = gate
    rec["auth_satisfied"] = sat
    return ok_object(serialize(rec), 201)


@bp2.get("/appointments")
@authed(*ALL4)
def list_appointments():
    items = list(db.appointments.values())
    f_patient = request_arg("patient_id")
    f_provider = request_arg("provider_code")
    f_dept = request_arg("department_code")
    f_status = request_arg("status")
    f_date = request_arg("date")
    f_referral = request_arg("referral_id")
    if f_patient is not None:
        items = [a for a in items if a["patient_id"] == f_patient]
    if f_provider is not None:
        items = [a for a in items if a["provider_code"] == f_provider]
    if f_dept is not None:
        items = [a for a in items if a["department_code"] == f_dept]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    if f_date is not None:
        items = [a for a in items if a["scheduled_start"][:10] == f_date]
    if f_referral is not None:
        items = [a for a in items if a["referral_id"] == f_referral]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp2.get("/appointments/<aid>")
@authed(*ALL4)
def get_appointment(aid):
    return ok_object(serialize(get_or_404("appointments", aid, "appointment")))


@bp2.route("/appointments/<aid>", methods=["PATCH"])
@authed("Registrar")
def patch_appointment(aid):
    appt = get_or_404("appointments", aid, "appointment")
    b = body()
    expected = v_int(b, "expected_appointment_version")
    new_start = v_datetime(b, "scheduled_start", required=False)
    new_duration = v_int(b, "duration_minutes", minv=5, required=False)
    new_provider = v_str(b, "provider_code", required=False)
    new_dept = v_str(b, "department_code", required=False)
    new_proc = v_str(b, "procedure_code", required=False)
    new_vt = v_enum(b, "visit_type", VISIT_TYPES, required=False)
    new_npi = v_str(b, "referring_provider_npi", required=False)
    if expected != appt["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_appointment_version does not match current version")
    eff_start = new_start if new_start is not None else appt["_start_dt"]
    eff_duration = new_duration if new_duration is not None else appt["duration_minutes"]
    eff_provider = new_provider if new_provider is not None else appt["provider_code"]
    # double-booking re-validated ahead of the date-range rule (PRD section 3.4)
    if double_booked(eff_provider, eff_start, eff_duration, exclude_id=appt["id"]):
        raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409,
                       "requested slot overlaps another live appointment of this provider")
    if new_start is not None and new_start.date() < now().date():
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "scheduled_start must not be in the past")
    if new_start is not None:
        appt["scheduled_start"] = iso(new_start)
        appt["_start_dt"] = new_start
    if new_duration is not None:
        appt["duration_minutes"] = new_duration
    if new_provider is not None:
        appt["provider_code"] = new_provider
    if new_dept is not None:
        appt["department_code"] = new_dept
    if new_proc is not None:
        appt["procedure_code"] = new_proc
    if new_vt is not None:
        appt["visit_type"] = new_vt
    if new_npi is not None:
        appt["referring_provider_npi"] = new_npi
    run_matching(appt)
    recompute_clearance(appt)
    touch(appt)
    return ok_object(serialize(appt))


@bp2.post("/appointments/<aid>/pre-check")
@authed("Registrar")
def pre_check(aid):
    appt = get_or_404("appointments", aid, "appointment")
    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "appointment is not SCHEDULED")
    patient = db.patients.get(appt["patient_id"])
    if patient is None or patient["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", 409, "patient is not REGISTERED")
    usable = None
    for c in db.eligibility_checks.values():
        if c["appointment_id"] != aid:
            continue
        refresh_staleness(c)
        if c["result"] in ("VERIFIED", "VERIFIED_WITH_AUTH"):
            if usable is None or c["_seq"] > usable["_seq"]:
                usable = c
    if usable is None:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "no fresh verified eligibility check exists for this appointment")
    appt["status"] = "PRE_CHECKED"
    recompute_clearance(appt)
    touch(appt)
    return ok_object(serialize(appt))


@bp2.post("/appointments/<aid>/revert-precheck")
@authed("Registrar")
def revert_precheck(aid):
    appt = get_or_404("appointments", aid, "appointment")
    if appt["status"] != "PRE_CHECKED":
        raise ApiError("ERR_INVALID_STATE", 409, "appointment is not PRE_CHECKED")
    appt["status"] = "SCHEDULED"
    recompute_clearance(appt)
    touch(appt)
    return ok_object(serialize(appt))


@bp2.post("/appointments/<aid>/mark-ready")
@authed("FinancialCounselor")
def mark_ready(aid):
    appt = get_or_404("appointments", aid, "appointment")
    if appt["status"] != "PRE_CHECKED":
        raise ApiError("ERR_INVALID_STATE", 409, "appointment is not PRE_CHECKED")
    gate, auth_satisfied = compute_clearance(appt)
    # pinned guardrail order: referral -> authorization -> deposit (PRD 3.5)
    from domain import primary_policy
    pp = primary_policy(appt["patient_id"])
    if (pp is not None and pp["plan_type"] in ("HMO", "EPO")
            and appt["referral_id"] is None):
        raise ApiError("ERR_REFERRAL_REQUIRED", 422,
                       "plan requires a matched referral before mark-ready")
    auth_needed = appt["visit_type"] in ("PROCEDURE", "IMAGING")
    if not auth_needed:
        chk = latest_fresh_check(aid)
        if chk is not None and chk["auth_required"]:
            auth_needed = True
    if auth_needed and not auth_satisfied:
        raise ApiError("ERR_AUTH_REQUIRED", 422,
                       "visit requires a current APPROVED authorization")
    if gate == "CLEAR_WITH_PAYMENT":
        est = latest_estimate(aid)
        if appt["amount_collected_cents"] < est["deposit_required_cents"]:
            raise ApiError("ERR_DEPOSIT_SHORTFALL", 402,
                           "collected amount is below the deposit target")
    elif gate == "BLOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "registration gate is BLOCKED")
    appt["status"] = "READY"
    touch(appt)
    return ok_object(serialize(appt))


@bp2.post("/appointments/<aid>/check-in")
@authed("FrontDeskAgent")
def check_in(aid):
    appt = get_or_404("appointments", aid, "appointment")
    b = body()
    stat_flag = v_bool(b, "stat_flag", required=False)
    if appt["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409, "appointment is not READY")
    # queue uniqueness comes before the clock (PRD section 3.6)
    for t in db.tickets.values():
        if t["appointment_id"] == aid and t["state"] in ("WAITING", "CALLED"):
            raise ApiError("ERR_TICKET_ALREADY_ACTIVE", 409,
                           "appointment already has an active queue ticket")
    start = appt["_start_dt"]
    now_dt = now()
    if now_dt > start + timedelta(minutes=LATE_ARRIVAL_CUTOFF_MINUTES):
        raise ApiError("ERR_TOO_LATE_FOR_CHECKIN", 422,
                       "arrival is past the late-arrival cutoff")
    appt["late_minutes"] = int((now_dt - start).total_seconds() // 60)
    appt["status"] = "ARRIVED"
    # issue the day's queue ticket
    dept = appt["department_code"]
    qdate = appt["scheduled_start"][:10]
    seq = 1 + sum(1 for t in db.tickets.values()
                  if t["department_code"] == dept and t["queue_date"] == qdate)
    if stat_flag is True:
        priority = "STAT"
    elif any(f["patient_id"] == appt["patient_id"] and f["active"]
             for f in db.flags.values()):
        priority = "ACCOMMODATION"
    else:
        priority = "STANDARD"
    ticket = new_record()
    ticket.update({
        "appointment_id": aid,
        "department_code": dept,
        "queue_date": qdate,
        "sequence_number": seq,
        "priority": priority,
        "state": "WAITING",
        "called_at": None,
    })
    db.tickets[ticket["id"]] = ticket
    # consume matched referral visit
    if appt["referral_id"] is not None:
        ref = db.referrals.get(appt["referral_id"])
        if ref is not None and ref["status"] == "OPEN":
            ref["visits_consumed"] += 1
            if ref["visits_consumed"] >= ref["visits_authorized"]:
                ref["status"] = "EXHAUSTED"
            touch(ref)
    # consume covering authorization
    auth = satisfying_auth(appt)
    if auth is not None:
        auth["status"] = "CONSUMED"
        touch(auth)
    touch(appt)
    return ok_object(serialize(appt))


@bp2.post("/appointments/<aid>/complete")
@authed("FrontDeskAgent")
def complete_appointment(aid):
    appt = get_or_404("appointments", aid, "appointment")
    if appt["status"] != "IN_ROOM":
        raise ApiError("ERR_INVALID_STATE", 409, "appointment is not IN_ROOM")
    appt["status"] = "COMPLETED"
    for t in db.tickets.values():
        if t["appointment_id"] == aid and t["state"] == "CALLED":
            t["state"] = "SERVED"
            touch(t)
    est = latest_provisional_estimate(aid)
    if est is not None:
        est["status"] = "FINAL"
        touch(est)
        appt["estimated_patient_responsibility_cents"] = \
            est["estimated_patient_responsibility_cents"]
    touch(appt)
    return ok_object(serialize(appt))


@bp2.post("/appointments/<aid>/cancel")
@authed("Registrar")
def cancel_appointment(aid):
    appt = get_or_404("appointments", aid, "appointment")
    b = body()
    reason = v_str(b, "reason", required=False)
    if appt["status"] not in PRE_ARRIVAL_STATES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "appointment cannot be cancelled from its current state")
    appt["status"] = "CANCELLED"
    appt["cancel_reason"] = reason
    for t in db.tickets.values():
        if t["appointment_id"] == aid and t["state"] == "WAITING":
            t["state"] = "REMOVED"
            touch(t)
    touch(appt)
    return ok_object(serialize(appt))


@bp2.post("/appointments/<aid>/mark-no-show")
@authed("FrontDeskAgent")
def mark_no_show(aid):
    appt = get_or_404("appointments", aid, "appointment")
    if appt["status"] not in PRE_ARRIVAL_STATES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "appointment cannot be marked NO_SHOW from its current state")
    if now() < appt["_start_dt"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "no-show grace period has not elapsed")
    appt["status"] = "NO_SHOW"
    touch(appt)
    propagate_strikes(appt["patient_id"])
    return ok_object(serialize(appt))


# --------------------------------------------------- appointment reverse lookups
@bp2.get("/appointments/<aid>/copay-estimates")
@authed(*REG_FC_SUP)
def appointment_estimates(aid):
    get_or_404("appointments", aid, "appointment")
    items = [e for e in db.estimates.values() if e["appointment_id"] == aid]
    status = request_arg("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp2.get("/appointments/<aid>/payments")
@authed(*REG_FC_SUP)
def appointment_payments(aid):
    get_or_404("appointments", aid, "appointment")
    items = [p for p in db.payments.values() if p["appointment_id"] == aid]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp2.get("/appointments/<aid>/queue-tickets")
@authed("FrontDeskAgent", "AccessSupervisor")
def appointment_tickets(aid):
    get_or_404("appointments", aid, "appointment")
    items = [t for t in db.tickets.values() if t["appointment_id"] == aid]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp2.get("/appointments/<aid>/eligibility-checks")
@authed(*REG_FC_SUP)
def appointment_checks(aid):
    get_or_404("appointments", aid, "appointment")
    items = [c for c in db.eligibility_checks.values() if c["appointment_id"] == aid]
    for c in items:
        refresh_staleness(c)
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


# ============================================================= eligibility checks
@bp2.post("/eligibility-checks")
@authed("Registrar")
def create_check():
    b = body()
    policy_id = v_str(b, "policy_id")
    appointment_id = v_str(b, "appointment_id")
    coverage = v_enum(b, "coverage_status", COVERAGE_STATUSES)
    copay = v_int(b, "copay_cents", minv=0)
    coins = v_int(b, "coinsurance_pct", minv=0, maxv=100)
    auth_required = v_bool(b, "auth_required")
    policy = get_or_404("policies", policy_id, "insurance policy")
    appt = get_or_404("appointments", appointment_id, "appointment")
    if policy["patient_id"] != appt["patient_id"]:
        raise ApiError("ERR_CROSS_PATIENT_REFERENCE", 422,
                       "policy does not belong to the appointment's patient")
    rec = new_record()
    if coverage != "ACTIVE":
        result = "FAILED"
    elif auth_required:
        result = "VERIFIED_WITH_AUTH"
    else:
        result = "VERIFIED"
    checked_dt = now()
    rec.update({
        "policy_id": policy_id,
        "appointment_id": appointment_id,
        "checked_at": iso(checked_dt),
        "_checked_dt": checked_dt,
        "coverage_status": coverage,
        "copay_cents": copay,
        "coinsurance_pct": coins,
        "auth_required": auth_required,
        "result": result,
    })
    db.eligibility_checks[rec["id"]] = rec
    recompute_clearance(appt)
    return ok_object(serialize(rec), 201)


# ================================================================ copay estimates
@bp2.post("/appointments/<aid>/copay-estimates")
@authed("FinancialCounselor")
def create_estimate(aid):
    appt = get_or_404("appointments", aid, "appointment")
    b = body()
    policy_id = v_str(b, "policy_id")
    allowed = v_int(b, "allowed_amount_cents", minv=0)
    policy = get_or_404("policies", policy_id, "insurance policy")
    if policy["patient_id"] != appt["patient_id"]:
        raise ApiError("ERR_CROSS_PATIENT_REFERENCE", 422,
                       "policy does not belong to the appointment's patient")
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "policy is not ACTIVE")
    method, resp, deposit = estimate_amounts(appt, policy, allowed)
    for e in db.estimates.values():
        if e["appointment_id"] == aid and e["status"] == "PROVISIONAL":
            e["status"] = "SUPERSEDED"
            touch(e)
    rec = new_record()
    rec.update({
        "appointment_id": aid,
        "policy_id": policy_id,
        "method": method,
        "allowed_amount_cents": allowed,
        "estimated_patient_responsibility_cents": resp,
        "deposit_required_cents": deposit,
        "status": "PROVISIONAL",
    })
    db.estimates[rec["id"]] = rec
    appt["estimated_patient_responsibility_cents"] = resp
    recompute_clearance(appt)
    touch(appt)
    return ok_object(serialize(rec), 201)


# ======================================================================= payments
@bp2.post("/appointments/<aid>/payments")
@authed("FinancialCounselor")
def create_payment(aid):
    appt = get_or_404("appointments", aid, "appointment")
    b = body()
    amount = v_int(b, "amount_cents", minv=1)
    method = v_enum(b, "method", PAYMENT_METHODS)
    kind = v_enum(b, "kind", PAYMENT_KINDS)
    if kind == "REFUND" and amount > appt["amount_collected_cents"]:
        raise ApiError("ERR_REFUND_EXCEEDS_COLLECTED", 422,
                       "refund exceeds current collected amount")
    rec = new_record()
    rec.update({
        "appointment_id": aid,
        "amount_cents": amount,
        "method": method,
        "kind": kind,
        "status": "POSTED",
    })
    db.payments[rec["id"]] = rec
    recompute_collected(appt)
    recompute_clearance(appt)
    touch(appt)
    return ok_object(serialize(rec), 201)


@bp2.post("/payments/<pid>/void")
@authed("AccessSupervisor")
def void_payment(pid):
    payment = get_or_404("payments", pid, "payment")
    if payment["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", 409, "payment is not POSTED")
    payment["status"] = "VOIDED"
    touch(payment)
    appt = db.appointments.get(payment["appointment_id"])
    if appt is not None:
        recompute_collected(appt)
        recompute_clearance(appt)
        touch(appt)
    return ok_object(serialize(payment))


# ========================================================================== queue
@bp2.post("/queue-tickets/call-next")
@authed("FrontDeskAgent")
def call_next():
    b = body()
    dept = v_str(b, "department_code")
    qdate = v_date(b, "queue_date")
    rank = {"STAT": 0, "ACCOMMODATION": 1, "STANDARD": 2}
    waiting = [t for t in db.tickets.values()
               if t["department_code"] == dept and t["queue_date"] == qdate
               and t["state"] == "WAITING"]
    if not waiting:
        raise ApiError("ERR_QUEUE_EMPTY", 404,
                       "no WAITING ticket for this department and date")
    waiting.sort(key=lambda t: (rank[t["priority"]], t["sequence_number"]))
    ticket = waiting[0]
    ticket["state"] = "CALLED"
    ticket["called_at"] = iso(now())
    touch(ticket)
    appt = db.appointments.get(ticket["appointment_id"])
    if appt is not None and appt["status"] == "ARRIVED":
        appt["status"] = "IN_ROOM"
        touch(appt)
    return ok_object(serialize(ticket))


@bp2.post("/queue-tickets/<tid>/skip")
@authed("FrontDeskAgent")
def skip_ticket(tid):
    ticket = get_or_404("tickets", tid, "queue ticket")
    if ticket["state"] != "CALLED":
        raise ApiError("ERR_INVALID_STATE", 409, "ticket is not CALLED")
    ticket["state"] = "SKIPPED"
    touch(ticket)
    appt = db.appointments.get(ticket["appointment_id"])
    if appt is not None and appt["status"] == "IN_ROOM":
        appt["status"] = "ARRIVED"
        touch(appt)
    return ok_object(serialize(ticket))


@bp2.get("/departments/<dcode>/queue")
@authed("FrontDeskAgent", "AccessSupervisor")
def department_queue(dcode):
    qdate = request_arg("queue_date")
    if qdate is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "queue_date is required")
    items = [t for t in db.tickets.values()
             if t["department_code"] == dcode and t["queue_date"] == qdate]
    state = request_arg("state")
    if state is not None:
        items = [t for t in items if t["state"] == state]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp2.post("/departments/<dcode>/close-day")
@authed("AccessSupervisor")
def close_day(dcode):
    b = body()
    qdate = v_date(b, "queue_date")
    now_dt = now()
    no_show_count = 0
    patients_touched = set()
    for a in db.appointments.values():
        if a["department_code"] != dcode:
            continue
        if a["status"] not in PRE_ARRIVAL_STATES:
            continue
        if a["_start_dt"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES) <= now_dt:
            a["status"] = "NO_SHOW"
            touch(a)
            no_show_count += 1
            patients_touched.add(a["patient_id"])
    for pid in patients_touched:
        propagate_strikes(pid)
    expired_ticket_count = 0
    for t in db.tickets.values():
        if (t["department_code"] == dcode and t["queue_date"] == qdate
                and t["state"] == "WAITING"):
            t["state"] = "REMOVED"
            touch(t)
            expired_ticket_count += 1
    return ok_object({
        "no_show_count": no_show_count,
        "expired_ticket_count": expired_ticket_count,
    })
