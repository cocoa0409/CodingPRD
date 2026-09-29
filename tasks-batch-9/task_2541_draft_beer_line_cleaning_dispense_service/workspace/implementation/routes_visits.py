"""Route booking, the field-work dimension and customer verification (PRD 3.3, 3.7)."""
from flask import Blueprint, g

import projections
import serializers
import settlement
import store
from common import (API_PREFIX, DISPUTE_WINDOW_HOURS, MAX_LEAD_DAYS, ROLE_AUDITOR,
                    ROLE_BREWER, ROLE_DISPATCH, ROLE_TECH, ROLE_VENUE,
                    TRAVEL_BUFFER_MINUTES, WAIVER_WAIT_HOURS, add_days, hours_between,
                    parse_date)
from envelope import object_response
from errors import raise_error
from helpers import listing, match, resolve_body, resolve_path
from security import guard, require_self_technician, venue_scope
from shape import F, bad, parse_body, query_enum, query_str
import shape

bp = Blueprint("visits", __name__)

VISIT_KINDS = ["ROUTINE_CLEANING", "EMERGENCY_TROUBLESHOOT", "GLYCOL_MAINTENANCE"]
WORK_STATUSES = ["SCHEDULED", "IN_PROGRESS", "WORK_COMPLETE", "ABANDONED"]
VERIFICATION_STATUSES = ["UNVERIFIED", "SIGNED", "WAIVED", "DISPUTED"]
SETTLEMENT_STATES = ["UNSETTLED", "SETTLED", "REVERSED"]
LIVE_WORK_STATUSES = ("SCHEDULED", "IN_PROGRESS")


def blank_visit_money():
    return {
        "abandon_reason": "NONE",
        "signer_name": None,
        "signed_at": None,
        "work_completed_at": None,
        "serviced_line_count": 0,
        "billable_line_count": 0,
        "cleaning_subtotal_cents": 0,
        "parts_charge_cents": 0,
        "provisional_charge_cents": 0,
        "settled_charge_cents": 0,
        "brewer_funded_cents": 0,
        "account_due_cents": 0,
    }


def screen_schedule(account, technician_id, date, start, end, exclude_visit_id=None):
    """The five scheduling rules (P30-P34), in ladder order."""
    today = store.today()
    if date < today:
        raise_error("ERR_VISIT_DATE_IN_PAST")
    if date > add_days(today, MAX_LEAD_DAYS):
        raise_error("ERR_SCHEDULE_LEAD_EXCEEDED")
    if (start < account["access_window_start_minute"]
            or end > account["access_window_end_minute"]):
        raise_error("ERR_OUTSIDE_ACCESS_WINDOW")
    # Venue slot exclusivity: non-strict on both sides, so touching slots clash.
    for other in store.sort_created(store.account_visits(account["id"])):
        if other["id"] == exclude_visit_id:
            continue
        if other["work_status"] not in LIVE_WORK_STATUSES:
            continue
        if other["scheduled_date"] != date:
            continue
        if start <= other["scheduled_end_minute"] and end >= other["scheduled_start_minute"]:
            raise_error("ERR_VENUE_SLOT_CONFLICT")
    # Technician route feasibility: strict on both sides, with a 30 minute buffer.
    buffer = TRAVEL_BUFFER_MINUTES
    for other in store.sort_created(list(store.visits.values())):
        if other["id"] == exclude_visit_id:
            continue
        if other["technician_id"] != technician_id:
            continue
        if other["work_status"] not in LIVE_WORK_STATUSES:
            continue
        if other["scheduled_date"] != date:
            continue
        if (start < other["scheduled_end_minute"] + buffer
                and other["scheduled_start_minute"] < end + buffer):
            raise_error("ERR_TECHNICIAN_ROUTE_CONFLICT")


def require_single_active_contract(account_id):
    contracts = [c for c in store.account_contracts(account_id) if c["status"] == "ACTIVE"]
    if len(contracts) != 1:
        raise_error("ERR_NO_ACTIVE_CONTRACT")
    return contracts[0]


