from flask import Blueprint, g, request

from db import new_id, store
from errors import err
from middleware import require_roles
from response import success
from services.common import emit_audit, serialize_segment, stamp_create, touch
from services.project_state import (re_evaluate_assignment_completion,
                                     re_evaluate_project_state)
from services.workload import recompute_workload

bp = Blueprint("segments", __name__)


def _find_assignment_for_segment(segment_id: str, role: str, translator_id: str):
    """Return the ACCEPTED assignment of this role covering the segment, owned by this translator."""
    for a in store.assignments.values():
        if a["state"] != "ACCEPTED":
            continue
        if a["role"] != role:
            continue
        if a["translator_id"] != translator_id:
            continue
        if segment_id in a["segment_ids"]:
            return a
    return None


@bp.get("/segments/<id>")
@require_roles("ProjectManager", "Translator")
def get_segment(id):
    s = store.segments.get(id)
    if not s:
        raise err("ERR_NOT_FOUND", "segment not found")
    return success(serialize_segment(s))


@bp.post("/segments/<id>/submit-translation")
@require_roles("Translator")
def submit_translation(id):
    s = store.segments.get(id)
    if not s:
        raise err("ERR_NOT_FOUND", "segment not found")
    body = request.get_json(silent=True) or {}
    text = body.get("translated_text")
    if not isinstance(text, str) or not text:
        raise err("ERR_VALIDATION_FAILED", "translated_text required and non-empty.")
    if s["state"] != "ASSIGNED":
        raise err("ERR_INVALID_SEGMENT_STATE", "segment not in ASSIGNED.")
    a = _find_assignment_for_segment(id, "TRANSLATOR", g.user_id)
    if a is None:
        raise err("ERR_INVALID_SEGMENT_STATE", "no ACCEPTED TRANSLATOR assignment for this caller.")

    prev = s["state"]
    s["translated_text"] = text
    s["state"] = "TRANSLATED"
    touch(s)
    emit_audit(
        subject_type="Segment",
        subject_id=s["id"],
        event="STATE_TRANSITION",
        from_state=prev,
        to_state="TRANSLATED",
        actor_role="Translator",
        actor_id=g.user_id,
        payload={"assignment_id": a["id"]},
    )

    recompute_workload(g.user_id)
    re_evaluate_assignment_completion(a["id"])
    re_evaluate_project_state(s["project_id"])
    return success(serialize_segment(s))


@bp.post("/segments/<id>/submit-review")
@require_roles("Translator")
def submit_review(id):
    s = store.segments.get(id)
    if not s:
        raise err("ERR_NOT_FOUND", "segment not found")
    body = request.get_json(silent=True) or {}
    text = body.get("reviewed_text")
    if not isinstance(text, str) or not text:
        raise err("ERR_VALIDATION_FAILED", "reviewed_text required and non-empty.")
    if s["state"] != "TRANSLATED":
        raise err("ERR_INVALID_SEGMENT_STATE", "segment not in TRANSLATED.")
    a = _find_assignment_for_segment(id, "REVIEWER", g.user_id)
    if a is None:
        raise err("ERR_INVALID_SEGMENT_STATE", "no ACCEPTED REVIEWER assignment for this caller.")

    prev = s["state"]
    s["reviewed_text"] = text
    s["state"] = "REVIEWED"
    touch(s)
    emit_audit(
        subject_type="Segment",
        subject_id=s["id"],
        event="STATE_TRANSITION",
        from_state=prev,
        to_state="REVIEWED",
        actor_role="Translator",
        actor_id=g.user_id,
        payload={"assignment_id": a["id"]},
    )
    re_evaluate_assignment_completion(a["id"])
    re_evaluate_project_state(s["project_id"])
    return success(serialize_segment(s))


