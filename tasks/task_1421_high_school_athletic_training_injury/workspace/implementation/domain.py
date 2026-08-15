"""Domain layer: enums, time helpers, derived calculations, cascades, sweeps."""
import calendar
import re
import uuid
from datetime import datetime, timedelta, timezone

import db
from errors import ApiError

# --------------------------------------------------------------------------
# Enum vocabularies
# --------------------------------------------------------------------------
SPORTS = [
    "FOOTBALL", "SOCCER", "BASKETBALL", "BASEBALL", "SOFTBALL", "VOLLEYBALL",
    "WRESTLING", "LACROSSE", "FIELD_HOCKEY", "CROSS_COUNTRY", "TRACK",
    "SWIMMING", "TENNIS", "GOLF",
]
STAFF_ROLES = ["ATHLETIC_TRAINER", "TEAM_COACH", "PHYSICIAN", "ATHLETIC_DIRECTOR", "SCHOOL_NURSE"]
TEAM_LEVELS = ["VARSITY", "JV", "FRESHMAN"]
SEXES = ["M", "F"]
PHYSICAL_OUTCOMES = ["CLEARED", "CLEARED_WITH_RESTRICTIONS", "NOT_CLEARED", "DEFERRED"]
VALIDITY_POLICIES = ["DISTRICT_13MO", "STATE_SCHOOL_YEAR"]
INSTRUMENTS = ["SCAT6", "IMPACT", "SWAY"]
VENUE_TYPES = ["INDOOR", "OUTDOOR"]
SURFACES = ["GRASS", "TURF", "COURT", "TRACK", "POOL", "GYM_FLOOR"]
EVENT_TYPES = ["PRACTICE", "SCRIMMAGE", "HOME_GAME", "AWAY_GAME", "TOURNAMENT"]
COVERAGE_ROLES = ["PRIMARY", "SECONDARY"]
READING_TYPES = ["HEAT_WBGT", "LIGHTNING_STRIKE"]
READING_SOURCES = ["ON_SITE_SENSOR", "WEATHER_SERVICE", "MANUAL"]
BODY_REGIONS = [
    "HEAD_NECK", "SHOULDER", "ARM_HAND", "TRUNK", "HIP_PELVIS", "KNEE",
    "LOWER_LEG", "ANKLE_FOOT", "SYSTEMIC",
]
INJURY_TYPES = ["CONCUSSION", "FRACTURE", "SPRAIN", "STRAIN", "LACERATION", "HEAT_ILLNESS", "CARDIAC", "OTHER"]
SEVERITIES = ["MINOR", "MODERATE", "SEVERE", "CRITICAL"]
RESTRICTED_ACTIVITIES = ["PRACTICE", "CONTACT", "GAME", "CONDITIONING", "WEIGHTS"]
URGENCIES = ["ROUTINE", "URGENT", "EMERGENT"]
REPORT_CLEARANCES = ["CLEARED_FULL", "CLEARED_RESTRICTED", "NOT_CLEARED"]
PROTOCOL_TYPES = ["GRADUATED_6_STAGE"]
SUPPLY_CATEGORIES = ["TAPE", "FIRST_AID", "HYDRATION", "EQUIPMENT", "MEDICATION"]
SUPPLY_UNITS = ["ROLL", "EACH", "CASE", "LITER", "BOX"]
TXN_TYPES = ["RESTOCK", "USAGE", "WASTE", "ADJUSTMENT"]
VALUATION_POLICIES = ["FIFO", "WAC_RUNNING", "WAC_EXACT"]
POSTURES = ["NOT_CLEARED", "INELIGIBLE", "MEDICAL_HOLD", "CLEARED_WITH_RESTRICTIONS", "CLEARED"]
PHYSICAL_STATUSES = ["RECORDED", "VERIFIED", "EXPIRED", "VOIDED"]
BASELINE_STATUSES = ["CURRENT", "SUPERSEDED", "EXPIRED"]
EAP_STATUSES = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "ACTIVE", "SUPERSEDED"]
EVENT_STATUSES = ["SCHEDULED", "COVERED", "IN_PROGRESS", "SUSPENDED_WEATHER", "COMPLETED", "CANCELLED"]
ASSIGNMENT_STATUSES = ["ASSIGNED", "ACKNOWLEDGED", "ON_SITE", "ON_HOLD", "COMPLETED", "DECLINED", "CANCELLED"]
INJURY_STATUSES = ["OPEN", "UNDER_CARE", "REFERRED", "RTP_IN_PROGRESS", "RESOLVED", "CLOSED"]
REFERRAL_STATUSES = ["REQUESTED", "SCHEDULED", "COMPLETED", "ADDENDUM_REQUESTED", "CLOSED", "CANCELLED", "EXPIRED"]
PROTOCOL_STATUSES = ["ACTIVE", "CLEARED", "TERMINATED"]
NOTIFICATION_STATUSES = ["QUEUED", "SENT", "FAILED", "ACKNOWLEDGED", "ESCALATED"]
NOTIFICATION_TYPES = ["INJURY_INITIAL", "REFERRAL_REQUEST", "RTP_REGRESSION", "CLEARANCE_GRANTED", "EVENT_SUSPENSION"]
ORDER_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "RECEIVED", "REJECTED", "CANCELLED"]

