"""LowIncomeVerification routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, now
from ..common import bump, check_occ, get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..fare_logic import LOW_INCOME_THRESHOLD_CENTS
from ..response import respond
from ..serializers import low_income_view
from ..store import store


bp = Blueprint("low_income", __name__, url_prefix="/transit/low-income-verifications")


@bp.post("")
@require_auth("Rider", "AgencyOfficer")
def create_low_income():
    body = get_json_body()
    require_fields(body, "rider_id", "declared_annual_income_cents")
    rider_id = body["rider_id"]
    declared = positive_int(body["declared_annual_income_cents"], "declared_annual_income_cents", allow_zero=True)

    with store.lock:
        if g.user_role == "Rider" and g.user_id != rider_id:
            raise ApiError("ERR_FORBIDDEN", "Riders may only create verifications for themselves")
        if rider_id not in store.riders:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Rider not found")
        verif = {
            "rider_id": rider_id,
            "declared_annual_income_cents": declared,
            "verified_annual_income_cents": None,
            "status": "PENDING",
            "approved_at": None,
        }
        stamp_new(verif)
        store.low_income_verifications[verif["id"]] = verif
    return respond(low_income_view(verif), 201)


@bp.post("/<verif_id>/approve")
@require_auth("AgencyOfficer")
def approve_low_income(verif_id: str):
    body = get_json_body()
    require_fields(body, "verified_annual_income_cents")
    verified = positive_int(body["verified_annual_income_cents"], "verified_annual_income_cents", allow_zero=True)

    with store.lock:
        verif = store.low_income_verifications.get(verif_id)
        if verif is None:
            raise ApiError("ERR_NOT_FOUND", "Verification not found")
        if verif["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Verification is not PENDING")
        check_occ(verif, body.get("version"))
        verif["verified_annual_income_cents"] = verified
        if verified <= LOW_INCOME_THRESHOLD_CENTS:
            verif["status"] = "ACTIVE"
            verif["approved_at"] = iso_format(now())
            rider = store.riders.get(verif["rider_id"])
            if rider is not None and not rider.get("low_income_verified"):
                rider["low_income_verified"] = True
                bump(rider)
        else:
            verif["status"] = "REJECTED"
        bump(verif)
    return respond(low_income_view(verif), 200)
