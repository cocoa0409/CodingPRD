"""Rogue-housing vendor monitoring, incidents and the warning cascade (PRD §3.8)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import STORE, base_record, clock_iso, parse_iso_datetime, sort_created, touch

bp = Blueprint("vendors", __name__, url_prefix="/housing")

DETECTION_SOURCES = ("ATTENDEE_REPORT", "HOTEL_REPORT", "WEB_MONITORING")
VENDOR_STATUSES = ("REPORTED", "UNDER_REVIEW", "CONFIRMED_POACHER", "CLEARED")
CONTACT_CHANNELS = ("EMAIL", "PHONE", "SMS", "WEB")
VENDOR_READ_ROLES = [
    "BureauCoordinator",
    "BureauController",
    "EventOrganizer",
    "ComplianceOfficer",
]


def _sync_vendor_score(vendor):
    score, verified_count = calc.vendor_derived(vendor)
    vendor["risk_score"] = score
    vendor["verified_incident_count"] = verified_count
    return score


@bp.post("/rogue-vendors")
def create_vendor():
    authenticate(["ComplianceOfficer"])
    body = V.json_body()

    event_id = V.field_str(body, "event_id")
    name = V.field_str(body, "name")
    contact_domain = V.field_str(body, "contact_domain")
    detection_source = V.field_enum(body, "detection_source", DETECTION_SOURCES)

    event = V.get_event(event_id)

    record = base_record()
    record.update(
        {
            "event_id": event["id"],
            "name": name,
            "contact_domain": contact_domain,
            "detection_source": detection_source,
            "status": "REPORTED",
            "risk_score": 0,
            "verified_incident_count": 0,
            "warning_issued_count": 0,
        }
    )
    STORE.vendors[record["id"]] = record
    _sync_vendor_score(record)
    return created(ser.vendor_out(record))


@bp.get("/rogue-vendors/<vendor_id>")
def read_vendor(vendor_id):
    authenticate(VENDOR_READ_ROLES)
    vendor = V.get_vendor(vendor_id)
    return ok(ser.vendor_out(vendor))


@bp.get("/rogue-vendors")
def list_vendors():
    authenticate(VENDOR_READ_ROLES)
    event_id = V.str_arg("event_id")
    status = V.enum_arg("status", VENDOR_STATUSES)
    limit, offset = V.pagination_args()

    items = list(STORE.vendors.values())
    if event_id is not None:
        items = [v for v in items if v["event_id"] == event_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_created(items)
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.vendor_out(v) for v in page], pagination)


@bp.post("/rogue-vendors/<vendor_id>/incidents")
def record_incident(vendor_id):
    authenticate(["ComplianceOfficer"])
    body = V.json_body()

    attendee_id = V.field_str(body, "attendee_id")
    contact_channel = V.field_enum(body, "contact_channel", CONTACT_CHANNELS)
    occurred_at = V.field_datetime(body, "occurred_at")
    verified = V.field_bool(body, "verified")
    solicited_payment = V.field_bool(body, "solicited_payment", required=False, default=False)

    # step 4 — the path identifier resolves before the body identifier.
    vendor = V.get_vendor(vendor_id)
    attendee = V.get_attendee(attendee_id)

    # step 5 — uniqueness of vendor + attendee + channel + instant
    occurred_instant = parse_iso_datetime(occurred_at)
    for existing in STORE.incidents.values():
        if (
            existing["rogue_vendor_id"] == vendor["id"]
            and existing["attendee_id"] == attendee["id"]
            and existing["contact_channel"] == contact_channel
            and parse_iso_datetime(existing["occurred_at"]) == occurred_instant
        ):
            fail("ERR_DUPLICATE_INCIDENT", "this contact has already been recorded")

    record = base_record()
    record.update(
        {
            "rogue_vendor_id": vendor["id"],
            "attendee_id": attendee["id"],
            "contact_channel": contact_channel,
            "occurred_at": occurred_at,
            "verified": verified,
            "solicited_payment": solicited_payment,
            "status": "RECORDED",
            "warning_issued_at": None,
            "warning_severity": None,
        }
    )
    STORE.incidents[record["id"]] = record

    # Every recorded incident re-derives the score, which may escalate the vendor.
    score = _sync_vendor_score(vendor)
    if score >= calc.VENDOR_REVIEW_SCORE_THRESHOLD and vendor["status"] == "REPORTED":
        vendor["status"] = "UNDER_REVIEW"
        touch(vendor)

    return created(ser.incident_out(record))


@bp.get("/rogue-vendors/<vendor_id>/incidents")
def list_vendor_incidents(vendor_id):
    authenticate(VENDOR_READ_ROLES)
    limit, offset = V.pagination_args()
    vendor = V.get_vendor(vendor_id)

    items = calc.incidents_of_vendor(vendor["id"])
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.incident_out(i) for i in page], pagination)


@bp.post("/rogue-vendors/<vendor_id>/confirm")
def confirm_vendor(vendor_id):
    authenticate(["ComplianceOfficer"])
    V.json_body()
    vendor = V.get_vendor(vendor_id)

    # step 8 — own-state
    if vendor["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_VENDOR_STATE", "only an UNDER_REVIEW vendor may be confirmed")
    warnable = [
        incident
        for incident in calc.incidents_of_vendor(vendor["id"])
        if incident["verified"] is True and incident["status"] == "RECORDED"
    ]
    if not warnable:
        fail("ERR_INVALID_VENDOR_STATE", "no verified RECORDED incident is available to warn on")

    # LINK 1 — warnings in occurred_at then contact_channel order.
    for incident in warnable:
        attendee = STORE.attendees.get(incident["attendee_id"])
        current_warnings = attendee["warning_count"] if attendee is not None else 0
        incident["status"] = "WARNING_ISSUED"
        incident["warning_issued_at"] = clock_iso()
        incident["warning_severity"] = "ADVISORY" if current_warnings == 0 else "URGENT"
        touch(incident)
        vendor["warning_issued_count"] += 1

        if attendee is None:
            continue
        # LINK 2 — the delegate's warning counter and housing-risk flag.
        was_flagged = attendee["housing_risk_flag"]
        attendee["warning_count"] += 1
        if (
            not was_flagged
            and attendee["warning_count"] >= calc.HOUSING_RISK_WARNING_THRESHOLD
        ):
            attendee["housing_risk_flag"] = True
        touch(attendee)

        # LINK 3 — a fresh flag puts the delegate's confirmed stays under review.
        if not was_flagged and attendee["housing_risk_flag"]:
            for reservation in STORE.reservations.values():
                if reservation["attendee_id"] != attendee["id"]:
                    continue
                if reservation["reservation_status"] != "CONFIRMED":
                    continue
                reservation["eligibility_review_required"] = True
                if reservation["transmission_status"] == "TRANSMITTED":
                    reservation["transmission_status"] = "CHANGE_PENDING"
                touch(reservation)

    vendor["status"] = "CONFIRMED_POACHER"
    _sync_vendor_score(vendor)
    touch(vendor)
    return ok(ser.vendor_out(vendor))


@bp.post("/rogue-vendors/<vendor_id>/clear")
def clear_vendor(vendor_id):
    authenticate(["ComplianceOfficer"])
    V.json_body()
    vendor = V.get_vendor(vendor_id)

    if vendor["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_VENDOR_STATE", "only an UNDER_REVIEW vendor may be cleared")

    for incident in calc.incidents_of_vendor(vendor["id"]):
        if incident["status"] == "RECORDED":
            incident["status"] = "DISMISSED"
            touch(incident)

    vendor["status"] = "CLEARED"
    _sync_vendor_score(vendor)
    touch(vendor)
    return ok(ser.vendor_out(vendor))
