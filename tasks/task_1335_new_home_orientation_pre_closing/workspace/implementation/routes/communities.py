"""Community policy envelope + quality trend (PRD §3.1, §3.8)."""
import re

from flask import Blueprint

import db
from db import communities
from errors import err_not_found, err_validation
from logic import quality_trend
from middleware import ROLE_BUYER, ROLE_MANAGER, ROLE_REP, require_roles
from response import success_object
from validation import (
    json_body, opt_bool, opt_int, opt_number, req_str,
)

bp = Blueprint("communities", __name__)

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


@bp.post("/api/communities")
def create_community():
    require_roles(ROLE_MANAGER)
    body = json_body()
    name = req_str(body, "name")
    multiplier = opt_number(body, "holdback_cost_multiplier")
    min_cents = opt_int(body, "holdback_min_cents")
    max_cents = opt_int(body, "holdback_max_cents")
    min_days = opt_int(body, "orientation_min_days_before_closing")
    max_days = opt_int(body, "orientation_max_days_before_closing")
    duration = opt_int(body, "appointment_duration_minutes")
    buffer_minutes = opt_int(body, "appointment_buffer_minutes")
    survey_days = opt_int(body, "survey_window_days")
    photo_required = opt_bool(body, "cosmetic_photo_required")

    rec = db.stamp({
        "id": db.new_id(),
        "name": name,
        "holdback_cost_multiplier": 1.5 if multiplier is None else multiplier,
        "holdback_min_cents": 50000 if min_cents is None else min_cents,
        "holdback_max_cents": 1000000 if max_cents is None else max_cents,
        "orientation_min_days_before_closing": 5 if min_days is None else min_days,
        "orientation_max_days_before_closing": 30 if max_days is None else max_days,
        "appointment_duration_minutes": 120 if duration is None else duration,
        "appointment_buffer_minutes": 30 if buffer_minutes is None else buffer_minutes,
        "survey_window_days": 14 if survey_days is None else survey_days,
        "cosmetic_photo_required": True if photo_required is None else photo_required,
    })
    communities[rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.get("/api/communities/<community_id>/quality-trend")
def get_quality_trend(community_id):
    require_roles(ROLE_MANAGER, ROLE_REP, ROLE_BUYER)
    from flask import request
    raw = request.args.get("period_month")
    if raw is None:
        raise err_validation("Query parameter 'period_month' is required (YYYY-MM).")
    m = _PERIOD_RE.match(raw)
    if not m:
        raise err_validation("Query parameter 'period_month' must be YYYY-MM.")
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        raise err_validation("Query parameter 'period_month' must be YYYY-MM.")
    community = communities.get(community_id)
    if community is None:
        raise err_not_found("Community %s not found." % community_id)
    return success_object(quality_trend(community_id, year, month))