ACTIVE_ASSIGNMENT_STATUSES = {"ASSIGNED", "ACKNOWLEDGED", "ON_SITE", "ON_HOLD"}

HIGH_CONTACT = {"FOOTBALL", "WRESTLING", "LACROSSE"}
MEDIUM_CONTACT = {"SOCCER", "BASKETBALL", "BASEBALL", "SOFTBALL", "FIELD_HOCKEY", "VOLLEYBALL"}

DISTRICT_BREAKS = (80.0, 84.0, 87.0, 90.0)
STATE_BREAKS = (82.0, 86.0, 89.0, 92.0)
HEAT_TIERS = ["NORMAL", "CAUTION", "MODERATE", "SEVERE", "EXTREME"]

REFERRAL_WINDOWS = {"ROUTINE": timedelta(days=14), "URGENT": timedelta(days=3), "EMERGENT": timedelta(days=1)}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# Time helpers (logical clock only; never wall-clock for domain logic)
# --------------------------------------------------------------------------
def now_dt():
    return datetime.fromisoformat(db.current_utc_iso.replace("Z", "+00:00"))


def now_iso_ms():
    dt = now_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 datetime." % field)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 datetime." % field)


def parse_date(value, field):
    if isinstance(value, str) and _DATE_RE.match(value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO date." % field)
        return value
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO date." % field)


def date_start_dt(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_months(dt, months):
    month_index = dt.year * 12 + (dt.month - 1) + months
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# --------------------------------------------------------------------------
# Request body field validators
# --------------------------------------------------------------------------
def body_json():
    from flask import request

    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % name)
    return body[name]


def req_string(body, name):
    value = req_field(body, name)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def opt_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return body[name]


def req_enum(body, name, allowed):
    value = req_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, allowed)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def req_int(body, name):
    value = req_field(body, name)
    if not is_int(value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return value


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name)


