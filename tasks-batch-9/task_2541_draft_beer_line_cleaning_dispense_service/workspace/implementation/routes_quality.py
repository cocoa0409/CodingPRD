"""Pour-quality complaints, glycol loop health and cooler readings (PRD 3.8, 3.9)."""
from flask import Blueprint, g

import calc
import projections
import serializers
import store
from common import (API_PREFIX, REOPEN_LIMIT, REOPEN_WINDOW_HOURS, ROLE_AUDITOR,
                    ROLE_DISPATCH, ROLE_TECH, ROLE_VENUE, hours_between)
from envelope import object_response
from errors import raise_error
from helpers import listing, match, resolve_body, resolve_path
from security import guard, require_self_technician, segregation, venue_scope
from shape import F, bad, parse_body, query_enum, query_str

bp = Blueprint("quality", __name__)

SYMPTOMS = ["FOAMY_POUR", "FLAT_POUR", "OFF_FLAVOR", "SLOW_POUR", "CLOUDY"]
COMPLAINT_STATUSES = ["OPEN", "DIAGNOSING", "AWAITING_PARTS", "ESCALATED", "RESOLVED"]
OUTCOMES = ["ROOT_CAUSE_FOUND", "PARTS_REQUIRED"]
FINDING_CODES = ["LINE_SOIL", "GAS_IMBALANCE", "TEMP_EXCURSION", "FAUCET_WEAR",
                 "KEG_DEFECT"]
DISPOSITIONS = ["RESOLVED", "ESCALATED"]
ROUND_OPEN_STATUSES = ("OPEN", "DIAGNOSING", "AWAITING_PARTS")
RESOLVE_FROM = ("OPEN", "DIAGNOSING", "AWAITING_PARTS", "ESCALATED")
ESCALATE_FROM = ("DIAGNOSING", "AWAITING_PARTS")
LOOP_STATUSES = ["NORMAL", "WATCH", "ALARM"]
READING_SOURCES = ["TECH_MANUAL", "VENUE_MANUAL"]


@bp.post(API_PREFIX + "/quality-complaints")
@guard(ROLE_VENUE)
def create_complaint():
    body = parse_body([
        F("account_id", "id", required=True),
        F("line_id", "id", required=True),
        F("symptom", "enum", required=True, values=SYMPTOMS),
    ])
    account = resolve_body("account_id", body["account_id"])
    line = resolve_body("line_id", body["line_id"])
    venue_scope(account["id"])
    if account["status"] != "ACTIVE":
        raise_error("ERR_ACCOUNT_NOT_ACTIVE")
    if line["account_id"] != account["id"]:
        raise_error("ERR_LINE_ACCOUNT_MISMATCH")
    reported_at = store.now()
    baseline = line["last_cleaned_at"] or line["created_at"]
    risk_days = calc.days_at_risk(reported_at, baseline)
    liters, cents = calc.provisional_yield_loss(
        body["symptom"], risk_days, line["average_daily_throughput_liters"])
    row = store.new_row({
        "account_id": account["id"],
        "line_id": line["id"],
        "symptom": body["symptom"],
        "reported_at": reported_at,
        "status": "OPEN",
        "diagnostic_round": 0,
        "reopen_count": 0,
        "days_at_risk": risk_days,
        "provisional_yield_loss_liters": liters,
        "provisional_yield_loss_cents": cents,
        "settled_yield_loss_liters": None,
        "settled_yield_loss_cents": None,
        "measured_waste_liters": None,
        "escalated_by_user_id": None,
        "closed_by_user_id": None,
        "resolved_at": None,
        "last_finding_code": "NONE",
    })
    store.complaints[row["id"]] = row
    projections.recompute_account_counters(account)
    return object_response(serializers.complaint(row), 201)


