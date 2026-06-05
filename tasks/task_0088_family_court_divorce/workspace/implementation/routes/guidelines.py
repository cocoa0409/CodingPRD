"""GuidelineSchedule endpoints (PRD §3.1). Immutable config: id + created_at only."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body, paginate_params, slice_page
from response import ok_object, ok_array
from services.common import serialize, serialize_list, sorted_by_creation, require

bp = Blueprint("guidelines", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]

# Default tuning parameters (PRD §3.1).
_PCT_DEFAULTS = {
    "spousal_payor_pct": 0.40,
    "spousal_payee_offset_pct": 0.50,
    "shared_custody_threshold_pct": 0.40,
}


def _validate_open_unit(value, name):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{name} must be a number")
    if not (0 < float(value) < 1):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{name} must be strictly between 0 and 1")


def _validate_tiers(tiers):
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "basic_obligation_tiers must be a non-empty array")
    for t in tiers:
        if not isinstance(t, dict):
            raise APIError(ERR_INVALID_REQUEST, 422, "each tier must be an object")
        for f in ("min_combined_monthly_cents", "max_combined_monthly_cents",
                  "base_cents_one_child"):
            if not isinstance(t.get(f), int) or isinstance(t.get(f), bool):
                raise APIError(ERR_INVALID_REQUEST, 422, f"tier.{f} must be an integer")
        m = t.get("marginal_pct_per_extra_child")
        if not isinstance(m, (int, float)) or isinstance(m, bool):
            raise APIError(ERR_INVALID_REQUEST, 422, "tier.marginal_pct_per_extra_child must be a number")


@bp.post("/api/guideline-schedules")
def create_guideline():
    require_auth(["Clerk"])()
    body = get_json_body()

    state_code = body.get("state_code")
    if not isinstance(state_code, str) or len(state_code) != 2 or not state_code.isupper():
        raise APIError(ERR_INVALID_REQUEST, 422, "state_code must be a 2-char uppercase string")
    # Uniqueness among schedules.
    for g in db.guideline_schedules.values():
        if g["state_code"] == state_code:
            raise APIError(ERR_INVALID_REQUEST, 422, "state_code already registered")

    tiers = body.get("basic_obligation_tiers")
    _validate_tiers(tiers)

    sched = {
        "state_code": state_code,
        "basic_obligation_tiers": tiers,
    }

    for name, default in _PCT_DEFAULTS.items():
        if name in body and body[name] is not None:
            _validate_open_unit(body[name], name)
            sched[name] = float(body[name])
        else:
            sched[name] = default

    if "long_marriage_months" in body and body["long_marriage_months"] is not None:
        lmm = body["long_marriage_months"]
        if not isinstance(lmm, int) or isinstance(lmm, bool) or lmm < 0:
            raise APIError(ERR_INVALID_REQUEST, 422, "long_marriage_months must be an integer >= 0")
        sched["long_marriage_months"] = lmm
    else:
        sched["long_marriage_months"] = 120

    db.stamp_immutable(sched)
    db.guideline_schedules[sched["id"]] = sched
    return ok_object(serialize(sched), 201)


@bp.get("/api/guideline-schedules/<rid>")
def get_guideline(rid):
    require_auth(READ_ROLES)()
    sched = require(db.guideline_schedules, rid, "GuidelineSchedule")
    return ok_object(serialize(sched), 200)


@bp.get("/api/guideline-schedules")
def list_guidelines():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.guideline_schedules.values()))
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [s for s in items if s["state_code"] == state_code]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
