"""Performance impairment, outage credits and the subscriber ledgers (PRD 3.8)."""

from flask import Blueprint

import billing
import capacity
import serialize
from auth import current_user_id, own_credit, roles
from clock import clock
from constants import (
    API_PREFIX,
    AUTHORIZED_STATES,
    CREDIT_DECISIONS,
    CREDIT_STATES,
    EVENT_STATES,
    OUTAGE_CAUSES,
    OUTAGE_SEVERITIES,
    SLA_MIN_OUTAGE_MINUTES,
)
from db import db, new_record, ordered, touch
from errors import fail
from numeric import floor_minutes
from response import list_response, object_response
from validators import (
    body_dict,
    filter_enum,
    filter_value,
    opt_str,
    pagination,
    paginate,
    req_dt,
    req_enum,
    req_str,
)

bp = Blueprint("impairment", __name__, url_prefix=API_PREFIX)


def find_event(event_id):
    record = db.outage_events.get(event_id)
    if record is None:
        fail("ERR_OUTAGE_EVENT_NOT_FOUND", "Outage event not found.")
    return record


def find_credit(credit_id):
    record = db.outage_credits.get(credit_id)
    if record is None:
        fail("ERR_OUTAGE_CREDIT_NOT_FOUND", "Outage credit not found.")
    return record


def _covers(event, moment):
    """A resolved event covers [started_at, ended_at); an open one has no bound."""
    if moment < event["started_at"]:
        return False
    if event["event_state"] == "OPEN":
        return True
    return moment < event["ended_at"]


# ---------------------------------------------------------------- events -------

@bp.post("/outage-events")
@roles("NetworkOpsEngineer")
def open_event():
    body = body_dict()
    beam_id = req_str(body, "beam_id", 1, 100)
    cause = req_enum(body, "cause", OUTAGE_CAUSES)
    severity = req_enum(body, "severity", OUTAGE_SEVERITIES)
    started_at = req_dt(body, "started_at")

    if beam_id not in db.beams:
        fail("ERR_BEAM_NOT_FOUND", "Beam not found.")

    for other in ordered(list(db.outage_events.values())):
        if other["beam_id"] != beam_id or other["cause"] != cause:
            continue
        if _covers(other, started_at):
            fail(
                "ERR_OUTAGE_WINDOW_OVERLAP",
                "Another event with the same cause already covers that instant.",
            )

    record = new_record()
    record.update(
        {
            "beam_id": beam_id,
            "cause": cause,
            "severity": severity,
            "started_at": started_at,
            "ended_at": None,
            "event_state": "OPEN",
            "outage_minutes": None,
            "credit_eligible": None,
            "generated_credit_count": 0,
        }
    )
    db.outage_events[record["id"]] = record
    return object_response(serialize.outage_event(record), 201)


@bp.get("/outage-events/<event_id>")
@roles("NetworkOpsEngineer", "ComplianceOfficer", "ProvisioningAgent")
def read_event(event_id):
    return object_response(serialize.outage_event(find_event(event_id)))


@bp.get("/outage-events")
@roles("NetworkOpsEngineer", "ComplianceOfficer", "ProvisioningAgent")
def list_events():
    limit, offset = pagination()
    beam_id = filter_value("beam_id")
    event_state = filter_enum("event_state", EVENT_STATES)
    cause = filter_enum("cause", OUTAGE_CAUSES)

    records = ordered(list(db.outage_events.values()))
    if beam_id is not None:
        records = [r for r in records if r["beam_id"] == beam_id]
    if event_state is not None:
        records = [r for r in records if r["event_state"] == event_state]
    if cause is not None:
        records = [r for r in records if r["cause"] == cause]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.outage_event), limit, offset, len(records)
    )


def _affected_subscriptions(event):
    """ACTIVE, authorised, on this beam, and live before the impairment began."""
    affected = []
    for subscription in ordered(list(db.subscriptions.values())):
        if subscription["service_state"] != "ACTIVE":
            continue
        if subscription["authorization_state"] not in AUTHORIZED_STATES:
            continue
        cell = capacity.cell_of_subscription(subscription)
        if cell is None or cell["beam_id"] != event["beam_id"]:
            continue
        if subscription["activated_at"] is None:
            continue
        if subscription["activated_at"] > event["started_at"]:
            continue
        affected.append(subscription)
    return affected


