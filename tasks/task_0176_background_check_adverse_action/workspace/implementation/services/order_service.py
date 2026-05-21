"""BackgroundCheckOrder lifecycle service.

Implements the full state machine: INTAKE -> IN_VERIFICATION ->
AWAITING_ADJUDICATION -> (COMPLETED_CLEAR | PRE_ADVERSE_ISSUED ->
AWAITING_FINAL -> TERMINATED_ADVERSE) plus REWORK and CANCELLED branches.
"""
from __future__ import annotations

from typing import List

from core.errors import (
    err_adverse_flow_already_exists,
    err_ban_the_box,
    err_candidate_not_eligible,
    err_consent_candidate_mismatch,
    err_consent_invalid,
    err_invalid_state,
    err_open_dispute_blocks_final,
    err_cooling_off_not_elapsed,
    err_resource_not_found,
    err_rework_cap_exceeded,
    err_sod_violation,
    err_validation_failed,
)
from core.store import store
from core.clock import logical_now, logical_now_iso
from core.utils import parse_iso
from services.audit_service import append_event
from services.calculations import (
    compute_composite_decision,
    compute_earliest_final_eligible_at,
    compute_severity_score,
    recompute_eligibility_posture,
)
from services.timestamps import stamp_create, stamp_update
from services.validations import (
    enforce_ban_the_box,
    enforce_requested_packages,
    enforce_salary_history_ban,
    get_active_consent_for_candidate,
)


