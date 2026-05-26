"""Candidate endpoints."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    get_json_or_400,
    require_str,
    require_enum,
    optional_str,
    optional_enum,
    optional_bool,
    new_id,
    now_iso,
    parse_pagination,
    paginate,
    get_or_404,
)
from errors import ApiError, ERR_INVALID_REQUEST
from response import success_object, success_array
from serializers import ser_candidate


bp = Blueprint("candidates", __name__)

SOURCE_CHANNELS = {"DIRECT", "REFERRAL", "AGENCY", "JOB_BOARD"}
EEO_ETHNICITY = {"WHITE", "BLACK", "HISPANIC", "ASIAN", "NATIVE", "PACIFIC", "TWO_OR_MORE", "DECLINED"}
EEO_GENDER = {"FEMALE", "MALE", "NONBINARY", "DECLINED"}


@bp.post("/ats/candidates")
def create_candidate():
    require_role({"Recruiter"})
    body = get_json_or_400()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    source_channel = require_enum(body, "source_channel", SOURCE_CHANNELS)
    referrer_user_id = optional_str(body, "referrer_user_id", default=None)
    eeo_ethnicity = optional_enum(body, "eeo_ethnicity", EEO_ETHNICITY, default="DECLINED")
    eeo_gender = optional_enum(body, "eeo_gender", EEO_GENDER, default="DECLINED")
    eeo_veteran = optional_bool(body, "eeo_veteran", default=False)
    eeo_disability = optional_bool(body, "eeo_disability", default=False)

    if source_channel == "REFERRAL":
        if not referrer_user_id:
            raise ApiError(ERR_INVALID_REQUEST, 400, "referrer_user_id required for REFERRAL source")
    else:
        referrer_user_id = None

    # Unique email.
    for c in db.candidates.values():
        if c["email"] == email:
            raise ApiError(ERR_INVALID_REQUEST, 400, "email already in use")

    cand = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "source_channel": source_channel,
        "referrer_user_id": referrer_user_id,
        "eeo_ethnicity": eeo_ethnicity,
        "eeo_gender": eeo_gender,
        "eeo_veteran": eeo_veteran,
        "eeo_disability": eeo_disability,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.candidates[cand["id"]] = cand
    return success_object(ser_candidate(cand), status=201)


@bp.get("/ats/candidates/<cand_id>")
def read_candidate(cand_id):
    require_role({"Recruiter", "HiringManager", "PlatformAdmin"})
    cand = get_or_404(db.candidates, cand_id, "candidate")
    return success_object(ser_candidate(cand), status=200)


@bp.get("/ats/candidates")
def list_candidates():
    require_role({"Recruiter", "HiringManager", "PlatformAdmin"})
    limit, offset = parse_pagination()
    src = request.args.get("source_channel")
    rows = list(db.candidates.values())
    if src:
        rows = [c for c in rows if c["source_channel"] == src]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_candidate(c) for c in page], limit, offset, total, status=200)
