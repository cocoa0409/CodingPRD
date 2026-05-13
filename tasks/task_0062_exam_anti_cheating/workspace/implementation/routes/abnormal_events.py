"""AbnormalEvent endpoints: record + list."""
from flask import Blueprint, g

import db
from clock import now_unix
from errors import err
from middleware import require_auth, get_json_body, get_pagination
from response import success, success_list
from services import cascade
from services.audit import append_audit
from services.severity import (
    compute_severity, should_force_recheck, should_cascade_disqualify,
)


bp = Blueprint("abnormal_events", __name__)


VALID_CHANNELS = {"SCREEN", "CAMERA", "AUDIO", "PROCESS", "NETWORK"}
VALID_RULES = {"FACE_LEAVE", "MULTI_PERSON", "WINDOW_SWITCH", "EXTERNAL_DEVICE"}
VALID_MODES = {"REALTIME_ALERT", "AFTER_THE_FACT"}


def _view(e: dict) -> dict:
    return db.public(e)


def _require_exam(exam_id):
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    return exam


def _require_attempt(exam_id, attempt_id):
    _require_exam(exam_id)
    a = db.attempts.get(attempt_id)
    if a is None or a.get("exam_id") != exam_id:
        raise err("ERR_ATTEMPT_NOT_FOUND", "attempt not found")
    return a


@bp.post("/exams/<exam_id>/attempts/<attempt_id>/abnormal-events")
@require_auth(roles={"Proctor"})
def record_event(exam_id, attempt_id):
    exam = _require_exam(exam_id)
    attempt = _require_attempt(exam_id, attempt_id)
    body = get_json_body()

    detected_at = body.get("detected_at")
    channel = body.get("monitoring_channel")
    rule = body.get("behavior_rule_code")
    mode = body.get("marking_mode")
    evidence = body.get("evidence_clip_uri")

    if not isinstance(detected_at, int) or isinstance(detected_at, bool):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "detected_at must be integer unix seconds")
    if channel not in VALID_CHANNELS:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"invalid monitoring_channel {channel!r}")
    if rule not in VALID_RULES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"invalid behavior_rule_code {rule!r}")
    if mode not in VALID_MODES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"invalid marking_mode {mode!r}")

    # Compute severity first to apply the evidence requirement.
    bucket, score = compute_severity(rule, channel, mode)
    if bucket != "INFO":
        if not isinstance(evidence, str) or not evidence:
            raise err("ERR_EVIDENCE_REQUIRED",
                      "evidence_clip_uri required for severity != INFO")

    # Clamp detected_at into the attempt's ACTIVE interval if the attempt has
    # started_at; (PRD §3.4 says server clamps).
    started = attempt.get("started_at")
    end_time = int(exam.get("end_time", 0))
    if started is not None:
        if detected_at < int(started):
            detected_at = int(started)
        if end_time and detected_at > end_time:
            detected_at = end_time

    force_recheck = should_force_recheck(rule, bucket, attempt.get("status"))
    should_disq = should_cascade_disqualify(rule, bucket, attempt.get("status"))

    ev = {
        "attempt_id": attempt_id,
        "detected_at": int(detected_at),
        "monitoring_channel": channel,
        "behavior_rule_code": rule,
        "severity": bucket,
        "severity_score": score,
        "marking_mode": mode,
        "evidence_clip_uri": evidence,
        "forced_recheck_emitted": bool(force_recheck),
    }
    db.stamp_create(ev, common_fields=False)
    db.abnormal_events[ev["id"]] = ev

    # Always emit an audit for the event creation (per scaffold action_code list).
    append_audit(
        subject_type="ABNORMAL_EVENT",
        subject_id=ev["id"],
        actor_role="Proctor",
        actor_id=g.user_id,
        action_code="ABNORMAL_EVENT_RECORDED",
        delta={
            "before": {},
            "after": {"severity": bucket, "severity_score": score,
                      "behavior_rule_code": rule},
        },
    )

    # Cascade disqualification (and score-zeroing) when applicable. The event
    # row is preserved regardless; only the cascade is idempotent on second
    # CRITICAL events against an already-DISQUALIFIED attempt.
    if should_disq:
        if attempt.get("status") == "ACTIVE":
            cascade.disqualify_attempt(
                attempt,
                actor_role="Proctor",
                actor_id=g.user_id,
                action_code="SCORE_ADJUSTED",
            )
        # If attempt no longer ACTIVE → cascade no-op; event persisted.

    return success(_view(ev), 201)


@bp.get("/exams/<exam_id>/attempts/<attempt_id>/abnormal-events")
@require_auth(roles={"Proctor", "ExamAdmin"})
def list_events(exam_id, attempt_id):
    _require_attempt(exam_id, attempt_id)
    limit, offset = get_pagination()
    rows = sorted(
        [e for e in db.abnormal_events.values() if e.get("attempt_id") == attempt_id],
        key=lambda e: e["_seq"],
    )
    total = len(rows)
    page = [_view(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit, offset, total)
