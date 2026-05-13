from flask import Blueprint, g, request

from clock import clock
from db import store
from errors import err
from middleware import require_roles
from response import success
from services.common import emit_audit, serialize_quality_score, stamp_create, touch
from services.pricing import compute_translator_credit
from services.quality import (compute_error_density, compute_score, refresh_translator_rating)
from services.validation import ERR_CATS, SEVERITIES

bp = Blueprint("quality_scores", __name__)


def _validate_errors(errors):
    if not isinstance(errors, list):
        raise err("ERR_VALIDATION_FAILED", "errors must be a list.")
    for e in errors:
        if not isinstance(e, dict):
            raise err("ERR_VALIDATION_FAILED", "error entry must be object.")
        if e.get("category") not in ERR_CATS:
            raise err("ERR_VALIDATION_FAILED", "error category invalid.")
        if e.get("severity") not in SEVERITIES:
            raise err("ERR_VALIDATION_FAILED", "error severity invalid.")
        cnt = e.get("count")
        if not isinstance(cnt, int) or isinstance(cnt, bool) or cnt < 1:
            raise err("ERR_VALIDATION_FAILED", "error count must be >= 1.")


@bp.post("/quality-scores")
@require_roles("Translator", "ProjectManager")
def create_quality_score():
    body = request.get_json(silent=True) or {}
    segment_id = body.get("segment_id")
    if not isinstance(segment_id, str):
        raise err("ERR_VALIDATION_FAILED", "segment_id required.")
    seg = store.segments.get(segment_id)
    if seg is None:
        raise err("ERR_NOT_FOUND", "segment not found")
    errors_list = body.get("errors", [])
    _validate_errors(errors_list)
    translator_id = compute_translator_credit(segment_id)
    q = {
        "segment_id": segment_id,
        "translator_id": translator_id,
        "errors": list(errors_list),
        "error_density": 0.00,
        "score": 100.00,
        "state": "DRAFT",
    }
    stamp_create(q)
    store.quality_scores[q["id"]] = q
    return success(serialize_quality_score(q), status=201)


@bp.post("/quality-scores/<id>/finalize")
@require_roles("Translator")
def finalize_quality_score(id):
    q = store.quality_scores.get(id)
    if not q:
        raise err("ERR_NOT_FOUND", "quality score not found")
    if q["state"] == "FINALIZED":
        raise err("ERR_QUALITY_SCORE_ALREADY_FINALIZED", "score already finalized.")
    if q["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "score not in DRAFT.")
    seg = store.segments.get(q["segment_id"])
    if seg is None:
        raise err("ERR_NOT_FOUND", "underlying segment not found")
    if seg["state"] != "FINAL_APPROVED":
        raise err("ERR_INVALID_STATE", "underlying segment is not FINAL_APPROVED.")
    if not q.get("errors"):
        # Zero-error flag — only the body says explicit zero. PRD: "errors[] non-empty OR
        # caller explicitly sets zero-error flag". Accept zero errors as a flag here.
        body = request.get_json(silent=True) or {}
        if not body.get("zero_error_flag"):
            raise err("ERR_VALIDATION_FAILED", "errors required or zero_error_flag must be true.")

    # Compute
    density = compute_error_density(q.get("errors", []), seg["word_count"])
    score = compute_score(density)
    q["error_density"] = density
    q["score"] = score
    q["state"] = "FINALIZED"
    q["finalized_at"] = clock.now()
    touch(q)
    emit_audit(
        subject_type="QualityScore",
        subject_id=q["id"],
        event="QUALITY_SCORED",
        from_state="DRAFT",
        to_state="FINALIZED",
        actor_role="Translator",
        actor_id=g.user_id,
        payload={"score": score, "error_density": density, "errors": list(q.get("errors", []))},
    )
    if q.get("translator_id"):
        refresh_translator_rating(q["translator_id"])
    return success(serialize_quality_score(q))


@bp.post("/quality-scores/<id>/void")
@require_roles("ProjectManager")
def void_quality_score(id):
    q = store.quality_scores.get(id)
    if not q:
        raise err("ERR_NOT_FOUND", "quality score not found")
    if q["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "score not in DRAFT.")
    q["state"] = "VOIDED"
    touch(q)
    emit_audit(
        subject_type="QualityScore",
        subject_id=q["id"],
        event="STATE_TRANSITION",
        from_state="DRAFT",
        to_state="VOIDED",
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={},
    )
    return success(serialize_quality_score(q))
