"""ExamAttempt endpoints."""
from __future__ import annotations

from typing import Any

from flask import Flask, g

from ..auth import require_auth
from ..clock import format_iso, now_dt
from ..errors import ApiError
from ..store import bump_version, common_fields_append_only, get_store, now_iso
from ..services.calculations import compute_exam_score, compute_final_credit
from ..services.lookups import get_exam_attempt
from ..services.serializers import serialize_exam_attempt
from ..services.sessions import get_pinned_snapshot
from ._helpers import created, get_json_body, ok, with_lock


# Default question bank (5 questions, weight 1) — server-composed
DEFAULT_QUESTION_BANK = [
    {"question_id": "q1", "weight": 1, "correct_answer": "A"},
    {"question_id": "q2", "weight": 1, "correct_answer": "B"},
    {"question_id": "q3", "weight": 1, "correct_answer": "C"},
    {"question_id": "q4", "weight": 1, "correct_answer": "D"},
    {"question_id": "q5", "weight": 1, "correct_answer": "A"},
]


def register(app: Flask) -> None:
    @app.post("/training/exam-attempts")
    @require_auth("Trainee")
    @with_lock
    def create_exam_attempt():
        body = get_json_body()
        enrollment_id = body.get("enrollment_id")
        if not enrollment_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "enrollment_id required.", http_status=422)
        store = get_store()
        e = store.enrollments.get(enrollment_id)
        if not e:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Enrollment not found.")
        if e["trainee_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Trainee may only create exam for own enrollment.")
        # Compose questions
        questions: list[dict[str, Any]] = []
        for q in DEFAULT_QUESTION_BANK:
            questions.append({**q, "given_answer": None})
        total_weight = sum(int(q["weight"]) for q in questions)
        base = common_fields_append_only()
        row = {
            **base,
            "enrollment_id": enrollment_id,
            "questions": questions,
            "total_weight": total_weight,
            "score": 0,
            "passed": False,
            "submitted_at": None,
        }
        store.exam_attempts[base["id"]] = row
        return created(serialize_exam_attempt(row))

    @app.post("/training/exam-attempts/<aid>/submit")
    @require_auth("Trainee")
    @with_lock
    def submit_exam_attempt(aid):
        a = get_exam_attempt(aid)
        store = get_store()
        # ownership
        e = store.enrollments.get(a["enrollment_id"])
        if not e or e["trainee_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Cannot submit another trainee's exam.")
        if a.get("submitted_at"):
            raise ApiError("ERR_INVALID_STATE", "Already submitted.")
        body = get_json_body()
        answers = body.get("answers")
        # PRD §3.5: "accepts a single body field answers and requires
        # that this payload include an answer for every question in
        # questions". PRD does not pin the shape of answers; accept
        # either an object keyed by question_id, or a list of
        # {question_id, given_answer} entries.
        questions = a["questions"]
        answer_map: dict[str, Any] = {}
        if isinstance(answers, dict):
            answer_map = dict(answers)
        elif isinstance(answers, list):
            for entry in answers:
                if not isinstance(entry, dict):
                    raise ApiError("ERR_INCOMPLETE_EXAM", "answers entries must be objects.")
                qid = entry.get("question_id")
                if qid is None:
                    raise ApiError("ERR_INCOMPLETE_EXAM", "answers entries must carry question_id.")
                answer_map[qid] = entry.get("given_answer")
        else:
            raise ApiError("ERR_INCOMPLETE_EXAM", "answers must be an object or list.")
        missing = [q for q in questions if answer_map.get(q["question_id"]) is None]
        if missing:
            raise ApiError("ERR_INCOMPLETE_EXAM", "Missing answers for some questions.")
        for q in questions:
            q["given_answer"] = answer_map.get(q["question_id"])
        score, passed, _ = compute_exam_score(questions)
        a["score"] = score
        a["passed"] = passed
        a["submitted_at"] = now_iso()

        # If parent session already COMPLETED, recompute Enrollment.final_credit
        sess = store.sessions.get(e["session_id"])
        if sess and sess["status"] == "COMPLETED":
            snapshot = get_pinned_snapshot(sess)
            cv = float(snapshot.get("credit_value") or 0)
            e["final_credit"] = compute_final_credit(cv, e.get("attendance_status") or "NOT_RECORDED", a)
            # Re-derive status: if exam failed and attendance present/partial -> FAILED
            if e["status"] in ("COMPLETED", "FAILED"):
                if not passed and e.get("attendance_status") in ("PRESENT", "PARTIAL"):
                    e["status"] = "FAILED"
                elif passed and e.get("attendance_status") in ("PRESENT", "PARTIAL"):
                    e["status"] = "COMPLETED"
            bump_version(e)
            # recompute pools
            from ..services.calculations import recompute_credit_pool_accumulated
            for pool in store.credit_pools.values():
                if pool["trainee_id"] == e["trainee_id"]:
                    recompute_credit_pool_accumulated(pool)
                    bump_version(pool)

        return ok(serialize_exam_attempt(a))
