"""Enrollment change event endpoints (PRD 3.8)."""
from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError, not_found,
    ERR_ENROLLMENT_NOT_REPORTED, ERR_CASE_NOT_APPROVED,
    ERR_NOT_BROKER_OF_RECORD,
)
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import enrollment_json
from services import calcs
from services.workflow import latest_validated_census
from validators import body, req_str, req_int, req_enum

bp = Blueprint("enrollment", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]
EVENT_TYPES = ["NEW_HIRE", "TERMINATION", "COBRA_ELECTION", "PLAN_MIGRATION"]


def get_event_or_404(event_id):
    event = store.enrollment_events.get(event_id)
    if event is None:
        raise not_found("Enrollment change event does not exist")
    return event


@bp.post("/underwriting-cases/<caseId>/enrollment-changes")
def create_enrollment_change(caseId):
    uid, role = auth(["Underwriter", "Broker"])
    case = store.cases.get(caseId)
    if case is None:
        raise not_found("Underwriting case does not exist")
    if role == "Broker" and case["broker_id"] != uid:
        raise ApiError(ERR_NOT_BROKER_OF_RECORD,
                       "Acting broker is not the broker of record on this case", 403)
    data = body()
    quote_id = req_str(data, "quote_id")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    change_count = req_int(data, "change_count")
    effective_date = req_str(data, "effective_date")
    quote = store.quotes.get(quote_id)
    if quote is None or quote["case_id"] != caseId:
        raise not_found("Quote does not exist")

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "quote_id": quote_id,
        "event_type": event_type,
        "change_count": change_count,
        "effective_date": effective_date,
        "revised_enrollment": 0,
        "enrollment_change_pct": 0,
        "guarantee_voided": False,
        "rate_adjustment_factor": 1.0,
        "status": "REPORTED",
    })
    store.enrollment_events[rec["id"]] = rec
    return created(enrollment_json(rec))


@bp.get("/underwriting-cases/<caseId>/enrollment-changes")
def list_enrollment_changes(caseId):
    auth(READ_ROLES)
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    items = [e for e in store.enrollment_events.values() if e["case_id"] == caseId]
    return paginated([enrollment_json(e) for e in sorted_items(items)])


@bp.get("/enrollment-changes/<eventId>")
def get_enrollment_change(eventId):
    auth(READ_ROLES)
    return ok(enrollment_json(get_event_or_404(eventId)))


@bp.post("/enrollment-changes/<eventId>/process")
def process_enrollment_change(eventId):
    auth(["Underwriter"])
    event = get_event_or_404(eventId)
    case = store.cases.get(event["case_id"])
    if case is None:
        raise not_found("Underwriting case does not exist")
    if case["status"] != "APPROVED":
        raise ApiError(ERR_CASE_NOT_APPROVED,
                       "Case must be APPROVED to process enrollment changes", 409)
    if event["status"] != "REPORTED":
        raise ApiError(ERR_ENROLLMENT_NOT_REPORTED,
                       "Enrollment change must be in REPORTED status", 409)

    quote = store.quotes.get(event["quote_id"])
    if quote is None:
        raise not_found("Quote does not exist")
    census = latest_validated_census(case["id"])
    enrolled = census["enrolled_employees"] if census else 0

    revised, pct, voided, factor = calcs.enrollment_impact(
        enrolled, event["change_count"], quote["enrollment_change_threshold"]
    )
    event["revised_enrollment"] = revised
    event["enrollment_change_pct"] = pct
    event["guarantee_voided"] = voided
    event["rate_adjustment_factor"] = factor
    if voided:
        event["status"] = "VOIDED_GUARANTEE"
        # The parent quote's rate is multiplied by the adjustment factor
        quote["pepm_rate_cents"] = calcs.round_cents(
            calcs.D(quote["pepm_rate_cents"]) * calcs.D(factor)
        )
        touch(quote)
    else:
        event["status"] = "PROCESSED"
    touch(event)
    return ok(enrollment_json(event))
