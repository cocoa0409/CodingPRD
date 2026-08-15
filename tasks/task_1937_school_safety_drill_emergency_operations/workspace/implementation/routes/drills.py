"""DrillEvent endpoints (PRD 3.4, 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_NO_ACTIVE_EOP, ERR_DRILL_NOT_TODAY,
    ERR_OUTSIDE_ACADEMIC_YEAR, ERR_REQUIREMENT_NOT_CONFIGURED, ERR_DRILL_OVERLAP,
    ERR_WALKTHROUGH_DRILL_CONFLICT, ERR_ROSTER_INCOMPLETE,
)
from middleware import authorized, ALL_ROLES, ROLE_OFFICER
from response import success_object
from services.core import (
    new_record, public, apply_changes, refresh_site, stale_reports_for_drill,
    roster_entries_of, compute_evac_assessment,
)
from util import CLOCK, parse_date
from validate import (
    get_body, reject_unknown, req_date, req_enum, req_int, req_str, req_time,
    opt_enum, opt_str,
)
from routes.helpers import check_site_fk, get_path, list_query, opt_query_date
from routes.requirements import DRILL_TYPES

bp = Blueprint("drills", __name__)


def _interval(drill):
    """Half-open interval [start, start+duration) as absolute minutes."""
    d = parse_date(drill["scheduled_date"]).toordinal()
    hh, mm = drill["scheduled_start_time"].split(":")
    start = d * 1440 + int(hh) * 60 + int(mm)
    return start, start + drill["duration_minutes"]


@bp.post("/drill-events")
def create_drill():
    authorized([ROLE_OFFICER])
    body = get_body()
    check_site_fk(body)
    reject_unknown(body, ["site_id", "drill_type", "scheduled_date",
                          "scheduled_start_time", "duration_minutes", "announcement_mode"])
    site_id = req_str(body, "site_id")
    drill_type = req_enum(body, "drill_type", DRILL_TYPES)
    scheduled_date = req_date(body, "scheduled_date")
    start_time = req_time(body, "scheduled_start_time")
    duration = req_int(body, "duration_minutes", minimum=1)
    announcement = opt_enum(body, "announcement_mode", ["ANNOUNCED", "UNANNOUNCED"],
                            default="ANNOUNCED")

    site = db["sites"][site_id]

    # priority 7: academic-year containment
    sd = parse_date(scheduled_date)
    if not (parse_date(site["academic_year_start"]) <= sd <= parse_date(site["academic_year_end"])):
        raise_error(ERR_OUTSIDE_ACADEMIC_YEAR,
                    "scheduled_date lies outside the site's academic year")

    # priority 8c: requirement configured for (site, drill_type)
    req = next(
        (r for r in db["requirements"].values()
         if r["site_id"] == site_id and r["drill_type"] == drill_type),
        None,
    )
    if req is None:
        raise_error(ERR_REQUIREMENT_NOT_CONFIGURED,
                    "no DrillTypeRequirement configured for this site and drill type")

    # priority 9: half-open overlap vs drills in SCHEDULED / IN_PROGRESS
    new_iv = _interval({"scheduled_date": scheduled_date,
                        "scheduled_start_time": start_time,
                        "duration_minutes": duration})
    for d in db["drill_events"].values():
        if d["site_id"] != site_id or d["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        s2, e2 = _interval(d)
        if new_iv[0] < e2 and s2 < new_iv[1]:
            raise_error(ERR_DRILL_OVERLAP,
                        "drill interval overlaps another scheduled drill at this site")

    # priority 9: whole-day exclusion vs SCHEDULED walkthroughs
    for w in db["walkthroughs"].values():
        if (w["site_id"] == site_id and w["status"] == "SCHEDULED"
                and w["scheduled_date"] == scheduled_date):
            raise_error(ERR_WALKTHROUGH_DRILL_CONFLICT,
                        "drill may not share a calendar date with a scheduled walkthrough")

    rec = new_record("drill_events", {
        "site_id": site_id,
        "drill_type": drill_type,
        "scheduled_date": scheduled_date,
        "scheduled_start_time": start_time,
        "duration_minutes": duration,
        "announcement_mode": announcement,
        "status": "SCHEDULED",
        "conducted_by_user_id": None,
        "actual_start_at": None,
        "all_clear_at": None,
        "last_accountability_at": None,
        "provisional_evac_seconds": None,
        "official_evac_seconds": None,
        "met_target_standard": None,
        "met_target_adjusted": None,
        "roster_total": 0,
        "unaccounted_count": 0,
        "accounted_count": 0,
        "released_count": 0,
        "completion_notes": None,
    })
    refresh_site(site_id)
    stale_reports_for_drill(site_id, scheduled_date)
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>/drill-events")
def list_drills(rid):
    authorized(ALL_ROLES)
    get_path("sites", rid)
    date_from = opt_query_date("scheduled_date_from")
    date_to = opt_query_date("scheduled_date_to")
    filters = {
        "site_id": rid,
        "status": request.args.get("status"),
        "drill_type": request.args.get("drill_type"),
    }
    items = list(db["drill_events"].values())
    for field, value in filters.items():
        if value is None:
            continue
        items = [r for r in items if r.get(field) == value]
    if date_from is not None:
        items = [r for r in items if parse_date(r["scheduled_date"]) >= parse_date(date_from)]
    if date_to is not None:
        items = [r for r in items if parse_date(r["scheduled_date"]) <= parse_date(date_to)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    from routes.helpers import get_pagination
    from response import success_list
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/drill-events/<rid>")
def get_drill(rid):
    authorized(ALL_ROLES)
    drill = get_path("drill_events", rid)
    return success_object(public(drill))


@bp.post("/drill-events/<rid>/start")
def start_drill(rid):
    caller = authorized([ROLE_OFFICER])
    drill = get_path("drill_events", rid)
    body = get_body()
    reject_unknown(body, [])

    if drill["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "drill must be SCHEDULED to start")

    # priority 6: active EOP gate
    has_active_eop = any(
        p["site_id"] == drill["site_id"] and p["status"] == "ACTIVE"
        for p in db["eops"].values()
    )
    if not has_active_eop:
        raise_error(ERR_NO_ACTIVE_EOP, "site has no ACTIVE EmergencyOperationsPlan")

    # priority 7: day-of check
    if CLOCK.today() != parse_date(drill["scheduled_date"]):
        raise_error(ERR_DRILL_NOT_TODAY, "drill may only start on its scheduled_date")

    apply_changes(drill, {
        "status": "IN_PROGRESS",
        "actual_start_at": CLOCK.now_iso(),
        "conducted_by_user_id": caller.user_id,
    })
    refresh_site(drill["site_id"])
    stale_reports_for_drill(drill["site_id"], drill["scheduled_date"])
    return success_object(public(drill))


@bp.post("/drill-events/<rid>/complete")
def complete_drill(rid):
    authorized([ROLE_OFFICER])
    drill = get_path("drill_events", rid)
    body = get_body()
    reject_unknown(body, ["completion_notes"])
    notes = opt_str(body, "completion_notes")

    if drill["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "drill must be IN_PROGRESS to complete")

    # priority 6: roster completeness (vacuously satisfied when empty)
    entries = roster_entries_of(drill["id"])
    if any(e["status"] == "UNACCOUNTED" for e in entries):
        raise_error(ERR_ROSTER_INCOMPLETE,
                    "all roster entries must be ACCOUNTED or RELEASED to complete")

    changes = {"status": "COMPLETED", "completion_notes": notes}
    changes.update(compute_evac_assessment(drill))
    apply_changes(drill, changes)
    refresh_site(drill["site_id"])
    stale_reports_for_drill(drill["site_id"], drill["scheduled_date"])
    return success_object(public(drill))


@bp.post("/drill-events/<rid>/cancel")
def cancel_drill(rid):
    authorized([ROLE_OFFICER])
    drill = get_path("drill_events", rid)
    body = get_body()
    reject_unknown(body, ["reason"])

    if drill["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "only a SCHEDULED drill may be cancelled")

    apply_changes(drill, {"status": "CANCELLED"})
    refresh_site(drill["site_id"])
    stale_reports_for_drill(drill["site_id"], drill["scheduled_date"])
    return success_object(public(drill))
