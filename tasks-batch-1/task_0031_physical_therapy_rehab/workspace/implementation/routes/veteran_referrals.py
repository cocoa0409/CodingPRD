"""VeteranReferral routes (scaffold §1.5 — Veteran Referrals; PRD §3.2 / §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    require_date,
    require_facility_code,
    require_fields,
    require_int,
    require_string,
    lookup_or_404,
)


bp = Blueprint("veteran_referrals", __name__)


@bp.post("/rehab/veteran-referrals")
def create_veteran_referral():
    require_auth(["VAReferralCoordinator", "PlatformAdmin"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "patient_id",
            "referring_va_facility_code",
            "referral_authorization_number",
            "max_authorized_visits",
            "expires_on",
        ],
    )
    patient_id = require_string(body["patient_id"], "patient_id")
    facility_code = require_facility_code(
        body["referring_va_facility_code"], "referring_va_facility_code"
    )
    auth_number = require_string(
        body["referral_authorization_number"], "referral_authorization_number"
    )
    max_visits = require_int(
        body["max_authorized_visits"], "max_authorized_visits", min_value=1, max_value=60
    )
    expires_on = require_date(body["expires_on"], "expires_on")

    # FK existence (priority 210)
    lookup_or_404(db.patients, patient_id, "Patient")

    # referral_authorization_number unique across VeteranReferral.
    for existing in db.veteran_referrals.values():
        if existing["referral_authorization_number"] == auth_number:
            raise APIError(
                ERR_INVALID_REQUEST,
                400,
                "referral_authorization_number must be unique",
            )

    with db.mutation_lock:
        referral = {
            "patient_id": patient_id,
            "referring_va_facility_code": facility_code,
            "referral_authorization_number": auth_number,
            "max_authorized_visits": max_visits,
            "expires_on": expires_on.isoformat(),
            "status": "ISSUED",
        }
        db.stamp_common(referral)
        db.veteran_referrals[referral["id"]] = referral
        return ok_object(referral, 201)


@bp.get("/rehab/veteran-referrals/<rid>")
def get_veteran_referral(rid: str):
    require_auth(
        ["PlatformAdmin", "CaseManager", "VAReferralCoordinator", "Therapist"]
    )()
    referral = lookup_or_404(db.veteran_referrals, rid, "VeteranReferral")
    return ok_object(referral, 200)


@bp.get("/rehab/veteran-referrals")
def list_veteran_referrals():
    require_auth(["PlatformAdmin", "CaseManager", "VAReferralCoordinator"])()
    limit, offset = paginate_params(request.args)
    items = list(db.veteran_referrals.values())
    if "patient_id" in request.args:
        items = [r for r in items if r["patient_id"] == request.args.get("patient_id")]
    if "status" in request.args:
        items = [r for r in items if r["status"] == request.args.get("status")]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/rehab/veteran-referrals/<rid>/cancel")
def cancel_veteran_referral(rid: str):
    require_auth(["VAReferralCoordinator", "PlatformAdmin"])()
    referral = lookup_or_404(db.veteran_referrals, rid, "VeteranReferral")
    if referral["status"] != "ISSUED":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"VeteranReferral cannot be cancelled from status={referral['status']}",
        )
    with db.mutation_lock:
        referral["status"] = "CANCELLED"
        db.bump(referral)
        return ok_object(referral, 200)
