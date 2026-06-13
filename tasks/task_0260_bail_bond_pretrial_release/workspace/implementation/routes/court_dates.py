"""CourtDate, Notification, appearance outcomes, and CheckIn endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import now_utc, now_iso, parse_iso
from errors import err
from helpers import paginate, require_enum, require_fields, require_int, require_str
from lookup import (get_bond, get_court_date, get_court_date_for_defendant,
                    get_defendant)
from middleware import (authenticate, get_json_body, parse_pagination,
                        require_role)
from response import array_response, object_response
from services import calculations as calc
from services import domain
from views import view, view_list

bp = Blueprint("court_dates", __name__)

HEARING_TYPES = {"ARRAIGNMENT", "PRETRIAL", "TRIAL", "SENTENCING"}
CHANNELS = {"SMS", "VOICE", "EMAIL"}
CONDITION_CODES = {"GPS", "CURFEW", "DRUG_TEST", "NO_CONTACT"}
RESULTS = {"PASS", "FAIL", "MISSED"}


@bp.route("/defendants/<defendant_id>/bonds/<bond_id>/court-dates", methods=["POST"])
def create_court_date(defendant_id, bond_id):
    _, role = authenticate()
    require_role(role, {"Court"})
    bond = db.bonds.get(bond_id)
    get_defendant(defendant_id)
    if bond is None or bond["defendant_id"] != defendant_id:
        raise err("ERR_NOT_FOUND", "Bond not found for this defendant.")

    body = get_json_body()
    require_fields(body, ["scheduled_utc"])
    scheduled_str = require_str(body, "scheduled_utc")
    scheduled_dt = parse_iso(scheduled_str)
    if scheduled_dt is None:
        raise err("ERR_INVALID_REQUEST", "scheduled_utc is not a valid ISO 8601 instant.")
    duration = require_int(body, "duration_minutes", required=False, default=60, gt=0)
    hearing_type = require_enum(body, "hearing_type", HEARING_TYPES,
                                required=False, default="ARRAIGNMENT")

    # scheduled_utc must be in the future at creation.
    if scheduled_dt <= now_utc():
        raise err("ERR_INVALID_REQUEST", "scheduled_utc must be in the future.")

    # Docket overlap check (priority 12) against SCHEDULED/NOTIFIED hearings on this bond.
    new_start = scheduled_dt
    new_end = scheduled_dt + timedelta(minutes=duration)
    buffer = timedelta(minutes=calc.DOCKET_BUFFER_MINUTES)
    for existing in domain.court_dates_for_bond(bond_id):
        if existing["status"] not in ("SCHEDULED", "NOTIFIED"):
            continue
        e_start = parse_iso(existing["scheduled_utc"])
        e_end = e_start + timedelta(minutes=existing["duration_minutes"])
        # collision iff new_start <= e_end+buffer AND e_start-buffer <= new_end (closed/inclusive)
        if new_start <= (e_end + buffer) and (e_start - buffer) <= new_end:
            raise err("ERR_DOCKET_OVERLAP", "Court date collides with an existing hearing.")

    rec = db.make_record({
        "bond_id": bond_id,
        "scheduled_utc": scheduled_str,
        "duration_minutes": duration,
        "hearing_type": hearing_type,
        "status": "SCHEDULED",
        "notified_at": None,
    })
    db.court_dates[rec["id"]] = rec
    return object_response(view(rec), 201)


@bp.route("/bonds/<bond_id>/court-dates", methods=["GET"])
def list_bond_court_dates(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    get_bond(bond_id)
    limit, offset = parse_pagination()
    records = [c for c in db.court_dates.values() if c["bond_id"] == bond_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        records = [c for c in records if c["status"] == status_filter]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/court-dates/<court_date_id>", methods=["GET"])
def fetch_court_date(court_date_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    c = get_court_date(court_date_id)
    return object_response(view(c), 200)


@bp.route("/defendants/<defendant_id>/court-dates/<court_date_id>/notify", methods=["POST"])
def notify(defendant_id, court_date_id):
    _, role = authenticate()
    require_role(role, {"Court"})
    cd = get_court_date_for_defendant(defendant_id, court_date_id)
    body = get_json_body()
    channel = require_enum(body, "channel", CHANNELS, required=False, default="SMS")

    # State: must be SCHEDULED.
    if cd["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Notification only from SCHEDULED.")
    # Timing: clock strictly before scheduled_utc.
    scheduled_dt = parse_iso(cd["scheduled_utc"])
    if now_utc() >= scheduled_dt:
        raise err("ERR_TIMING_VIOLATION", "Notification must be before scheduled_utc.")

    defendant = db.defendants[defendant_id]
    lead_hours = calc.notification_lead_hours(scheduled_dt, now_utc())
    notif = db.make_record({
        "court_date_id": court_date_id,
        "channel": channel,
        "lead_hours": lead_hours,
        "destination": defendant["phone_e164"],
    }, mutable=False)
    db.notifications[notif["id"]] = notif

    cd["status"] = "NOTIFIED"
    cd["notified_at"] = now_iso()
    db.touch(cd)
    return object_response(view(cd), 200)


@bp.route("/court-dates/<court_date_id>/notifications", methods=["GET"])
def list_notifications(court_date_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer"})
    get_court_date(court_date_id)
    limit, offset = parse_pagination()
    records = [n for n in db.notifications.values() if n["court_date_id"] == court_date_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/defendants/<defendant_id>/court-dates/<court_date_id>/record-appearance",
          methods=["POST"])
def record_appearance(defendant_id, court_date_id):
    _, role = authenticate()
    require_role(role, {"Court"})
    cd = get_court_date_for_defendant(defendant_id, court_date_id)
    if cd["status"] not in ("SCHEDULED", "NOTIFIED"):
        raise err("ERR_INVALID_STATE", "Appearance only from SCHEDULED or NOTIFIED.")
    cd["status"] = "APPEARED"
    db.touch(cd)
    return object_response(view(cd), 200)


@bp.route("/defendants/<defendant_id>/court-dates/<court_date_id>/record-fta", methods=["POST"])
def record_fta(defendant_id, court_date_id):
    _, role = authenticate()
    require_role(role, {"Court"})
    cd = get_court_date_for_defendant(defendant_id, court_date_id)

    # State: SCHEDULED or NOTIFIED.
    if cd["status"] not in ("SCHEDULED", "NOTIFIED"):
        raise err("ERR_INVALID_STATE", "FTA only from SCHEDULED or NOTIFIED.")
    # Timing: clock at/after scheduled_utc.
    scheduled_dt = parse_iso(cd["scheduled_utc"])
    if now_utc() < scheduled_dt:
        raise err("ERR_TIMING_VIOLATION", "FTA cannot be recorded before scheduled_utc.")
    # Linked bond must be ACTIVE.
    bond = db.bonds.get(cd["bond_id"])
    if bond is None or bond["coverage_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Linked bond is not ACTIVE.")

    cd["status"] = "FAILED_TO_APPEAR"
    db.touch(cd)
    defendant = db.defendants[defendant_id]
    domain.forfeit_bond(defendant, bond, cd)
    return object_response(view(cd), 200)


@bp.route("/defendants/<defendant_id>/court-dates/<court_date_id>/continue", methods=["POST"])
def continue_court_date(defendant_id, court_date_id):
    _, role = authenticate()
    require_role(role, {"Court"})
    cd = get_court_date_for_defendant(defendant_id, court_date_id)
    if cd["status"] not in ("SCHEDULED", "NOTIFIED"):
        raise err("ERR_INVALID_STATE", "Continue only from SCHEDULED or NOTIFIED.")
    cd["status"] = "CONTINUED"
    db.touch(cd)
    return object_response(view(cd), 200)


# ---- Check-ins ----

@bp.route("/defendants/<defendant_id>/check-ins", methods=["POST"])
def create_check_in(defendant_id):
    _, role = authenticate()
    require_role(role, {"RecoveryAgent", "ComplianceOfficer"})
    get_defendant(defendant_id)
    body = get_json_body()
    require_fields(body, ["bond_id", "condition_code", "result"])
    bond_id = require_str(body, "bond_id")
    condition_code = require_enum(body, "condition_code", CONDITION_CODES)
    result = require_enum(body, "result", RESULTS)

    # Body FK existence + bond belongs to defendant.
    bond = db.bonds.get(bond_id)
    if bond is None:
        raise err("ERR_FK_NOT_FOUND", "bond_id does not reference an existing bond.")
    if bond["defendant_id"] != defendant_id:
        raise err("ERR_FK_NOT_FOUND", "bond_id does not belong to this defendant.")

    weight = calc.compliance_weight(result, condition_code)
    rec = db.make_record({
        "bond_id": bond_id,
        "condition_code": condition_code,
        "result": result,
        "occurred_utc": now_iso(),
        "weight": weight,
    }, mutable=False)
    db.check_ins[rec["id"]] = rec

    # GPS FAIL drives an ACTIVE device on this bond to TAMPER + increments violation_count.
    if condition_code == "GPS" and result == "FAIL":
        for d in domain.devices_for_bond(bond_id):
            if d["status"] == "ACTIVE":
                d["status"] = "TAMPER"
                d["violation_count"] = d.get("violation_count", 0) + 1
                db.touch(d)
    return object_response(view(rec), 201)


@bp.route("/bonds/<bond_id>/check-ins", methods=["GET"])
def list_check_ins(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer", "RecoveryAgent"})
    get_bond(bond_id)
    limit, offset = parse_pagination()
    records = [c for c in db.check_ins.values() if c["bond_id"] == bond_id]
    code_filter = request.args.get("condition_code")
    if code_filter is not None:
        records = [c for c in records if c["condition_code"] == code_filter]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)
