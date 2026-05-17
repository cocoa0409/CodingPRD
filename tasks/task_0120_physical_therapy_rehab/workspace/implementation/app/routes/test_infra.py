"""Test-only driver endpoints: /_clock and /_clock/advance, plus /_health."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_BILLER, ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..clock import clock, iso_format, now
from ..helpers import parse_iso8601, require_json_object
from ..responses import ok
from ..services.sweeps import run_sweeps
from ..store import store

bp = Blueprint("test_infra", __name__)


@bp.route("/_health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


@bp.route("/_clock", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def get_clock(**_kwargs):
    return ok({"now": iso_format(now())})


@bp.route("/_clock/advance", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def advance_clock(**_kwargs):
    body = require_json_object()
    target = parse_iso8601(body.get("to"), "to")
    s = store()
    with s.lock:
        clock.advance_to(target)
        run_sweeps()
    return ok({"now": iso_format(now())})
