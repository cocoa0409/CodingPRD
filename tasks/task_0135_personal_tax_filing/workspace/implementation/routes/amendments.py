"""AmendedReturn (1040X) routes (PRD §3.9)."""
from __future__ import annotations

from flask import Blueprint, g

from config import (
    ACCOUNT_ACTIVE,
    AMEND_STATUS_ACCEPTED,
    AMEND_STATUS_DRAFT,
    AMEND_STATUS_REJECTED,
    AMEND_STATUS_SUBMITTED,
    DEDUCTION_METHODS,
    FILING_STATUSES,
    RETURN_STATUS_ACCEPTED,
    RETURN_STATUS_AMENDED,
    RETURN_STATUS_SUPERSEDED,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
)
from db import store
from errors import (
    err_amendment_already_open,
    err_amendment_not_allowed,
    err_forbidden,
    err_invalid_input,
    err_invalid_state,
    err_qualifying_children_exceed,
    err_taxpayer_locked,
)
from middleware import require_auth
from response import success
from services import engine
from services.audit import append_audit
from utils import iso_now, is_nonempty_str, new_uuid

from routes._helpers import (
    check_version,
    get_amendment_or_404,
    get_json,
    get_return_or_404,
    get_taxpayer_or_404,
    parse_version,
)


bp = Blueprint("amendments", __name__)


def _serialize_amendment(a: dict) -> dict:
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "original_return_id": a["original_return_id"],
        "form_code": a["form_code"],
        "reason_summary": a["reason_summary"],
        "status": a["status"],
        "delta_agi_cents": a["delta_agi_cents"],
        "delta_tax_cents": a["delta_tax_cents"],
        "delta_balance_due_or_refund_cents": a["delta_balance_due_or_refund_cents"],
        "restated_return_snapshot": a.get("restated_return_snapshot"),
        "submitted_at": a.get("submitted_at"),
        "restated_filing_status": a.get("restated_filing_status"),
        "restated_dependents_count": a.get("restated_dependents_count"),
        "restated_qualifying_children_under_17": a.get("restated_qualifying_children_under_17"),
        "restated_deduction_method": a.get("restated_deduction_method"),
    }


# ── POST /amendments ────────────────────────────────────────────────────


