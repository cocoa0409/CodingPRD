"""Deterministic-clock routes (test affordances)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_roles
from ..clock import clock, iso_format, now
from ..helpers import parse_iso8601, require_json_object
from ..responses import ok
from ..services.cascades import expire_due_licenses_and_cascade
from ..store import store

bp = Blueprint("clock", __name__, url_prefix="/practice/_clock")


@bp.get("")
@require_roles("PracticeAdmin", "Therapist", "Supervisor", "BillingClerk")
def read_clock(**_):
    return ok({"now": iso_format(now())})


@bp.post("/advance")
@require_roles("PracticeAdmin")
def advance_clock(**_):
    body = require_json_object()
    target = parse_iso8601(body.get("to"), "to")
    clock.advance_to(target)
    # After advancing, fire any deferred automatic transitions.
    s = store()
    with s.lock:
        expire_due_licenses_and_cascade(s)
    return ok({"now": iso_format(now())})
