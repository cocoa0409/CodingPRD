"""Delegate roster import, reads and per-delegate poaching history (PRD §3.1, §3.8)."""

from flask import Blueprint

import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import ALL_ROLES, STORE, base_record, sort_created

bp = Blueprint("attendees", __name__, url_prefix="/housing")

ATTENDEE_TYPES = ("GENERAL", "VIP", "STAFF", "EXHIBITOR")
ROSTER_ROLES = ["BureauCoordinator", "BureauController", "EventOrganizer", "ComplianceOfficer"]


@bp.post("/attendees")
def create_attendee():
    authenticate(["BureauCoordinator"])
    body = V.json_body()

    event_id = V.field_str(body, "event_id")
    email = V.field_str(body, "email")
    full_name = V.field_str(body, "full_name")
    registration_id = V.field_str(body, "registration_id")
    attendee_type = V.field_enum(body, "attendee_type", ATTENDEE_TYPES)
    eligibility_codes = V.field_str_array(body, "eligibility_codes", required=False, default=[])

    event = V.get_event(event_id)

    for existing in STORE.attendees.values():
        if existing["event_id"] == event["id"] and existing["email"] == email:
            fail(
                "ERR_ATTENDEE_EMAIL_DUPLICATE",
                "another attendee of this event already uses %s" % email,
            )

    record = base_record()
    record.update(
        {
            "event_id": event["id"],
            "email": email,
            "full_name": full_name,
            "registration_id": registration_id,
            "attendee_type": attendee_type,
            "eligibility_codes": eligibility_codes,
            "warning_count": 0,
            "housing_risk_flag": False,
            "no_show_strikes": 0,
        }
    )
    STORE.attendees[record["id"]] = record
    return created(ser.attendee_out(record))


@bp.get("/attendees/<attendee_id>")
def read_attendee(attendee_id):
    authenticate(ALL_ROLES)
    attendee = V.get_attendee(attendee_id)
    return ok(ser.attendee_out(attendee))


@bp.get("/attendees")
def list_attendees():
    authenticate(ROSTER_ROLES)
    event_id = V.str_arg("event_id")
    housing_risk_flag = V.bool_arg("housing_risk_flag")
    limit, offset = V.pagination_args()

    items = list(STORE.attendees.values())
    if event_id is not None:
        items = [a for a in items if a["event_id"] == event_id]
    if housing_risk_flag is not None:
        items = [a for a in items if a["housing_risk_flag"] is housing_risk_flag]
    items = sort_created(items)
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.attendee_out(a) for a in page], pagination)


@bp.get("/attendees/<attendee_id>/poaching-incidents")
def list_attendee_incidents(attendee_id):
    authenticate(ROSTER_ROLES)
    limit, offset = V.pagination_args()
    attendee = V.get_attendee(attendee_id)

    items = [i for i in STORE.incidents.values() if i["attendee_id"] == attendee["id"]]
    items = sort_created(items)
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.incident_out(i) for i in page], pagination)