@bp.post("/amendments")
@require_auth([ROLE_TAXPAYER])
def create_amendment():
    body = get_json()

    with store.lock:
        original_id = body.get("original_return_id")
        if not is_nonempty_str(original_id):
            raise err_invalid_input("original_return_id is required")
        original = get_return_or_404(original_id)
        if original["taxpayer_id"] != g.user_id:
            raise err_forbidden("Cannot amend another taxpayer's return")

        tp = get_taxpayer_or_404(original["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()

        # Priority 8: original must be ACCEPTED.
        if original["status"] != RETURN_STATUS_ACCEPTED:
            raise err_amendment_not_allowed()

        # Priority 9: no other active amendment on this original.
        if engine.has_active_amendment(original_id):
            raise err_amendment_already_open()

        reason = body.get("reason_summary")
        if not is_nonempty_str(reason):
            raise err_invalid_input("reason_summary is required")

        # Optional restated fields validation.
        restated_fs = body.get("restated_filing_status")
        if restated_fs is not None and restated_fs not in FILING_STATUSES:
            raise err_invalid_input("restated_filing_status must be a valid enum value")
        restated_dep = body.get("restated_dependents_count")
        if restated_dep is not None and (
            isinstance(restated_dep, bool) or not isinstance(restated_dep, int) or restated_dep < 0
        ):
            raise err_invalid_input("restated_dependents_count must be a non-negative integer")
        restated_q = body.get("restated_qualifying_children_under_17")
        if restated_q is not None and (
            isinstance(restated_q, bool) or not isinstance(restated_q, int) or restated_q < 0
        ):
            raise err_invalid_input("restated_qualifying_children_under_17 must be a non-negative integer")
        # Cross-field constraint when both restated counts are present.
        if (restated_dep is not None) and (restated_q is not None) and restated_q > restated_dep:
            raise err_qualifying_children_exceed()
        # If only qualifying_children is restated, compare against original dependents (or restated if given).
        if restated_q is not None and restated_dep is None:
            if restated_q > original["dependents_count"]:
                raise err_qualifying_children_exceed()
        restated_dm = body.get("restated_deduction_method")
        if restated_dm is not None and restated_dm not in DEDUCTION_METHODS:
            raise err_invalid_input("restated_deduction_method must be STANDARD or ITEMIZED")

        a = {
            "id": new_uuid(),
            "original_return_id": original_id,
            "form_code": "1040X",
            "reason_summary": reason,
            "status": AMEND_STATUS_DRAFT,
            "delta_agi_cents": 0,
            "delta_tax_cents": 0,
            "delta_balance_due_or_refund_cents": 0,
            "restated_return_snapshot": None,
            "submitted_at": None,
            "restated_filing_status": restated_fs,
            "restated_dependents_count": restated_dep,
            "restated_qualifying_children_under_17": restated_q,
            "restated_deduction_method": restated_dm,
        }
        engine.stamp_create(a)
        store.amendments[a["id"]] = a

    return success(_serialize_amendment(a), 201)


# ── GET /amendments/{id} ────────────────────────────────────────────────


@bp.get("/amendments/<amendment_id>")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def get_amendment(amendment_id):
    a = get_amendment_or_404(amendment_id)
    if g.role == ROLE_TAXPAYER:
        original = get_return_or_404(a["original_return_id"])
        if original["taxpayer_id"] != g.user_id:
            raise err_forbidden("Taxpayer can only access own amendments")
    return success(_serialize_amendment(a), 200)


# ── POST /amendments/{id}/submit ────────────────────────────────────────


@bp.post("/amendments/<amendment_id>/submit")
@require_auth([ROLE_TAXPAYER])
def submit_amendment(amendment_id):
    body = get_json()
    expected = parse_version(body)
    with store.lock:
        a = get_amendment_or_404(amendment_id)
        original = get_return_or_404(a["original_return_id"])
        if original["taxpayer_id"] != g.user_id:
            raise err_forbidden("Cannot submit another taxpayer's amendment")
        tp = get_taxpayer_or_404(original["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if a["status"] != AMEND_STATUS_DRAFT:
            raise err_invalid_state("Amendment must be in DRAFT to submit")
        if original["status"] != RETURN_STATUS_ACCEPTED:
            raise err_amendment_not_allowed()
        # Priority 9: serialize concurrent submissions on same original.
        if engine.has_active_amendment(original["id"], exclude_id=a["id"]):
            raise err_amendment_already_open()

        # At least one restated field must differ from the original snapshot.
        diff_found = False
        if a.get("restated_filing_status") is not None and a["restated_filing_status"] != original["filing_status"]:
            diff_found = True
        if a.get("restated_dependents_count") is not None and a["restated_dependents_count"] != original["dependents_count"]:
            diff_found = True
        if a.get("restated_qualifying_children_under_17") is not None and a["restated_qualifying_children_under_17"] != original["qualifying_children_under_17"]:
            diff_found = True
        if a.get("restated_deduction_method") is not None and a["restated_deduction_method"] != original["deduction_method"]:
            diff_found = True
        if not diff_found:
            raise err_invalid_state("At least one restated field must differ from the original")

        check_version(a, expected)

        # Compute restated snapshot.
        snap = engine.run_amendment_compute(a, original, tp)

        # Compute deltas (PRD §3.9).
        orig_total_credits = original.get("total_credits_cents", 0) or 0
        orig_final_tax = (original.get("regular_tax_cents", 0) or 0) + (original.get("amt_cents", 0) or 0)
        new_final_tax = snap["regular_tax_cents"] + snap["amt_cents"]
        new_total_credits = snap["total_credits_cents"]
        delta_agi = snap["agi_cents"] - (original.get("agi_cents", 0) or 0)
        delta_tax = (new_final_tax - new_total_credits) - (orig_final_tax - orig_total_credits)
        delta_balance = snap["balance_due_or_refund_cents"] - (original.get("balance_due_or_refund_cents", 0) or 0)

        a["status"] = AMEND_STATUS_SUBMITTED
        a["submitted_at"] = iso_now(store.clock_now())
        a["restated_return_snapshot"] = snap
        a["delta_agi_cents"] = delta_agi
        a["delta_tax_cents"] = delta_tax
        a["delta_balance_due_or_refund_cents"] = delta_balance
        engine.stamp_update(a)

        # Cascade: original ACCEPTED → AMENDED.
        original["status"] = RETURN_STATUS_AMENDED
        engine.stamp_update(original)

        append_audit(
            actor_role=g.role,
            actor_id=g.user_id,
            action="RETURN_AMENDED",
            target_entity="TaxReturn",
            target_id=original["id"],
            payload={"amendment_id": a["id"]},
        )

    return success(_serialize_amendment(a), 200)


# ── POST /amendments/{id}/decide ────────────────────────────────────────


@bp.post("/amendments/<amendment_id>/decide")
@require_auth([ROLE_IRSADJUDICATOR])
def decide_amendment(amendment_id):
    body = get_json()
    outcome = body.get("outcome")
    rejection_message = body.get("rejection_message")
    if outcome not in (AMEND_STATUS_ACCEPTED, AMEND_STATUS_REJECTED):
        raise err_invalid_input("outcome must be ACCEPTED or REJECTED")
    if outcome == AMEND_STATUS_REJECTED and not is_nonempty_str(rejection_message):
        raise err_invalid_input("rejection_message is required when outcome=REJECTED")

    with store.lock:
        a = get_amendment_or_404(amendment_id)
        if a["status"] != AMEND_STATUS_SUBMITTED:
            raise err_invalid_state("Amendment must be in SUBMITTED to decide")
        original = get_return_or_404(a["original_return_id"])

        if outcome == AMEND_STATUS_ACCEPTED:
            a["status"] = AMEND_STATUS_ACCEPTED
            engine.stamp_update(a)
            original["status"] = RETURN_STATUS_SUPERSEDED
            engine.stamp_update(original)
            append_audit(
                actor_role=g.role,
                actor_id=g.user_id,
                action="AMENDMENT_ACCEPTED",
                target_entity="AmendedReturn",
                target_id=a["id"],
                payload={"original_return_id": original["id"]},
            )
            append_audit(
                actor_role=g.role,
                actor_id=g.user_id,
                action="RETURN_SUPERSEDED",
                target_entity="TaxReturn",
                target_id=original["id"],
                payload={"amendment_id": a["id"]},
            )
        else:
            a["status"] = AMEND_STATUS_REJECTED
            engine.stamp_update(a)
            # Revert original from AMENDED back to ACCEPTED.
            original["status"] = RETURN_STATUS_ACCEPTED
            engine.stamp_update(original)
            append_audit(
                actor_role=g.role,
                actor_id=g.user_id,
                action="AMENDMENT_REJECTED",
                target_entity="AmendedReturn",
                target_id=a["id"],
                payload={
                    "original_return_id": original["id"],
                    "rejection_message": rejection_message,
                },
            )

    return success(_serialize_amendment(a), 200)
