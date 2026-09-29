"""Member assessments when losses exceed plan reserves (PRD 3.9)."""

from flask import Blueprint

import lookup
from db import db, new_record, touch
from errors import fail
from middleware import own, require
from response import created, ok
from routes.common import matches, page
from services import assessment as assessment_svc
from services.constants import ALLOCATION_BASES, ALLOCATION_STATUSES
from util import D
from validate import (
    body,
    filter_enum,
    pagination,
    req_enum,
    req_int,
    req_string,
    store_instant,
)

bp = Blueprint("assessments", __name__)


@bp.post("/assessment-events")
def open_event():
    require("PlanAdmin")
    data = body()
    cat_zone_id = req_string(data, "cat_zone_id")
    trigger_loss_cents = req_int(data, "trigger_loss_cents", minimum=0)
    reserve_balance_cents = req_int(
        data, "reserve_balance_cents_at_trigger", minimum=0)
    allocation_basis = req_enum(data, "allocation_basis", ALLOCATION_BASES)

    zone = lookup.cat_zone(cat_zone_id)

    assessable = trigger_loss_cents - reserve_balance_cents
    if assessable < 0:
        assessable = 0

    event = new_record({
        "cat_zone_id": zone["id"],
        "trigger_loss_cents": trigger_loss_cents,
        "reserve_balance_cents_at_trigger": reserve_balance_cents,
        "allocation_basis": allocation_basis,
        "assessable_amount_cents": assessable,
        "allocated_total_cents": 0,
        "remainder_cents": 0,
        "status": "DRAFT",
        "allocation_run_count": 0,
        "cancellation_reason": None,
    })
    db.assessment_events[event["id"]] = event
    return created(event)


@bp.post("/assessment-events/<event_id>/allocation-run")
def run_allocation(event_id):
    require("PlanAdmin")
    data = body()
    expected_version = req_int(data, "expected_assessment_event_version", minimum=0)

    event = lookup.assessment_event(event_id)

    if expected_version != event["version"]:
        fail("ERR_STALE_VERSION",
             "Assessment event version is %s, not %s"
             % (event["version"], expected_version))

    if event["status"] not in ("DRAFT", "ALLOCATED"):
        fail("ERR_ASSESSMENT_STATE_INVALID",
             "Event status %s does not accept an allocation run" % event["status"])

    if event["assessable_amount_cents"] <= 0:
        fail("ERR_LOSSES_WITHIN_RESERVES",
             "The incurred loss does not exceed the plan reserve")

    members = assessment_svc.eligible_members()
    total_weight = sum(
        (assessment_svc.weight_of(m, event["allocation_basis"]) for m in members),
        D(0))
    if not members or total_weight <= 0:
        fail("ERR_NO_ASSESSABLE_MEMBERS",
             "No eligible member carries a positive basis weight")

    assessment_svc.run_allocation(event)
    return ok(event)


@bp.post("/assessment-events/<event_id>/invoicing")
def invoice_event(event_id):
    require("PlanAdmin")
    body()

    event = lookup.assessment_event(event_id)
    if event["status"] != "ALLOCATED":
        fail("ERR_ASSESSMENT_STATE_INVALID",
             "Event status %s cannot be invoiced" % event["status"])
    if event["allocated_total_cents"] != event["assessable_amount_cents"]:
        fail("ERR_ASSESSMENT_STATE_INVALID",
             "The allocated total does not equal the assessable amount")

    event["status"] = "INVOICED"
    touch(event)
    return ok(event)


@bp.post("/assessment-events/<event_id>/cancellation")
def cancel_event(event_id):
    require("PlanAdmin")
    data = body()
    reason = req_string(data, "reason")

    event = lookup.assessment_event(event_id)
    if event["status"] not in ("DRAFT", "ALLOCATED", "INVOICED"):
        fail("ERR_ASSESSMENT_STATE_INVALID",
             "Event status %s cannot be cancelled" % event["status"])

    touched = set()
    assessment_svc.abate_pending(event, touched)
    assessment_svc.recompute_allocated_total(event)
    event["cancellation_reason"] = reason
    event["status"] = "CANCELLED"
    touch(event)

    for member_id in touched:
        member = db.member_insurers.get(member_id)
        if member is not None:
            assessment_svc.recompute_member_cumulative(member)
            touch(member)

    return ok(event)


@bp.get("/assessment-events/<event_id>")
def read_event(event_id):
    require("PlanAdmin", "Regulator", "MemberInsurerUser")
    return ok(lookup.assessment_event(event_id))


@bp.get("/assessment-events/<event_id>/allocations")
def list_event_allocations(event_id):
    require("PlanAdmin", "Regulator", "MemberInsurerUser")
    limit, offset = pagination()
    status = filter_enum("status", ALLOCATION_STATUSES)
    event = lookup.assessment_event(event_id)
    rows = [a for a in assessment_svc.allocations_of(event["id"])
            if matches(a, {"status": status})]
    return page(rows, limit, offset)


@bp.post("/assessment-allocations/<allocation_id>/payment")
def pay_allocation(allocation_id):
    caller = require("MemberInsurerUser")
    data = body()
    amount_cents = req_int(data, "amount_cents", minimum=0)

    allocation = lookup.assessment_allocation(allocation_id)
    own(allocation["member_insurer_id"] == caller.user_id,
        "An operator may only settle its own carrier's allocation")

    event = db.assessment_events.get(allocation["assessment_event_id"])
    if (allocation["status"] != "PENDING" or event is None
            or event["status"] != "INVOICED"):
        fail("ERR_ALLOCATION_NOT_PAYABLE",
             "The allocation is not payable in its current state")

    member = db.member_insurers.get(allocation["member_insurer_id"])
    if member is None or member["status"] not in ("ACTIVE", "RUNOFF"):
        fail("ERR_MEMBER_NOT_ACTIVE", "A WITHDRAWN carrier may not pay")

    if amount_cents != allocation["net_due_cents"]:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "The plan accepts neither partial nor over-payment; %d cents is due"
             % allocation["net_due_cents"])

    allocation["status"] = "PAID"
    allocation["paid_at"] = store_instant(db.now())
    touch(allocation)

    assessment_svc.settle_if_complete(event)
    return ok(allocation)
