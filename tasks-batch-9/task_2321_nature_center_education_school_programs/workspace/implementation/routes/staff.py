"""School partners, the educator hiring pipeline and training records."""

from datetime import timedelta

from flask import Blueprint

import calc
import derive
import flows
import logical_clock
from envelope import array_response, object_response
from errors import ApiError
from schema import (body_json, lookup, opt_dt, opt_enum, opt_int, opt_str,
                    pagination, paginate, query_enum, req_enum, req_num,
                    req_str)
from security import authorize, naturalist_scope
from store import (db, new_entity, public, set_dt, set_system_dt, sorted_rows,
                   touch)

bp = Blueprint("staff", __name__)

GRADE_BANDS = ("K_2", "G3_5", "G6_8", "G9_12")
EMPLOYMENT_TYPES = ("STAFF_NATURALIST", "SEASONAL_EDUCATOR")
TRACKS = ("CURRICULUM", "LIVE_ANIMAL_HANDLING")
HANDLING_TIERS = ("TIER_1", "TIER_2")
TRAINING_STATUSES = ("ENROLLED", "ASSESSED_PASS", "ASSESSED_FAIL", "EXPIRED")


# ------------------------------------------------------------------ schools
@bp.post("/schools")
def create_school():
    authorize(("EducationDirector", "BookingCoordinator"))
    body = body_json()
    name = req_str(body, "name")
    district_code = req_str(body, "district_code")
    title_i_pct = req_num(body, "title_i_pct", low=0, high=1)
    distance_miles = req_num(body, "distance_miles", high=400, exclusive_low=0)
    contact_email = opt_str(body, "contact_email")

    school = new_entity()
    school.update({
        "name": name,
        "district_code": district_code,
        "title_i_pct": title_i_pct,
        "distance_miles": distance_miles,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "equity_tier": calc.equity_tier(title_i_pct),
        "no_show_strikes": 0,
        "outstanding_balance_cents": 0,
    })
    db.schools[school["id"]] = school
    derive.sync()
    return object_response(public(school), 201)


@bp.get("/schools/<school_id>")
def read_school(school_id):
    authorize(("EducationDirector", "BookingCoordinator", "GrantsOfficer"))
    school = lookup("school", school_id)
    return object_response(public(school))


# ---------------------------------------------------------------- educators
@bp.post("/educators")
def create_educator():
    authorize(("EducationDirector",))
    body = body_json()
    full_name = req_str(body, "full_name")
    employment_type = req_enum(body, "employment_type", EMPLOYMENT_TYPES)
    season_raw, season_dt = opt_dt(body, "season_end_date")

    educator = new_entity()
    educator.update({
        "full_name": full_name,
        "employment_type": employment_type,
        "season_end_date": None,
        "status": "APPLICANT",
        "background_check_started_at": None,
        "curriculum_certified_grade_bands": [],
        "animal_handling_tier": "NONE",
        "delivery_load_minutes_this_week": 0,
    })
    if season_raw is not None:
        set_dt(educator, "season_end_date", season_raw, season_dt)
    db.educators[educator["id"]] = educator
    derive.sync()
    return object_response(public(educator), 201)


@bp.get("/educators/<educator_id>")
def read_educator(educator_id):
    actor = authorize(("EducationDirector", "BookingCoordinator", "Naturalist"))
    educator = lookup("educator", educator_id)
    naturalist_scope(actor, educator["id"])
    return object_response(public(educator))


@bp.post("/educators/<educator_id>/advance-hiring")
def advance_hiring(educator_id):
    authorize(("EducationDirector",))
    body = body_json()
    action = req_enum(body, "action", ("START_ONBOARDING", "CLEAR", "DEACTIVATE"))
    educator = lookup("educator", educator_id)

    if action == "START_ONBOARDING":
        if educator["status"] != "APPLICANT":
            raise ApiError("ERR_INVALID_EDUCATOR_STATE")
        educator["status"] = "ONBOARDING"
        set_system_dt(educator, "background_check_started_at", logical_clock.now())
        touch(educator)
    elif action == "CLEAR":
        if educator["status"] != "ONBOARDING":
            raise ApiError("ERR_INVALID_EDUCATOR_STATE")
        passed = any(
            r["track"] == "CURRICULUM" and r["status"] == "ASSESSED_PASS"
            for r in derive.training_for(educator["id"])
        )
        if not passed:
            raise ApiError("ERR_INVALID_EDUCATOR_STATE")
        educator["status"] = "CLEARED"
        touch(educator)
    else:
        if educator["status"] not in ("CLEARED", "ONBOARDING"):
            raise ApiError("ERR_INVALID_EDUCATOR_STATE")
        was_cleared = educator["status"] == "CLEARED"
        educator["status"] = "INACTIVE"
        touch(educator)
        if was_cleared:
            flows.release_bookings_for_educator(educator)
    derive.sync()
    return object_response(public(educator))


