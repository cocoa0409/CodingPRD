"""Fraud referrals: filing, investigation and the substantiation cascade."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.reads import fetch
from services import calc, cascades, derive

bp = Blueprint("fraud", __name__)


@bp.post("/v1/fraud-referrals")
def file_referral():
    user_id, _role = mw.authenticate("Inspector", "StateTitleClerk")
    data = mw.body()

    # 4. body foreign keys, in declared field order
    vehicle_id = data.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not vehicle_id.strip():
        mw.bad("vehicle_id", "is required")
    vehicle = db.db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")

    application_id = data.get("application_id")
    if application_id is not None:
        if not isinstance(application_id, str) or not application_id.strip():
            mw.bad("application_id", "must be a string identifier")
        if db.db.applications.get(application_id) is None:
            raise ApiError("ERR_APPLICATION_NOT_FOUND")

    inspection_id = data.get("inspection_id")
    if inspection_id is not None:
        if not isinstance(inspection_id, str) or not inspection_id.strip():
            mw.bad("inspection_id", "must be a string identifier")
        if db.db.inspections.get(inspection_id) is None:
            raise ApiError("ERR_INSPECTION_NOT_FOUND")

    # 5. well-formedness
    referral_type = mw.req_enum(data, "referral_type", calc.REFERRAL_TYPES)
    evidence_summary = mw.req_str(data, "evidence_summary")

    # 9. state-machine admissibility
    for existing in derive.referrals_of_vehicle(vehicle_id):
        if existing["referral_type"] == referral_type and existing["status"] in (
            "OPEN",
            "INVESTIGATING",
        ):
            raise ApiError(
                "ERR_REFERRAL_STATE_INVALID",
                "A referral of this type is already live against this vehicle.",
            )

    row = cascades.open_referral(
        vehicle,
        referral_type,
        "MANUAL",
        user_id,
        evidence_summary,
        application_id=application_id,
        inspection_id=inspection_id,
    )
    return response.single(derive.referral_out(row), 201)


@bp.post("/v1/fraud-referrals/<row_id>/investigate")
def investigate_referral(row_id):
    user_id, _role = mw.authenticate("FraudInvestigator")
    referral = fetch(db.db.referrals, row_id, "ERR_REFERRAL_NOT_FOUND")
    data = mw.body()
    mw.opt_str(data, "investigation_note")

    # 9. state-machine admissibility
    if referral["status"] != "OPEN":
        raise ApiError(
            "ERR_REFERRAL_STATE_INVALID", "Only an OPEN referral may be taken up."
        )

    referral["status"] = "INVESTIGATING"
    referral["investigator_user_id"] = user_id
    db.touch(referral)

    vehicle = db.db.vehicles.get(referral["vehicle_id"])
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=True)
    return response.single(derive.referral_out(referral))


@bp.post("/v1/fraud-referrals/<row_id>/resolve")
def resolve_referral(row_id):
    user_id, _role = mw.authenticate("FraudInvestigator")
    referral = fetch(db.db.referrals, row_id, "ERR_REFERRAL_NOT_FOUND")
    data = mw.body()
    outcome = mw.req_enum(data, "outcome", calc.REFERRAL_OUTCOMES)
    mw.opt_str(data, "resolution_note")

    # 9. state-machine admissibility
    if referral["status"] != "INVESTIGATING":
        raise ApiError(
            "ERR_REFERRAL_STATE_INVALID", "Only an INVESTIGATING referral may be resolved."
        )

    # 10. business safety — the principal who raised it may not adjudicate it
    if referral["opened_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The principal who filed this referral may not resolve it.",
        )

    referral["status"] = outcome
    referral["resolved_at"] = db.now_iso()
    db.touch(referral)

    if outcome == "SUBSTANTIATED":
        cascades.substantiation_cascade(referral)
    else:
        vehicle = db.db.vehicles.get(referral["vehicle_id"])
        if vehicle is not None:
            derive.recompute_vehicle(vehicle, touch_row=True)
        if referral.get("application_id"):
            application = db.db.applications.get(referral["application_id"])
            if application is not None:
                rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
                if rebuilder is not None:
                    derive.recompute_rebuilder(rebuilder, touch_row=True)
    return response.single(derive.referral_out(referral))
