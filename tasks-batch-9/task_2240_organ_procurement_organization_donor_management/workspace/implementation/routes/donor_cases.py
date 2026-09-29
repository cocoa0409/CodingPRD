"""Donor case conversion, physiologic charting and organ registration."""

from flask import Blueprint, request

from constants import CASE_POSTURES, CIT_LIMIT_MINUTES, ORGAN_TYPES
from db import base_record, clock_now, db, lock, ordered
from errors import ApiError
from middleware import authenticate
from response import ok, paginated
from services.calculations import dmg_bundle_met, viability_index_snapshot
from services.domain import (
    observations_of_case,
    organs_of_case,
    project_observations,
    refresh_organ_counters,
    screening_for_referral,
    touch,
)
from validation import Body, json_body, page, pagination

bp = Blueprint("donor_cases", __name__)


def resolve_case(case_id):
    record = db.donor_cases.get(case_id)
    if record is None:
        raise ApiError("ERR_DONOR_CASE_NOT_FOUND")
    return record


def refuse_when_frozen(case):
    if case["case_posture"] == "FROZEN":
        raise ApiError("ERR_CASE_FROZEN")


@bp.post("/opo/donor-cases")
def create_donor_case():
    authenticate("DonorCoordinator")
    with lock:
        raw = json_body()
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

        supplied_referral = raw.get("referral_id")
        if supplied_referral is not None:
            if not isinstance(supplied_referral, str) or supplied_referral not in db.death_referrals:
                raise ApiError("ERR_REFERRAL_NOT_FOUND")
        supplied_auth = raw.get("authorization_id")
        if supplied_auth is not None:
            if not isinstance(supplied_auth, str) or supplied_auth not in db.authorizations:
                raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")

        body = Body(raw)
        referral_id = body.string("referral_id", required=True)
        authorization_id = body.string("authorization_id", required=True)
        donor_code = body.string("donor_code", required=True, min_len=3, max_len=16)

        for existing in db.donor_cases.values():
            if existing["donor_code"] == donor_code:
                raise ApiError("ERR_DUPLICATE_KEY", "donor_code is already in use.")

        referral = db.death_referrals[referral_id]
        authorization = db.authorizations[authorization_id]
        screening = screening_for_referral(referral_id)

        if referral["status"] != "AUTH_PENDING" or screening is None or screening["status"] != "CLEARED":
            raise ApiError("ERR_SCREENING_NOT_CLEARED")
        if authorization["status"] != "AUTHORIZED":
            raise ApiError("ERR_AUTHORIZATION_NOT_GRANTED")
        if screening["absolute_contraindication"]:
            raise ApiError("ERR_ABSOLUTE_CONTRAINDICATION")
        if authorization["referral_id"] != referral_id:
            raise ApiError("ERR_AUTHORIZATION_REFERRAL_MISMATCH")

        record = base_record()
        record.update(
            {
                "referral_id": referral_id,
                "authorization_id": authorization_id,
                "donor_code": donor_code,
                "physiologic_status": "STABILIZING",
                "allocation_status": "NOT_STARTED",
                "case_posture": "OPEN",
                "viability_index": 0,
                "dmg_bundle_met_count": 0,
                "observation_count": 0,
                "organ_count": 0,
                "organs_accepted_count": 0,
                "organs_recovered_count": 0,
                "organs_nontransplantable_count": 0,
                "risk_tier_snapshot": screening["risk_tier"],
                "closed_reason": None,
            }
        )
        db.donor_cases[record["id"]] = record

        referral["status"] = "CONVERTED"
        touch(referral)
        hospital = db.hospital_partners.get(referral["hospital_partner_id"])
        if hospital is not None:
            hospital["converted_donor_count"] += 1
            touch(hospital)

        return ok(record, 201)


@bp.get("/opo/donor-cases/<case_id>")
def read_donor_case(case_id):
    authenticate(
        "OpoAdmin", "DonorCoordinator", "MedicalDirector", "AllocationSpecialist", "RecoveryLogistics"
    )
    with lock:
        return ok(resolve_case(case_id))


