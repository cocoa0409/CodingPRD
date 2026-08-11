"""Order operations: submission, split, cancellation, the audit summary and tender."""
from decimal import Decimal

from flask import Blueprint

import clock
import serializers
import store
import validation
from calendar_util import is_business_day, round_half_up
from constants import API_PREFIX, RUSH_CUTOFF_HOUR_UTC, SPLIT_ADMIN_FEE_CENTS
from errors import fail
from routes.common import AUDIT_ROLES, created, endpoint, ok
from routes.order_routes import new_order_row
from services import (
    cascade, custody, legs, lookup, money, pricing, projection, readiness, sla,
)
from validation import Body

bp = Blueprint("order_ops", __name__)
P = API_PREFIX


# ------------------------------------------------------------------ submit ---
@bp.route(P + "/orders/<order_id>/submit", methods=["POST"])
@endpoint("orders.submit", ["CaseManager"])
def submit_order(ctx, order_id):
    order = validation.need_order(order_id)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    # Rung 10 admits BOTH INTAKE and READY_FOR_SUBMISSION on purpose; an INTAKE
    # order that is genuinely not ready falls through to rung 34.
    validation.require_state(order["workflow_status"], ("INTAKE", "READY_FOR_SUBMISSION"))
    # Rung 12 sits above every substantive submission rung.
    if order["quoted_by_user_id"] is not None and ctx.user_id == order["quoted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    # Rung 34
    counted = lookup.counted_applicants(order)
    if any(a["readiness_status"] != "COMPLETE" for a in counted):
        fail("ERR_REQUIRED_DOCUMENTS_INCOMPLETE")
    # Rung 35
    if order["service_level"] == "RUSH":
        instant = clock.now()
        consulate = lookup.consulate_of(order)
        if instant.hour >= RUSH_CUTOFF_HOUR_UTC or not is_business_day(instant.date(), consulate):
            fail("ERR_RUSH_CUTOFF_MISSED")
    # Rung 36
    if order["feasibility_status"] not in ("FEASIBLE", "ACKNOWLEDGED_INFEASIBLE"):
        fail("ERR_TRAVEL_DATE_INFEASIBLE")
    # Rung 37
    if order["outstanding_cents"] < order["total_quoted_cents"]:
        fail("ERR_BALANCE_OUTSTANDING")

    order["workflow_status"] = "SUBMITTED"
    order["submitted_at"] = clock.now()
    order["submitted_by_user_id"] = ctx.user_id
    order["effective_submission_date"] = projection.effective_submission_date(order)
    readiness.raise_stage(order, "SUBMITTED")
    money.record_earn(order, order["service_fee_quoted_cents"], "SERVICE_RECOGNITION")
    sla.append_segment(order, "RUNNING", "SUBMISSION", started_at=order["submitted_at"])
    store.touch(order)
    return ok(serializers.order(order))


# ------------------------------------------------------------------- split ---
@bp.route(P + "/orders/<order_id>/split", methods=["POST"])
@endpoint("orders.split", ["CaseManager"])
def split_order(ctx, order_id):
    order = validation.need_order(order_id)

    raw_ids = ctx.body.get("applicant_ids")
    moved = []
    if isinstance(raw_ids, list) and raw_ids and all(isinstance(x, str) for x in raw_ids):
        moved = [validation.need("applicants", x) for x in raw_ids]

    body = Body(ctx.body)
    body.string_array("applicant_ids")
    override = body.integer("transfer_cents_override", required=False, minimum=0)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(order["workflow_status"], ("INTAKE", "READY_FOR_SUBMISSION"))

    # Rung 32
    moved_ids = {a["id"] for a in moved}
    for applicant in moved:
        if applicant["order_id"] != order["id"] or applicant["readiness_status"] != "COMPLETE":
            fail("ERR_APPLICANT_NOT_READY")
    remaining = [a for a in lookup.counted_applicants(order) if a["id"] not in moved_ids]
    if not remaining:
        fail("ERR_APPLICANT_NOT_READY")

    pricing.recompute_applicant_count(order)
    parent_count_before = order["applicant_count"]
    moved_count = len(moved_ids)
    gov_transfer = round_half_up(
        Decimal(order["collected_government_cents"]) * moved_count / parent_count_before
    ) if parent_count_before else 0
    svc_transfer = round_half_up(
        Decimal(order["collected_service_cents"]) * moved_count / parent_count_before
    ) if parent_count_before else 0
    transfer_cents = gov_transfer + svc_transfer

    # Rung 33
    if override is not None and override != transfer_cents:
        fail("ERR_SPLIT_PARTITION_MISMATCH")

    child = store.insert("orders", new_order_row(
        order["catalog_item_id"], order["consulate_id"], order["service_level"],
        order["travel_date"], order["return_date"], order["delivery_region_code"],
        parent_order_id=order["id"], workflow_status="INTAKE",
        furthest_stage_reached="INTAKE",
    ))
    custody.append_first(child, order["custody_holder"], "ORDER_CREATED")

    for applicant in moved:
        applicant["order_id"] = child["id"]
        store.touch(applicant)

    if gov_transfer > 0:
        money.record_transfer_out(order, "GOVERNMENT", gov_transfer)
        money.record_transfer_in(child, "GOVERNMENT", gov_transfer)
    if svc_transfer > 0:
        money.record_transfer_out(order, "SERVICE", svc_transfer)
        money.record_transfer_in(child, "SERVICE", svc_transfer)

    # Adjudication of friction 4: min(SPLIT_ADMIN_FEE_CENTS, outstanding after
    # the transfer). The flat reading can drive outstanding_cents negative and
    # break Invariant 1, making conservation_ok true unreachable.
    admin_fee = min(SPLIT_ADMIN_FEE_CENTS, max(order["outstanding_cents"], 0))
    if admin_fee > 0:
        money.record_earn(order, admin_fee, "SPLIT_PARTITION")

    for target in (order, child):
        money.recompute_collected(target)
        pricing.run_full_quote(target, Decimal("0.00"))
        money.derive_payment_status(target)

    store.touch(order)
    for target in (order, child):
        for applicant in lookup.applicants_of(target):
            readiness.recompute_readiness(applicant, bump=False)
        readiness.reevaluate_gate(target, bump=False)

    # A newly created row is born at version 1 and is not additionally bumped
    # by the request that created it (PRD 2.10).
    child["version"] = 1
    child["updated_at"] = child["created_at"]
    return created(serializers.order(child))


# ------------------------------------------------------------------ cancel ---
@bp.route(P + "/orders/<order_id>/cancel", methods=["POST"])
@endpoint("orders.cancel", ["CaseManager", "Traveler"])
def cancel_order(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    body = Body(ctx.body)
    acknowledge = body.boolean("acknowledge_government_fee_forfeit", required=False, default=None)
    body.check()
    validation.guard_order(ctx, order)
    stage = order["workflow_status"]
    validation.require_state(stage, (
        "DRAFT", "QUOTED", "INTAKE", "READY_FOR_SUBMISSION", "SUBMITTED", "AT_AGENCY",
    ))
    # Rung 38
    if order["custody_holder"] == "AGENCY" and acknowledge is not True:
        fail("ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED")

    order["workflow_status"] = "CANCELLED"
    money.adjudicate_refund(order, "CANCELLATION_REFUND")
    # Adjudication of friction 5: the traveller withdrawal applies to EVERY
    # cancellation, which keeps the appointment/slot cascade reachable from an
    # AT_AGENCY cancel.
    cascade.withdraw_applicants(order)
    if stage in ("INTAKE", "READY_FOR_SUBMISSION"):
        cascade.cancel_outstanding_legs(order)
    if stage in ("SUBMITTED", "AT_AGENCY"):
        sla.close_open_segment(order)
    if stage == "AT_AGENCY":
        legs.create_return_leg(order)
    pricing.recompute_applicant_count(order)
    store.touch(order)
    return ok(serializers.order(order))


# ----------------------------------------------------------------- summary ---
@bp.route(P + "/orders/<order_id>/summary", methods=["GET"])
@endpoint("orders.summary", AUDIT_ROLES)
def read_summary(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    open_event = custody.open_event(order)
    return ok({
        "collected_cents": money.collected_cents(order),
        "government_tendered_cents": order["government_tendered_cents"],
        "service_earned_cents": order["service_earned_cents"],
        "refunded_cents": order["refunded_cents"],
        "refund_scheduled_cents": order["refund_scheduled_cents"],
        "outstanding_cents": order["outstanding_cents"],
        "conservation_ok": money.conservation_ok(order),
        "open_custody_count": custody.open_count(order),
        "open_custody_holder": open_event["holder_type"] if open_event else None,
        "sla_running_business_minutes": sla.running_minutes(order),
        "sla_paused_business_minutes": sla.paused_minutes(order),
        "sla_gross_business_minutes": sla.gross_minutes(order),
    })


# ------------------------------------------------------------------ tender ---
@bp.route(P + "/orders/<order_id>/tender", methods=["POST"])
@endpoint("orders.tender", ["AgencyLiaison"])
def tender_order(ctx, order_id):
    order = validation.need_order(order_id)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    validation.require_state(order["workflow_status"], ("SUBMITTED",))
    if order["custody_holder"] != "AGENCY":
        fail("ERR_CUSTODY_MISMATCH")

    order["workflow_status"] = "AT_AGENCY"
    order["tendered_at"] = clock.now()
    readiness.raise_stage(order, "AT_AGENCY")
    money.record_tender(order, order["government_fee_quoted_cents"])
    money.recompute_collected(order)
    store.touch(order)
    return ok(serializers.order(order))
