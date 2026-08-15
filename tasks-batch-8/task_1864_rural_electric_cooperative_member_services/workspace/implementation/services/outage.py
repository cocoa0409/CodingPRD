"""Outage report service: reporting, acknowledgment, dispatch, restore, duplicate folding, cancel."""
from errors import ApiError
import db
from db import store, new_common, touch


def create_outage_report(body, user_id, user_role):
    required = ["service_location_id", "cause"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")

    loc = store.service_locations.get(body["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")

    # Member ownership check: Member role can only report on own locations
    if user_role == "Member":
        if loc.get("member_id") != user_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Member acting on a resource they do not own")

    # Check: suspended member's locations accept no new reports
    member = store.members.get(loc.get("member_id"))
    if member and member.get("status") == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No new outage reports for suspended member's locations")

    if body.get("cause") not in ("WEATHER", "EQUIPMENT", "VEGETATION", "ANIMAL", "UNKNOWN"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid cause")

    report = new_common({
        "service_location_id": body["service_location_id"],
        "reported_by_member_id": user_id if user_role == "Member" else loc.get("member_id"),
        "status": "REPORTED",
        "cause": body["cause"],
        "parent_outage_id": body.get("parent_outage_id"),
        "restored_at": None,
        "notified_member_count": 0,
    })
    store.outage_reports[report["id"]] = report
    return report


def get_outage_report(report_id):
    r = store.outage_reports.get(report_id)
    if not r:
        raise ApiError("ERR_NOT_FOUND", 404, "OutageReport not found")
    return r


def list_outage_reports(service_location_id=None, status=None,
                        reported_by_member_id=None, parent_outage_id=None):
    rows = list(store.outage_reports.values())
    if service_location_id is not None:
        rows = [r for r in rows if r.get("service_location_id") == service_location_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if reported_by_member_id is not None:
        rows = [r for r in rows if r.get("reported_by_member_id") == reported_by_member_id]
    if parent_outage_id is not None:
        rows = [r for r in rows if r.get("parent_outage_id") == parent_outage_id]
    return rows


def acknowledge_report(report_id):
    r = get_outage_report(report_id)
    if r["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be REPORTED to acknowledge")
    r["status"] = "ACKNOWLEDGED"
    r["notified_member_count"] = r.get("notified_member_count", 0) + 1
    touch(r)
    return r


def dispatch_report(report_id):
    r = get_outage_report(report_id)
    if r["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be ACKNOWLEDGED to dispatch")
    r["status"] = "CREW_DISPATCHED"
    touch(r)
    return r


def restore_report(report_id):
    r = get_outage_report(report_id)
    if r["status"] != "CREW_DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be CREW_DISPATCHED to restore")
    r["status"] = "RESTORED"
    r["restored_at"] = db.wall_now()
    touch(r)

    # Cascade: all DUPLICATE reports with parent_outage_id == this id -> RESTORED
    for dup in store.outage_reports.values():
        if dup.get("parent_outage_id") == report_id and dup.get("status") == "DUPLICATE":
            dup["status"] = "RESTORED"
            dup["restored_at"] = db.wall_now()
            touch(dup)

    # Recompute notified_member_count across parent + duplicates
    all_related = [r] + [d for d in store.outage_reports.values()
                         if d.get("parent_outage_id") == report_id]
    unique_reporters = len({x.get("reported_by_member_id") for x in all_related if x.get("reported_by_member_id")})
    r["notified_member_count"] = unique_reporters
    touch(r)

    return r


def mark_duplicate(report_id, body):
    r = get_outage_report(report_id)
    if r["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be REPORTED to mark as duplicate")

    parent_id = body.get("parent_outage_id")
    if not parent_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "parent_outage_id is required")

    parent = store.outage_reports.get(parent_id)
    if not parent:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent OutageReport not found")

    if parent["status"] not in ("REPORTED", "ACKNOWLEDGED", "CREW_DISPATCHED"):
        raise ApiError("ERR_PARENT_OUTAGE_TERMINAL", 409,
                       "Parent outage is already in a terminal state")

    r["status"] = "DUPLICATE"
    r["parent_outage_id"] = parent_id
    touch(r)

    parent["notified_member_count"] = parent.get("notified_member_count", 0) + 1
    touch(parent)

    return r


def cancel_report(report_id):
    r = get_outage_report(report_id)
    if r["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be REPORTED to cancel")
    r["status"] = "CANCELLED"
    touch(r)
    return r