@bp.get("/opo/donor-cases")
def list_donor_cases():
    authenticate("OpoAdmin", "DonorCoordinator", "MedicalDirector", "AllocationSpecialist")
    with lock:
        limit, offset = pagination()
        referral_id = request.args.get("referral_id")
        authorization_id = request.args.get("authorization_id")
        posture = request.args.get("case_posture")
        rows = list(db.donor_cases.values())
        if referral_id is not None:
            rows = [r for r in rows if r["referral_id"] == referral_id]
        if authorization_id is not None:
            rows = [r for r in rows if r["authorization_id"] == authorization_id]
        if posture is not None:
            rows = [r for r in rows if r["case_posture"] == posture and posture in CASE_POSTURES]
        rows = ordered(rows)
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/donor-cases/<case_id>/observations")
def chart_observation(case_id):
    user_id, _role = authenticate("DonorCoordinator")
    with lock:
        case = resolve_case(case_id)
        body = Body()
        recorded_at = body.instant("recorded_at", required=True)
        map_mmhg = body.number("map_mmhg", required=True, minimum=0, maximum=200)
        ratio = body.number("pao2_fio2_ratio", required=True, minimum=0, maximum=600)
        sodium = body.number("sodium", required=True, minimum=100, maximum=200)
        urine = body.number("urine_output_ml_per_kg_hr", required=True, minimum=0, maximum=20)
        pressor_count = body.integer("pressor_count", required=True, minimum=0, maximum=5)
        cardiac_arrest = body.boolean("cardiac_arrest", default=False)

        refuse_when_frozen(case)
        if recorded_at > clock_now():
            raise ApiError("ERR_OBSERVATION_IN_FUTURE")

        record = base_record(managed=False)
        record.update(
            {
                "donor_case_id": case_id,
                "recorded_at": recorded_at,
                "map_mmhg": map_mmhg,
                "pao2_fio2_ratio": ratio,
                "sodium": sodium,
                "urine_output_ml_per_kg_hr": urine,
                "pressor_count": pressor_count,
                "cardiac_arrest": cardiac_arrest,
                "recorded_by_user_id": user_id,
            }
        )
        record["dmg_bundle_met"] = dmg_bundle_met(record)
        record["viability_index_snapshot"] = viability_index_snapshot(record)
        db.observations[record["id"]] = record

        project_observations(case)
        return ok(record, 201)


@bp.get("/opo/donor-cases/<case_id>/observations")
def list_observations(case_id):
    authenticate("OpoAdmin", "DonorCoordinator", "MedicalDirector")
    with lock:
        resolve_case(case_id)
        limit, offset = pagination()
        rows = observations_of_case(case_id)
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/donor-cases/<case_id>/organs")
def register_organ(case_id):
    authenticate("DonorCoordinator")
    with lock:
        case = resolve_case(case_id)
        body = Body()
        organ_type = body.enum("organ_type", ORGAN_TYPES, required=True)

        for existing in organs_of_case(case_id):
            if existing["organ_type"] == organ_type:
                raise ApiError(
                    "ERR_DUPLICATE_KEY", "This organ_type is already registered on the case."
                )
        refuse_when_frozen(case)

        record = base_record()
        record.update(
            {
                "donor_case_id": case_id,
                "organ_type": organ_type,
                "status": "PENDING_EVAL",
                "cit_limit_minutes": CIT_LIMIT_MINUTES[organ_type],
                "viability_hold": False,
                "accepted_offer_id": None,
                "cross_clamp_at": None,
                "transport_asset_id": None,
                "transport_mode": None,
                "transport_depart_at": None,
                "transport_arrive_at": None,
                "transit_minutes": None,
                "implant_prep_minutes": None,
                "projected_cold_ischemic_minutes": None,
                "projected_cit_margin_minutes": None,
                "nontransplantable_reason": None,
                "research_protocol_code": None,
                "tissue_processor_code": None,
            }
        )
        db.organs[record["id"]] = record
        refresh_organ_counters(case)
        return ok(record, 201)