@bp.post("/outage-events/<event_id>/resolve")
@roles("NetworkOpsEngineer")
def resolve_event(event_id):
    body = body_dict()
    ended_at = req_dt(body, "ended_at")

    record = find_event(event_id)
    if ended_at <= record["started_at"]:
        fail(
            "ERR_INVALID_REQUEST",
            "'ended_at' must be strictly later than 'started_at'.",
        )
    if ended_at > clock.now():
        fail("ERR_INVALID_REQUEST", "'ended_at' may not be in the future.")
    if record["event_state"] != "OPEN":
        fail("ERR_OUTAGE_ALREADY_RESOLVED", "The event has already been resolved.")

    minutes = floor_minutes((ended_at - record["started_at"]).total_seconds())
    record["event_state"] = "RESOLVED"
    record["ended_at"] = ended_at
    record["outage_minutes"] = minutes
    record["credit_eligible"] = (
        record["cause"] != "PLANNED_MAINTENANCE" and minutes >= SLA_MIN_OUTAGE_MINUTES
    )

    # The drafting gate is looser than the eligibility gate: rows are created
    # whenever the impairment ran for at least 30 minutes, whatever the cause.
    drafted = 0
    if minutes >= SLA_MIN_OUTAGE_MINUTES:
        for subscription in _affected_subscriptions(record):
            plan = capacity.plan_of_subscription(subscription)
            if plan is None:
                continue
            credit = new_record()
            credit.update(
                {
                    "subscription_id": subscription["id"],
                    "outage_event_id": record["id"],
                    "provisional_credit_cents": billing.provisional_credit_cents(
                        record, plan
                    ),
                    "final_credit_cents": None,
                    "credit_state": "DRAFT",
                    "submitted_by_user_id": None,
                    "decided_by_user_id": None,
                    "decision_reason": None,
                }
            )
            db.outage_credits[credit["id"]] = credit
            drafted += 1
            # the subscriber's pending ledger has moved
            subscriber = db.subscribers.get(subscription["subscriber_id"])
            if subscriber is not None:
                touch(subscriber)

    record["generated_credit_count"] = drafted
    touch(record)
    return object_response(serialize.outage_event(record))


# --------------------------------------------------------------- credits -------

@bp.get("/outage-credits/<credit_id>")
@roles("ProvisioningAgent", "ComplianceOfficer", "Subscriber")
def read_credit(credit_id):
    own_credit(credit_id)
    return object_response(serialize.outage_credit(find_credit(credit_id)))


@bp.get("/outage-credits")
@roles("ProvisioningAgent", "ComplianceOfficer", "Subscriber", "NetworkOpsEngineer")
def list_credits():
    limit, offset = pagination()
    subscription_id = filter_value("subscription_id")
    event_id = filter_value("outage_event_id")
    credit_state = filter_enum("credit_state", CREDIT_STATES)

    records = ordered(list(db.outage_credits.values()))
    if subscription_id is not None:
        records = [r for r in records if r["subscription_id"] == subscription_id]
    if event_id is not None:
        records = [r for r in records if r["outage_event_id"] == event_id]
    if credit_state is not None:
        records = [r for r in records if r["credit_state"] == credit_state]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.outage_credit), limit, offset, len(records)
    )


@bp.post("/outage-credits/<credit_id>/submit")
@roles("ProvisioningAgent")
def submit_credit(credit_id):
    record = find_credit(credit_id)
    if record["credit_state"] != "DRAFT":
        fail("ERR_CREDIT_STATE_INVALID", "Submission is only legal from DRAFT.")

    event = db.outage_events.get(record["outage_event_id"])
    if event is None or event["event_state"] != "RESOLVED" or not event["credit_eligible"]:
        fail("ERR_CREDIT_NOT_ELIGIBLE", "The credit's outage event is not eligible.")

    record["credit_state"] = "SUBMITTED"
    record["submitted_by_user_id"] = current_user_id()
    touch(record)
    # DRAFT and SUBMITTED both count as pending, so no ledger moves here.
    return object_response(serialize.outage_credit(record))


@bp.post("/outage-credits/<credit_id>/decide")
@roles("ComplianceOfficer")
def decide_credit(credit_id):
    body = body_dict()
    decision = req_enum(body, "decision", CREDIT_DECISIONS)
    decision_reason = opt_str(body, "decision_reason", 1, 1000)

    record = find_credit(credit_id)
    if record["credit_state"] != "SUBMITTED":
        fail("ERR_CREDIT_STATE_INVALID", "A decision is only legal from SUBMITTED.")
    if record["submitted_by_user_id"] == current_user_id():
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The submitting operator may not decide their own credit.",
        )

    record["decided_by_user_id"] = current_user_id()
    record["decision_reason"] = decision_reason

    subscription = db.subscriptions.get(record["subscription_id"])
    if decision == "APPROVE":
        event = db.outage_events.get(record["outage_event_id"])
        plan = capacity.plan_of_subscription(subscription) if subscription else None
        record["credit_state"] = "APPROVED"
        record["final_credit_cents"] = (
            billing.final_credit_cents(event, plan) if event and plan else 0
        )
    else:
        record["credit_state"] = "REJECTED"
        record["final_credit_cents"] = None
    touch(record)

    # The provisional amount always leaves the pending ledger; only an approval
    # moves the final amount onto the balance.
    if subscription is not None:
        subscriber = db.subscribers.get(subscription["subscriber_id"])
        if subscriber is not None:
            touch(subscriber)

    return object_response(serialize.outage_credit(record))
