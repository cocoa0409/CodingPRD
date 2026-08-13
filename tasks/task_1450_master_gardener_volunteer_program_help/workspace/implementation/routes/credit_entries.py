"""CreditEntry endpoints: create (volunteer self-service), list, get, approve/reject/revoke.
RecertificationRecord endpoints: list, get, evaluate, grant-exemption."""

from flask import request, Blueprint

import db
import util
from util import D, is_multiple_quarter
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("credit", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]

ENTRY_KINDS = ("SERVICE", "CONTINUING_ED")
ACTIVITY_TYPES = ("HELP_DESK", "OUTREACH", "GARDEN", "PROJECT", "OTHER")
MANUAL_SOURCE_TYPES = ("NONE", "PROJECT")


def get_entry_or_404(entry_id):
    e = db.credit_entries.get(entry_id)
    if e is None:
        raise_err("ERR_NOT_FOUND", "CreditEntry not found")
    return e


def _recompute_after_entry_change(entry):
    rec = calc.record_for(entry["volunteer_id"], entry["cycle_id"])
    if rec is not None and rec["status"] == "PENDING":
        calc.recompute_record(rec)
    vol = db.volunteers.get(entry["volunteer_id"])
    if vol is not None:
        calc.recompute_recognition(vol)


@bp.route("/volunteers/<volunteerId>/credit-entries", methods=["POST"])
def create_credit_entry(volunteerId):
    user_id, role = auth_context(["Volunteer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    # schema (priority 3)
    for f in ("cycle_id", "entry_kind", "activity_date", "hours"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not isinstance(body["cycle_id"], str):
        raise_err("ERR_INVALID_REQUEST", "cycle_id must be a string")
    if body["entry_kind"] not in ENTRY_KINDS:
        raise_err("ERR_INVALID_REQUEST", "entry_kind must be SERVICE or CONTINUING_ED")
    if not isinstance(body["activity_date"], str) or not util.is_iso_date(body["activity_date"]):
        raise_err("ERR_INVALID_REQUEST", "activity_date must be an ISO 8601 date")
    hours = body["hours"]
    if not isinstance(hours, (int, float)) or isinstance(hours, bool):
        raise_err("ERR_INVALID_REQUEST", "hours must be a number")
    hd = D(hours)
    if hd <= 0 or hd > D("12.0") or not is_multiple_quarter(hd):
        raise_err("ERR_INVALID_FIELD_VALUE", "hours must be a positive multiple of 0.25 and <= 12.0")

    entry_kind = body["entry_kind"]
    activity_type = body.get("activity_type")
    provider = body.get("provider")
    title = body.get("title")
    source_type = body.get("source_type", "NONE")
    source_id = body.get("source_id")
    note = body.get("note")

    if entry_kind == "SERVICE":
        if activity_type is None:
            raise_err("ERR_MISSING_KIND_FIELDS", "SERVICE entry requires activity_type")
        if activity_type not in ACTIVITY_TYPES:
            raise_err("ERR_INVALID_REQUEST", "activity_type is not a valid enum member")
        if provider is not None or title is not None:
            raise_err("ERR_MISSING_KIND_FIELDS", "provider/title are forbidden on SERVICE entries")
    else:  # CONTINUING_ED
        if activity_type is not None:
            raise_err("ERR_MISSING_KIND_FIELDS", "activity_type is forbidden on CONTINUING_ED entries")
        if not provider or not isinstance(provider, str) or not title or not isinstance(title, str):
            raise_err("ERR_MISSING_KIND_FIELDS", "CONTINUING_ED entry requires provider and title")

    if source_type not in MANUAL_SOURCE_TYPES:
        # SHIFT/ROTATION reserved for system-generated entries
        if source_type in ("SHIFT", "ROTATION"):
            raise_err("ERR_MISSING_KIND_FIELDS", "source_type SHIFT/ROTATION is reserved for system-generated entries")
        raise_err("ERR_INVALID_REQUEST", "source_type is not a valid enum member")
    if source_type != "NONE" and not source_id:
        raise_err("ERR_MISSING_KIND_FIELDS", "source_id is required when source_type is not NONE")
    if source_type == "NONE":
        source_id = None

    # existence (priority 4): path id first, then body refs
    vol = db.volunteers.get(volunteerId)
    if vol is None:
        raise_err("ERR_NOT_FOUND", "Volunteer not found")
    # ownership (priority 5)
    if user_id != vol["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Credit entries may only be logged for oneself")
    cycle = db.program_cycles.get(body["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "cycle_id does not resolve")

    # posture (priority 7): cycle OPEN
    if cycle["status"] != "OPEN":
        raise_err("ERR_CYCLE_NOT_OPEN", "Credit-entry writes require an OPEN cycle")
    # volunteer ACTIVE (state tier)
    if vol["status"] != "ACTIVE":
        raise_err("ERR_VOLUNTEER_NOT_ACTIVE", "Volunteer must be ACTIVE to log credit entries")

    # temporal (priority 11): activity_date inside cycle window
    adate = util.parse_date(body["activity_date"])
    if adate < util.parse_date(cycle["start_date"]) or adate > util.parse_date(cycle["end_date"]):
        raise_err("ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW", "activity_date is outside the cycle window")

    # referential (priority 12): PROJECT source must be APPROVED or CLOSED
    if source_type == "PROJECT":
        project = db.community_projects.get(source_id)
        if project is None:
            raise_err("ERR_NOT_FOUND", "source_id does not resolve to an existing project")
        if project["status"] not in ("APPROVED", "CLOSED"):
            raise_err("ERR_PROJECT_NOT_CREDITABLE", "Project must be APPROVED or CLOSED to source credit")

    entry = util.new_resource({
        "volunteer_id": vol["id"],
        "cycle_id": cycle["id"],
        "entry_kind": entry_kind,
        "activity_type": activity_type,
        "provider": provider,
        "title": title,
        "activity_date": body["activity_date"],
        "hours": float(hd),
        "status": "PENDING",
        "source_type": source_type,
        "source_id": source_id,
        "note": note,
        "decided_at": None,
    })
    db.credit_entries[entry["id"]] = entry
    return success_object(entry, 201)


@bp.route("/credit-entries", methods=["GET"])
def list_credit_entries():
    auth_context(ALL_ROLES)
    items = list(db.credit_entries.values())
    for param in ("volunteer_id", "cycle_id", "entry_kind", "status", "source_type", "source_id"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/credit-entries/<entryId>", methods=["GET"])
def get_credit_entry(entryId):
    auth_context(ALL_ROLES)
    return success_object(get_entry_or_404(entryId))


def _entry_cycle_gate(entry):
    cycle = db.program_cycles.get(entry["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "Entry's cycle not found")
    if cycle["status"] != "OPEN":
        raise_err("ERR_CYCLE_NOT_OPEN", "Credit-entry writes require an OPEN cycle")
    return cycle


@bp.route("/credit-entries/<entryId>/approve", methods=["POST"])
def approve_entry(entryId):
    auth_context(PC)
    entry = get_entry_or_404(entryId)
    # posture (priority 7) precedes target state (priority 8)
    _entry_cycle_gate(entry)
    if entry["status"] != "PENDING":
        raise_err("ERR_ENTRY_NOT_PENDING", "Approve requires a PENDING entry")
    entry["status"] = "APPROVED"
    entry["decided_at"] = util.logical_clock_iso()
    util.touch(entry)
    _recompute_after_entry_change(entry)
    return success_object(entry)


@bp.route("/credit-entries/<entryId>/reject", methods=["POST"])
def reject_entry(entryId):
    auth_context(PC)
    body = request.get_json(silent=True) or {}
    entry = get_entry_or_404(entryId)
    _entry_cycle_gate(entry)
    if entry["status"] != "PENDING":
        raise_err("ERR_ENTRY_NOT_PENDING", "Reject requires a PENDING entry")
    entry["status"] = "REJECTED"
    entry["decided_at"] = util.logical_clock_iso()
    util.touch(entry)
    _recompute_after_entry_change(entry)
    return success_object(entry)


@bp.route("/credit-entries/<entryId>/revoke", methods=["POST"])
def revoke_entry(entryId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "reason" not in body or not isinstance(body.get("reason"), str) or not body.get("reason"):
        raise_err("ERR_INVALID_REQUEST", "reason is required")
    entry = get_entry_or_404(entryId)
    _entry_cycle_gate(entry)
    if entry["status"] != "APPROVED":
        raise_err("ERR_ENTRY_NOT_APPROVED", "Revoke requires an APPROVED entry")
    entry["status"] = "VOIDED"
    entry["decided_at"] = util.logical_clock_iso()
    util.touch(entry)
    _recompute_after_entry_change(entry)
    return success_object(entry)


# =====================================================================
# RecertificationRecord endpoints
# =====================================================================

def _get_record_or_404(record_id):
    r = db.recertification_records.get(record_id)
    if r is None:
        raise_err("ERR_NOT_FOUND", "RecertificationRecord not found")
    return r


@bp.route("/recertification-records", methods=["GET"])
def list_records():
    auth_context(ALL_ROLES)
    items = list(db.recertification_records.values())
    for param in ("volunteer_id", "cycle_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/recertification-records/<recordId>", methods=["GET"])
def get_record(recordId):
    auth_context(ALL_ROLES)
    return success_object(_get_record_or_404(recordId))


@bp.route("/recertification-records/<recordId>/evaluate", methods=["POST"])
def evaluate_record(recordId):
    auth_context(PC)
    record = _get_record_or_404(recordId)
    if record["status"] != "PENDING":
        raise_err("ERR_RECORD_NOT_PENDING", "Evaluate requires a PENDING record")
    calc.recompute_record(record, stamp_evaluated=True)
    vol = db.volunteers.get(record["volunteer_id"])
    if vol is not None:
        calc.recompute_recognition(vol)
    return success_object(record)


@bp.route("/recertification-records/<recordId>/grant-exemption", methods=["POST"])
def grant_exemption(recordId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "reason" not in body or not isinstance(body.get("reason"), str) or not body.get("reason"):
        raise_err("ERR_INVALID_REQUEST", "reason is required")
    record = _get_record_or_404(recordId)
    if record["status"] != "PENDING":
        raise_err("ERR_RECORD_NOT_PENDING", "Grant-exemption requires a PENDING record")
    record["hardship_exemption"] = True
    record["exemption_reason"] = body["reason"]
    calc.recompute_record(record)
    return success_object(record)
