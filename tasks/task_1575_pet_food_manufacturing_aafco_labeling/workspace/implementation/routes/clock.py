"""Logical clock endpoint."""

from flask import Blueprint

import errors
from db import store, parse_iso, iso_format
from middleware import require_roles, get_json_body, require_field
from response import success_object
from services.calculations import (touch, compute_brand_complaint_score)

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_json_body()
    to = require_field(body, "to_iso8601")
    dt = parse_iso(to)
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    store.advance_clock(dt)
    _run_expiry_sweep()
    _recompute_windowed_scores()
    return success_object({"current_utc": iso_format(store.now())}, 200)


def _recompute_windowed_scores():
    """Re-evaluate windowed complaint-risk rollups against the new clock reading
    (PRD §2.5): the trailing 90-day rollup window and the 30-day post-closure
    decay both key off the logical clock, so advancing it refreshes each brand's
    complaint_score."""
    for brand in store.brand_owners.values():
        new_score = compute_brand_complaint_score(brand["id"])
        if new_score != brand.get("complaint_score"):
            brand["complaint_score"] = new_score
            touch(brand)


def _run_expiry_sweep():
    """Move APPROVED registrations past their annual expiry to EXPIRED.

    Annual expiry: 1 year after decided_at (approval timestamp).
    """
    now = store.now()
    for reg in store.state_registrations.values():
        if reg["status"] != "APPROVED":
            continue
        decided_dt = reg.get("_decided_at_dt")
        if decided_dt is None:
            continue
        # Annual expiry: one calendar year after approval
        try:
            expiry = decided_dt.replace(year=decided_dt.year + 1)
        except ValueError:
            # Feb 29 edge
            expiry = decided_dt.replace(year=decided_dt.year + 1, day=28)
        if now >= expiry:
            reg["status"] = "EXPIRED"
            touch(reg, status_changed=True)
