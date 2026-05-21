"""Test-only reset endpoint.

Wipes the in-memory store and resets the server clock to its initial
epoch so each pytest function starts from a clean slate. Restricted to
the TestDriver role.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..store import reset_store, store
from ..util import format_iso8601

bp = Blueprint("test_reset", __name__)


@bp.route("/__test__/reset", methods=["POST"])
@require_roles(["TestDriver"])
def test_reset():
    reset_store()
    s = store()
    return jsonify(success_object({"now": format_iso8601(s.now())})), 200
