"""Test-only convenience endpoint.

The benchmark harness calls POST /__test__/reset between tests to wipe
in-memory state. We accept it for any caller (auth not required) so the
harness can reset cleanly even if it doesn't supply role headers.
"""
from __future__ import annotations

from flask import Blueprint

from ..responses import ok
from ..store import reset_store

bp = Blueprint("test_infra", __name__)


@bp.post("/__test__/reset")
def reset(**_kw):
    reset_store()
    return ok({"reset": True})