@bp.post(API_PREFIX + "/service-visits")
@guard(ROLE_DISPATCH)
def create_visit():
    body = parse_body([
        F("account_id", "id", required=True),
        F("technician_id", "id", required=True),
        F("visit_kind", "enum", required=True, values=VISIT_KINDS),
        F("scheduled_date", "date", required=True),
        F("scheduled_start_minute", "int", required=True, min_value=0, max_value=1439),
        F("scheduled_end_minute", "int", required=True, min_value=1, max_value=1440),
    ])
    if body["scheduled_end_minute"] <= body["scheduled_start_minute"]:
        bad("scheduled_end_minute must be strictly greater than scheduled_start_minute.")
    account = resolve_body("account_id", body["account_id"])
    technician = resolve_body("technician_id", body["technician_id"])
    if account["status"] != "ACTIVE":
        raise_error("ERR_ACCOUNT_NOT_ACTIVE")
    require_single_active_contract(account["id"])
    if technician["status"] != "ACTIVE":
        raise_error("ERR_TECHNICIAN_INACTIVE")
    screen_schedule(account, technician["id"], body["scheduled_date"],
                    body["scheduled_start_minute"], body["scheduled_end_minute"])
    if body["visit_kind"] == "GLYCOL_MAINTENANCE":
        if not account["glycol_system_present"] or store.account_loop(account["id"]) is None:
            raise_error("ERR_NO_GLYCOL_SYSTEM")
    row = store.new_row(dict(blank_visit_money(), **{
        "account_id": account["id"],
        "technician_id": technician["id"],
        "rescheduled_from_visit_id": None,
        "visit_kind": body["visit_kind"],
        "scheduled_date": body["scheduled_date"],
        "scheduled_start_minute": body["scheduled_start_minute"],
        "scheduled_end_minute": body["scheduled_end_minute"],
        "work_status": "SCHEDULED",
        "verification_status": "UNVERIFIED",
        "settlement_state": "UNSETTLED",
    }))
    store.visits[row["id"]] = row
    return object_response(serializers.visit(row), 201)


