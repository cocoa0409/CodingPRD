"""Test-only reset endpoint — wipes the in-memory store between tests.

Not part of the PRD-defined API surface; exists solely to support
per-test isolation in the benchmark's test conftest, which posts to
POST /__test__/reset between tests.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..store import reset_store

bp = Blueprint("test_reset", __name__)


@bp.post("/__test__/reset")
def reset():
    reset_store()
    return jsonify({"ok": True}), 200
