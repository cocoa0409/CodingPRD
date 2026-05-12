"""Test-driver endpoints: clock advance, payment, banking, logistics events."""

from flask import Blueprint, g

from clock import CLOCK, parse_iso, now_iso
from db import DB, LOCK, new_id
from errors import (
    invalid_state,
    not_found,
    validation_error,
)
from middleware import require_roles
from response import success_object
from services.audit import append_audit, append_escrow
from services.calculations import channel_fee_for_order, commission_for_order
from services.common import bump_version
from services.projects import (
    _synthesize_refund_record,
    recompute_final,
    resolve_all_due_deadlines,
)
from services.refunds import execute_refund_internal
from services.serializers import order_view, settlement_view, refund_view


bp = Blueprint("events", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def clock_advance():
    from services.common import get_json_body
    body = get_json_body()
    to_raw = body.get("to")
    if not to_raw:
        raise validation_error("'to' is required")
    try:
        to_dt = parse_iso(to_raw)
    except ValueError as e:
        raise validation_error(str(e))
    with LOCK:
        new_now = CLOCK.advance_to(to_dt)
        # After advancing, resolve any due deadlines and close any expired
        # modification windows. (Modification windows close passively because
        # they are checked at modify time against now() — no extra work needed.)
        resolve_all_due_deadlines()
    return success_object({"now": now_iso()})


@bp.route("/_events/payment", methods=["POST"])
@require_roles("PlatformAdmin")
def event_payment():
    from services.common import get_json_body
    body = get_json_body()
    order_id = body.get("order_id")
    result = body.get("result")
    external_ref = body.get("external_ref")
    if not isinstance(order_id, str) or not order_id:
        raise validation_error("order_id required")
    if result not in ("SUCCESS", "FAILURE"):
        raise validation_error("result must be SUCCESS or FAILURE")

    with LOCK:
        order = DB.orders.get(order_id)
        if order is None:
            raise not_found()
        if order["payment_status"] != "CHARGE_PENDING":
            raise invalid_state("Order not in CHARGE_PENDING")

        project = DB.projects.get(order["project_id"])
        if result == "SUCCESS":
            order["payment_status"] = "CHARGED"
            order["refundable_remainder_cents"] = int(order["order_total_cents"])
            bump_version(order)
            # Pin commission and channel fee
            commission = commission_for_order(int(order["order_total_cents"]), project["category"])
            channel_fee = channel_fee_for_order(int(order["order_total_cents"]))
            DB.order_charge_pins[order["id"]] = {
                "commission_cents": commission,
                "channel_fee_cents": channel_fee,
                "charged_at": CLOCK.now(),
            }
            # Ledger
            append_escrow(project["id"], order["id"], "CHARGE_CAPTURE",
                          amount_cents=int(order["order_total_cents"]),
                          external_ref=external_ref)
            append_escrow(project["id"], order["id"], "COMMISSION_HOLD", amount_cents=commission)
            append_escrow(project["id"], order["id"], "CHANNEL_FEE", amount_cents=channel_fee)
            append_audit(
                subject_type="ORDER",
                subject_id=order["id"],
                event_type="STATUS_CHANGE",
                payload={"from": "CHARGE_PENDING", "to": "CHARGED"},
                actor_role="SYSTEM",
                actor_id="SYSTEM",
            )
            append_audit(
                subject_type="ORDER",
                subject_id=order["id"],
                event_type="FUND_FLOW",
                payload={"amount_cents": int(order["order_total_cents"]), "commission_cents": commission, "channel_fee_cents": channel_fee},
                actor_role="SYSTEM",
                actor_id="SYSTEM",
            )
            recompute_final(project)
        else:  # FAILURE
            attempts = int(order.get("charge_attempts", 0))
            if attempts >= 3:
                # Terminal failure
                order["payment_status"] = "CHARGE_FAILED"
                bump_version(order)
                append_audit(
                    subject_type="ORDER",
                    subject_id=order["id"],
                    event_type="STATUS_CHANGE",
                    payload={"from": "CHARGE_PENDING", "to": "CHARGE_FAILED"},
                    actor_role="SYSTEM",
                    actor_id="SYSTEM",
                )
                # Synthesize PLATFORM_MANDATORY refund (amount 0, EXECUTED) for audit
                rr = _synthesize_refund_record(
                    order=order,
                    reason="PLATFORM_MANDATORY",
                    triggered_by="PLATFORM_AUTO",
                    approved_amount_cents=0,
                    status_value="EXECUTED",
                )
                append_audit(
                    subject_type="REFUND_REQUEST",
                    subject_id=rr["id"],
                    event_type="REFUND_EXECUTED",
                    payload={"amount_cents": 0, "reason": "PLATFORM_MANDATORY"},
                    actor_role="SYSTEM",
                    actor_id="SYSTEM",
                )
            else:
                # Revert to AUTHORIZED for retry
                order["payment_status"] = "AUTHORIZED"
                bump_version(order)
                append_audit(
                    subject_type="ORDER",
                    subject_id=order["id"],
                    event_type="STATUS_CHANGE",
                    payload={"from": "CHARGE_PENDING", "to": "AUTHORIZED", "retry": True},
                    actor_role="SYSTEM",
                    actor_id="SYSTEM",
                )
                # PRD §3.6: 'cycling AUTHORIZED → CHARGE_PENDING →
                # AUTHORIZED until charge_attempts reaches 3'. The system
                # immediately re-enqueues the charge so the next payment
                # event finds the order in CHARGE_PENDING again, and
                # charge_attempts is incremented per the rule that the
                # counter advances each time the order leaves AUTHORIZED
                # for CHARGE_PENDING.
                order["payment_status"] = "CHARGE_PENDING"
                order["charge_attempts"] = int(order.get("charge_attempts", 0)) + 1
                bump_version(order)
                append_audit(
                    subject_type="ORDER",
                    subject_id=order["id"],
                    event_type="STATUS_CHANGE",
                    payload={"from": "AUTHORIZED", "to": "CHARGE_PENDING",
                             "retry": True,
                             "charge_attempts": order["charge_attempts"]},
                    actor_role="SYSTEM",
                    actor_id="SYSTEM",
                )
        return success_object(order_view(order))


@bp.route("/_events/banking", methods=["POST"])
@require_roles("PlatformAdmin")
def event_banking():
    from services.common import get_json_body
    body = get_json_body()
    subject_type = body.get("subject_type")
    subject_id = body.get("subject_id")
    result = body.get("result")
    external_ref = body.get("external_ref")
    if subject_type not in ("REFUND_REQUEST", "SETTLEMENT_BATCH"):
        raise validation_error("subject_type must be REFUND_REQUEST or SETTLEMENT_BATCH")
    if not isinstance(subject_id, str) or not subject_id:
        raise validation_error("subject_id required")
    if result not in ("SUCCESS", "FAILURE"):
        raise validation_error("result must be SUCCESS or FAILURE")

    with LOCK:
        if subject_type == "REFUND_REQUEST":
            rec = DB.refund_requests.get(subject_id)
            if rec is None:
                raise not_found()
            if rec["status"] != "APPROVED":
                raise invalid_state("Refund not APPROVED")
            if result == "SUCCESS":
                # Banking confirms refund: execute it
                execute_refund_internal(rec, actor_role="SYSTEM", actor_id="SYSTEM")
            else:
                rec["status"] = "FAILED"
                bump_version(rec)
                append_audit(
                    subject_type="REFUND_REQUEST",
                    subject_id=rec["id"],
                    event_type="STATUS_CHANGE",
                    payload={"from": "APPROVED", "to": "FAILED", "external_ref": external_ref},
                    actor_role="SYSTEM",
                    actor_id="SYSTEM",
                )
            return success_object({
                "subject_type": "REFUND_REQUEST",
                "subject_id": rec["id"],
                "status": rec["status"],
            })
        else:  # SETTLEMENT_BATCH
            batch = DB.settlement_batches.get(subject_id)
            if batch is None:
                raise not_found()
            if batch["status"] != "FINALIZED":
                raise invalid_state("Batch not FINALIZED")
            if result == "SUCCESS":
                batch["status"] = "PAID"
                bump_version(batch)
                append_escrow(batch["project_id"], None, "SETTLEMENT_PAYOUT",
                              amount_cents=-int(batch["net_payout_cents"]),
                              external_ref=external_ref)
                append_audit(
                    subject_type="SETTLEMENT_BATCH",
                    subject_id=batch["id"],
                    event_type="SETTLEMENT_PAID",
                    payload={"net_payout_cents": int(batch["net_payout_cents"])},
                    actor_role="SYSTEM",
                    actor_id="SYSTEM",
                )
            else:
                batch["status"] = "FAILED"
                bump_version(batch)
                append_audit(
                    subject_type="SETTLEMENT_BATCH",
                    subject_id=batch["id"],
                    event_type="STATUS_CHANGE",
                    payload={"from": "FINALIZED", "to": "FAILED", "external_ref": external_ref},
                    actor_role="SYSTEM",
                    actor_id="SYSTEM",
                )
            return success_object({
                "subject_type": "SETTLEMENT_BATCH",
                "subject_id": batch["id"],
                "status": batch["status"],
            })


@bp.route("/_events/logistics", methods=["POST"])
@require_roles("PlatformAdmin")
def event_logistics():
    from services.common import get_json_body
    body = get_json_body()
    order_id = body.get("order_id")
    lines = body.get("lines")
    if not isinstance(order_id, str) or not order_id:
        raise validation_error("order_id required")
    if not isinstance(lines, list):
        raise validation_error("lines must be a list")
    cleaned_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise validation_error("each line must be an object")
        value = line.get("value_cents", 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise validation_error("line.value_cents must be a non-negative integer")
        line_id = line.get("line_id") or new_id()
        cleaned_lines.append({"line_id": line_id, "value_cents": value, "fully_shipped": bool(line.get("fully_shipped", False))})

    with LOCK:
        order = DB.orders.get(order_id)
        if order is None:
            raise not_found()

        # Append shipments
        DB.shipments.setdefault(order_id, []).extend(cleaned_lines)
        # Recompute fulfillment
        total_shipped_value = sum(int(l["value_cents"]) for l in DB.shipments[order_id])
        order_total = int(order["order_total_cents"])

        # Determine fulfillment status
        any_shipped = total_shipped_value > 0 or any(l.get("fully_shipped") for l in DB.shipments[order_id])
        # Fully shipped if shipped value >= order_total OR any line marked fully_shipped explicitly
        if total_shipped_value >= order_total and total_shipped_value > 0:
            order["fulfillment_status"] = "FULLY_SHIPPED"
        elif any_shipped:
            order["fulfillment_status"] = "PARTIALLY_SHIPPED"
        # else stays as-is (NOT_STARTED or NOT_APPLICABLE)

        # Recompute refundable_remainder_cents = max(0, order_total - shipped)
        order["refundable_remainder_cents"] = max(0, order_total - total_shipped_value)
        bump_version(order)

        append_audit(
            subject_type="ORDER",
            subject_id=order["id"],
            event_type="EXTERNAL_EVENT_RECEIVED",
            payload={"event": "logistics_shipment", "lines": cleaned_lines, "fulfillment_status": order["fulfillment_status"]},
            actor_role="SYSTEM",
            actor_id="SYSTEM",
        )
        return success_object(order_view(order))
