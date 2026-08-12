"""Evidence requests, the partitioned SLA clock and the agency decision."""
from flask import Blueprint

import clock
import serializers
import store
import validation
from calendar_util import advance_business_days, day_at_hour
from constants import (
    AGENCY_DECISIONS,
    API_PREFIX,
    BUSINESS_DAY_END_HOUR_UTC,
    DOC_TYPES,
    RFE_ADJUDICATIONS,
    RFE_RESPONSE_BUSINESS_DAYS,
    RFE_ROUND_CAP,
)
from errors import fail
from routes.common import READ_ROLES, created, endpoint, listing, ok
from services import cascade, legs, lookup, money, pricing, sla
from validation import Body

bp = Blueprint("rfes", __name__)
P = API_PREFIX


def compute_deadline(order, issued_at):
    consulate = lookup.consulate_of(order)
    day = advance_business_days(issued_at.date(), RFE_RESPONSE_BUSINESS_DAYS, consulate)
    return day_at_hour(day, BUSINESS_DAY_END_HOUR_UTC)


@bp.route(P + "/orders/<order_id>/rfes", methods=["POST"])
@endpoint("orders.rfes.create", ["AgencyLiaison"])
def issue_rfe(ctx, order_id):
    order = validation.need_order(order_id)
    body = Body(ctx.body)
    doc_type = body.enum("requested_doc_type", DOC_TYPES)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(order["workflow_status"], ("AT_AGENCY",))
    order["rfe_round_count"] = len(lookup.rfes_of(order))
    if order["rfe_round_count"] >= RFE_ROUND_CAP:
        fail("ERR_RFE_ROUND_CAP_EXCEEDED")

    issued_at = clock.now()
    row = store.insert("rfes", {
        "order_id": order["id"],
        "round_index": order["rfe_round_count"] + 1,
        "requested_doc_type": doc_type,
        "issued_at": issued_at,
        "deadline_at": compute_deadline(order, issued_at),
        "rfe_status": "OPEN",
        "responded_at": None,
        "response_count": 0,
    })
    order["rfe_round_count"] += 1
    order["workflow_status"] = "RFE_PENDING"
    sla.close_open_segment(order)
    sla.append_segment(order, "PAUSED", "RFE_ISSUED", started_at=issued_at)
    store.touch(order)
    return created(serializers.rfe(row))


@bp.route(P + "/orders/<order_id>/rfes", methods=["GET"])
@endpoint("orders.rfes.list", READ_ROLES)
def list_rfes(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    rows = lookup.rfes_of(order)
    rows = validation.apply_filter(rows, "rfe_status")
    return listing(rows, serializers.rfe)


@bp.route(P + "/rfes/<rfe_id>/respond", methods=["POST"])
@endpoint("rfes.respond", ["CaseManager", "Traveler"])
def respond_rfe(ctx, rfe_id):
    row = validation.need("rfes", rfe_id)
    order = lookup.order_of_rfe(row)
    validation.check_membership(ctx, order)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    validation.require_state(row["rfe_status"], ("OPEN",))
    if clock.now() > row["deadline_at"]:
        fail("ERR_RFE_DEADLINE_PASSED")

    row["rfe_status"] = "RESPONDED"
    row["responded_at"] = clock.now()
    row["response_count"] += 1
    store.touch(row)
    return ok(serializers.rfe(row))


def _abandon(order):
    sla.close_open_segment(order)
    order["workflow_status"] = "ABANDONED"
    order["decided_at"] = clock.now()
    money.adjudicate_refund(order)
    legs.create_return_leg(order)
    store.touch(order)


@bp.route(P + "/rfes/<rfe_id>/adjudicate", methods=["POST"])
@endpoint("rfes.adjudicate", ["AgencyLiaison"])
def adjudicate_rfe(ctx, rfe_id):
    row = validation.need("rfes", rfe_id)
    order = lookup.order_of_rfe(row)
    body = Body(ctx.body)
    outcome = body.enum("outcome", RFE_ADJUDICATIONS)
    body.check()
    validation.guard_order(ctx, order)

    if outcome == "EXPIRED":
        validation.require_state(row["rfe_status"], ("OPEN",))
        if clock.now() <= row["deadline_at"]:
            fail("ERR_INVALID_STATE", "The evidence-request deadline has not passed.")
        row["rfe_status"] = "EXPIRED"
        store.touch(row)
        _abandon(order)
        return ok(serializers.rfe(row))

    validation.require_state(row["rfe_status"], ("RESPONDED",))

    if outcome == "CLEARED":
        row["rfe_status"] = "CLEARED"
        store.touch(row)
        order["workflow_status"] = "AT_AGENCY"
        sla.close_open_segment(order)
        sla.append_segment(order, "RUNNING", "RFE_RESPONDED")
        store.touch(order)
        return ok(serializers.rfe(row))

    # INSUFFICIENT
    if row["response_count"] < RFE_ROUND_CAP:
        row["rfe_status"] = "OPEN"
        row["issued_at"] = clock.now()
        row["deadline_at"] = compute_deadline(order, row["issued_at"])
        store.touch(row)
        return ok(serializers.rfe(row))

    row["rfe_status"] = "INSUFFICIENT"
    store.touch(row)
    _abandon(order)
    return ok(serializers.rfe(row))


@bp.route(P + "/orders/<order_id>/agency-decision", methods=["POST"])
@endpoint("orders.agency_decision", ["AgencyLiaison"])
def agency_decision(ctx, order_id):
    order = validation.need_order(order_id)
    body = Body(ctx.body)
    decision = body.enum("decision", AGENCY_DECISIONS)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(order["workflow_status"], ("AT_AGENCY",))
    for row in lookup.rfes_of(order):
        if row["rfe_status"] in ("OPEN", "RESPONDED"):
            fail("ERR_INVALID_STATE", "An evidence request of this order is still outstanding.")

    decided_at = clock.now()
    order["decided_at"] = decided_at
    sla.close_open_segment(order)

    if decision == "APPROVED":
        order["workflow_status"] = "APPROVED"
        sla.append_segment(
            order, "RUNNING", "DECISION",
            started_at=decided_at, ended_at=decided_at, business_minutes=0,
        )
        legs.create_return_leg(order)
    else:
        order["workflow_status"] = "REJECTED"
        money.adjudicate_refund(order)
        legs.create_return_leg(order)
        cascade.withdraw_applicants(order)
        pricing.recompute_applicant_count(order)
    store.touch(order)
    return ok(serializers.order(order))
