"""StateRule and FplSchedule configuration endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from common import (
    stamp_create, touch, serialize,
    require_str, require_bool, require_int, optional_bool, optional_int, optional_enum,
    get_or_404,
)
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import authenticate, get_json_body
from response import ok_object

bp = Blueprint("config", __name__)


# --- StateRule --------------------------------------------------------------

@bp.post("/state-rules")
def create_state_rule():
    authenticate(["CaseWorker"])
    body = get_json_body()

    state_code = require_str(body, "state_code")
    if len(state_code) != 2 or not state_code.isupper():
        raise APIError(ERR_INVALID_REQUEST, 422, "state_code must be two uppercase letters")

    rec = {
        "state_code": state_code,
        "is_expansion_state": require_bool(body, "is_expansion_state"),
        "magi_adult_threshold_pct": require_int(body, "magi_adult_threshold_pct", non_negative=True),
        "magi_child_threshold_pct": require_int(body, "magi_child_threshold_pct", non_negative=True),
        "abd_asset_limit_cents": require_int(body, "abd_asset_limit_cents", non_negative=True),
        "standard_asset_limit_cents": require_int(body, "standard_asset_limit_cents", non_negative=True),
        "continuous_coverage_active": optional_bool(body, "continuous_coverage_active", False),
    }
    stamp_create(rec)
    db.state_rules[state_code] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/state-rules/<state_code>")
def get_state_rule(state_code):
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    rec = get_or_404(db.state_rules, state_code, "StateRule")
    return ok_object(serialize(rec), 200)


@bp.patch("/state-rules/<state_code>")
def update_state_rule(state_code):
    authenticate(["CaseWorker"])
    rec = get_or_404(db.state_rules, state_code, "StateRule")
    body = get_json_body()

    if "is_expansion_state" in body:
        rec["is_expansion_state"] = require_bool(body, "is_expansion_state")
    if "magi_adult_threshold_pct" in body:
        rec["magi_adult_threshold_pct"] = require_int(body, "magi_adult_threshold_pct", non_negative=True)
    if "magi_child_threshold_pct" in body:
        rec["magi_child_threshold_pct"] = require_int(body, "magi_child_threshold_pct", non_negative=True)
    if "abd_asset_limit_cents" in body:
        rec["abd_asset_limit_cents"] = require_int(body, "abd_asset_limit_cents", non_negative=True)
    if "standard_asset_limit_cents" in body:
        rec["standard_asset_limit_cents"] = require_int(body, "standard_asset_limit_cents", non_negative=True)
    if "continuous_coverage_active" in body:
        rec["continuous_coverage_active"] = require_bool(body, "continuous_coverage_active")

    touch(rec)
    return ok_object(serialize(rec), 200)


# --- FplSchedule (immutable; only id + created_at) --------------------------

@bp.post("/fpl-schedules")
def create_fpl_schedule():
    authenticate(["CaseWorker"])
    body = get_json_body()

    rec = {
        "year": require_int(body, "year"),
        "base_annual_cents": require_int(body, "base_annual_cents", non_negative=True),
        "per_member_increment_cents": require_int(body, "per_member_increment_cents", non_negative=True),
    }
    stamp_create(rec, versioned=False)
    db.fpl_schedules[rec["id"]] = rec
    db.fpl_by_year[rec["year"]] = rec["id"]
    return ok_object(serialize(rec), 201)