@bp.get(API_PREFIX + "/service-visits/<visit_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE, ROLE_BREWER)
def read_visit(visit_id):
    return object_response(serializers.visit(resolve_path("visit_id", visit_id)))


@bp.get(API_PREFIX + "/service-visits")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_visits():
    account_id = query_str("account_id")
    technician_id = query_str("technician_id")
    predecessor = query_str("rescheduled_from_visit_id")
    work_status = query_enum("work_status", WORK_STATUSES)
    verification_status = query_enum("verification_status", VERIFICATION_STATUSES)
    settlement_state = query_enum("settlement_state", SETTLEMENT_STATES)
    raw_date = query_str("scheduled_date")
    scheduled_date = None
    if raw_date is not None:
        scheduled_date = parse_date(raw_date)
        if scheduled_date is None:
            bad("Query parameter 'scheduled_date' must be a YYYY-MM-DD date.")
    rows = [r for r in store.visits.values()
            if match(r, "account_id", account_id)
            and match(r, "technician_id", technician_id)
            and match(r, "rescheduled_from_visit_id", predecessor)
            and match(r, "work_status", work_status)
            and match(r, "verification_status", verification_status)
            and match(r, "settlement_state", settlement_state)
            and match(r, "scheduled_date", scheduled_date)]
    return listing(rows, serializers.visit)


@bp.post(API_PREFIX + "/service-visits/<visit_id>/start")
@guard(ROLE_TECH)
def start_visit(visit_id):
    visit = resolve_path("visit_id", visit_id)
    parse_body([])
    require_self_technician(visit["technician_id"])
    if visit["work_status"] != "SCHEDULED":
        raise_error("ERR_VISIT_NOT_SCHEDULED")
    account = store.accounts.get(visit["account_id"])
    if account is None or account["status"] != "ACTIVE":
        raise_error("ERR_ACCOUNT_NOT_ACTIVE")
    if store.today() < visit["scheduled_date"]:
        raise_error("ERR_VISIT_START_TOO_EARLY")
    visit["work_status"] = "IN_PROGRESS"
    store.touch(visit)
    return object_response(serializers.visit(visit))


@bp.post(API_PREFIX + "/service-visits/<visit_id>/complete-work")
@guard(ROLE_TECH)
def complete_visit_work(visit_id):
    visit = resolve_path("visit_id", visit_id)
    parse_body([])
    require_self_technician(visit["technician_id"])
    if visit["work_status"] != "IN_PROGRESS":
        raise_error("ERR_VISIT_NOT_IN_PROGRESS")
    if visit["visit_kind"] == "GLYCOL_MAINTENANCE":
        loop = store.account_loop(visit["account_id"])
        serviced = (loop is not None and loop["last_serviced_at"] is not None
                    and loop["last_serviced_at"].date() >= visit["scheduled_date"])
        if not serviced:
            raise_error("ERR_NO_WORK_RECORDED")
    else:
        posted = [c for c in store.visit_cycles(visit["id"])
                  if c["record_status"] == "POSTED"]
        if not posted:
            raise_error("ERR_NO_WORK_RECORDED")
    visit["work_completed_at"] = store.now()
    visit["work_status"] = "WORK_COMPLETE"
    settlement.run_provisional(visit)
    store.touch(visit)
    return object_response(serializers.visit(visit))


@bp.post(API_PREFIX + "/service-visits/<visit_id>/reschedule")
@guard(ROLE_DISPATCH)
def reschedule_visit(visit_id):
    original = resolve_path("visit_id", visit_id)
    body = parse_body([
        F("scheduled_date", "date", required=True),
        F("scheduled_start_minute", "int", required=True, min_value=0, max_value=1439),
        F("scheduled_end_minute", "int", required=True, min_value=1, max_value=1440),
        F("technician_id", "id"),
    ])
    if body["scheduled_end_minute"] <= body["scheduled_start_minute"]:
        bad("scheduled_end_minute must be strictly greater than scheduled_start_minute.")
    replacement_tech = resolve_body("technician_id", body["technician_id"], optional=True)
    if original["work_status"] != "SCHEDULED":
        raise_error("ERR_VISIT_NOT_SCHEDULED")
    technician = replacement_tech
    if technician is None:
        technician = store.technicians.get(original["technician_id"])
    if technician is None or technician["status"] != "ACTIVE":
        raise_error("ERR_TECHNICIAN_INACTIVE")
    account = store.accounts.get(original["account_id"])
    # The replacement slot is re-screened exactly as a fresh booking, except that
    # the original visit it displaces cannot conflict with itself.
    screen_schedule(account, technician["id"], body["scheduled_date"],
                    body["scheduled_start_minute"], body["scheduled_end_minute"],
                    exclude_visit_id=original["id"])
    original["work_status"] = "ABANDONED"
    original["abandon_reason"] = "RESCHEDULED"
    store.touch(original)
    row = store.new_row(dict(blank_visit_money(), **{
        "account_id": original["account_id"],
        "technician_id": technician["id"],
        "rescheduled_from_visit_id": original["id"],
        "visit_kind": original["visit_kind"],
        "scheduled_date": body["scheduled_date"],
        "scheduled_start_minute": body["scheduled_start_minute"],
        "scheduled_end_minute": body["scheduled_end_minute"],
        "work_status": "SCHEDULED",
        "verification_status": "UNVERIFIED",
        "settlement_state": "UNSETTLED",
    }))
    store.visits[row["id"]] = row
    return object_response(serializers.visit(row), 201)


@bp.post(API_PREFIX + "/service-visits/<visit_id>/verification")
@guard(ROLE_VENUE)
def decide_verification(visit_id):
    visit = resolve_path("visit_id", visit_id)
    body = parse_body([
        F("decision", "enum", required=True, values=["SIGN", "DISPUTE"]),
        F("signer_name", "str", max_len=120),
        F("dispute_reason", "str"),
    ])
    decision = body["decision"]
    if decision == "SIGN" and body["signer_name"] is None:
        bad("signer_name is required when decision is SIGN.")
    if decision == "DISPUTE" and body["dispute_reason"] is None:
        bad("dispute_reason is required when decision is DISPUTE.")
    venue_scope(visit["account_id"])
    # The verification dimension is consulted first: it decides whether the
    # decision is admissible at all (PRD 3.7).
    if decision == "SIGN":
        if visit["verification_status"] not in ("UNVERIFIED", "DISPUTED"):
            raise_error("ERR_VERIFICATION_ALREADY_RECORDED")
    else:
        if visit["verification_status"] != "SIGNED":
            raise_error("ERR_VERIFICATION_ALREADY_RECORDED")
    if visit["work_status"] != "WORK_COMPLETE":
        raise_error("ERR_WORK_NOT_COMPLETE")
    if decision == "SIGN":
        visit["signer_name"] = body["signer_name"]
        visit["signed_at"] = store.now()
        visit["verification_status"] = "SIGNED"
        settlement.run_settled(visit, False)
    else:
        signed_at = visit["signed_at"]
        if signed_at is None or hours_between(store.now(), signed_at) > DISPUTE_WINDOW_HOURS:
            raise_error("ERR_DISPUTE_WINDOW_CLOSED")
        visit["dispute_reason"] = body["dispute_reason"]
        visit["verification_status"] = "DISPUTED"
        settlement.reverse_settlement(visit)
    store.touch(visit)
    return object_response(serializers.visit(visit))


@bp.post(API_PREFIX + "/service-visits/<visit_id>/verification-waiver")
@guard(ROLE_AUDITOR)
def waive_verification(visit_id):
    visit = resolve_path("visit_id", visit_id)
    body = parse_body([F("waiver_note", "str", required=True)])
    if visit["verification_status"] != "UNVERIFIED":
        raise_error("ERR_VERIFICATION_ALREADY_RECORDED")
    if visit["work_status"] != "WORK_COMPLETE":
        raise_error("ERR_WORK_NOT_COMPLETE")
    completed_at = visit["work_completed_at"]
    if completed_at is None or hours_between(store.now(), completed_at) < WAIVER_WAIT_HOURS:
        raise_error("ERR_WAIVER_TOO_EARLY")
    visit["waiver_note"] = body["waiver_note"]
    visit["verification_status"] = "WAIVED"
    settlement.run_settled(visit, True)
    store.touch(visit)
    return object_response(serializers.visit(visit))
