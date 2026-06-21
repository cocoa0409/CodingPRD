"""Reserve endpoints (PRD §3.4, §3.7). One reserve per claim; conserved ledger."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_DUPLICATE_RESOURCE
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_int, require_enum
from services import calculations as calc
from services import reserve as reserve_svc
from routes._common import get_claim, get_reserve

bp = Blueprint("reserves", __name__)

SEVERITY_TIERS = ["MINOR", "MODERATE", "SEVERE"]


@bp.post("/reserves")
def create_reserve():
    require_auth(["ClaimsAdjuster"])()
    body = get_json_body()

    claim_id = require_str(body, "claim_id")
    claim = get_claim(claim_id)

    # Uniqueness (priority 12): at most one reserve per claim.
    if reserve_svc.reserve_for_claim(claim_id) is not None:
        raise APIError(ERR_DUPLICATE_RESOURCE, 409, "A reserve already exists for this claim")

    severity_tier = require_enum(body, "severity_tier", SEVERITY_TIERS)
    projected_weeks = require_int(body, "projected_weeks", minimum=0)

    weekly = reserve_svc.controlling_weekly_rate(claim_id)
    indemnity_reserve = calc.indemnity_reserve_forward(weekly, projected_weeks)
    medical_reserve = calc.medical_reserve_for_tier(severity_tier)

    reserve = {
        "claim_id": claim_id,
        "severity_tier": severity_tier,
        "projected_weeks": projected_weeks,
        "indemnity_reserve_cents": indemnity_reserve,
        "medical_reserve_cents": medical_reserve,
        "indemnity_paid_cents": 0,
        "medical_paid_cents": 0,
        "total_incurred_cents": 0,
    }
    reserve_svc.recompute_total(reserve)
    # Record the adjuster who set the reserve for the separation-of-duties bar.
    reserve["reserve_set_by"] = _current_user_id()

    db.stamp_common(reserve)
    db.reserves[reserve["id"]] = reserve
    return ok_object(_public(reserve), 201)


@bp.get("/reserves/<rid>")
def get_reserve_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster"])()
    return ok_object(_public(get_reserve(rid)), 200)


@bp.get("/claims/<rid>/reserves")
def list_claim_reserves(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster"])()
    get_claim(rid)
    limit, offset = paginate_params(request.args)
    items = [r for r in db.reserves.values() if r["claim_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array([_public(r) for r in page], limit, offset, total, 200)


@bp.post("/reserves/<rid>/medical-payments")
def post_medical_payment(rid):
    require_auth(["ClaimsAdjuster"])()
    reserve = get_reserve(rid)
    body = get_json_body()
    amount = require_int(body, "amount_cents", minimum=0)
    reserve_svc.apply_medical_payment(reserve, amount)
    return ok_object(_public(reserve), 201)


# ---- helpers ----------------------------------------------------------------

def _current_user_id():
    from middleware import current_user_id
    return current_user_id()


def _public(reserve):
    """Strip the internal reserve_set_by bookkeeping field from responses."""
    return {k: v for k, v in reserve.items() if k != "reserve_set_by"}