@bp.post("/segments/<id>/final-approve")
@require_roles("Translator")
def final_approve(id):
    s = store.segments.get(id)
    if not s:
        raise err("ERR_NOT_FOUND", "segment not found")
    if s["state"] != "REVIEWED":
        raise err("ERR_INVALID_SEGMENT_STATE", "segment not in REVIEWED.")
    a = _find_assignment_for_segment(id, "FINAL_REVIEWER", g.user_id)
    if a is None:
        raise err("ERR_INVALID_SEGMENT_STATE", "no ACCEPTED FINAL_REVIEWER assignment for this caller.")
    # Project-scoped terminology must have no CONFLICT
    from services.terminology import project_has_open_terminology_conflict
    if project_has_open_terminology_conflict(s["project_id"]):
        raise err("ERR_INVALID_SEGMENT_STATE", "project terminology conflicts unresolved.")

    prev = s["state"]
    s["state"] = "FINAL_APPROVED"
    touch(s)
    emit_audit(
        subject_type="Segment",
        subject_id=s["id"],
        event="STATE_TRANSITION",
        from_state=prev,
        to_state="FINAL_APPROVED",
        actor_role="Translator",
        actor_id=g.user_id,
        payload={"assignment_id": a["id"]},
    )
    re_evaluate_assignment_completion(a["id"])
    re_evaluate_project_state(s["project_id"])
    return success(serialize_segment(s))


@bp.post("/segments/<id>/reject")
@require_roles("Translator")
def reject_segment(id):
    s = store.segments.get(id)
    if not s:
        raise err("ERR_NOT_FOUND", "segment not found")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise err("ERR_VALIDATION_FAILED", "reason required.")
    errors_list = body.get("errors")

    # Branch on segment state to determine which rejection path applies.
    if s["state"] == "TRANSLATED":
        # Reviewer rejection: TRANSLATED -> NEW
        a = _find_assignment_for_segment(id, "REVIEWER", g.user_id)
        if a is None:
            raise err("ERR_INVALID_SEGMENT_STATE", "no ACCEPTED REVIEWER assignment for this caller.")
        original_translator = None
        if s.get("assignment_id"):
            orig_a = store.assignments.get(s["assignment_id"])
            if orig_a:
                original_translator = orig_a["translator_id"]
        prev = s["state"]
        s["state"] = "NEW"
        s["assignment_id"] = None
        touch(s)
        emit_audit(
            subject_type="Segment",
            subject_id=s["id"],
            event="STATE_TRANSITION",
            from_state=prev,
            to_state="NEW",
            actor_role="Translator",
            actor_id=g.user_id,
            payload={"reason": reason, "rejected_by": "REVIEWER"},
        )
        if original_translator:
            recompute_workload(original_translator)
        re_evaluate_project_state(s["project_id"])
        return success(serialize_segment(s))

    if s["state"] == "REVIEWED":
        # Final reviewer rejection: REVIEWED -> TRANSLATED
        a = _find_assignment_for_segment(id, "FINAL_REVIEWER", g.user_id)
        if a is None:
            raise err("ERR_INVALID_SEGMENT_STATE", "no ACCEPTED FINAL_REVIEWER assignment for this caller.")
        prev = s["state"]
        s["state"] = "TRANSLATED"
        touch(s)
        emit_audit(
            subject_type="Segment",
            subject_id=s["id"],
            event="STATE_TRANSITION",
            from_state=prev,
            to_state="TRANSLATED",
            actor_role="Translator",
            actor_id=g.user_id,
            payload={"reason": reason, "rejected_by": "FINAL_REVIEWER"},
        )
        # If errors[] supplied, create DRAFT QualityScore
        if isinstance(errors_list, list) and errors_list:
            from services.validation import ERR_CATS, SEVERITIES
            # Validate errors shape
            for e in errors_list:
                if not isinstance(e, dict):
                    raise err("ERR_VALIDATION_FAILED", "errors[] entry must be an object.")
                if e.get("category") not in ERR_CATS:
                    raise err("ERR_VALIDATION_FAILED", "error category invalid.")
                if e.get("severity") not in SEVERITIES:
                    raise err("ERR_VALIDATION_FAILED", "error severity invalid.")
                cnt = e.get("count")
                if not isinstance(cnt, int) or isinstance(cnt, bool) or cnt < 1:
                    raise err("ERR_VALIDATION_FAILED", "error count must be >= 1.")
            # Translator credit for the underlying segment
            from services.pricing import compute_translator_credit
            translator_id = compute_translator_credit(s["id"])
            q = {
                "segment_id": s["id"],
                "translator_id": translator_id,
                "errors": list(errors_list),
                "error_density": 0.00,
                "score": 100.00,
                "state": "DRAFT",
            }
            stamp_create(q)
            store.quality_scores[q["id"]] = q
        re_evaluate_project_state(s["project_id"])
        return success(serialize_segment(s))

    raise err("ERR_INVALID_SEGMENT_STATE", "segment not in a rejectable state.")
