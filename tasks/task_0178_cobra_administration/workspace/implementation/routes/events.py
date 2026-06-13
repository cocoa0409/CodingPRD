"""Qualifying-event endpoints + send-notice/void transitions."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_role
from models import (
    _common, serialize, EVENT_FIELDS, NOTICE_FIELDS,
)
from response import object_response, array_response
from timeutil import add_days, add_months
from services.lookup import (
    get_or_404, require_body, require_enum, require_datetime,
    paginate, sorted_by_creation,
)

bp = Blueprint("events", __name__)

EVENT_TYPES = {
    "TERMINATION", "REDUCTION_OF_HOURS", "DIVORCE", "DEATH_OF_EMPLOYEE",
    "MEDICARE_ENTITLEMENT", "DEPENDENT_AGE_OUT",
}
# Employer-side events get an employer_notice_deadline + late_reported.
EMPLOYER_SIDE = {"TERMINATION", "REDUCTION_OF_HOURS", "DEATH_OF_EMPLOYEE", "MEDICARE_ENTITLEMENT"}


def _max_coverage_months(event_type):
    if event_type in ("TERMINATION", "REDUCTION_OF_HOURS"):
        return 18
    return 36


@bp.post("/events")
@require_role({"PlanSponsor", "PlanAdministrator"})
def create_event():
    body = require_body()
    # Existence (FK) before body shape: plan_id then beneficiary_id, left->right.
    plan_id = body.get("plan_id")
    if plan_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: plan_id")
    plan = get_or_404(store.plans, plan_id)
    beneficiary_id = body.get("beneficiary_id")
    if beneficiary_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: beneficiary_id")
    get_or_404(store.beneficiaries, beneficiary_id)

    event_type = require_enum(body, "event_type", EVENT_TYPES)
    event_date = require_datetime(body, "event_date")
    coverage_loss_date = require_datetime(body, "coverage_loss_date")

    now = store.now()
    if event_type in EMPLOYER_SIDE:
        deadline = add_days(event_date, plan["employer_notice_days"])
        late = now > deadline
    else:
        deadline = None
        late = False

    event = {
        "plan_id": plan_id,
        "beneficiary_id": beneficiary_id,
        "event_type": event_type,
        "event_date": event_date,
        "coverage_loss_date": coverage_loss_date,
        "max_coverage_months": _max_coverage_months(event_type),
        "reported_at": now,
        "employer_notice_deadline": deadline,
        "late_reported": late,
        "status": "RECORDED",
    }
    _common(event)
    store.events[event["id"]] = event
    return object_response(serialize(event, EVENT_FIELDS), status=201)


@bp.get("/events/<eid>")
@require_role({"PlanAdministrator", "PlanSponsor", "BillingAgent", "QualifiedBeneficiary"})
def get_event(eid):
    event = get_or_404(store.events, eid)
    return object_response(serialize(event, EVENT_FIELDS))


@bp.get("/events")
@require_role({"PlanAdministrator", "PlanSponsor", "BillingAgent"})
def list_events():
    plan_id = request.args.get("plan_id")
    beneficiary_id = request.args.get("beneficiary_id")
    items = list(store.events.values())
    if plan_id is not None:
        items = [e for e in items if e["plan_id"] == plan_id]
    if beneficiary_id is not None:
        items = [e for e in items if e["beneficiary_id"] == beneficiary_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(e, EVENT_FIELDS) for e in page],
                          limit, offset, total)


@bp.post("/events/<eid>/send-notice")
@require_role({"PlanAdministrator"})
def send_notice(eid):
    event = get_or_404(store.events, eid)
    # State (409) before business eligibility.
    if event["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", "Event is not in RECORDED status")
    beneficiary = store.beneficiaries.get(event["beneficiary_id"])
    if beneficiary is None:
        raise ApiError("ERR_NOT_FOUND", "Beneficiary not found")
    if beneficiary["status"] != "ACTIVE_EMPLOYEE_COVERAGE":
        raise ApiError("ERR_BENEFICIARY_NOT_ELIGIBLE",
                       "Beneficiary is not eligible for an election notice")
    plan = store.plans.get(event["plan_id"])

    from models import _common as common
    now = store.now()
    anchor = max(event["coverage_loss_date"], now)
    deadline = add_days(anchor, plan["election_window_days"])
    notice = {
        "event_id": event["id"],
        "beneficiary_id": beneficiary["id"],
        "notice_sent_date": now,
        "election_window_anchor": anchor,
        "election_deadline": deadline,
        "status": "OUTSTANDING",
    }
    common(notice)
    store.notices[notice["id"]] = notice

    from models import touch
    event["status"] = "NOTICE_SENT"
    touch(event)
    beneficiary["status"] = "COBRA_ELIGIBLE"
    touch(beneficiary)

    return object_response(serialize(notice, NOTICE_FIELDS), status=201)


@bp.post("/events/<eid>/void")
@require_role({"PlanAdministrator"})
def void_event(eid):
    event = get_or_404(store.events, eid)
    if event["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", "Event is not in RECORDED status")
    from models import touch
    event["status"] = "VOID"
    touch(event)
    return object_response(serialize(event, EVENT_FIELDS))
