"""Death referral intake, listing and screening creation."""

from flask import Blueprint, request

from constants import (
    CAUSE_OF_DEATH_CATEGORIES,
    REFERRAL_STATUSES,
    TIMELINESS_FLAGS,
)
from db import base_record, clock_now, db, lock, ordered
from errors import ApiError
from middleware import authenticate, enforce_hospital_scope
from response import ok, paginated
from services.calculations import lifetime_rate, partner_posture, referral_timeliness
from services.domain import screening_for_referral, touch
from validation import Body, json_body, page, pagination

bp = Blueprint("referrals", __name__)


def resolve_referral(referral_id):
    record = db.death_referrals.get(referral_id)
    if record is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND")
    return record


@bp.post("/opo/death-referrals")
def create_death_referral():
    user_id, role = authenticate("HospitalReferralClerk", "ReferralCoordinator")
    with lock:
        raw = json_body()
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

        # Precedence 3: a clerk may only refer for its own hospital.
        supplied_hospital = raw.get("hospital_partner_id")
        enforce_hospital_scope(user_id, role, supplied_hospital)

        # Precedence 5: body foreign keys resolve before body shape is examined.
        if supplied_hospital is not None:
            if not isinstance(supplied_hospital, str) or supplied_hospital not in db.hospital_partners:
                raise ApiError("ERR_HOSPITAL_NOT_FOUND")

        body = Body(raw)
        hospital_id = body.string("hospital_partner_id", required=True)
        patient_mrn = body.string("patient_mrn", required=True, min_len=1)
        age_years = body.integer("age_years", required=True, minimum=0, maximum=100)
        ventilated = body.boolean("ventilated", required=True)
        gcs_score = body.integer("gcs_score", required=True, minimum=3, maximum=15)
        cause = body.enum("cause_of_death_category", CAUSE_OF_DEATH_CATEGORIES, required=True)
        trigger_event_at = body.instant("trigger_event_at", required=True)
        death_pronounced_at = body.instant("death_pronounced_at", default=None)

        hospital = db.hospital_partners[hospital_id]
        referred_at = clock_now()

        if referred_at < trigger_event_at:
            raise ApiError("ERR_REFERRAL_BEFORE_TRIGGER")
        if death_pronounced_at is not None and death_pronounced_at < trigger_event_at:
            raise ApiError("ERR_REFERRAL_BEFORE_TRIGGER")

        lag, flag, audit_lag = referral_timeliness(
            referred_at,
            trigger_event_at,
            death_pronounced_at,
            hospital["timely_referral_window_minutes"],
        )

        record = base_record()
        record.update(
            {
                "hospital_partner_id": hospital_id,
                "patient_mrn": patient_mrn,
                "age_years": age_years,
                "ventilated": ventilated,
                "gcs_score": gcs_score,
                "cause_of_death_category": cause,
                "trigger_event_at": trigger_event_at,
                "death_pronounced_at": death_pronounced_at,
                "referred_at": referred_at,
                "referral_lag_minutes": lag,
                "timeliness_flag": flag,
                "audit_lag_minutes": audit_lag,
                "status": "RECEIVED",
            }
        )
        db.death_referrals[record["id"]] = record

        hospital["referral_count"] += 1
        if flag == "TIMELY":
            hospital["timely_referral_count"] += 1
        else:
            hospital["untimely_referral_count"] += 1
        hospital["timely_referral_rate"] = lifetime_rate(
            hospital["timely_referral_count"], hospital["referral_count"]
        )
        hospital["partner_posture"] = partner_posture(
            hospital["referral_count"], hospital["timely_referral_rate"]
        )
        touch(hospital)

        return ok(record, 201)


@bp.get("/opo/death-referrals/<referral_id>")
def read_death_referral(referral_id):
    authenticate(
        "OpoAdmin",
        "ReferralCoordinator",
        "MedicalDirector",
        "AuthorizationSpecialist",
        "DonorCoordinator",
        "HospitalReferralClerk",
    )
    with lock:
        return ok(resolve_referral(referral_id))


@bp.get("/opo/death-referrals")
def list_death_referrals():
    authenticate("OpoAdmin", "ReferralCoordinator", "MedicalDirector")
    with lock:
        limit, offset = pagination()
        hospital_id = request.args.get("hospital_partner_id")
        status = request.args.get("status")
        flag = request.args.get("timeliness_flag")
        rows = list(db.death_referrals.values())
        if hospital_id is not None:
            rows = [r for r in rows if r["hospital_partner_id"] == hospital_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status and status in REFERRAL_STATUSES]
        if flag is not None:
            rows = [r for r in rows if r["timeliness_flag"] == flag and flag in TIMELINESS_FLAGS]
        rows = ordered(rows)
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/death-referrals/<referral_id>/screenings")
def open_screening(referral_id):
    authenticate("ReferralCoordinator")
    with lock:
        referral = resolve_referral(referral_id)
        if referral["status"] != "RECEIVED" or screening_for_referral(referral_id) is not None:
            raise ApiError("ERR_REFERRAL_NOT_SCREENABLE")

        record = base_record()
        record.update(
            {
                "referral_id": referral_id,
                "status": "PENDING",
                "info_request_count": 0,
                "risk_factors": [],
                "unresolved_factors": [],
                "informant_reliability": None,
                "risk_score": None,
                "risk_tier": None,
                "risk_variant_applied": None,
                "risk_assessed_by_user_id": None,
                "absolute_contraindication": False,
                "decided_by_user_id": None,
                "ruled_out_reason": None,
            }
        )
        db.eligibility_screenings[record["id"]] = record

        referral["status"] = "SCREENING"
        touch(referral)
        return ok(record, 201)


@bp.get("/opo/death-referrals/<referral_id>/screenings")
def list_screenings_for_referral(referral_id):
    authenticate(
        "OpoAdmin", "ReferralCoordinator", "MedicalDirector", "SerologyLab", "DonorCoordinator"
    )
    with lock:
        resolve_referral(referral_id)
        limit, offset = pagination()
        rows = ordered(
            [s for s in db.eligibility_screenings.values() if s["referral_id"] == referral_id]
        )
        return paginated(page(rows, limit, offset), limit, offset, len(rows))
