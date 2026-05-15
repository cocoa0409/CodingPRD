"""EditorDecision endpoints: create, recommend, finalize."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_auth
from ..calculations import (
    MAJOR_DAYS,
    MINOR_DAYS,
    aggregate_score,
    aggregated_category,
)
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..store import fmt_ts, store
from ..utils import check_version, get_json_body, require_str


decisions_bp = Blueprint("decisions", __name__)

_REC_VALUES = {"ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT", "TRANSFER"}


def _submitted_reviews_sorted(mid: str, rd: int) -> list[dict]:
    rows = [
        r for r in store.reviews.values()
        if r["manuscript_id"] == mid and r["revision_round"] == rd and r["status"] == "SUBMITTED"
    ]
    rows.sort(key=lambda r: r["submitted_at"] or "")
    return rows


@decisions_bp.route("/manuscripts/<mid>/decisions", methods=["POST"])
@require_auth(["AssociateEditor"])
def create_decision(mid: str):
    body = get_json_body()
    rec = require_str(body, "recommendation_from_associate")
    if rec not in _REC_VALUES:
        raise api_error("ERR_VALIDATION", "recommendation_from_associate invalid")
    with store.lock:
        m = store.manuscripts.get(mid)
        if not m:
            raise api_error("ERR_NOT_FOUND", "Manuscript not found")
        if g.user_id != m.get("associate_editor_id"):
            raise api_error("ERR_FORBIDDEN", "Caller is not the assigned associate editor")
        if m["status"] != "UNDER_REVIEW":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in UNDER_REVIEW state")
        decision = {
            "manuscript_id": mid,
            "revision_round": m["revision_round"],
            "recommendation_from_associate": rec,
            "aggregate_score": None,
            "aggregated_category": None,
            "final_decision": None,
            "decision_letter_body": None,
            "compiled_reviewer_comments": None,
            "status": "DRAFT",
            "finalized_at": None,
        }
        store.stamp_create(decision)
        store.editor_decisions[decision["id"]] = decision
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="EditorDecision", entity_id=decision["id"],
            action="DECISION_CREATED", from_state=None, to_state="DRAFT",
        )
        return success_envelope(decision, status=201, response_type="object")


def _resolve_decision(mid: str, did: str) -> tuple[dict, dict]:
    m = store.manuscripts.get(mid)
    if not m:
        raise api_error("ERR_NOT_FOUND", "Manuscript not found")
    d = store.editor_decisions.get(did)
    if not d or d["manuscript_id"] != mid:
        raise api_error("ERR_NOT_FOUND", "Decision not found")
    return m, d


@decisions_bp.route("/manuscripts/<mid>/decisions/<did>/recommend", methods=["POST"])
@require_auth(["AssociateEditor"])
def recommend_decision(mid: str, did: str):
    body = get_json_body()
    with store.lock:
        m, d = _resolve_decision(mid, did)
        if g.user_id != m.get("associate_editor_id"):
            raise api_error("ERR_FORBIDDEN", "Caller is not the assigned associate editor")
        if d["status"] != "DRAFT":
            raise api_error("ERR_INVALID_STATE", "Decision not in DRAFT state")
        check_version(body, d)
        submitted = _submitted_reviews_sorted(mid, m["revision_round"])
        if len(submitted) < 2:
            raise api_error("ERR_INSUFFICIENT_REVIEWS",
                            "At least two submitted reviews required at current revision_round")
        # Aggregations
        recs = [r["recommendation"] for r in submitted]
        cat = aggregated_category(recs, d["recommendation_from_associate"])
        score = aggregate_score([{"rating": r["rating"], "recommendation": r["recommendation"]} for r in submitted])
        compiled = "\n\n".join((r.get("comments_to_author") or "") for r in submitted)
        d["aggregated_category"] = cat
        d["aggregate_score"] = _decimal_to_float(score)
        d["compiled_reviewer_comments"] = compiled
        prev = d["status"]
        d["status"] = "RECOMMENDED"
        store.stamp_update(d)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="EditorDecision", entity_id=d["id"],
            action="DECISION_RECOMMENDED", from_state=prev, to_state="RECOMMENDED",
            details={"aggregate_score": _decimal_to_float(score), "aggregated_category": cat},
        )
        return success_envelope(d, status=200, response_type="object")


def _decimal_to_float(v: Decimal) -> float:
    """Quantise to two decimals and return as float for JSON serialisation.

    Using float here is safe because Decimal has already done round_half_up to
    two decimal places; round-trip via str avoids IEEE 754 surprises.
    """
    return float(str(v))


@decisions_bp.route("/manuscripts/<mid>/decisions/<did>/finalize", methods=["POST"])
@require_auth(["EditorInChief"])
def finalize_decision(mid: str, did: str):
    body = get_json_body()
    final_decision = require_str(body, "final_decision")
    decision_letter_body = require_str(body, "decision_letter_body")
    if final_decision not in _REC_VALUES:
        raise api_error("ERR_VALIDATION", "final_decision invalid")
    with store.lock:
        m, d = _resolve_decision(mid, did)
        if d["status"] != "RECOMMENDED":
            raise api_error("ERR_INVALID_STATE", "Decision not in RECOMMENDED state")
        check_version(body, d)
        # Round-match check
        if d["revision_round"] != m["revision_round"]:
            raise api_error("ERR_REVIEW_ROUND_MISMATCH",
                            "EditorDecision.revision_round != Manuscript.revision_round")
        # Manuscript must still be in UNDER_REVIEW
        if m["status"] != "UNDER_REVIEW":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in UNDER_REVIEW state")
        # Still need at least two submitted reviews
        submitted = _submitted_reviews_sorted(mid, m["revision_round"])
        if len(submitted) < 2:
            raise api_error("ERR_INSUFFICIENT_REVIEWS",
                            "Need at least two submitted reviews to finalize")

        # Apply transitions
        prev_d = d["status"]
        prev_m = m["status"]
        d["final_decision"] = final_decision
        d["decision_letter_body"] = decision_letter_body
        d["status"] = "FINALIZED"
        d["finalized_at"] = fmt_ts(clock.now())
        store.stamp_update(d)

        new_ms_state = None
        if final_decision == "ACCEPT":
            new_ms_state = "ACCEPTED"
        elif final_decision == "REJECT":
            new_ms_state = "REJECTED"
        elif final_decision in ("MINOR_REVISION", "MAJOR_REVISION"):
            new_ms_state = "REVISION_REQUIRED"
            days = MINOR_DAYS if final_decision == "MINOR_REVISION" else MAJOR_DAYS
            m["revision_deadline_at"] = fmt_ts(clock.now() + timedelta(days=days))
        elif final_decision == "TRANSFER":
            # Treat TRANSFER like a soft reject for manuscript lifecycle: transition to REJECTED
            # The PRD/scaffold does not explicitly assign a manuscript state for TRANSFER, but
            # it appears alongside REJECT in finalize signature. Use REJECTED to keep
            # the manuscript out of UNDER_REVIEW per finalize semantics.
            new_ms_state = "REJECTED"
        else:  # pragma: no cover
            raise api_error("ERR_VALIDATION", "Unsupported final_decision")

        m["status"] = new_ms_state
        store.stamp_update(m)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="EditorDecision", entity_id=d["id"],
            action="DECISION_FINALIZED", from_state=prev_d, to_state="FINALIZED",
            details={"final_decision": final_decision},
        )
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="Manuscript", entity_id=m["id"],
            action=_ms_action_for_final(final_decision),
            from_state=prev_m, to_state=new_ms_state,
        )
        return success_envelope(d, status=200, response_type="object")


def _ms_action_for_final(final_decision: str) -> str:
    return {
        "ACCEPT": "ACCEPTED",
        "REJECT": "REJECTED",
        "TRANSFER": "TRANSFERRED",
        "MINOR_REVISION": "REVISION_REQUESTED",
        "MAJOR_REVISION": "REVISION_REQUESTED",
    }[final_decision]
