"""DisclosureEvent endpoints: logging a request and deciding it."""

from datetime import timedelta

from flask import Blueprint

from db import clock_date, clock_iso, clock_now, db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_LEGAL_ADVOCATE,
                        ROLE_PRIVACY_OFFICER, ROLE_SHELTER_MANAGER, acting_staff_id, auth)
from response import created, ok
from routes.common import (by_created, filtered, get_client, get_disclosure, get_staff,
                           insert, list_page)
from services import calc, derive
from validation import (bad, date_out, dt_out, get_body, opt_date, q_enum, q_str, req_enum,
                        req_str)

bp = Blueprint("disclosure", __name__)

STATUSES = ("REQUESTED", "RELEASED", "PARTIALLY_RELEASED", "DENIED")
DECISIONS = ("RELEASE", "DENY")
RAISE_ROLES = (ROLE_PRIVACY_OFFICER, ROLE_HOTLINE_ADVOCATE, ROLE_LEGAL_ADVOCATE,
               ROLE_SHELTER_MANAGER)
READ_ROLES = (ROLE_PRIVACY_OFFICER, ROLE_LEGAL_ADVOCATE, ROLE_AGENCY_ADMIN)
DEADLINE_HOURS = 24
ROI_KINDS = ("PARTNER_AGENCY", "COURT_SUBPOENA")


def _field_keys(body):
    value = body.get("requested_field_keys")
    if not isinstance(value, list):
        raise bad("requested_field_keys must be an array")
    if len(value) < 1 or len(value) > len(calc.KEY_VOCABULARY):
        raise bad("requested_field_keys must hold between 1 and 10 keys")
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in calc.KEY_VOCABULARY:
            raise bad("requested_field_keys holds a key outside the disclosure vocabulary")
        if item in seen:
            raise bad("requested_field_keys may not repeat a key")
        seen.append(item)
    return seen


@bp.post("/disclosure-events")
def create_event():
    auth(RAISE_ROLES)
    body = get_body()
    client_id = req_str(body, "client_id")
    requested_by_staff_id = req_str(body, "requested_by_staff_id")
    kind = req_enum(body, "kind", calc.DISCLOSURE_KINDS)
    requester_org = req_str(body, "requester_org", 1, 120)
    requested_field_keys = _field_keys(body)
    roi_signed_on = opt_date(body, "roi_signed_on")
    roi_expires_on = opt_date(body, "roi_expires_on")
    client = get_client(client_id)
    requester = get_staff(requested_by_staff_id)

    event = insert("disclosure_events", {
        "client_id": client["id"],
        "requested_by_staff_id": requester["id"],
        "decided_by_staff_id": None,
        "kind": kind,
        "requester_org": requester_org,
        "requested_field_keys": list(requested_field_keys),
        "roi_signed_on": date_out(roi_signed_on) if roi_signed_on else None,
        "roi_expires_on": date_out(roi_expires_on) if roi_expires_on else None,
        "status": "REQUESTED",
        "released_field_keys": [],
        "suppressed_field_keys": [],
        "decision_deadline_utc": None,
        "decided_at": None,
        "late_filed": False,
        "denial_reason": None,
    })
    if kind == "MANDATED_REPORT":
        anchor = derive.as_datetime(event["created_at"])
        event["decision_deadline_utc"] = dt_out(anchor + timedelta(hours=DEADLINE_HOURS))
    return created(public(event))


@bp.get("/disclosure-events/<event_id>")
def read_event(event_id):
    auth(READ_ROLES)
    return ok(public(get_disclosure(event_id)))


@bp.get("/disclosure-events")
def list_events():
    auth(READ_ROLES)
    filters = {
        "client_id": q_str("client_id"),
        "requested_by_staff_id": q_str("requested_by_staff_id"),
        "decided_by_staff_id": q_str("decided_by_staff_id"),
        "kind": q_enum("kind", calc.DISCLOSURE_KINDS),
        "status": q_enum("status", STATUSES),
    }
    return list_page(by_created(filtered("disclosure_events", filters)))


@bp.post("/disclosure-events/<event_id>/decide")
def decide_event(event_id):
    user_id, role = auth((ROLE_PRIVACY_OFFICER,))
    event = get_disclosure(event_id)

    # segregation of duties precedes request shape (2.7 step 3)
    if acting_staff_id(user_id, role) == event["requested_by_staff_id"]:
        raise ApiError("ERR_SELF_DECISION_FORBIDDEN")

    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    denial_reason = None
    if decision == "DENY":
        denial_reason = req_str(body, "denial_reason", 1, 2000)

    if event["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a REQUESTED disclosure event may be decided")

    client = db.clients.get(event["client_id"])
    if decision == "RELEASE":
        if client is not None and client["confidentiality_posture"] == "SEALED":
            raise ApiError("ERR_CONFIDENTIALITY_HOLD")
        if event["kind"] == "HMIS_EXPORT":
            if client is None or client["hmis_disclosure_consent"] != "GRANTED":
                raise ApiError("ERR_HMIS_CONSENT_ABSENT")
        if event["kind"] in ROI_KINDS:
            expires = event["roi_expires_on"]
            if not expires or derive.as_date(expires) < clock_date():
                raise ApiError("ERR_ROI_EXPIRED")

    released, suppressed, status = calc.disclosure_field_projection(
        event["kind"], event["requested_field_keys"], decision)

    decided_at = clock_iso()
    event["released_field_keys"] = released
    event["suppressed_field_keys"] = suppressed
    event["status"] = status
    event["decided_by_staff_id"] = acting_staff_id(user_id, role)
    event["decided_at"] = decided_at
    event["denial_reason"] = denial_reason
    late = False
    if event["kind"] == "MANDATED_REPORT" and event["decision_deadline_utc"]:
        late = clock_now() > derive.as_datetime(event["decision_deadline_utc"])
    event["late_filed"] = late
    touch(event)

    if decision == "DENY" and event["kind"] == "HMIS_EXPORT" and client is not None:
        touch(client)
        derive.recompute_client_posture(client)
    return ok(public(event))
