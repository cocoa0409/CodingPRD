"""Core business engine: verification/order/adverse-action transitions, cascades,
overall_result calc, risk score.
"""

from datetime import timedelta
from decimal import Decimal

from db import db, iso_from_datetime
from errors import raise_api
from util import stamp_update, round_half_up_2
from services.audit import append_audit


# ---------- Risk-score weights (scaffold §1.3) ----------
STREAM_FAILURE_WEIGHTS = {
    "CRIMINAL": Decimal("0.65"),
    "MVR": Decimal("0.25"),
    "EDUCATION": Decimal("0.10"),
}
STREAM_ORDER = ["CRIMINAL", "MVR", "EDUCATION"]
RISK_THRESHOLD = Decimal("0.50")
FEDERAL_WAITING_DAY_FLOOR = 5


def verifications_for_order(order_id: str):
    return [v for v in db.verifications.values() if v["order_id"] == order_id]


# ---------- Overall result ----------

def compute_overall_result(order_id: str):
    """Return CONSIDER if any of the three verifications has result FAIL,
    otherwise CLEAR. Only called once the order's status==COMPLETE."""
    verifs = verifications_for_order(order_id)
    effective_results = [v.get("result") for v in verifs]
    if any(r == "FAIL" for r in effective_results):
        return "CONSIDER"
    return "CLEAR"


# ---------- Risk score ----------

def compute_risk_score(order_id: str):
    """Return dict { score, variant, exceeds_threshold, threshold }.

    Variant 'provisional_in_review' iff order.status == IN_REVIEW (some PENDING).
    Variant 'final_complete' iff order.status == COMPLETE (all three contribute).
    """
    order = db.orders.get(order_id)
    if not order:
        raise_api("ERR_NOT_FOUND", "Order not found")
    verifs_by_type = {
        v["verification_type"]: v for v in verifications_for_order(order_id)
    }
    contributions = []
    for stream in STREAM_ORDER:
        v = verifs_by_type.get(stream)
        if v is None:
            continue
        if v["status"] == "PENDING":
            continue
        weight = STREAM_FAILURE_WEIGHTS[stream]
        raw = weight if v.get("result") == "FAIL" else Decimal("0")
        contributions.append(round_half_up_2(raw))
    total = round_half_up_2(sum(contributions, Decimal("0")))
    variant = (
        "final_complete" if order["status"] == "COMPLETE"
        else "provisional_in_review"
    )
    return {
        "score": float(total),
        "variant": variant,
        "exceeds_threshold": bool(total >= RISK_THRESHOLD),
        "threshold": float(RISK_THRESHOLD),
    }


# ---------- AdverseAction helpers ----------

def adverse_action_for_order(order_id: str):
    for a in db.adverse_actions.values():
        if a["order_id"] == order_id:
            return a
    return None


def _create_adverse_action(order: dict):
    """Auto-create AdverseAction in PRE_ADVERSE_SENT for an order whose
    overall_result just settled to CONSIDER. Computes earliest_final_at."""
    from util import new_id  # local to avoid cycle at module import time

    application = db.applications.get(order["application_id"])
    jurisdiction = db.jurisdictions.get(application["jurisdiction_id"])
    base_dt = db.current_utc_dt()
    earliest_dt = base_dt + timedelta(days=int(jurisdiction["pre_adverse_waiting_days"]))
    now_iso = iso_from_datetime(base_dt)
    aa = {
        "id": new_id(),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "order_id": order["id"],
        "status": "PRE_ADVERSE_SENT",
        "pre_adverse_sent_at": now_iso,
        "earliest_final_at": iso_from_datetime(earliest_dt),
        "finalized_at": None,
        "finalized_by_user_id": None,
        "dispute_reason": None,
    }
    db.adverse_actions[aa["id"]] = aa
    return aa


# ---------- Order posture recompute ----------

def _set_order_status(order: dict, new_status: str):
    """Mutate order.status; bump version + updated_at; recompute overall_result
    on COMPLETE."""
    order["status"] = new_status
    stamp_update(order)
    if new_status == "COMPLETE":
        order["overall_result"] = compute_overall_result(order["id"])
    return order


def recompute_order_posture_after_report(order: dict, actor_role: str, actor_user_id: str, just_reported_id: str = None):
    """Called after a Verification transitions PENDING -> REPORTED.

    Drive order PENDING -> IN_REVIEW (one PENDING + one non-PENDING),
    or PENDING/IN_REVIEW -> COMPLETE (no PENDING children remain).
    Bridge any *sibling* that was REPORTED to RESOLVED on COMPLETE entry
    (PRD §3.4/§3.5: 'sibling' = a row other than the one that just transitioned).
    On COMPLETE w/ CONSIDER, auto-create AdverseAction.
    """
    verifs = verifications_for_order(order["id"])
    statuses = [v["status"] for v in verifs]
    pending_count = sum(1 for s in statuses if s == "PENDING")
    # If we have all three children and none are PENDING, COMPLETE.
    if len(verifs) == 3 and pending_count == 0:
        prior = order["status"]
        if order["status"] != "COMPLETE":
            # Bridge any REPORTED *sibling* (NOT the just-reported one) to RESOLVED.
            for v in verifs:
                if v["id"] == just_reported_id:
                    continue
                if v["status"] == "REPORTED":
                    v["status"] = "RESOLVED"
                    stamp_update(v)
            _set_order_status(order, "COMPLETE")
            # CONSIDER -> create AdverseAction
            if order.get("overall_result") == "CONSIDER" and adverse_action_for_order(order["id"]) is None:
                _create_adverse_action(order)
            # No audit row spec'd for system-driven order COMPLETE; only the
            # caller's explicit action (e.g. VERIFICATION_REPORT) is logged.
        return
    # Otherwise — at least one PENDING child remains; first non-PENDING drives IN_REVIEW.
    if order["status"] == "PENDING" and pending_count < len(verifs):
        _set_order_status(order, "IN_REVIEW")


def recompute_order_posture_after_resolve(order: dict):
    """Called after Verification DISPUTED -> RESOLVED.

    Per PRD §3.5: if parent.status==COMPLETE, recompute overall_result.
    If recompute yields CLEAR and AdverseAction exists, cascade-cancel it.
    If recompute leaves CONSIDER and no children DISPUTED, cycle AdverseAction
    DISPUTED -> PRE_ADVERSE_SENT.
    """
    if order["status"] != "COMPLETE":
        return
    new_result = compute_overall_result(order["id"])
    order["overall_result"] = new_result
    stamp_update(order)

    aa = adverse_action_for_order(order["id"])
    if aa is None:
        return
    if new_result == "CLEAR":
        if aa["status"] in {"PRE_ADVERSE_SENT", "DISPUTED"}:
            aa["status"] = "CANCELLED"
            stamp_update(aa)
    else:  # CONSIDER
        # cycle back DISPUTED -> PRE_ADVERSE_SENT if no children still DISPUTED
        if aa["status"] == "DISPUTED":
            any_disputed = any(
                v["status"] == "DISPUTED"
                for v in verifications_for_order(order["id"])
            )
            if not any_disputed:
                aa["status"] = "PRE_ADVERSE_SENT"
                stamp_update(aa)
