"""TransferPortalEntry endpoints."""

from flask import Blueprint, g, request

import db
import services
from errors import (
    APIError,
    ERR_PORTAL_WINDOW_CLOSED,
    ERR_ATHLETE_NOT_CERTIFIED,
    ERR_SLOT_CAP_EXCEEDED,
    ERR_STALE_ENTRY_VERSION,
    invalid_request,
    invalid_state,
    not_found,
    unauthorized,
)
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("transfer_portal", __name__)


ENTRY_STATUSES = {"ENTERED", "MATCHED", "WITHDRAWN", "EXPIRED"}


@bp.post("/ncaa/transfer-portal-entries")
def create_entry():
    require_roles("StudentAthlete")
    body = get_body()
    athlete_id = require_field(body, "student_athlete_id", str)
    source_program_id = require_field(body, "source_program_id", str)
    athlete = db.student_athletes.get(athlete_id)
    if athlete is None:
        raise not_found("StudentAthlete not found.")
    source_program = db.programs.get(source_program_id)
    if source_program is None:
        raise not_found("Source Program not found.")
    # Ownership: acting athlete is the entry's subject
    if g.user_id != athlete_id:
        raise unauthorized(
            "StudentAthlete may only create transfer entries for themselves."
        )
    entered_at = db.current_utc_iso()
    window_closes_at = db.iso_plus_days(entered_at, 45)
    row = {
        "id": db.new_id(),
        "student_athlete_id": athlete_id,
        "source_program_id": source_program_id,
        "matched_program_id": None,
        "entered_at": entered_at,
        "window_closes_at": window_closes_at,
        "status": "ENTERED",
    }
    db.stamp_create(row)
    db.transfer_portal_entries[row["id"]] = row
    # Flip athlete.in_transfer_portal := true
    athlete["in_transfer_portal"] = True
    db.stamp_update(athlete)
    return ok_object(row, 201)


@bp.get("/ncaa/transfer-portal-entries/<entry_id>")
def get_entry(entry_id):
    require_roles("ComplianceOfficer", "StudentAthlete")
    row = db.transfer_portal_entries.get(entry_id)
    if row is None:
        raise not_found("TransferPortalEntry not found.")
    return ok_object(row)


@bp.get("/ncaa/transfer-portal-entries")
def list_entries():
    require_roles("ComplianceOfficer", "StudentAthlete")
    limit, offset = parse_pagination()
    athlete = request.args.get("student_athlete_id")
    status = request.args.get("status")
    src = request.args.get("source_program_id")
    matched = request.args.get("matched_program_id")
    if status is not None and status not in ENTRY_STATUSES:
        raise invalid_request("status filter is not a valid enum.")
    rows = list(db.transfer_portal_entries.values())
    if athlete is not None:
        rows = [r for r in rows if r["student_athlete_id"] == athlete]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if src is not None:
        rows = [r for r in rows if r["source_program_id"] == src]
    if matched is not None:
        rows = [r for r in rows if r["matched_program_id"] == matched]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/ncaa/transfer-portal-entries/<entry_id>/match")
def match_entry(entry_id):
    require_roles("ComplianceOfficer")
    entry = db.transfer_portal_entries.get(entry_id)
    if entry is None:
        raise not_found("TransferPortalEntry not found.")
    body = get_body()
    # Required: matched_program_id, expected_transferportalentry_version
    matched_program_id = require_field(body, "matched_program_id", str)
    if "expected_transferportalentry_version" not in body:
        raise invalid_request("expected_transferportalentry_version is required.")
    raw_v = body["expected_transferportalentry_version"]
    if isinstance(raw_v, bool) or not isinstance(raw_v, int):
        raise invalid_request("expected_transferportalentry_version must be an integer.")
    # FK resolution: matched program exists
    dest_program = db.programs.get(matched_program_id)
    if dest_program is None:
        raise not_found("Matched Program not found.")
    # State check
    if entry["status"] != "ENTERED":
        raise invalid_state("Entry is not in ENTERED state.")
    # OCC (priority 6)
    if int(raw_v) != int(entry["version"]):
        raise APIError(
            ERR_STALE_ENTRY_VERSION,
            "expected_transferportalentry_version does not match.",
            412,
        )
    # Window check (priority 11)
    now_dt = db.current_utc_dt()
    if now_dt >= db.parse_iso(entry["window_closes_at"]):
        raise APIError(
            ERR_PORTAL_WINDOW_CLOSED,
            "Transfer-portal window has closed for this entry.",
            422,
        )
    # Athlete must be CERTIFIED
    athlete = db.student_athletes.get(entry["student_athlete_id"])
    if athlete is None or athlete["eligibility_status"] != "CERTIFIED":
        raise APIError(
            ERR_ATHLETE_NOT_CERTIFIED,
            "Athlete must be CERTIFIED to match a transfer-portal entry.",
            422,
        )
    # Destination program slot capacity
    committed = services.compute_slots_committed(matched_program_id)
    if committed + 1 > dest_program["scholarship_slot_cap"]:
        raise APIError(
            ERR_SLOT_CAP_EXCEEDED,
            "Matched program is at scholarship_slot_cap.",
            422,
        )
    # Apply
    entry["matched_program_id"] = matched_program_id
    entry["status"] = "MATCHED"
    db.stamp_update(entry)
    athlete["enrolled_program_id"] = matched_program_id
    athlete["in_transfer_portal"] = False
    db.stamp_update(athlete)
    return ok_object(entry)


@bp.post("/ncaa/transfer-portal-entries/<entry_id>/withdraw")
def withdraw_entry(entry_id):
    require_roles("StudentAthlete")
    entry = db.transfer_portal_entries.get(entry_id)
    if entry is None:
        raise not_found("TransferPortalEntry not found.")
    if entry["status"] != "ENTERED":
        raise invalid_state("Entry is not in ENTERED state.")
    # Ownership
    if g.user_id != entry["student_athlete_id"]:
        raise unauthorized(
            "Acting StudentAthlete is not the entry's subject."
        )
    # Window check
    now_dt = db.current_utc_dt()
    if now_dt >= db.parse_iso(entry["window_closes_at"]):
        raise APIError(
            ERR_PORTAL_WINDOW_CLOSED,
            "Transfer-portal window has closed for this entry.",
            422,
        )
    entry["status"] = "WITHDRAWN"
    db.stamp_update(entry)
    athlete = db.student_athletes.get(entry["student_athlete_id"])
    if athlete is not None:
        athlete["in_transfer_portal"] = False
        db.stamp_update(athlete)
    return ok_object(entry)