@bp.get(API_PREFIX + "/quality-complaints/<complaint_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def read_complaint(complaint_id):
    return object_response(serializers.complaint(
        resolve_path("complaint_id", complaint_id)))


@bp.get(API_PREFIX + "/quality-complaints")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_complaints():
    account_id = query_str("account_id")
    line_id = query_str("line_id")
    status = query_enum("status", COMPLAINT_STATUSES)
    symptom = query_enum("symptom", SYMPTOMS)
    rows = [r for r in store.complaints.values()
            if match(r, "account_id", account_id)
            and match(r, "line_id", line_id)
            and match(r, "status", status)
            and match(r, "symptom", symptom)]
    return listing(rows, serializers.complaint)


@bp.post(API_PREFIX + "/quality-complaints/<complaint_id>/diagnostic-round")
@guard(ROLE_AUDITOR)
def log_diagnostic_round(complaint_id):
    complaint = resolve_path("complaint_id", complaint_id)
    body = parse_body([
        F("outcome", "enum", required=True, values=OUTCOMES),
        F("finding_code", "enum", required=True, values=FINDING_CODES),
    ])
    if complaint["status"] not in ROUND_OPEN_STATUSES:
        raise_error("ERR_COMPLAINT_ALREADY_CLOSED")
    if complaint["diagnostic_round"] >= 3:
        raise_error("ERR_DIAGNOSTIC_ROUNDS_EXHAUSTED")
    current = complaint["status"]
    if body["outcome"] == "ROOT_CAUSE_FOUND":
        if current in ("OPEN", "AWAITING_PARTS"):
            complaint["status"] = "DIAGNOSING"
    else:
        if current in ("OPEN", "DIAGNOSING"):
            complaint["status"] = "AWAITING_PARTS"
    complaint["diagnostic_round"] = complaint["diagnostic_round"] + 1
    complaint["last_finding_code"] = body["finding_code"]
    store.touch(complaint)
    return object_response(serializers.complaint(complaint))


@bp.post(API_PREFIX + "/quality-complaints/<complaint_id>/closure")
@guard(ROLE_AUDITOR)
def close_complaint(complaint_id):
    complaint = resolve_path("complaint_id", complaint_id)
    body = parse_body([
        F("disposition", "enum", required=True, values=DISPOSITIONS),
        F("measured_waste_liters", "num", min_value=0),
    ])
    resolving = body["disposition"] == "RESOLVED"
    if resolving and body["measured_waste_liters"] is None:
        bad("measured_waste_liters is required to resolve a complaint.")
    segregation(complaint["escalated_by_user_id"])
    if resolving:
        if complaint["status"] not in RESOLVE_FROM:
            raise_error("ERR_COMPLAINT_ALREADY_CLOSED")
    elif complaint["status"] not in ESCALATE_FROM:
        raise_error("ERR_COMPLAINT_ALREADY_CLOSED")
    line = store.lines.get(complaint["line_id"])
    if resolving:
        if line is None or line["status"] != "IN_SERVICE":
            raise_error("ERR_LINE_OUT_OF_SERVICE")
        resolved_at = store.now()
        liters, cents, _days = calc.settled_yield_loss(
            body["measured_waste_liters"], complaint["reported_at"], resolved_at)
        complaint["status"] = "RESOLVED"
        complaint["resolved_at"] = resolved_at
        complaint["closed_by_user_id"] = g.user_id
        complaint["measured_waste_liters"] = body["measured_waste_liters"]
        complaint["settled_yield_loss_liters"] = liters
        complaint["settled_yield_loss_cents"] = cents
    else:
        complaint["status"] = "ESCALATED"
        complaint["escalated_by_user_id"] = g.user_id
    store.touch(complaint)
    account = store.accounts.get(complaint["account_id"])
    if account is not None:
        projections.recompute_account_counters(account)
    return object_response(serializers.complaint(complaint))


@bp.post(API_PREFIX + "/quality-complaints/<complaint_id>/reopen")
@guard(ROLE_VENUE)
def reopen_complaint(complaint_id):
    complaint = resolve_path("complaint_id", complaint_id)
    body = parse_body([F("reopen_reason", "str", required=True)])
    venue_scope(complaint["account_id"])
    if complaint["status"] != "RESOLVED":
        raise_error("ERR_COMPLAINT_ALREADY_CLOSED")
    resolved_at = complaint["resolved_at"]
    if resolved_at is None or hours_between(store.now(), resolved_at) > REOPEN_WINDOW_HOURS:
        raise_error("ERR_REOPEN_WINDOW_CLOSED")
    if complaint["reopen_count"] >= REOPEN_LIMIT:
        raise_error("ERR_REOPEN_LIMIT_EXCEEDED")
    complaint["status"] = "OPEN"
    complaint["reopen_count"] = complaint["reopen_count"] + 1
    complaint["diagnostic_round"] = 0
    complaint["resolved_at"] = None
    complaint["closed_by_user_id"] = None
    complaint["measured_waste_liters"] = None
    complaint["settled_yield_loss_liters"] = None
    complaint["settled_yield_loss_cents"] = None
    complaint["reopen_reason"] = body["reopen_reason"]
    store.touch(complaint)
    account = store.accounts.get(complaint["account_id"])
    if account is not None:
        projections.recompute_account_counters(account)
    return object_response(serializers.complaint(complaint))


# ------------------------------------------------------------------ glycol loops

def require_glycol_system(account):
    """The common gate shared by maintenance, readings and glycol bookings."""
    if (account is None or not account["glycol_system_present"]
            or store.account_loop(account["id"]) is None):
        raise_error("ERR_NO_GLYCOL_SYSTEM")


@bp.get(API_PREFIX + "/glycol-loops/<loop_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def read_loop(loop_id):
    return object_response(serializers.glycol_loop(resolve_path("loop_id", loop_id)))


@bp.get(API_PREFIX + "/glycol-loops")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_loops():
    account_id = query_str("account_id")
    status = query_enum("status", LOOP_STATUSES)
    rows = [r for r in store.glycol_loops.values()
            if match(r, "account_id", account_id)
            and (status is None or projections.loop_status(r) == status)]
    return listing(rows, serializers.glycol_loop)


@bp.post(API_PREFIX + "/glycol-loops/<loop_id>/maintenance")
@guard(ROLE_TECH)
def service_loop(loop_id):
    loop = resolve_path("loop_id", loop_id)
    body = parse_body([
        F("visit_id", "id", required=True),
        F("glycol_pct", "num", required=True),
        F("pump_psi", "num", required=True),
        F("bath_temp_f", "num", required=True),
    ])
    visit = resolve_body("visit_id", body["visit_id"])
    require_self_technician(visit["technician_id"])
    if visit["work_status"] != "IN_PROGRESS":
        raise_error("ERR_VISIT_NOT_IN_PROGRESS")
    require_glycol_system(store.accounts.get(loop["account_id"]))
    loop["glycol_pct"] = body["glycol_pct"]
    loop["pump_psi"] = body["pump_psi"]
    loop["bath_temp_f"] = body["bath_temp_f"]
    loop["last_serviced_at"] = store.now()
    store.touch(loop)
    return object_response(serializers.glycol_loop(loop))


# ---------------------------------------------------------------- cooler readings

@bp.post(API_PREFIX + "/cooler-readings")
@guard(ROLE_TECH, ROLE_VENUE)
def create_reading():
    body = parse_body([
        F("glycol_loop_id", "id", required=True),
        F("cooler_temp_f", "num", required=True),
        F("glycol_supply_temp_f", "num", required=True),
    ])
    loop = resolve_body("glycol_loop_id", body["glycol_loop_id"])
    venue_scope(loop["account_id"])
    require_glycol_system(store.accounts.get(loop["account_id"]))
    row = store.new_row({
        "glycol_loop_id": loop["id"],
        "reading_at": store.now(),
        "cooler_temp_f": body["cooler_temp_f"],
        "glycol_supply_temp_f": body["glycol_supply_temp_f"],
        "source": "TECH_MANUAL" if g.user_role == ROLE_TECH else "VENUE_MANUAL",
        "recorded_by_user_id": g.user_id,
    }, mutable=False)
    store.cooler_readings[row["id"]] = row
    return object_response(serializers.cooler_reading(row), 201)


@bp.get(API_PREFIX + "/cooler-readings/<reading_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def read_reading(reading_id):
    return object_response(serializers.cooler_reading(
        resolve_path("reading_id", reading_id)))


@bp.get(API_PREFIX + "/cooler-readings")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_readings():
    loop_id = query_str("glycol_loop_id")
    source = query_enum("source", READING_SOURCES)
    rows = [r for r in store.cooler_readings.values()
            if match(r, "glycol_loop_id", loop_id) and match(r, "source", source)]
    return listing(rows, serializers.cooler_reading)