def req_number(body, name):
    value = req_field(body, name)
    if not is_number(value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    return float(value)


def opt_number(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_number(body, name)


def req_bool(body, name):
    value = req_field(body, name)
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_bool(body, name)


def req_dt(body, name):
    return parse_dt(req_field(body, name), name)


def opt_dt(body, name):
    if name not in body or body[name] is None:
        return None
    return parse_dt(body[name], name)


def opt_string_list(body, name, default=None, allowed=None):
    if name not in body or body[name] is None:
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings." % name)
    if allowed is not None:
        for v in value:
            if v not in allowed:
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s' contains an unsupported value." % name)
    return list(value)


def uuid_str():
    return str(uuid.uuid4())


def get_path_resource(store, raw_id, error_id, message):
    """Resolve a path identifier per PRD §2.8: an identifier that cannot be
    parsed at all draws the generic ERR_NOT_FOUND; a well-formed UUID that
    matches no record draws the family-specific error."""
    if not isinstance(raw_id, str):
        raise ApiError("ERR_NOT_FOUND", "The requested resource was not found.")
    try:
        uuid.UUID(raw_id)
    except (ValueError, AttributeError, TypeError):
        raise ApiError("ERR_NOT_FOUND", "The requested resource was not found.")
    rec = store.get(raw_id)
    if rec is None:
        raise ApiError(error_id, message)
    return rec


# --------------------------------------------------------------------------
# Resource construction
# --------------------------------------------------------------------------
_seq_counter = 0


def _next_seq():
    """Monotonic creation counter; breaks ties when the logical clock is frozen."""
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_resource(fields, common=True):
    rec = {"id": uuid_str()}
    rec.update(fields)
    ts = now_iso_ms()
    rec["created_at"] = ts
    rec["_seq"] = _next_seq()
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso_ms()
    rec["version"] += 1


def bump(rec):
    rec["version"] += 1


def set_props(rec, **kwargs):
    for key, value in kwargs.items():
        rec[key] = value
    touch(rec)


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def ser_staff(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "role_type": s["role_type"],
        "sport_certifications": list(s["sport_certifications"]),
        "is_active": s["is_active"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_athlete(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "date_of_birth": a["date_of_birth"],
        "grade": a["grade"],
        "sex": a["sex"],
        "primary_sport": a["primary_sport"],
        "team_level": a["team_level"],
        "guardian_name": a["guardian_name"],
        "guardian_user_id": a["guardian_user_id"],
        "guardian_email": a["guardian_email"],
        "guardian_phone": a["guardian_phone"],
        "participation_posture": a["participation_posture"],
        "posture_reasons": list(a["posture_reasons"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_physical(p):
    return {
        "id": p["id"],
        "athlete_id": p["athlete_id"],
        "exam_date": p["exam_date"],
        "examining_physician_name": p["examining_physician_name"],
        "outcome": p["outcome"],
        "validity_policy": p["validity_policy"],
        "restriction_notes": p["restriction_notes"],
        "recorded_by_staff_id": p["recorded_by_staff_id"],
        "verified_by_staff_id": p["verified_by_staff_id"],
        "expires_on": p["expires_on"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_baseline(b):
    return {
        "id": b["id"],
        "athlete_id": b["athlete_id"],
        "test_date": b["test_date"],
        "instrument": b["instrument"],
        "symptom_score": b["symptom_score"],
        "memory_index": b["memory_index"],
        "reaction_time_ms": b["reaction_time_ms"],
        "balance_errors": b["balance_errors"],
        "administered_by_staff_id": b["administered_by_staff_id"],
        "valid_until": b["valid_until"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_venue(v):
    return {
        "id": v["id"],
        "venue_name": v["venue_name"],
        "venue_type": v["venue_type"],
        "surface": v["surface"],
        "lightning_detection": v["lightning_detection"],
        "lightning_radius_miles": v["lightning_radius_miles"],
        "address": v["address"],
        "is_active": v["is_active"],
        "active_eap_id": v["active_eap_id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_eap(e):
    return {
        "id": e["id"],
        "venue_id": e["venue_id"],
        "version_label": e["version_label"],
        "evacuation_route": e["evacuation_route"],
        "aed_location": e["aed_location"],
        "ems_contact": e["ems_contact"],
        "nearest_hospital": e["nearest_hospital"],
        "supersedes_eap_id": e["supersedes_eap_id"],
        "authored_by_staff_id": e["authored_by_staff_id"],
        "approved_by_staff_id": e["approved_by_staff_id"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "event_name": e["event_name"],
        "sport": e["sport"],
        "team_level": e["team_level"],
        "event_type": e["event_type"],
        "venue_id": e["venue_id"],
        "scheduled_start": e["scheduled_start"],
        "scheduled_end": e["scheduled_end"],
        "expected_attendance": e["expected_attendance"],
        "required_trainer_count": e["required_trainer_count"],
        "active_assignment_count": e["active_assignment_count"],
        "status": e["status"],
        "suspension_reason": e["suspension_reason"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "event_id": a["event_id"],
        "staff_id": a["staff_id"],
        "coverage_role": a["coverage_role"],
        "status": a["status"],
        "pre_hold_status": a["pre_hold_status"],
        "acknowledged_at": a["acknowledged_at"],
        "checked_in_at": a["checked_in_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_reading(r):
    return {
        "id": r["id"],
        "venue_id": r["venue_id"],
        "reading_type": r["reading_type"],
        "value_wbgt_f": r["value_wbgt_f"],
        "strike_distance_miles": r["strike_distance_miles"],
        "recorded_at": r["recorded_at"],
        "source": r["source"],
        "created_at": r["created_at"],
    }


def ser_injury(i):
    return {
        "id": i["id"],
        "athlete_id": i["athlete_id"],
        "event_id": i["event_id"],
        "body_region": i["body_region"],
        "injury_type": i["injury_type"],
        "severity": i["severity"],
        "mechanism": i["mechanism"],
        "evaluated_at": i["evaluated_at"],
        "restricted_activities": list(i["restricted_activities"]),
        "reopen_of_id": i["reopen_of_id"],
        "evaluated_by_staff_id": i["evaluated_by_staff_id"],
        "recurrence_count": i["recurrence_count"],
        "resolved_at": i["resolved_at"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_referral(r):
    return {
        "id": r["id"],
        "injury_id": r["injury_id"],
        "athlete_id": r["athlete_id"],
        "physician_staff_id": r["physician_staff_id"],
        "reason": r["reason"],
        "urgency": r["urgency"],
        "due_by": r["due_by"],
        "appointment_at": r["appointment_at"],
        "report_diagnosis": r["report_diagnosis"],
        "report_clearance": r["report_clearance"],
        "reported_at": r["reported_at"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_protocol(p):
    return {
        "id": p["id"],
        "injury_id": p["injury_id"],
        "athlete_id": p["athlete_id"],
        "protocol_type": p["protocol_type"],
        "current_stage": p["current_stage"],
        "stage_entered_at": p["stage_entered_at"],
        "recurrence_count": p["recurrence_count"],
        "clearance_authority_required": p["clearance_authority_required"],
        "stage_history": [dict(h) for h in p["stage_history"]],
        "cleared_by_staff_id": p["cleared_by_staff_id"],
        "cleared_at": p["cleared_at"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "athlete_id": n["athlete_id"],
        "injury_id": n["injury_id"],
        "referral_id": n["referral_id"],
        "notification_type": n["notification_type"],
        "channel": n["channel"],
        "subject": n["subject"],
        "sent_at": n["sent_at"],
        "acknowledged_at": n["acknowledged_at"],
        "attempts": n["attempts"],
        "status": n["status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def ser_supply_item(s):
    return {
        "id": s["id"],
        "item_name": s["item_name"],
        "category": s["category"],
        "unit": s["unit"],
        "par_level": s["par_level"],
        "reorder_threshold": s["reorder_threshold"],
        "unit_cost_cents": s["unit_cost_cents"],
        "is_discontinued": s["is_discontinued"],
        "current_stock": s["current_stock"],
        "stock_status": s["stock_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_inventory_txn(t):
    return {
        "id": t["id"],
        "supply_item_id": t["supply_item_id"],
        "txn_type": t["txn_type"],
        "quantity": t["quantity"],
        "unit_cost_cents": t["unit_cost_cents"],
        "occurred_at": t["occurred_at"],
        "event_id": t["event_id"],
        "restock_order_id": t["restock_order_id"],
        "reason": t["reason"],
        "recorded_by_staff_id": t["recorded_by_staff_id"],
        "created_at": t["created_at"],
    }


def ser_restock_order(o):
    return {
        "id": o["id"],
        "supply_item_id": o["supply_item_id"],
        "quantity": o["quantity"],
        "unit_cost_cents": o["unit_cost_cents"],
        "fiscal_year": o["fiscal_year"],
        "extended_cost_cents": o["extended_cost_cents"],
        "requested_by_staff_id": o["requested_by_staff_id"],
        "approved_by_staff_id": o["approved_by_staff_id"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_budget(b):
    return {
        "id": b["id"],
        "fiscal_year": b["fiscal_year"],
        "total_budget_cents": b["total_budget_cents"],
        "realized_spend_cents": b["realized_spend_cents"],
        "committed_spend_cents": b["committed_spend_cents"],
        "available_cents": b["available_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


# --------------------------------------------------------------------------
# Calculations: physical expiry / baseline validity
# --------------------------------------------------------------------------
def physical_expires_on(exam_date_str, validity_policy):
    exam = date_start_dt(exam_date_str)
    if validity_policy == "DISTRICT_13MO":
        exp = add_months(exam, 13)
    else:  # STATE_SCHOOL_YEAR
        year = exam.year if exam.month < 8 else exam.year + 1
        exp = datetime(year, 8, 1, tzinfo=timezone.utc)
    return iso_z(exp)


def baseline_valid_until(test_date_str):
    return iso_z(add_months(date_start_dt(test_date_str), 24))


# --------------------------------------------------------------------------
# Calculation: athlete participation posture (section 3.1)
# --------------------------------------------------------------------------
def recompute_posture(athlete_id):
    athlete = db.athletes.get(athlete_id)
    if athlete is None:
        return
    now = now_dt()

    # "A VERIFIED physical has ever existed" = verified at some point, even if
    # the clock sweep has since moved it to EXPIRED (verified_by_staff_id is set
    # only by the verify transition and never cleared).
    verified = [
        p for p in db.physicals.values()
        if p["athlete_id"] == athlete_id and p["verified_by_staff_id"] is not None
    ]
    if not verified:
        posture, reasons = "NOT_CLEARED", ["NO_VERIFIED_PHYSICAL"]
    else:
        latest = max(verified, key=lambda p: (date_start_dt(p["exam_date"]), p["created_at"], p["_seq"]))
        reasons = []
        if now >= parse_dt(latest["expires_on"], "expires_on"):
            reasons.append("PHYSICAL_EXPIRED")
        if latest["outcome"] in ("NOT_CLEARED", "DEFERRED"):
            reasons.append("PHYSICAL_OUTCOME_BLOCKS")
        baseline_ok = any(
            b["athlete_id"] == athlete_id
            and b["status"] == "CURRENT"
            and parse_dt(b["valid_until"], "valid_until") > now
            for b in db.baselines.values()
        )
        if not baseline_ok:
            reasons.append("NO_CURRENT_BASELINE")
        if reasons:
            posture = "INELIGIBLE"
        else:
            hold_reasons = []
            if any(
                i["athlete_id"] == athlete_id and i["status"] in ("OPEN", "REFERRED")
                for i in db.injuries.values()
            ):
                hold_reasons.append("ACUTE_INJURY_OPEN")
            for p in db.protocols.values():
                if (
                    p["athlete_id"] == athlete_id
                    and p["status"] == "ACTIVE"
                    and p["recurrence_count"] >= 2
                ):
                    injury = db.injuries.get(p["injury_id"])
                    if injury is not None and injury["injury_type"] == "CONCUSSION":
                        cleared = any(
                            r["injury_id"] == p["injury_id"]
                            and r["status"] in ("COMPLETED", "CLOSED")
                            and r["report_clearance"] in ("CLEARED_FULL", "CLEARED_RESTRICTED")
                            for r in db.referrals.values()
                        )
                        if not cleared:
                            hold_reasons.append("PHYSICIAN_REVIEW_PENDING")
                            break
            if hold_reasons:
                posture, reasons = "MEDICAL_HOLD", hold_reasons
            else:
                restr = []
                if any(
                    i["athlete_id"] == athlete_id and i["status"] in ("UNDER_CARE", "RTP_IN_PROGRESS")
                    for i in db.injuries.values()
                ):
                    restr.append("INJURY_RESTRICTIONS")
                if latest["outcome"] == "CLEARED_WITH_RESTRICTIONS":
                    restr.append("PHYSICAL_RESTRICTIONS")
                if restr:
                    posture, reasons = "CLEARED_WITH_RESTRICTIONS", restr
                else:
                    posture, reasons = "CLEARED", []

    if athlete["participation_posture"] != posture or athlete["posture_reasons"] != reasons:
        set_props(athlete, participation_posture=posture, posture_reasons=reasons)


# --------------------------------------------------------------------------
# Calculations: event coverage requirement + active count + bubble up/down
# --------------------------------------------------------------------------
def compute_required_trainers(event):
    sport = event["sport"]
    if sport in HIGH_CONTACT:
        base = 1 if event["event_type"] == "PRACTICE" else 2
    else:
        base = 1
    modifiers = 0
    if event["event_type"] == "TOURNAMENT":
        modifiers += 1
    restricted = sum(
        1
        for a in db.athletes.values()
        if a["primary_sport"] == event["sport"]
        and a["team_level"] == event["team_level"]
        and a["participation_posture"] == "CLEARED_WITH_RESTRICTIONS"
    )
    if restricted >= 4:
        modifiers += 1
    if event["expected_attendance"] >= 1000:
        modifiers += 1
    return min(4, max(1, base + modifiers))


def update_event_coverage(event):
    count = sum(
        1
        for a in db.assignments.values()
        if a["event_id"] == event["id"] and a["status"] in ACTIVE_ASSIGNMENT_STATUSES
    )
    required = compute_required_trainers(event)
    status = event["status"]
    if status == "SCHEDULED" and count >= required:
        status = "COVERED"
    elif status == "COVERED" and count < required:
        status = "SCHEDULED"
    if (
        event["active_assignment_count"] != count
        or event["required_trainer_count"] != required
        or event["status"] != status
    ):
        set_props(
            event,
            active_assignment_count=count,
            required_trainer_count=required,
            status=status,
        )


def posture_dependent_recompute(athlete_id):
    """After a posture recompute, refresh events whose restricted-roster count may have moved."""
    athlete = db.athletes.get(athlete_id)
    if athlete is None:
        return
    for event in db.events.values():
        if (
            event["sport"] == athlete["primary_sport"]
            and event["team_level"] == athlete["team_level"]
            and event["status"] in ("SCHEDULED", "COVERED")
        ):
            update_event_coverage(event)


# --------------------------------------------------------------------------
# Calculations: heat tier / lightning hold
# --------------------------------------------------------------------------
def heat_tier_for(wbgt, tournament):
    breaks = STATE_BREAKS if tournament else DISTRICT_BREAKS
    value = round(float(wbgt), 1)
    if value < breaks[0]:
        return "NORMAL"
    if value < breaks[1]:
        return "CAUTION"
    if value < breaks[2]:
        return "MODERATE"
    if value < breaks[3]:
        return "SEVERE"
    return "EXTREME"


def venue_heat_tier(venue_id, tournament=False):
    readings = [
        r for r in db.readings.values()
        if r["venue_id"] == venue_id and r["reading_type"] == "HEAT_WBGT"
    ]
    if not readings:
        return "NORMAL"
    latest = max(
        readings,
        key=lambda r: (parse_dt(r["recorded_at"], "recorded_at"), r["created_at"], r["_seq"]),
    )
    return heat_tier_for(latest["value_wbgt_f"], tournament)


def venue_lightning_hold_until(venue_id, tournament=False):
    venue = db.venues.get(venue_id)
    if venue is None:
        return None
    minutes = 45 if tournament else 30
    radius = float(venue["lightning_radius_miles"])
    hold_until = None
    for r in db.readings.values():
        if r["venue_id"] != venue_id or r["reading_type"] != "LIGHTNING_STRIKE":
            continue
        if float(r["strike_distance_miles"]) <= radius:
            candidate = parse_dt(r["recorded_at"], "recorded_at") + timedelta(minutes=minutes)
            if hold_until is None or candidate > hold_until:
                hold_until = candidate
    return hold_until


def venue_lightning_hold_active(venue_id, tournament=False):
    hold_until = venue_lightning_hold_until(venue_id, tournament)
    return hold_until is not None and now_dt() < hold_until


# --------------------------------------------------------------------------
# Guardian notifications
# --------------------------------------------------------------------------
def create_notification(athlete_id, ntype, injury_id=None, referral_id=None):
    athlete = db.athletes.get(athlete_id)
    channel = "EMAIL" if (athlete and athlete.get("guardian_email")) else "PHONE"
    subject = ntype.replace("_", " ").title()
    notif = new_resource(
        {
            "athlete_id": athlete_id,
            "injury_id": injury_id,
            "referral_id": referral_id,
            "notification_type": ntype,
            "channel": channel,
            "subject": subject,
            "sent_at": None,
            "acknowledged_at": None,
            "attempts": 0,
            "status": "QUEUED",
        }
    )
    db.notifications[notif["id"]] = notif
    return notif


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def cascade_event_suspension(event, reason):
    for a in db.assignments.values():
        if a["event_id"] == event["id"] and a["status"] in ("ACKNOWLEDGED", "ON_SITE"):
            set_props(a, status="ON_HOLD", pre_hold_status=a["status"])
    for athlete in db.athletes.values():
        if (
            athlete["primary_sport"] == event["sport"]
            and athlete["team_level"] == event["team_level"]
        ):
            has_active_injury = any(
                i["athlete_id"] == athlete["id"]
                and i["status"] in ("OPEN", "UNDER_CARE", "REFERRED", "RTP_IN_PROGRESS")
                for i in db.injuries.values()
            )
            if has_active_injury:
                create_notification(athlete["id"], "EVENT_SUSPENSION")


def cascade_event_resume(event):
    for a in db.assignments.values():
        if a["event_id"] == event["id"] and a["status"] == "ON_HOLD":
            set_props(a, status=a["pre_hold_status"] or "ACKNOWLEDGED", pre_hold_status=None)


def cascade_event_complete(event):
    for a in db.assignments.values():
        if a["event_id"] == event["id"] and a["status"] in ("ON_SITE", "ACKNOWLEDGED", "ON_HOLD"):
            set_props(a, status="COMPLETED")


def cascade_event_cancel(event):
    for a in db.assignments.values():
        if a["event_id"] == event["id"] and a["status"] in ("ASSIGNED", "ACKNOWLEDGED", "ON_HOLD"):
            set_props(a, status="CANCELLED")


# --------------------------------------------------------------------------
# Clock sweep (section 2.4)
# --------------------------------------------------------------------------
def run_clock_sweep():
    now = now_dt()
    athlete_ids = set()

    for p in db.physicals.values():
        if p["status"] in ("RECORDED", "VERIFIED") and now >= parse_dt(p["expires_on"], "expires_on"):
            set_props(p, status="EXPIRED")
            athlete_ids.add(p["athlete_id"])

    for b in db.baselines.values():
        if b["status"] == "CURRENT" and now >= parse_dt(b["valid_until"], "valid_until"):
            set_props(b, status="EXPIRED")
            athlete_ids.add(b["athlete_id"])

    for r in db.referrals.values():
        if r["status"] in ("REQUESTED", "SCHEDULED") and now > parse_dt(r["due_by"], "due_by"):
            set_props(r, status="EXPIRED")

    for n in db.notifications.values():
        if (
            n["status"] == "SENT"
            and n["sent_at"] is not None
            and now >= parse_dt(n["sent_at"], "sent_at") + timedelta(hours=24)
        ):
            set_props(n, status="ESCALATED")

    for aid in athlete_ids:
        recompute_posture(aid)
    for aid in athlete_ids:
        posture_dependent_recompute(aid)
