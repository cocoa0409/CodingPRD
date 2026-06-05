"""Registration + MaintenanceFiling routes (PRD §3.5). Maintenance loop
revisits ACTIVE; ACTIVE -> GRACE -> {ACTIVE | EXPIRED}.
"""

from flask import Blueprint

from db import db, parse_iso, iso_from_datetime
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services import models, calc
from services.body import get_json_body, require_nonempty_string, require_enum, require_int
from services.pagination import parse_pagination, slice_sorted
from services.dateutil import add_days

bp = Blueprint("registrations", __name__)

FILING_TYPES = {"SECTION_8", "SECTION_8_AND_9"}


# ----- Reads ----------------------------------------------------------------

@bp.get("/registrations/<rid>")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def get_registration(rid, _user_id, _role):
    rec = models.get_or_404(db.registrations, rid, "Registration")
    return success(models.ser_registration(rec), 200)


@bp.get("/registrations/<rid>/maintenance-filings")
@require_roles("Attorney", "Applicant", "Examiner")
def list_maintenance_filings(rid, _user_id, _role):
    models.get_or_404(db.registrations, rid, "Registration")
    limit, offset = parse_pagination()
    items = [
        f for f in db.maintenance_filings.values() if f["registration_id"] == rid
    ]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_maintenance_filing(f) for f in page], limit, offset, total
    )


# ----- Enter grace (system: ACTIVE -> GRACE) --------------------------------

@bp.post("/registrations/<rid>/enter-grace")
@require_roles("Examiner")
def enter_grace(rid, _user_id, _role):
    reg = models.get_or_404(db.registrations, rid, "Registration")
    if reg["status"] != "ACTIVE":
        raise_api("ERR_INVALID_STATE", "Registration is not ACTIVE")
    now = db.current_utc_dt()
    if reg.get("next_maintenance_due_at") is None or now <= parse_iso(
        reg["next_maintenance_due_at"]
    ):
        raise_api("ERR_INVALID_STATE", "Maintenance window has not yet closed")

    models.set_docket_status("MAINTENANCE", rid, "MISSED", only_pending=True)
    reg["status"] = "GRACE"
    models.touch(reg)
    return success(models.ser_registration(reg), 200)


# ----- Expire (system: GRACE -> EXPIRED) ------------------------------------

@bp.post("/registrations/<rid>/expire")
@require_roles("Examiner")
def expire_registration(rid, _user_id, _role):
    reg = models.get_or_404(db.registrations, rid, "Registration")
    if reg["status"] != "GRACE":
        raise_api("ERR_INVALID_STATE", "Registration is not in GRACE")
    now = db.current_utc_dt()
    grace_end = add_days(parse_iso(reg["next_maintenance_due_at"]), calc.GRACE_WINDOW_DAYS)
    if now <= grace_end:
        raise_api("ERR_INVALID_STATE", "Grace window has not yet elapsed")

    reg["next_maintenance_due_at"] = None
    reg["status"] = "EXPIRED"
    models.touch(reg)
    return success(models.ser_registration(reg), 200)


# ----- File maintenance (OCC-guarded) ---------------------------------------

mf_bp = Blueprint("maintenance_filings", __name__)


@mf_bp.post("/maintenance-filings")
@require_roles("Attorney", "Applicant")
def file_maintenance(_user_id, _role):
    body = get_json_body()
    registration_id = require_nonempty_string(body, "registration_id")
    filing_type = require_enum(body, "filing_type", FILING_TYPES)
    expected_version = require_int(body, "expected_registration_version")

    reg = models.get_or_404(db.registrations, registration_id, "Registration")

    # Ownership (priority 4): the registration's underlying application owner.
    app = db.applications.get(reg["application_id"])
    if app is not None:
        from services.ownership import check_application_owner
        check_application_owner(app, _role, _user_id)

    # OCC (priority 7).
    if expected_version != reg["version"]:
        raise_api("ERR_STALE_VERSION", "Registration version is stale")

    # Business temporal (priority 16): not before the window opens.
    now = db.current_utc_dt()
    due_at = reg.get("next_maintenance_due_at")
    if due_at is None:
        raise_api("ERR_MAINTENANCE_WINDOW_NOT_OPEN", "No maintenance window is open")
    due_dt = parse_iso(due_at)
    window_open = calc.maintenance_window_open_at(due_dt)
    if now < window_open:
        raise_api("ERR_MAINTENANCE_WINDOW_NOT_OPEN", "Maintenance window is not yet open")

    # in_grace_period: filed strictly after due_at and on/before due_at + grace.
    grace_end = add_days(due_dt, calc.GRACE_WINDOW_DAYS)
    in_grace = (now > due_dt) and (now <= grace_end)

    class_count = _registration_class_count(reg)
    fee = calc.maintenance_fee(filing_type, class_count, in_grace)

    rec = models.make_record({
        "registration_id": registration_id,
        "filing_type": filing_type,
        "filed_at": db.current_utc_iso(),
        "in_grace_period": in_grace,
        "fee_cents": fee,
        "status": "SUBMITTED",
    })
    db.maintenance_filings[rec["id"]] = rec

    # Filing increments the registration's version (OCC supersede semantics).
    models.touch(reg)
    return success(models.ser_maintenance_filing(rec), 201)


@mf_bp.post("/maintenance-filings/<rid>/accept")
@require_roles("Examiner")
def accept_maintenance(rid, _user_id, _role):
    filing = models.get_or_404(db.maintenance_filings, rid, "MaintenanceFiling")
    reg = db.registrations[filing["registration_id"]]

    if filing["status"] != "SUBMITTED":
        raise_api("ERR_INVALID_STATE", "Maintenance filing is not SUBMITTED")

    if not filing["in_grace_period"]:
        # Timely acceptance: registration must be ACTIVE.
        if reg["status"] != "ACTIVE":
            raise_api("ERR_INVALID_STATE", "Registration is not ACTIVE for a timely filing")
        timely = True
    else:
        # Grace acceptance: registration must be in GRACE and still within window.
        if reg["status"] != "GRACE":
            raise_api("ERR_INVALID_STATE", "Registration is not in GRACE for a grace filing")
        now = db.current_utc_dt()
        grace_end = add_days(parse_iso(reg["next_maintenance_due_at"]), calc.GRACE_WINDOW_DAYS)
        if now > grace_end:
            raise_api("ERR_INVALID_STATE", "Grace window has elapsed")
        timely = False

    filing["status"] = "ACCEPTED"
    models.touch(filing)

    # A timely acceptance marks the prior MAINTENANCE deadline MET; a grace
    # acceptance does not (it was already swept MISSED on entering grace).
    if timely:
        models.set_docket_status("MAINTENANCE", reg["id"], "MET", only_pending=True)

    reg["maintenance_cycle"] += 1
    new_due = calc.maintenance_due_at(parse_iso(reg["registered_at"]), reg["maintenance_cycle"])
    reg["next_maintenance_due_at"] = iso_from_datetime(new_due)
    reg["status"] = "ACTIVE"
    if reg["next_maintenance_due_at"] is not None:
        models.create_docket_deadline(
            "MAINTENANCE", reg["id"], reg["next_maintenance_due_at"], application_id=None
        )
    models.touch(reg)
    return success(models.ser_registration(reg), 200)


# ----- Helpers --------------------------------------------------------------

def _registration_class_count(reg: dict) -> int:
    app_id = reg["application_id"]
    classes = {
        g["nice_class_id"]
        for g in db.goods_services.values()
        if g["application_id"] == app_id
    }
    return len(classes)
