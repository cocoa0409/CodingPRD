"""Dispute service — open + resolve."""
from __future__ import annotations

from core.errors import (
    err_dispute_not_owned,
    err_invalid_state,
    err_resource_not_found,
    err_rework_cap_exceeded,
    err_sod_violation,
    err_validation_failed,
)
from core.store import store
from services.audit_service import append_event
from services.calculations import (
    compute_earliest_final_eligible_at,
    recompute_eligibility_posture,
)
from services.timestamps import stamp_create, stamp_update


_DISPUTABLE_ITEM_STATES = {"RETURNED", "FAILED", "REWORK_REQUIRED"}


def open_dispute(*, body: dict, actor_role: str, actor_user_id: str) -> dict:
    if actor_role != "Candidate":
        # Routes layer also enforces role allow-list; defensive guard.
        raise err_dispute_not_owned()

    verification_item_id = body.get("verification_item_id")
    reason_text = body.get("reason_text")
    if not isinstance(verification_item_id, str) or verification_item_id == "":
        raise err_validation_failed("verification_item_id is required.")
    if not isinstance(reason_text, str) or len(reason_text) < 1 or len(reason_text) > 1000:
        raise err_validation_failed("reason_text must be 1..1000 characters.")

    item = store.verification_items.get(verification_item_id)
    if item is None:
        raise err_resource_not_found("VerificationItem not found.")
    order = store.orders.get(item["order_id"])
    if order is None:
        raise err_resource_not_found("Parent order not found.")
    # Ownership check (priority 14 ERR_DISPUTE_NOT_OWNED).
    if order["candidate_id"] != actor_user_id:
        raise err_dispute_not_owned()

    # State precondition.
    if order["status"] in {"COMPLETED_CLEAR", "TERMINATED_ADVERSE", "CANCELLED"}:
        raise err_invalid_state("Cannot dispute an item on a terminal order.")
    if item["status"] not in _DISPUTABLE_ITEM_STATES:
        raise err_invalid_state(
            f"Item is in {item['status']}, not disputable."
        )

    dispute = {
        "verification_item_id": verification_item_id,
        "candidate_id": order["candidate_id"],
        "reason_text": reason_text,
        "status": "OPEN",
        "resolution_note": None,
    }
    stamp_create(dispute)
    store.disputes[dispute["id"]] = dispute

    # Item moves to DISPUTED.
    item["status"] = "DISPUTED"
    item["dispute_id"] = dispute["id"]
    stamp_update(item)

    # Pause the cooling-off clock if flow exists.
    flow = store.adverse_flow_for_order(order["id"])
    if flow is not None and flow.get("procedural_status") != "DISPUTE_PAUSED":
        flow["procedural_status"] = "DISPUTE_PAUSED"
        stamp_update(flow)

    append_event(
        event_type="DISPUTE_OPENED",
        subject_entity="Dispute",
        subject_id=dispute["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return dispute


def resolve_dispute(
    dispute: dict,
    body: dict,
    *,
    actor_role: str,
    actor_user_id: str,
) -> dict:
    status = body.get("status")
    resolution_note = body.get("resolution_note")
    if status not in {"UPHELD", "OVERTURNED"}:
        raise err_validation_failed("status must be UPHELD or OVERTURNED.")
    if not isinstance(resolution_note, str) or resolution_note == "":
        raise err_validation_failed("resolution_note is required.")
    if dispute["status"] != "OPEN":
        raise err_invalid_state(
            f"Dispute is in {dispute['status']}, not resolvable."
        )

    item = store.verification_items.get(dispute["verification_item_id"])
    if item is None:
        raise err_resource_not_found("Underlying item not found.")
    order = store.orders.get(item["order_id"])
    if order is None:
        raise err_resource_not_found("Parent order not found.")

    # SoD: resolver must differ from order opener.
    if order.get("opened_by_user_id") == actor_user_id:
        raise err_sod_violation(
            "Adjudicator must differ from the order opener."
        )

    if status == "UPHELD":
        # Dispute denied. Item moves to FAILED.
        dispute["status"] = "UPHELD"
        dispute["resolution_note"] = resolution_note
        stamp_update(dispute)
        item["status"] = "FAILED"
        item["dispute_id"] = None
        stamp_update(item)
        # If flow exists and no other OPEN disputes remain on the order,
        # return procedural_status to PRE_AWAITING_DISPUTE_WINDOW and
        # recompute cooling-off.
        flow = store.adverse_flow_for_order(order["id"])
        if flow is not None and not _any_other_open_dispute(order["id"], exclude=dispute["id"]):
            flow["procedural_status"] = "PRE_AWAITING_DISPUTE_WINDOW"
            # Recompute earliest_final_eligible_at using the elapsed window.
            flow["earliest_final_eligible_at"] = compute_earliest_final_eligible_at(
                pre_adverse_sent_at_iso=flow["pre_adverse_notice_sent_at"],
                waiting_period_business_days=int(flow["waiting_period_business_days"]),
            )
            stamp_update(flow)
        append_event(
            event_type="DISPUTE_RESOLVED",
            subject_entity="Dispute",
            subject_id=dispute["id"],
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
        return dispute

    # OVERTURNED branch.
    cur_rework = int(item.get("rework_count", 0))
    if cur_rework + 1 > 2:
        # Cap exceeded — force order to TERMINATED_ADVERSE and reject.
        dispute["status"] = "OVERTURNED"
        dispute["resolution_note"] = resolution_note
        stamp_update(dispute)
        # Force terminate (do NOT bump rework_count beyond 2).
        order["status"] = "TERMINATED_ADVERSE"
        stamp_update(order)
        flow = store.adverse_flow_for_order(order["id"])
        if flow is not None:
            from core.clock import logical_now_iso

            flow["final_adverse_action_at"] = logical_now_iso()
            flow["notification_status"] = "FINAL_DELIVERED"
            flow["procedural_status"] = "FINALIZED"
            stamp_update(flow)
        candidate = store.candidates.get(order["candidate_id"])
        if candidate is not None:
            recompute_eligibility_posture(candidate)
            stamp_update(candidate)
        append_event(
            event_type="DISPUTE_RESOLVED",
            subject_entity="Dispute",
            subject_id=dispute["id"],
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
        raise err_rework_cap_exceeded()

    dispute["status"] = "OVERTURNED"
    dispute["resolution_note"] = resolution_note
    stamp_update(dispute)
    item["status"] = "REWORK_REQUIRED"
    item["rework_count"] = cur_rework + 1
    item["dispute_id"] = None
    stamp_update(item)

    flow = store.adverse_flow_for_order(order["id"])
    if flow is not None and not _any_other_open_dispute(order["id"], exclude=dispute["id"]):
        flow["procedural_status"] = "PRE_AWAITING_DISPUTE_WINDOW"
        flow["earliest_final_eligible_at"] = compute_earliest_final_eligible_at(
            pre_adverse_sent_at_iso=flow["pre_adverse_notice_sent_at"],
            waiting_period_business_days=int(flow["waiting_period_business_days"]),
        )
        stamp_update(flow)

    append_event(
        event_type="DISPUTE_RESOLVED",
        subject_entity="Dispute",
        subject_id=dispute["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return dispute


def _any_other_open_dispute(order_id: str, *, exclude: str) -> bool:
    for it in store.list_items_for_order(order_id):
        for d in store.list_disputes_for_item(it["id"]):
            if d["id"] == exclude:
                continue
            if d.get("status") == "OPEN":
                return True
    return False
