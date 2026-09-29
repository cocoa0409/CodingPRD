"""Calendar events and the three conflict geometries (PRD 3.8)."""

import datetime

from flask import Blueprint, request

import auth
import calc
import response
import serialize
import store
import validation as v
from errors import ApiError

bp = Blueprint("calendar", __name__)

CONTINUABLE = ("MASTER_CALENDAR_HEARING", "INDIVIDUAL_HEARING", "ASYLUM_INTERVIEW")
UNAUTHORIZED = ("AUTHORIZATION_SUSPENDED", "UNAUTHORIZED")
BOOL_FILTERS = ("coverage_gap_flag",)


def _facility_rules(event_type, facility_id, rep_id, starts):
    """The two facility-access rules; they run before the conflict scan."""
    if event_type != "FACILITY_VISIT":
        return
    facility = store.get("facilities", facility_id)
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    lead_hours = int(facility.get("visit_lead_time_hours") or 0)
    earliest = store.clock_dt() + datetime.timedelta(hours=lead_hours)
    if starts < earliest:
        raise ApiError("ERR_FACILITY_LEAD_TIME_NOT_MET",
                       "The visit must start at least "
                       f"{lead_hours} hours after the current logical time.")
    if not facility.get("access_credential_required"):
        return
    rep = store.get("representatives", rep_id) if rep_id else None
    expires = store.parse_date(
        rep.get("facility_access_credential_expires_on") if rep else None)
    if expires is None or expires < starts.date():
        raise ApiError("ERR_FACILITY_CREDENTIAL_EXPIRED",
                       "The assigned representative has no valid facility credential "
                       "for the event date.")


def _candidate(row, starts, ends):
    payload = dict(row)
    payload["starts_at_utc"] = starts
    payload["ends_at_utc"] = ends
    return payload


@bp.post("/calendar-events")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def create_event():
    payload = v.body()
    matter_id = v.as_id(payload, "matter_id")
    auth.scope_matter(matter_id)
    matter = store.get("matters", matter_id)
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    rep_id = v.as_id(payload, "assigned_representative_id", required=False, default=None)
    if rep_id is not None and store.get("representatives", rep_id) is None:
        raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")
    facility_id = v.as_id(payload, "facility_id", required=False, default=None)
    if facility_id is not None and store.get("facilities", facility_id) is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")

    event_type = v.as_enum(payload, "event_type", calc.EVENT_TYPES)
    starts = v.as_datetime(payload, "starts_at_utc")
    ends = v.as_datetime(payload, "ends_at_utc")
    location = v.upper_code(payload, "location_code", 2, 12)
    waived = v.as_bool(payload, "client_conflict_waived", default=False)
    if ends <= starts:
        v.bad("ends_at_utc must be strictly after starts_at_utc.")
    if event_type == "FACILITY_VISIT" and facility_id is None:
        v.bad("facility_id is required for a FACILITY_VISIT.")
    if event_type != "FACILITY_VISIT" and facility_id is not None:
        v.bad("facility_id is only permitted for a FACILITY_VISIT.")
    if rep_id is None and event_type != "FILING_DEADLINE":
        v.bad("assigned_representative_id is required unless event_type is "
              "FILING_DEADLINE.")

    if matter.get("closed_at_utc"):
        raise ApiError("ERR_MATTER_CLOSED")

    fields = {
        "matter_id": matter_id,
        "facility_id": facility_id,
        "assigned_representative_id": rep_id,
        "continued_from_event_id": None,
        "event_type": event_type,
        "starts_at_utc": store.iso(starts),
        "ends_at_utc": store.iso(ends),
        "location_code": location,
        "travel_buffer_minutes": calc.travel_buffer(event_type),
        "status": "SCHEDULED",
        "reschedule_count": 0,
        "coverage_gap_flag": False,
        "client_conflict_waived": waived,
    }
    _facility_rules(event_type, facility_id, rep_id, starts)
    calc.scan_calendar_conflicts(_candidate(fields, starts, ends))
    row = store.insert("events", store.new_row(fields))
    return response.created(serialize.event(row))


@bp.get("/calendar-events")
@auth.requires("ProgramDirector", "SupervisingAttorney", "CaseRepresentative",
               "ClientPortalUser", scoped=True)
def list_events():
    client_id = auth.portal_client_id()
    auth.check_rep_active()
    rows = store.rows("events")
    args = request.args
    if client_id is not None:
        rows = [r for r in rows
                if calc.matter_client_id(r.get("matter_id")) == client_id]
    for key in ("matter_id", "facility_id", "assigned_representative_id",
                "continued_from_event_id", "event_type", "status"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    for key in BOOL_FILTERS:
        if args.get(key) is not None and args.get(key) != "":
            wanted = args[key].lower() == "true"
            rows = [r for r in rows if bool(r.get(key)) is wanted]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.event(r) for r in page], meta)


