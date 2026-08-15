"""Routes: daily rosters and their lifecycle."""
from flask import Blueprint, request

from store import db
from errors import ApiError
from envelope import ok, ok_list
from validate import auth, get_body, check_body, sort_and_page, apply_filters
import serializers as ser

bp = Blueprint("rosters", __name__, url_prefix="/anesthesia-ops")

SCHED = ["Scheduler"]
ALL = ["GroupAdministrator", "Scheduler", "AttendingAnesthesiologist", "CRNA",
       "BillingSpecialist", "ComplianceAuditor"]


def _get_roster(roster_id):
    rec = db.rosters.get(roster_id)
    if rec is None:
        raise ApiError("ERR_ROSTER_NOT_FOUND", 404, "Roster not found")
    return rec


@bp.post("/rosters")
def create_roster():
    auth(SCHED)
    body = get_body()
    check_body(body, {
        "site_id": {"kind": "str", "req": True},
        "service_date": {"kind": "date", "req": True},
        "required_primary_slots": {"kind": "int", "req": True, "min": 0},
        "scheduled_day_end_minute": {"kind": "int", "req": True, "min": 0, "max": 1438},
    })
    if db.sites.get(body["site_id"]) is None:
        raise ApiError("ERR_SITE_NOT_FOUND", 404, "Site not found")
    for r in db.rosters.values():
        if r["site_id"] == body["site_id"] and r["service_date"] == body["service_date"]:
            raise ApiError("ERR_DUPLICATE_ROSTER", 409,
                           "A roster already exists for this site and service date")
    rec = db.new_record(site_id=body["site_id"], service_date=body["service_date"],
                        required_primary_slots=body["required_primary_slots"],
                        scheduled_day_end_minute=body["scheduled_day_end_minute"],
                        lifecycle="DRAFT")
    db.rosters[rec["id"]] = rec
    return ok(ser.roster(rec), 201)


@bp.get("/rosters")
def list_rosters():
    auth(ALL)
    items = apply_filters(db.rosters.values(), request.args,
                          ["site_id", "service_date", "lifecycle"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.roster(r) for r in page], limit, offset, total)


@bp.get("/rosters/<roster_id>")
def get_roster(roster_id):
    auth(ALL)
    return ok(ser.roster(_get_roster(roster_id)))


@bp.patch("/rosters/<roster_id>")
def patch_roster(roster_id):
    auth(SCHED)
    body = get_body()
    check_body(body, {
        "required_primary_slots": {"kind": "int", "req": False, "min": 0},
        "scheduled_day_end_minute": {"kind": "int", "req": False, "min": 0, "max": 1438},
        "expected_roster_version": {"kind": "int", "req": True},
    })
    rec = _get_roster(roster_id)
    if rec["lifecycle"] == "LOCKED":
        raise ApiError("ERR_ROSTER_LIFECYCLE_LOCKED", 409,
                       "Mutation not allowed on a LOCKED roster")
    if body["expected_roster_version"] != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Roster version is stale")
    if "required_primary_slots" in body:
        rec["required_primary_slots"] = body["required_primary_slots"]
    if "scheduled_day_end_minute" in body:
        rec["scheduled_day_end_minute"] = body["scheduled_day_end_minute"]
    db.bump(rec)
    return ok(ser.roster(rec))


@bp.post("/rosters/<roster_id>/publish")
def publish_roster(roster_id):
    auth(SCHED)
    get_body()  # tolerate empty body
    rec = _get_roster(roster_id)
    if rec["lifecycle"] != "DRAFT":
        raise ApiError("ERR_ROSTER_NOT_DRAFT", 409, "Publish requires lifecycle DRAFT")
    rec["lifecycle"] = "PUBLISHED"
    db.bump(rec)
    return ok(ser.roster(rec))


@bp.post("/rosters/<roster_id>/unpublish")
def unpublish_roster(roster_id):
    auth(SCHED)
    get_body()
    rec = _get_roster(roster_id)
    if rec["lifecycle"] == "LOCKED":
        raise ApiError("ERR_ROSTER_LIFECYCLE_LOCKED", 409,
                       "Mutation not allowed on a LOCKED roster")
    if rec["lifecycle"] != "PUBLISHED":
        raise ApiError("ERR_ROSTER_NOT_PUBLISHED", 409, "Unpublish requires lifecycle PUBLISHED")
    for c in db.cases.values():
        if c["roster_id"] == rec["id"] and c["status"] in ("IN_PROGRESS", "COMPLETED"):
            raise ApiError("ERR_CASES_OUTSTANDING", 409,
                           "Roster has cases that are IN_PROGRESS or COMPLETED")
    rec["lifecycle"] = "DRAFT"
    db.bump(rec)
    return ok(ser.roster(rec))


@bp.post("/rosters/<roster_id>/lock")
def lock_roster(roster_id):
    auth(SCHED)
    get_body()
    rec = _get_roster(roster_id)
    if rec["lifecycle"] != "PUBLISHED":
        raise ApiError("ERR_ROSTER_NOT_PUBLISHED", 409, "Lock requires lifecycle PUBLISHED")
    for c in db.cases.values():
        if c["roster_id"] == rec["id"] and c["status"] not in ("COMPLETED", "CANCELLED"):
            raise ApiError("ERR_CASES_OUTSTANDING", 409,
                           "Lock requires every case on the roster to be terminal")
    rec["lifecycle"] = "LOCKED"
    db.bump(rec)
    return ok(ser.roster(rec))
