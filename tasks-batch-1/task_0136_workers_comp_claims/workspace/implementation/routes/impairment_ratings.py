"""ImpairmentRating endpoints (PRD §3.8). Dispute cascades an IMEOrder;
finalize cascades the claim to MMI and is segregation-of-duties guarded."""
from __future__ import annotations

from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_auth, get_json_body, current_user_id
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_number, require_enum
from services import reserve as reserve_svc
from routes._common import get_claim, get_impairment_rating

bp = Blueprint("impairment_ratings", __name__)

RATER_ROLES = ["TREATING", "IME"]


def _reserve_set_by(claim_id: str):
    r = reserve_svc.reserve_for_claim(claim_id)
    return r.get("reserve_set_by") if r else None


def _ime_completed_for_claim(claim_id: str) -> bool:
    for ime in db.ime_orders.values():
        if ime["claim_id"] == claim_id and ime["status"] == "COMPLETED":
            return True
    return False


@bp.post("/impairment-ratings")
def create_impairment_rating():
    require_auth(["MedicalReviewer"])()
    body = get_json_body()

    claim_id = require_str(body, "claim_id")
    get_claim(claim_id)

    whole_body_pct = require_number(body, "whole_body_pct", minimum=0, maximum=100)
    rater_role = require_enum(body, "rater_role", RATER_ROLES)

    rating = {
        "claim_id": claim_id,
        "whole_body_pct": whole_body_pct,
        "rater_role": rater_role,
        "status": "PROPOSED",
        "finalized_pct": None,
    }
    db.stamp_common(rating)
    db.impairment_ratings[rating["id"]] = rating
    return ok_object(rating, 201)


@bp.get("/impairment-ratings/<rid>")
def get_impairment_rating_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer"])()
    return ok_object(get_impairment_rating(rid), 200)


@bp.get("/claims/<rid>/impairment-ratings")
def list_claim_impairment_ratings(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer"])()
    get_claim(rid)
    limit, offset = paginate_params(request.args)
    items = [r for r in db.impairment_ratings.values() if r["claim_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/impairment-ratings/<rid>/dispute")
def dispute_rating(rid):
    require_auth(["ClaimsAdjuster"])()
    rating = get_impairment_rating(rid)
    if rating["status"] != "PROPOSED" or rating["rater_role"] != "TREATING":
        raise APIError(ERR_INVALID_STATE, 409,
                       "Only a PROPOSED treating-physician rating may be disputed")
    rating["status"] = "DISPUTED"
    db.bump(rating)

    # Cascade: create an IMEOrder (SCHEDULED) starting now, ending now+1day,
    # examiner_name = PENDING_ASSIGNMENT — immediately completable.
    now = db.get_current_utc_dt()
    start_iso = db.get_current_utc()
    end_iso = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{(now + timedelta(days=1)).microsecond // 1000:03d}Z"
    ime = {
        "claim_id": rating["claim_id"],
        "scheduled_start": start_iso,
        "scheduled_end": end_iso,
        "examiner_name": "PENDING_ASSIGNMENT",
        "status": "SCHEDULED",
    }
    db.stamp_common(ime)
    db.ime_orders[ime["id"]] = ime
    return ok_object(rating, 200)


@bp.post("/impairment-ratings/<rid>/finalize")
def finalize_rating(rid):
    require_auth(["MedicalReviewer"])()
    rating = get_impairment_rating(rid)

    # Segregation of duties (priority 3): the adjuster who set the claim's reserve
    # may not be the operator finalizing the rating.
    if current_user_id() == _reserve_set_by(rating["claim_id"]):
        raise APIError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The reserve-setter may not finalize this claim's rating")

    status = rating["status"]
    if status == "PROPOSED" and rating["rater_role"] == "IME":
        pass  # IME-issued rating finalizes directly
    elif status == "DISPUTED":
        if not _ime_completed_for_claim(rating["claim_id"]):
            raise APIError(ERR_INVALID_STATE, 409,
                           "A COMPLETED IME is required to finalize a disputed rating")
    else:
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot finalize a rating in status {status} "
                       f"with rater_role {rating['rater_role']}")

    rating["status"] = "FINALIZED"
    rating["finalized_pct"] = rating["whole_body_pct"]
    db.bump(rating)

    # Cascade: claim -> MMI.
    claim = db.claims.get(rating["claim_id"])
    if claim is not None:
        claim["status"] = "MMI"
        db.bump(claim)
    return ok_object(rating, 200)
