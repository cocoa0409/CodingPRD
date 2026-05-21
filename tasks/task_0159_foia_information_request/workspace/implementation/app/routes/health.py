"""Public liveness probe."""

from flask import Blueprint, jsonify

from ..envelope import build_meta

health_bp = Blueprint("health", __name__)


@health_bp.get("/healthz")
def healthz():
    body = {
        "meta": build_meta(),
        "response_type": "object",
        "data": {"status": "ok"},
    }
    return jsonify(body), 200
