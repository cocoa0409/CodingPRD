"""Recipient candidates and their waitlist status events."""

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, now, touch
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from response import list_response, object_response
from routes.programs import find_program
from validation import (
    get_body,
    opt_int,
    opt_num,
    pagination,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("recipients", __name__)

# Endpoint-driven transitions of RecipientCandidate.listing_status.
# ACTIVE -> TRANSPLANTED is system-driven only (segment completion) and is
# therefore deliberately absent here.
LISTING_TRANSITIONS = {
    "WORKUP": ("APPROVED_NOT_LISTED", "DECLINED"),
    "APPROVED_NOT_LISTED": ("ACTIVE",),
    "ACTIVE": ("INACTIVE_HOLD", "REMOVED"),
    "INACTIVE_HOLD": ("ACTIVE", "REMOVED"),
}


def find_recipient(recipient_id):
    recipient = db.recipients.get(recipient_id)
    if recipient is None:
        raise ApiError(
            "ERR_RECIPIENT_NOT_FOUND", "no RecipientCandidate with id %s" % recipient_id
        )
    return recipient


@bp.post("/recipient-candidates")
def create_recipient():
    authenticate(["TransplantCoordinator"])
    body = get_body()
    program_id = req_str(body, "program_id")
    mrn = req_str(body, "mrn")
    abo = req_enum(body, "abo_blood_type", calc.ABO_TYPES)
    age_years = req_int(body, "age_years", minimum=0)
    cpra = req_num(body, "cpra", minimum=0, maximum=1)
    dialysis_years = opt_num(body, "dialysis_years", 0, minimum=0)
    urgency = opt_int(body, "medical_urgency_points", 0)

    program = find_program(program_id)

    row = new_entity(
        "RecipientCandidate",
        {
            "program_id": program["id"],
            "mrn": mrn,
            "abo_blood_type": abo,
            "age_years": age_years,
            "cpra": cpra,
            "dialysis_years": dialysis_years,
            "medical_urgency_points": urgency,
            "listing_status": "WORKUP",
            "candidacy_approved_by_staff_id": None,
            "registered_at": None,
        },
    )
    db.recipients[row["id"]] = row
    return object_response(serialize.recipient_candidate(row), 201)


@bp.get("/recipient-candidates")
def list_recipients():
    authenticate(ALL_ROLES)
    program_id = q_str("program_id")
    listing_status = q_enum("listing_status", calc.LISTING_STATUSES)
    approver = q_str("candidacy_approved_by_staff_id")
    limit, offset = pagination()

    rows = list(db.recipients.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if listing_status is not None:
        rows = [r for r in rows if r["listing_status"] == listing_status]
    if approver is not None:
        rows = [r for r in rows if r["candidacy_approved_by_staff_id"] == approver]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.recipient_candidate(r) for r in page], limit, offset, total)


@bp.get("/recipient-candidates/<recipient_id>")
def get_recipient(recipient_id):
    authenticate(ALL_ROLES)
    recipient = find_recipient(recipient_id)
    return object_response(serialize.recipient_candidate(recipient))


@bp.get("/recipient-candidates/<recipient_id>/waitlist-events")
def list_waitlist_events(recipient_id):
    authenticate(ALL_ROLES)
    recipient = find_recipient(recipient_id)
    limit, offset = pagination()
    rows = domain.waitlist_events_of(recipient)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.waitlist_event(r) for r in page], limit, offset, total)


@bp.post("/recipient-candidates/<recipient_id>/status-updates")
def update_listing_status(recipient_id):
    authenticate(["TransplantCoordinator"])
    recipient = find_recipient(recipient_id)

    body = get_body()
    to_status = req_enum(body, "to_status", calc.EVENT_TO_STATUSES)
    reason_code = req_str(body, "reason_code")
    effective_at = req_dt(body, "effective_at")

    from_status = recipient["listing_status"]
    allowed = LISTING_TRANSITIONS.get(from_status, ())
    if to_status not in allowed:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a recipient in %s may not move to %s" % (from_status, to_status),
        )

    events = domain.waitlist_events_of(recipient)
    if events and effective_at < events[-1]["effective_at"]:
        raise ApiError(
            "ERR_EFFECTIVE_AT_OUT_OF_ORDER",
            "effective_at precedes the latest recorded waitlist event",
        )
    if effective_at > now():
        raise ApiError(
            "ERR_EFFECTIVE_AT_OUT_OF_ORDER", "effective_at is in the future"
        )

    recipient["listing_status"] = to_status
    if to_status == "APPROVED_NOT_LISTED":
        recipient["candidacy_approved_by_staff_id"] = g.user_id
    if to_status == "ACTIVE" and recipient["registered_at"] is None:
        recipient["registered_at"] = effective_at
    touch(recipient)

    domain.record_waitlist_event(
        recipient, from_status, to_status, reason_code, effective_at, g.user_id
    )

    if to_status == "INACTIVE_HOLD":
        for segment in domain.segments_of_recipient(recipient):
            if segment["status"] == "OFFER_SENT":
                segment["status"] = "PLANNED"
                for field in domain.OFFER_FIELDS_TO_CLEAR:
                    segment[field] = None
                touch(segment)
    elif to_status == "REMOVED":
        domain.cascade_participant_withdrawal(
            domain.segments_of_recipient(recipient), "RECIPIENT_REMOVED"
        )

    return object_response(serialize.recipient_candidate(recipient))
