"""Routes: medication orders & logs, ADL logs, caregivers, shifts."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request

from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_UNAUTHORIZED, ERR_OUTSIDE_MED_WINDOW,
    ERR_CAREGIVER_NOT_ON_SHIFT, ERR_ORDER_DISCONTINUED, ERR_SHIFT_CONFLICT,
    ERR_UNDERSTAFFED,
)
from util import (
    ok_object, ok_list, paginate, require_roles, get_or_404, body,
    need_str, need_enum, need, need_ts, opt_bool,
    stamp_new, touch, pub, sort_created, fmt_ts, parse_ts,
)
from logic import (
    med_window_ok, caregiver_on_shift, caregiver_schedule_conflict,
    forward_staffing_ok, scheduled_shifts, home_tz,
)

bp = Blueprint("routes_c", __name__)

ALL = ("Provider", "Nurse", "CaregiverRole")
PROVIDER = ("Provider",)
NURSE = ("Nurse",)
PROVIDER_NURSE = ("Provider", "Nurse")
LOGGERS = ("Nurse", "CaregiverRole")

MED_OUTCOMES = ("GIVEN", "REFUSED", "HELD", "SELF_ADMINISTERED")
ADL_TYPES = ("BATHING", "DRESSING", "GROOMING", "TOILETING", "TRANSFERRING", "EATING")
ASSISTANCE_LEVELS = ("INDEPENDENT", "SUPERVISION", "PARTIAL", "FULL")
OVERNIGHT_MODES = ("AWAKE", "ASLEEP")


def _check_caregiver_ownership(b):
    """CaregiverRole callers may only log care under their own caregiver id."""
    if g.user_role == "CaregiverRole":
        cid = b.get("caregiver_id")
        if cid is not None and cid != g.user_id:
            raise_err(ERR_UNAUTHORIZED, "caregiver may only log under their own id")


def _valid_schedule_time(t):
    if not isinstance(t, str):
        return False
    parts = t.split(":")
    if len(parts) != 2:
        return False
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59


# ---------------------------------------------------------------------------
# Medication orders
# ---------------------------------------------------------------------------

@bp.post("/api/residents/<id>/medication-orders")
@require_roles(*NURSE)
def create_med_order(id):
    resident = get_or_404(db.residents, id, "resident")
    if resident["status"] != "ADMITTED":
        raise_err(ERR_INVALID_STATE, "resident is not ADMITTED")
    b = body()
    drug_name = need_str(b, "drug_name")
    dose = need_str(b, "dose")
    times = need(b, "schedule_times")
    if not isinstance(times, list) or not (1 <= len(times) <= 6):
        raise_err(ERR_INVALID_REQUEST, "schedule_times must be a list of 1..6 entries")
    if not all(_valid_schedule_time(t) for t in times):
        raise_err(ERR_INVALID_REQUEST, "schedule_times entries must be 'HH:MM'")
    rec = stamp_new({
        "resident_id": id,
        "drug_name": drug_name,
        "dose": dose,
        "schedule_times": list(times),
        "status": "ACTIVE",
    })
    db.med_orders[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/residents/<id>/medication-orders")
@require_roles(*ALL)
def list_med_orders(id):
    get_or_404(db.residents, id, "resident")
    items = sort_created([o for o in db.med_orders.values() if o["resident_id"] == id])
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(items)
    return ok_list([pub(o) for o in page], meta)


@bp.post("/api/medication-orders/<id>/discontinue")
@require_roles(*NURSE)
def discontinue_med_order(id):
    order = get_or_404(db.med_orders, id, "medication order")
    if order["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "medication order is not ACTIVE")
    resident = db.residents.get(order["resident_id"])
    if resident is not None and resident["status"] == "DISCHARGED":
        raise_err(ERR_INVALID_STATE, "resident is DISCHARGED")
    order["status"] = "DISCONTINUED"
    touch(order)
    return ok_object(pub(order))


# ---------------------------------------------------------------------------
# Medication logs
# ---------------------------------------------------------------------------

@bp.post("/api/medication-logs")
@require_roles(*LOGGERS)
def create_med_log():
    b = body()
    _check_caregiver_ownership(b)
    # 3. existence, body identifiers left-to-right
    resident = get_or_404(db.residents, b.get("resident_id"), "resident") \
        if "resident_id" in b else None
    order = get_or_404(db.med_orders, b.get("order_id"), "medication order") \
        if "order_id" in b else None
    if resident is not None and order is not None and order["resident_id"] != resident["id"]:
        raise_err(ERR_NOT_FOUND, "medication order does not belong to the resident")
    caregiver = get_or_404(db.caregivers, b.get("caregiver_id"), "caregiver") \
        if "caregiver_id" in b else None
    # administered_at must parse for the window check; structural failure is
    # deferred to step 22 when it does not.
    admin_dt = None
    if isinstance(b.get("administered_at"), str):
        try:
            admin_dt = parse_ts(b["administered_at"])
        except ValueError:
            admin_dt = None
    # 9. med window + duplicate-dose check
    if order is not None and admin_dt is not None:
        home = db.homes.get(resident["home_id"]) if resident else None
        if home is not None:
            inside, dup = med_window_ok(home, order, admin_dt, b.get("outcome"))
            if not inside or dup:
                raise_err(ERR_OUTSIDE_MED_WINDOW,
                          "administered_at is outside every open window or duplicates a dose")
    # 15. on-shift verification
    if resident is not None and caregiver is not None and admin_dt is not None:
        if not caregiver_on_shift(resident["home_id"], caregiver["id"], admin_dt):
            raise_err(ERR_CAREGIVER_NOT_ON_SHIFT,
                      "caregiver has no SCHEDULED shift covering administered_at")
    # 16. order still active
    if order is not None and order["status"] != "ACTIVE":
        raise_err(ERR_ORDER_DISCONTINUED, "medication order is DISCONTINUED")
    # 22. structural validity
    resident_id = need_str(b, "resident_id")
    order_id = need_str(b, "order_id")
    admin_dt = need_ts(b, "administered_at")
    outcome = need_enum(b, "outcome", MED_OUTCOMES)
    caregiver_id = need_str(b, "caregiver_id")
    note = b.get("note")
    if outcome in ("REFUSED", "HELD") and (note is None or not isinstance(note, str) or note == ""):
        raise_err(ERR_INVALID_REQUEST, "note is required when outcome is REFUSED or HELD")
    if note is not None and not isinstance(note, str):
        raise_err(ERR_INVALID_REQUEST, "note must be a string")
    rec = stamp_new({
        "resident_id": resident_id,
        "order_id": order_id,
        "administered_at": fmt_ts(admin_dt),
        "_admin_dt": admin_dt,
        "outcome": outcome,
        "caregiver_id": caregiver_id,
        "note": note,
    }, common=False)
    db.med_logs[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/medication-logs")
@require_roles(*PROVIDER_NURSE)
def list_med_logs():
    items = sort_created(list(db.med_logs.values()))
    for f in ("resident_id", "order_id", "caregiver_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    page, meta = paginate(items)
    return ok_list([pub(l) for l in page], meta)


@bp.get("/api/medication-logs/<id>")
@require_roles(*PROVIDER_NURSE)
def get_med_log(id):
    rec = get_or_404(db.med_logs, id, "medication log")
    return ok_object(pub(rec))


# ---------------------------------------------------------------------------
# ADL logs
# ---------------------------------------------------------------------------

@bp.post("/api/adl-logs")
@require_roles(*LOGGERS)
def create_adl_log():
    b = body()
    _check_caregiver_ownership(b)
    resident = get_or_404(db.residents, b.get("resident_id"), "resident") \
        if "resident_id" in b else None
    caregiver = get_or_404(db.caregivers, b.get("caregiver_id"), "caregiver") \
        if "caregiver_id" in b else None
    performed_dt = None
    if isinstance(b.get("performed_at"), str):
        try:
            performed_dt = parse_ts(b["performed_at"])
        except ValueError:
            performed_dt = None
    # 15. on-shift verification
    if resident is not None and caregiver is not None and performed_dt is not None:
        if not caregiver_on_shift(resident["home_id"], caregiver["id"], performed_dt):
            raise_err(ERR_CAREGIVER_NOT_ON_SHIFT,
                      "caregiver has no SCHEDULED shift covering performed_at")
    # 22. structural validity
    resident_id = need_str(b, "resident_id")
    adl_type = need_enum(b, "adl_type", ADL_TYPES)
    level = need_enum(b, "assistance_level", ASSISTANCE_LEVELS)
    performed_dt = need_ts(b, "performed_at")
    caregiver_id = need_str(b, "caregiver_id")
    rec = stamp_new({
        "resident_id": resident_id,
        "adl_type": adl_type,
        "assistance_level": level,
        "performed_at": fmt_ts(performed_dt),
        "_performed_dt": performed_dt,
        "caregiver_id": caregiver_id,
    }, common=False)
    db.adl_logs[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/adl-logs")
@require_roles(*PROVIDER_NURSE)
def list_adl_logs():
    items = sort_created(list(db.adl_logs.values()))
    for f in ("resident_id", "caregiver_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    page, meta = paginate(items)
    return ok_list([pub(l) for l in page], meta)


@bp.get("/api/adl-logs/<id>")
@require_roles(*PROVIDER_NURSE)
def get_adl_log(id):
    rec = get_or_404(db.adl_logs, id, "ADL log")
    return ok_object(pub(rec))


# ---------------------------------------------------------------------------
# Caregivers
# ---------------------------------------------------------------------------

@bp.post("/api/homes/<id>/caregivers")
@require_roles(*PROVIDER)
def create_caregiver(id):
    get_or_404(db.homes, id, "home")
    b = body()
    full_name = need_str(b, "full_name")
    credential_id = need_str(b, "credential_id")
    awake_q = opt_bool(b, "awake_overnight_qualified", False)
    for c in db.caregivers.values():
        if c["credential_id"] == credential_id:
            raise_err(ERR_INVALID_REQUEST, "credential_id must be unique across homes")
    rec = stamp_new({
        "home_id": id,
        "full_name": full_name,
        "credential_id": credential_id,
        "awake_overnight_qualified": awake_q,
        "status": "ACTIVE",
    })
    db.caregivers[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/homes/<id>/caregivers")
@require_roles(*PROVIDER_NURSE)
def list_caregivers(id):
    get_or_404(db.homes, id, "home")
    items = sort_created([c for c in db.caregivers.values() if c["home_id"] == id])
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return ok_list([pub(c) for c in page], meta)


@bp.get("/api/caregivers/<id>")
@require_roles(*ALL)
def get_caregiver(id):
    rec = get_or_404(db.caregivers, id, "caregiver")
    return ok_object(pub(rec))


@bp.post("/api/caregivers/<id>/suspend")
@require_roles(*PROVIDER)
def suspend_caregiver(id):
    rec = get_or_404(db.caregivers, id, "caregiver")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "caregiver is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok_object(pub(rec))


@bp.post("/api/caregivers/<id>/reinstate")
@require_roles(*PROVIDER)
def reinstate_caregiver(id):
    rec = get_or_404(db.caregivers, id, "caregiver")
    if rec["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "caregiver is not SUSPENDED")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok_object(pub(rec))


@bp.post("/api/caregivers/<id>/terminate")
@require_roles(*PROVIDER)
def terminate_caregiver(id):
    rec = get_or_404(db.caregivers, id, "caregiver")
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "caregiver cannot be terminated from its current state")
    rec["status"] = "TERMINATED"
    touch(rec)
    now = db.now()
    for s in db.shifts.values():
        if (s["caregiver_id"] == id and s["status"] == "SCHEDULED"
                and s["_start_dt"] > now):
            s["status"] = "CANCELLED"
            touch(s)
    return ok_object(pub(rec))


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

def _covers_overnight(home, start_dt, end_dt):
    tz = home_tz(home)
    la = start_dt.astimezone(tz)
    lb = end_dt.astimezone(tz)
    days = {la.date(), lb.date(), la.date() - timedelta(days=1), la.date() + timedelta(days=1)}
    for d in days:
        o_start = datetime(d.year, d.month, d.day, 22, 0, tzinfo=tz)
        o_end = o_start + timedelta(hours=8)
        if la < o_end and o_start < lb:
            return True
    return False


@bp.post("/api/shifts")
@require_roles(*PROVIDER)
def create_shift():
    b = body()
    # 3. existence, body identifiers left-to-right
    home = get_or_404(db.homes, b.get("home_id"), "home") if "home_id" in b else None
    caregiver = get_or_404(db.caregivers, b.get("caregiver_id"), "caregiver") \
        if "caregiver_id" in b else None
    if home is not None and caregiver is not None and caregiver["home_id"] != home["id"]:
        raise_err(ERR_NOT_FOUND, "caregiver does not belong to the home")
    # 4. OCC on the caregiver
    if caregiver is not None and "expected_caregiver_version" in b \
            and b["expected_caregiver_version"] is not None:
        if b["expected_caregiver_version"] != caregiver["version"]:
            raise_err(ERR_STALE_VERSION,
                      "expected_caregiver_version does not match caregiver version")
    # 5. state legality: caregiver must be ACTIVE
    if caregiver is not None and caregiver["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "caregiver is not ACTIVE")
    # Parse times leniently so the conflict/staffing checks can run before
    # structural validation (step 22) when possible.
    start_dt = end_dt = None
    if isinstance(b.get("start_at"), str):
        try:
            start_dt = parse_ts(b["start_at"])
        except ValueError:
            start_dt = None
    if isinstance(b.get("end_at"), str):
        try:
            end_dt = parse_ts(b["end_at"])
        except ValueError:
            end_dt = None
    usable_interval = (start_dt is not None and end_dt is not None and end_dt > start_dt)
    overnight_mode = b.get("overnight_mode")
    # 10. caregiver overlap + rolling 16h cap
    if caregiver is not None and usable_interval:
        if caregiver_schedule_conflict(caregiver["id"], start_dt, end_dt):
            raise_err(ERR_SHIFT_CONFLICT,
                      "overlapping shift or more than 16 scheduled hours in a rolling 24h window")
    # 11. forward staffing-ratio adequacy
    if home is not None and usable_interval:
        candidate = {
            "id": "__candidate__",
            "home_id": home["id"],
            "caregiver_id": caregiver["id"] if caregiver else None,
            "status": "SCHEDULED",
            "overnight_mode": overnight_mode if overnight_mode in OVERNIGHT_MODES else None,
            "_start_dt": start_dt,
            "_end_dt": end_dt,
        }
        if not forward_staffing_ok(home, scheduled_shifts(home["id"], extra=candidate),
                                   start_dt, end_dt):
            raise_err(ERR_UNDERSTAFFED,
                      "the shift would leave an occupied hour below the required staffing ratio")
    # 22. structural validity
    need_str(b, "home_id")
    need_str(b, "caregiver_id")
    start_dt = need_ts(b, "start_at")
    end_dt = need_ts(b, "end_at")
    if end_dt <= start_dt:
        raise_err(ERR_INVALID_REQUEST, "end_at must be strictly after start_at")
    if (end_dt - start_dt).total_seconds() > 16 * 3600:
        raise_err(ERR_INVALID_REQUEST, "shift duration may not exceed 16 hours")
    if overnight_mode is not None and overnight_mode not in OVERNIGHT_MODES:
        raise_err(ERR_INVALID_REQUEST, "overnight_mode must be AWAKE or ASLEEP")
    if home is not None and _covers_overnight(home, start_dt, end_dt) and overnight_mode is None:
        raise_err(ERR_INVALID_REQUEST,
                  "overnight_mode is required when the shift covers 22:00-06:00")
    need(b, "expected_caregiver_version")
    rec = stamp_new({
        "home_id": home["id"],
        "caregiver_id": caregiver["id"],
        "start_at": fmt_ts(start_dt),
        "end_at": fmt_ts(end_dt),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "overnight_mode": overnight_mode,
        "status": "SCHEDULED",
    })
    db.shifts[rec["id"]] = rec
    touch(caregiver)  # creating the shift increments the caregiver's version
    return ok_object(pub(rec), 201)


@bp.get("/api/shifts")
@require_roles(*PROVIDER_NURSE)
def list_shifts():
    items = sort_created(list(db.shifts.values()))
    for f in ("home_id", "caregiver_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    page, meta = paginate(items)
    return ok_list([pub(s) for s in page], meta)


@bp.get("/api/shifts/<id>")
@require_roles(*PROVIDER_NURSE)
def get_shift(id):
    rec = get_or_404(db.shifts, id, "shift")
    return ok_object(pub(rec))


@bp.post("/api/shifts/<id>/cancel")
@require_roles(*PROVIDER)
def cancel_shift(id):
    rec = get_or_404(db.shifts, id, "shift")
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "shift is not SCHEDULED")
    home = db.homes.get(rec["home_id"])
    if home is not None:
        if not forward_staffing_ok(home, scheduled_shifts(home["id"], exclude_id=id),
                                   rec["_start_dt"], rec["_end_dt"]):
            raise_err(ERR_UNDERSTAFFED,
                      "cancelling would leave an occupied hour below the required staffing ratio")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(pub(rec))
