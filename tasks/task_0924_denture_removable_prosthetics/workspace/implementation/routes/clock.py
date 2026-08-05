"""The logical clock (PRD 2.6).

Nothing in this system reads the host machine's wall clock.  Before any caller
sets it the logical clock reads exactly 2026-05-01T00:00:00.000Z.
"""
from flask import Blueprint

import envelope
import guards
from store import db
from util import iso

bp = Blueprint("clock", __name__)


@bp.post("/prosthetics/_clock/set_current_utc")
@guards.endpoint(["PlatformAdmin"])
def set_current_utc(ctx):
    # rung 7 -- request schema (the caller-supplied instant is normalised into
    # the canonical rendering on the way in, exactly like every other instant).
    target = guards.require_instant(ctx, "to_iso8601")
    db.set_clock(target)
    return envelope.ok({"current_utc": iso(db.now())})
