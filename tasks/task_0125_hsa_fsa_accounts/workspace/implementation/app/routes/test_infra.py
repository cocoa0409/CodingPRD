"""Test-only convenience endpoint.

The benchmark harness calls POST /__test__/reset between tests to wipe
in-memory state. We accept it for any caller (auth not required) so the
harness can reset cleanly even if it doesn't supply role headers.

This endpoint is harness infrastructure, NOT a PRD-required surface.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..responses import build_success_envelope
from ..store import store

bp = Blueprint("test_infra", __name__)


@bp.post("/__test__/reset")
def reset():
    store.reset()
    return jsonify(build_success_envelope({"reset": True})), 200