# --------------------------------------------------------- training records
@bp.post("/educators/<educator_id>/training-records")
def enroll_training(educator_id):
    actor = authorize(("CurriculumSpecialist", "EducationDirector"))
    body = body_json()
    track = req_enum(body, "track", TRACKS)
    grade_band = opt_enum(body, "grade_band", GRADE_BANDS)
    handling_tier = opt_enum(body, "handling_tier", HANDLING_TIERS)
    educator = lookup("educator", educator_id)

    if track == "CURRICULUM":
        if grade_band is None or handling_tier is not None:
            raise ApiError("ERR_TRACK_FIELD_MISMATCH")
    else:
        if handling_tier is None or grade_band is not None:
            raise ApiError("ERR_TRACK_FIELD_MISMATCH")

    record = new_entity()
    record.update({
        "educator_id": educator["id"],
        "track": track,
        "grade_band": grade_band,
        "handling_tier": handling_tier,
        "status": "ENROLLED",
        "score": None,
        "attempt_count": 0,
        "enrolled_by_user_id": actor.user_id,
        "assessed_by_user_id": None,
        "passed_at": None,
        "expires_on": None,
    })
    db.training[record["id"]] = record
    derive.sync()
    return object_response(public(record), 201)


@bp.get("/educators/<educator_id>/training-records")
def list_training(educator_id):
    actor = authorize(("EducationDirector", "CurriculumSpecialist", "Naturalist"))
    limit, offset = pagination()
    track = query_enum("track", TRACKS)
    status = query_enum("status", TRAINING_STATUSES)
    educator = lookup("educator", educator_id)
    naturalist_scope(actor, educator["id"])

    rows = [r for r in sorted_rows(db.training.values()) if r["educator_id"] == educator["id"]]
    if track is not None:
        rows = [r for r in rows if r["track"] == track]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.post("/training-records/<record_id>/assess")
def assess_training(record_id):
    actor = authorize(("CurriculumSpecialist", "EducationDirector"))
    body = body_json()
    outcome = req_enum(body, "outcome", ("PASS", "FAIL"))
    score = opt_int(body, "score", 0, 100)
    record = lookup("training", record_id)

    if actor.user_id == record.get("enrolled_by_user_id"):
        raise ApiError("ERR_SOD_ASSESS_SAME_ACTOR")
    if outcome == "PASS" and score is None:
        raise ApiError("ERR_TRACK_FIELD_MISMATCH")
    if record["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_TRAINING_STATE")
    if outcome == "PASS" and score < 70:
        raise ApiError("ERR_INVALID_TRAINING_STATE")

    record["attempt_count"] = record["attempt_count"] + 1
    record["assessed_by_user_id"] = actor.user_id
    if score is not None:
        record["score"] = score
    if outcome == "FAIL":
        record["status"] = "ASSESSED_FAIL"
    else:
        record["status"] = "ASSESSED_PASS"
        passed_at = logical_clock.now()
        set_system_dt(record, "passed_at", passed_at)
        set_system_dt(record, "expires_on", passed_at + timedelta(days=calc.TRAINING_VALIDITY_DAYS))
    touch(record)
    derive.sync()
    return object_response(public(record))


@bp.post("/training-records/<record_id>/reenroll")
def reenroll_training(record_id):
    authorize(("EducationDirector",))
    record = lookup("training", record_id)
    if record["status"] != "ASSESSED_FAIL":
        raise ApiError("ERR_INVALID_TRAINING_STATE")
    if record["attempt_count"] >= 3:
        raise ApiError("ERR_TRAINING_ATTEMPTS_EXHAUSTED")
    record["status"] = "ENROLLED"
    record["score"] = None
    touch(record)
    derive.sync()
    return object_response(public(record))
