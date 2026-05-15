"""EvaluationSurvey endpoints."""
from __future__ import annotations

from flask import Flask, g

from ..auth import require_auth
from ..errors import ApiError
from ..store import common_fields_append_only, get_store
from ..services.calculations import compute_evaluation_aggregate, recompute_instructor_avg_eval
from ..services.serializers import serialize_evaluation
from ._helpers import created, get_json_body, with_lock


def register(app: Flask) -> None:
    @app.post("/training/evaluations")
    @require_auth("Trainee")
    @with_lock
    def create_evaluation():
        body = get_json_body()
        enrollment_id = body.get("enrollment_id")
        try:
            cs = int(body.get("content_score"))
            iss = int(body.get("instructor_score"))
            ls = int(body.get("logistics_score"))
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "scores must be integers.", http_status=422)
        for v in (cs, iss, ls):
            if not (1 <= v <= 5):
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "scores must be in 1..5.", http_status=422)

        if not enrollment_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "enrollment_id required.", http_status=422)
        store = get_store()
        e = store.enrollments.get(enrollment_id)
        if not e:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Enrollment not found.")
        if e["trainee_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Trainee may only evaluate own enrollment.")

        agg = compute_evaluation_aggregate(cs, iss, ls)
        base = common_fields_append_only()
        row = {
            **base,
            "enrollment_id": enrollment_id,
            "content_score": cs,
            "instructor_score": iss,
            "logistics_score": ls,
            "aggregate_score": agg,
        }
        store.evaluations[base["id"]] = row

        # Recompute instructor avg
        sess = store.sessions.get(e["session_id"])
        if sess:
            recompute_instructor_avg_eval(sess["instructor_id"])

        return created(serialize_evaluation(row))