_VALID_STAGES = {"PRE_OFFER", "POST_INTERVIEW", "POST_OFFER"}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create_order(
    *,
    candidate: dict,
    body: dict,
    actor_role: str,
    actor_user_id: str,
) -> dict:
    """Open a new BackgroundCheckOrder. Enforces priority-ordered validations
    per scaffold §1.4.
    """
    consent_disclosure_id = body.get("consent_disclosure_id")
    stage_at_order = body.get("stage_at_order")
    requested_packages = body.get("requested_packages")

    if not isinstance(consent_disclosure_id, str) or consent_disclosure_id == "":
        raise err_validation_failed("consent_disclosure_id is required.")
    if not isinstance(stage_at_order, str) or stage_at_order not in _VALID_STAGES:
        raise err_validation_failed(
            "stage_at_order must be one of PRE_OFFER, POST_INTERVIEW, POST_OFFER."
        )

    # Priority 7 - Ban-the-Box.
    enforce_ban_the_box(
        stage_at_order=stage_at_order,
        jurisdiction_code=candidate["residence_jurisdiction"],
    )

    # Priority 8 - Salary-history ban.
    enforce_salary_history_ban(
        body=body,
        candidate=candidate,
        jurisdiction_code=candidate.get("residence_jurisdiction"),
    )

    # Priority 9 - Consent. Lookup BEFORE checking candidate_match.
    consent = store.consents.get(consent_disclosure_id)
    if consent is None:
        raise err_consent_invalid("consent_disclosure_id not found.")
    # Priority 13 — referential consent/candidate mismatch.
    if consent.get("candidate_id") != candidate["id"]:
        raise err_consent_candidate_mismatch()
    if consent.get("status") != "ACTIVE":
        raise err_consent_invalid("Referenced consent is not ACTIVE.")
    if not consent.get("consent_signature"):
        raise err_consent_invalid("consent_signature missing on referenced consent.")

    # Priority 15 - Packages constraint.
    pkgs = enforce_requested_packages(requested_packages)

    # Priority 16 - eligibility_posture must be ELIGIBLE.
    if candidate.get("eligibility_posture") != "ELIGIBLE":
        raise err_candidate_not_eligible()

    # Construct the order row.
    order = {
        "candidate_id": candidate["id"],
        "consent_disclosure_id": consent_disclosure_id,
        "stage_at_order": stage_at_order,
        "requested_packages": pkgs,
        "status": "INTAKE",
        "composite_decision": "PENDING",
        "opened_by_role": actor_role,
        "opened_by_user_id": actor_user_id,
        "adjudicated_by_user_id": None,
    }
    stamp_create(order)
    store.orders[order["id"]] = order
    store.order_openers[order["id"]] = actor_user_id

    # Spawn VerificationItems (QUEUED).
    for kind in pkgs:
        item = {
            "order_id": order["id"],
            "kind": kind,
            "status": "QUEUED",
            "raw_finding": None,
            "severity_score": 0,
            "rework_count": 0,
            "dispute_id": None,
        }
        stamp_create(item)
        store.verification_items[item["id"]] = item

    # Recompute candidate posture -> UNDER_REVIEW.
    recompute_eligibility_posture(candidate)
    stamp_update(candidate)

    # Audit: ORDER_OPENED on the order subject (first event for that subject).
    append_event(
        event_type="ORDER_OPENED",
        subject_entity="BackgroundCheckOrder",
        subject_id=order["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )

    return order


# ---------------------------------------------------------------------------
# start-verification (INTAKE -> IN_VERIFICATION)
# ---------------------------------------------------------------------------
def start_verification(order: dict, *, actor_role: str, actor_user_id: str) -> dict:
    if order["status"] != "INTAKE":
        raise err_invalid_state(
            f"Order is in {order['status']}, expected INTAKE for start-verification."
        )
    candidate = store.candidates.get(order["candidate_id"])
    if candidate is None:
        raise err_resource_not_found("Candidate has been removed.")
    consent = store.consents.get(order["consent_disclosure_id"])
    if consent is None or consent.get("status") != "ACTIVE":
        # PRD §3.4: start-verification is rejected when the pinned
        # ConsentDisclosure is not ACTIVE. PRD §3.3 names
        # ERR_CONSENT_INVALID for the analogous consent-not-ACTIVE
        # condition on order creation; we surface the same code here.
        raise err_consent_invalid(
            "Pinned consent is no longer ACTIVE; verification cannot start."
        )
    if candidate.get("eligibility_posture") == "LOCKED":
        raise err_invalid_state("Candidate is LOCKED; verification cannot start.")

    items = store.list_items_for_order(order["id"])
    for it in items:
        if it["status"] == "QUEUED":
            it["status"] = "IN_PROGRESS"
            stamp_update(it)

    order["status"] = "IN_VERIFICATION"
    stamp_update(order)
    recompute_eligibility_posture(candidate)
    stamp_update(candidate)
    return order


# ---------------------------------------------------------------------------
# Cancel (INTAKE | IN_VERIFICATION | PRE_ADVERSE_ISSUED -> CANCELLED)
# ---------------------------------------------------------------------------
def cancel_order(order: dict, *, actor_role: str, actor_user_id: str) -> dict:
    candidate = store.candidates.get(order["candidate_id"])
    status = order["status"]
    if status == "INTAKE":
        # Unconditional.
        pass
    elif status == "IN_VERIFICATION":
        consent = store.consents.get(order["consent_disclosure_id"])
        consent_revoked = consent is not None and consent.get("status") == "REVOKED"
        # "no items have been adjudicated" — none in PASSED/FAILED.
        items = store.list_items_for_order(order["id"])
        any_adjudicated = any(i["status"] in {"PASSED", "FAILED"} for i in items)
        if not consent_revoked and any_adjudicated:
            raise err_invalid_state(
                "Cannot cancel IN_VERIFICATION order whose items have been adjudicated."
            )
        # Freeze IN_PROGRESS items (severity_score stays at current value).
        for it in items:
            if it["status"] == "IN_PROGRESS":
                # mark with a cancelled marker — we'll set status to FAILED-like
                # 'CANCELLED' but the scaffold does not enumerate a CANCELLED
                # item status. Per PRD §3.9 the items "are marked cancelled".
                it["status"] = "CANCELLED"
                stamp_update(it)
    elif status == "PRE_ADVERSE_ISSUED":
        # Recruiter cancel permitted when no open dispute remains.
        open_disp = _any_open_dispute(order["id"])
        if open_disp:
            raise err_invalid_state(
                "Cannot cancel PRE_ADVERSE_ISSUED order with an OPEN dispute."
            )
        flow = store.adverse_flow_for_order(order["id"])
        if flow is not None:
            flow["procedural_status"] = "ABANDONED"
            stamp_update(flow)
    else:
        raise err_invalid_state(
            f"Cannot cancel order in status {status}."
        )

    order["status"] = "CANCELLED"
    stamp_update(order)
    if candidate is not None:
        recompute_eligibility_posture(candidate)
        stamp_update(candidate)

    append_event(
        event_type="ORDER_CANCELLED",
        subject_entity="BackgroundCheckOrder",
        subject_id=order["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return order


# ---------------------------------------------------------------------------
# pre-adverse (AWAITING_ADJUDICATION -> PRE_ADVERSE_ISSUED)
# ---------------------------------------------------------------------------
def issue_pre_adverse(order: dict, *, actor_role: str, actor_user_id: str) -> dict:
    if order["status"] != "AWAITING_ADJUDICATION":
        raise err_invalid_state(
            f"Order is in {order['status']}, expected AWAITING_ADJUDICATION."
        )
    if order.get("composite_decision") not in {"CONSIDER", "INELIGIBLE"}:
        raise err_invalid_state(
            "composite_decision must be CONSIDER or INELIGIBLE for Pre-Adverse."
        )
    # Concurrency / uniqueness check.
    if store.adverse_flow_for_order(order["id"]) is not None:
        raise err_adverse_flow_already_exists()
    # SoD: actor != opener.
    if order.get("opened_by_user_id") == actor_user_id:
        raise err_sod_violation(
            "Adjudicator must differ from the order opener (segregation of duties)."
        )

    candidate = store.candidates.get(order["candidate_id"])
    jur_code = candidate["residence_jurisdiction"] if candidate else None
    jur = store.jurisdiction_policies.get(jur_code) if jur_code else None
    waiting_days = int(jur["adverse_action_waiting_business_days"]) if jur else 5

    sent_at = logical_now_iso()
    earliest = compute_earliest_final_eligible_at(
        pre_adverse_sent_at_iso=sent_at,
        waiting_period_business_days=waiting_days,
    )
    flow = {
        "order_id": order["id"],
        "pre_adverse_notice_sent_at": sent_at,
        "waiting_period_business_days": waiting_days,
        "earliest_final_eligible_at": earliest,
        "final_adverse_action_at": None,
        "notification_status": "PRE_DELIVERED",
        "procedural_status": "PRE_AWAITING_DISPUTE_WINDOW",
    }
    stamp_create(flow)
    store.adverse_flows[flow["id"]] = flow
    store.adverse_flow_by_order[order["id"]] = flow["id"]

    order["status"] = "PRE_ADVERSE_ISSUED"
    order["adjudicated_by_user_id"] = actor_user_id
    stamp_update(order)

    append_event(
        event_type="PRE_ADVERSE_SENT",
        subject_entity="BackgroundCheckOrder",
        subject_id=order["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return flow


# ---------------------------------------------------------------------------
# request-rework (PRE_ADVERSE_ISSUED -> REWORK)
# ---------------------------------------------------------------------------
def request_rework(
    order: dict,
    body: dict,
    *,
    actor_role: str,
    actor_user_id: str,
) -> dict:
    if order["status"] != "PRE_ADVERSE_ISSUED":
        raise err_invalid_state(
            f"Order is in {order['status']}, expected PRE_ADVERSE_ISSUED."
        )
    if order.get("opened_by_user_id") == actor_user_id:
        raise err_sod_violation()

    target_ids = body.get("target_item_ids")
    if not isinstance(target_ids, list) or len(target_ids) == 0:
        raise err_validation_failed("target_item_ids must be a non-empty array.")

    # Validate existence and ownership.
    items = []
    for tid in target_ids:
        if not isinstance(tid, str):
            raise err_validation_failed("target_item_ids entries must be strings.")
        it = store.verification_items.get(tid)
        if it is None or it["order_id"] != order["id"]:
            raise err_resource_not_found("Target item not found on this order.")
        items.append(it)

    # At least one item must have rework_count < 2.
    eligible_items = [i for i in items if int(i.get("rework_count", 0)) < 2]
    if not eligible_items:
        raise err_rework_cap_exceeded()

    for it in eligible_items:
        it["status"] = "REWORK_REQUIRED"
        it["rework_count"] = int(it.get("rework_count", 0)) + 1
        stamp_update(it)

    order["status"] = "REWORK"
    stamp_update(order)

    flow = store.adverse_flow_for_order(order["id"])
    if flow is not None:
        flow["procedural_status"] = "DISPUTE_PAUSED"
        stamp_update(flow)

    append_event(
        event_type="REWORK_REQUESTED",
        subject_entity="BackgroundCheckOrder",
        subject_id=order["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return order


# ---------------------------------------------------------------------------
# resume-verification (REWORK -> IN_VERIFICATION)
# ---------------------------------------------------------------------------
def resume_verification(order: dict, *, actor_role: str, actor_user_id: str) -> dict:
    if order["status"] != "REWORK":
        raise err_invalid_state(
            f"Order is in {order['status']}, expected REWORK."
        )
    if order.get("opened_by_user_id") == actor_user_id:
        raise err_sod_violation()

    items = store.list_items_for_order(order["id"])
    rework_items = [i for i in items if i["status"] == "REWORK_REQUIRED"]
    # PRD requires "All REWORK_REQUIRED items have refreshed raw_finding".
    # We interpret "refreshed" as: raw_finding present (non-null). The
    # cleanest path is to move them all to IN_PROGRESS unconditionally so
    # that the Verifier can post `/return` next.
    for it in rework_items:
        it["status"] = "IN_PROGRESS"
        it["dispute_id"] = None
        stamp_update(it)

    order["status"] = "IN_VERIFICATION"
    stamp_update(order)
    return order


# ---------------------------------------------------------------------------
# final-adverse (AWAITING_FINAL -> TERMINATED_ADVERSE)
# ---------------------------------------------------------------------------
def issue_final_adverse(order: dict, *, actor_role: str, actor_user_id: str) -> dict:
    if order["status"] != "AWAITING_FINAL":
        raise err_invalid_state(
            f"Order is in {order['status']}, expected AWAITING_FINAL."
        )
    flow = store.adverse_flow_for_order(order["id"])
    if flow is None:
        raise err_invalid_state("AdverseActionFlow does not exist for this order.")

    # Priority 10 — SoD: Final Adverse must come from the SAME adjudicator who
    # issued Pre-Adverse. Different role from the order opener was already
    # enforced at Pre-Adverse time.
    if order.get("adjudicated_by_user_id") != actor_user_id:
        raise err_sod_violation(
            "Final Adverse must be issued by the same Adjudicator who issued Pre-Adverse."
        )

    # Priority 11 — cooling-off.
    eligible_at = parse_iso(flow["earliest_final_eligible_at"])
    if logical_now() < eligible_at:
        raise err_cooling_off_not_elapsed()

    # Priority 12 — open dispute blocks final.
    if _any_open_dispute(order["id"]):
        raise err_open_dispute_blocks_final()

    flow["final_adverse_action_at"] = logical_now_iso()
    flow["notification_status"] = "FINAL_DELIVERED"
    flow["procedural_status"] = "FINALIZED"
    stamp_update(flow)

    order["status"] = "TERMINATED_ADVERSE"
    stamp_update(order)

    # Cascade cancel of non-terminal sibling orders for the same candidate.
    candidate = store.candidates.get(order["candidate_id"])
    if candidate is not None:
        for sib in store.list_orders_for_candidate(candidate["id"]):
            if sib["id"] == order["id"]:
                continue
            if sib["status"] not in {
                "COMPLETED_CLEAR",
                "TERMINATED_ADVERSE",
                "CANCELLED",
            }:
                sib["status"] = "CANCELLED"
                stamp_update(sib)
                append_event(
                    event_type="ORDER_CANCELLED",
                    subject_entity="BackgroundCheckOrder",
                    subject_id=sib["id"],
                    actor_role="system",
                    actor_user_id="system",
                )
        recompute_eligibility_posture(candidate)
        stamp_update(candidate)

    append_event(
        event_type="FINAL_ADVERSE_ISSUED",
        subject_entity="BackgroundCheckOrder",
        subject_id=order["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return order


# ---------------------------------------------------------------------------
# System auto-transitions: IN_VERIFICATION -> AWAITING_ADJUDICATION (and
# AWAITING_ADJUDICATION -> COMPLETED_CLEAR when composite_decision == CLEAR).
# Called from VerificationItem service after each return.
# ---------------------------------------------------------------------------
def maybe_advance_to_adjudication(order: dict) -> None:
    if order["status"] != "IN_VERIFICATION":
        return
    items = store.list_items_for_order(order["id"])
    if not items:
        return
    # The contributing statuses for "every item arrived" check.
    target = {"RETURNED", "PASSED", "FAILED"}
    if not all(i["status"] in target for i in items):
        return
    order["status"] = "AWAITING_ADJUDICATION"
    stamp_update(order)

    # Adjudicate each RETURNED item to PASSED/FAILED per per-item threshold.
    for it in items:
        if it["status"] == "RETURNED":
            score = int(it.get("severity_score", 0))
            if score < 15:
                it["status"] = "PASSED"
            else:
                it["status"] = "FAILED"
                append_event(
                    event_type="ITEM_FAILED",
                    subject_entity="VerificationItem",
                    subject_id=it["id"],
                    actor_role="system",
                    actor_user_id="system",
                )
            stamp_update(it)

    candidate = store.candidates.get(order["candidate_id"])
    if candidate is None:
        return
    decision = compute_composite_decision(order, candidate)
    order["composite_decision"] = decision
    stamp_update(order)

    if decision == "CLEAR":
        order["status"] = "COMPLETED_CLEAR"
        stamp_update(order)
        recompute_eligibility_posture(candidate)
        stamp_update(candidate)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _any_open_dispute(order_id: str) -> bool:
    for it in store.list_items_for_order(order_id):
        for d in store.list_disputes_for_item(it["id"]):
            if d.get("status") == "OPEN":
                return True
    return False