def _event_or_404(event_id):
    row = store.get("events", event_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The calendar event does not exist.")
    return row


@bp.post("/calendar-events/<event_id>/reschedule")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def reschedule_event(event_id):
    row = _event_or_404(event_id)
    auth.scope_matter(row.get("matter_id"))
    payload = v.body()
    starts = v.as_datetime(payload, "starts_at_utc")
    ends = v.as_datetime(payload, "ends_at_utc")
    location = v.upper_code(payload, "location_code", 2, 12, required=False, default=None)
    rep_id = v.as_id(payload, "assigned_representative_id", required=False, default=None)
    waived = v.as_bool(payload, "client_conflict_waived", default=None)
    if ends <= starts:
        v.bad("ends_at_utc must be strictly after starts_at_utc.")
    if rep_id is not None and store.get("representatives", rep_id) is None:
        raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")

    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SCHEDULED event may be rescheduled.")
    if int(row.get("reschedule_count") or 0) + 1 > calc.MAX_RESCHEDULES:
        raise ApiError("ERR_RESCHEDULE_LIMIT_REACHED",
                       "The event has already been rescheduled "
                       f"{calc.MAX_RESCHEDULES} times.")

    candidate = dict(row)
    if location is not None:
        candidate["location_code"] = location
    if rep_id is not None:
        candidate["assigned_representative_id"] = rep_id
    if waived is not None:
        candidate["client_conflict_waived"] = waived
    _facility_rules(candidate["event_type"], candidate.get("facility_id"),
                    candidate.get("assigned_representative_id"), starts)
    calc.scan_calendar_conflicts(_candidate(candidate, starts, ends),
                                 exclude_event_id=row["id"])

    row["starts_at_utc"] = store.iso(starts)
    row["ends_at_utc"] = store.iso(ends)
    row["location_code"] = candidate["location_code"]
    row["assigned_representative_id"] = candidate.get("assigned_representative_id")
    row["client_conflict_waived"] = bool(candidate.get("client_conflict_waived"))
    row["travel_buffer_minutes"] = calc.travel_buffer(row["event_type"])
    row["reschedule_count"] = int(row.get("reschedule_count") or 0) + 1
    store.touch(row)
    return response.ok(serialize.event(row))


def _credential_valid(row):
    """The FACILITY_VISIT credential rule, without the lead-time rule."""
    if row.get("event_type") != "FACILITY_VISIT":
        return
    facility = store.get("facilities", row.get("facility_id"))
    if facility is None or not facility.get("access_credential_required"):
        return
    rep = store.get("representatives", row.get("assigned_representative_id"))
    expires = store.parse_date(
        rep.get("facility_access_credential_expires_on") if rep else None)
    starts = store.parse_dt(row.get("starts_at_utc"))
    if expires is None or (starts is not None and expires < starts.date()):
        raise ApiError("ERR_FACILITY_CREDENTIAL_EXPIRED",
                       "The assigned representative has no valid facility credential "
                       "for the event date.")


def _continue(row, payload):
    if row["event_type"] not in CONTINUABLE:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "CONTINUE is only legal for a hearing or an asylum interview.")
    starts = v.as_datetime(payload, "successor_starts_at_utc")
    ends = v.as_datetime(payload, "successor_ends_at_utc")
    if ends <= starts:
        v.bad("successor_ends_at_utc must be strictly after successor_starts_at_utc.")
    predecessor_end = store.parse_dt(row.get("ends_at_utc"))
    if predecessor_end is not None and starts <= predecessor_end:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "successor_starts_at_utc must be strictly after the "
                       "predecessor's ends_at_utc.")
    fields = {
        "matter_id": row.get("matter_id"),
        "facility_id": row.get("facility_id"),
        "assigned_representative_id": row.get("assigned_representative_id"),
        "continued_from_event_id": row["id"],
        "event_type": row["event_type"],
        "starts_at_utc": store.iso(starts),
        "ends_at_utc": store.iso(ends),
        "location_code": row.get("location_code"),
        "travel_buffer_minutes": calc.travel_buffer(row["event_type"]),
        "status": "SCHEDULED",
        "reschedule_count": 0,
        "coverage_gap_flag": False,
        "client_conflict_waived": bool(row.get("client_conflict_waived")),
    }
    calc.scan_calendar_conflicts(_candidate(fields, starts, ends),
                                 exclude_event_id=row["id"])
    return store.insert("events", store.new_row(fields))


@bp.post("/calendar-events/<event_id>/transition")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def transition_event(event_id):
    row = _event_or_404(event_id)
    auth.scope_matter(row.get("matter_id"))
    payload = v.body()
    action = v.as_enum(payload, "action",
                       ("CONFIRM", "COMPLETE", "MARK_MISSED", "CONTINUE", "CANCEL"))
    v.as_str(payload, "reason_code", required=False, min_len=1, max_len=40, default=None)
    status = row["status"]
    open_states = ("SCHEDULED", "CONFIRMED")

    if action == "CONFIRM":
        if status != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "CONFIRM is only legal from SCHEDULED.")
        rep = store.get("representatives", row.get("assigned_representative_id"))
        if rep is None:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The event has no assigned representative to confirm.")
        if calc.authorization_status(rep) in UNAUTHORIZED:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The assigned representative is not authorized.")
        _credential_valid(row)
        row["status"] = "CONFIRMED"
        store.touch(row)
        return response.ok(serialize.event(row))

    if status not in open_states:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is only legal from SCHEDULED or CONFIRMED." % action)

    if action in ("COMPLETE", "MARK_MISSED"):
        ends = store.parse_dt(row.get("ends_at_utc"))
        if ends is not None and store.clock_dt() < ends:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The event has not finished yet.")
        if action == "COMPLETE":
            row["status"] = "COMPLETED"
            store.touch(row)
        else:
            row["status"] = "MISSED"
            store.touch(row)
            if row["event_type"] in ("MASTER_CALENDAR_HEARING", "INDIVIDUAL_HEARING"):
                matter = store.get("matters", row.get("matter_id"))
                if matter is not None:
                    matter["coverage_gap_flag"] = True
                    store.touch(matter)
    elif action == "CONTINUE":
        _continue(row, payload)
        row["status"] = "CONTINUED"
        store.touch(row)
    else:
        row["status"] = "CANCELLED"
        store.touch(row)
    return response.ok(serialize.event(row))
