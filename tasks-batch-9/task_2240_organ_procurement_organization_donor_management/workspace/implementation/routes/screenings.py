"""Eligibility screening: risk assessment, serology, info requests and the ruling."""

from flask import Blueprint

from constants import (
    ABSOLUTE_MARKERS,
    INFORMANT_RELIABILITIES,
    MAX_INFO_REQUESTS,
    RISK_FACTORS,
    RULED_OUT_REASONS,
    SCREENING_DECISIONS,
    SEROLOGY_MARKERS,
    SEROLOGY_OUTCOMES,
)
from db import base_record, db, lock, ordered
from errors import ApiError
from middleware import authenticate
from response import ok, paginated
from services.calculations import behavioral_risk_score
from services.domain import touch
from validation import Body, page, pagination

bp = Blueprint("screenings", __name__)


def resolve_screening(screening_id):
    record = db.eligibility_screenings.get(screening_id)
    if record is None:
        raise ApiError("ERR_SCREENING_NOT_FOUND")
    return record


@bp.get("/opo/eligibility-screenings/<screening_id>")
def read_screening(screening_id):
    authenticate(
        "OpoAdmin", "ReferralCoordinator", "MedicalDirector", "SerologyLab", "DonorCoordinator"
    )
    with lock:
        return ok(resolve_screening(screening_id))


@bp.post("/opo/eligibility-screenings/<screening_id>/risk-assessment")
def submit_risk_assessment(screening_id):
    user_id, _role = authenticate("ReferralCoordinator")
    with lock:
        screening = resolve_screening(screening_id)
        body = Body()
        risk_factors = body.enum_array("risk_factors", RISK_FACTORS, required=True)
        reliability = body.enum("informant_reliability", INFORMANT_RELIABILITIES, required=True)
        expected = body.integer("expected_screening_version", required=True)
        unresolved = body.enum_array("unresolved_factors", RISK_FACTORS)
        if set(risk_factors) & set(unresolved):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "unresolved_factors must be disjoint from risk_factors.",
            )

        if screening["status"] not in ("PENDING", "INFO_REQUESTED"):
            raise ApiError("ERR_SCREENING_NOT_PENDING")
        if expected != screening["version"]:
            raise ApiError("ERR_STALE_VERSION")

        score, tier, variant = behavioral_risk_score(risk_factors, unresolved, reliability)
        # The prior assessment is fully replaced, never merged.
        screening["risk_factors"] = list(risk_factors)
        screening["unresolved_factors"] = list(unresolved)
        screening["informant_reliability"] = reliability
        screening["risk_score"] = score
        screening["risk_tier"] = tier
        screening["risk_variant_applied"] = variant
        screening["risk_assessed_by_user_id"] = user_id
        if screening["status"] == "INFO_REQUESTED":
            screening["status"] = "PENDING"
        touch(screening)
        return ok(screening)


@bp.post("/opo/eligibility-screenings/<screening_id>/serology-results")
def file_serology_result(screening_id):
    authenticate("SerologyLab")
    with lock:
        screening = resolve_screening(screening_id)
        body = Body()
        marker = body.enum("marker", SEROLOGY_MARKERS, required=True)
        result = body.enum("result", SEROLOGY_OUTCOMES, required=True)
        resulted_at = body.instant("resulted_at", required=True)
        nat_confirmed = body.boolean("nat_confirmed", default=False)

        if screening["status"] == "RULED_OUT":
            raise ApiError("ERR_ALREADY_TERMINAL")

        absolute = bool(marker in ABSOLUTE_MARKERS and result == "POSITIVE" and nat_confirmed)

        record = base_record(managed=False)
        record.update(
            {
                "screening_id": screening_id,
                "marker": marker,
                "result": result,
                "nat_confirmed": nat_confirmed,
                "resulted_at": resulted_at,
                "absolute_contraindication_marker": absolute,
            }
        )
        db.serology_results[record["id"]] = record

        if absolute:
            if screening["status"] in ("PENDING", "INFO_REQUESTED"):
                screening["absolute_contraindication"] = True
                screening["ruled_out_reason"] = "SEROLOGY_CONTRAINDICATION"
                screening["status"] = "RULED_OUT"
                touch(screening)
                referral = db.death_referrals.get(screening["referral_id"])
                if referral is not None and referral["status"] == "SCREENING":
                    referral["status"] = "RULED_OUT"
                    touch(referral)
            elif screening["status"] == "CLEARED":
                # Accepted deliberately: no state transition, the contraindication
                # blocks donor-case conversion downstream instead.
                screening["absolute_contraindication"] = True
                touch(screening)

        return ok(record, 201)


@bp.get("/opo/eligibility-screenings/<screening_id>/serology-results")
def list_serology_results(screening_id):
    authenticate("OpoAdmin", "ReferralCoordinator", "MedicalDirector", "SerologyLab")
    with lock:
        resolve_screening(screening_id)
        limit, offset = pagination()
        rows = ordered(
            [r for r in db.serology_results.values() if r["screening_id"] == screening_id]
        )
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/eligibility-screenings/<screening_id>/request-info")
def request_info(screening_id):
    authenticate("MedicalDirector")
    with lock:
        screening = resolve_screening(screening_id)
        body = Body()
        body.string("info_request_note")

        if screening["status"] != "PENDING":
            raise ApiError("ERR_SCREENING_NOT_PENDING")
        if screening["info_request_count"] >= MAX_INFO_REQUESTS:
            raise ApiError("ERR_INFO_REQUEST_LIMIT_REACHED")

        screening["status"] = "INFO_REQUESTED"
        screening["info_request_count"] += 1
        touch(screening)
        return ok(screening)


@bp.post("/opo/eligibility-screenings/<screening_id>/decision")
def decide_screening(screening_id):
    user_id, _role = authenticate("MedicalDirector")
    with lock:
        screening = resolve_screening(screening_id)
        body = Body()
        decision = body.enum("decision", SCREENING_DECISIONS, required=True)
        reason = body.enum("ruled_out_reason", RULED_OUT_REASONS)

        if screening["status"] != "PENDING":
            raise ApiError("ERR_SCREENING_NOT_PENDING")
        if screening["risk_score"] is None:
            raise ApiError("ERR_RISK_ASSESSMENT_MISSING")
        if (
            screening["risk_assessed_by_user_id"] is not None
            and screening["risk_assessed_by_user_id"] == user_id
        ):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if decision == "CLEARED" and screening["absolute_contraindication"]:
            raise ApiError("ERR_ABSOLUTE_CONTRAINDICATION")

        screening["decided_by_user_id"] = user_id
        referral = db.death_referrals.get(screening["referral_id"])
        if decision == "CLEARED":
            screening["status"] = "CLEARED"
            if referral is not None and referral["status"] == "SCREENING":
                referral["status"] = "SCREEN_CLEARED"
                touch(referral)
        else:
            screening["status"] = "RULED_OUT"
            screening["ruled_out_reason"] = reason or "DIRECTOR_DECISION"
            if referral is not None and referral["status"] == "SCREENING":
                referral["status"] = "RULED_OUT"
                touch(referral)
        touch(screening)
        return ok(screening)
