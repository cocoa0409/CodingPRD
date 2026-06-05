"""HomeExerciseProgram routes (scaffold §1.5; PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_or_404,
    require_date,
    require_fields,
    require_int,
    require_string,
)


bp = Blueprint("home_exercise_programs", __name__)


@bp.post("/rehab/home-exercise-programs")
def create_hep():
    require_auth(["Therapist"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "plan_of_care_id",
            "prescribed_by_therapist_id",
            "exercise_count",
            "weekly_frequency",
            "prescribed_on",
        ],
    )
    poc_id = require_string(body["plan_of_care_id"], "plan_of_care_id")
    therapist_id = require_string(body["prescribed_by_therapist_id"], "prescribed_by_therapist_id")
    exercise_count = require_int(
        body["exercise_count"], "exercise_count", min_value=1, max_value=20
    )
    weekly_frequency = require_int(
        body["weekly_frequency"], "weekly_frequency", min_value=1, max_value=14
    )
    prescribed_on = require_date(body["prescribed_on"], "prescribed_on")

    poc = lookup_or_404(db.plans_of_care, poc_id, "PlanOfCare")
    lookup_or_404(db.therapists, therapist_id, "Therapist")

    poc_start = db.parse_iso_date(poc["certified_start_date"])
    if poc_start is not None and prescribed_on < poc_start:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "prescribed_on must be on or after PlanOfCare.certified_start_date",
        )

    with db.mutation_lock:
        # Supersede prior ACTIVE HEPs on the same POC.
        for hep in db.home_exercise_programs.values():
            if hep["plan_of_care_id"] != poc_id:
                continue
            if hep["status"] == "ACTIVE":
                hep["status"] = "SUPERSEDED"
                db.bump(hep)

        new_hep = {
            "plan_of_care_id": poc_id,
            "prescribed_by_therapist_id": therapist_id,
            "exercise_count": exercise_count,
            "weekly_frequency": weekly_frequency,
            "prescribed_on": prescribed_on.isoformat(),
            "status": "ACTIVE",
        }
        db.stamp_common(new_hep)
        db.home_exercise_programs[new_hep["id"]] = new_hep
        return ok_object(new_hep, 201)


@bp.get("/rehab/home-exercise-programs/<hid>")
def get_hep(hid: str):
    require_auth(["PlatformAdmin", "Therapist", "CaseManager"])()
    hep = lookup_or_404(db.home_exercise_programs, hid, "HomeExerciseProgram")
    return ok_object(hep, 200)


@bp.get("/rehab/home-exercise-programs")
def list_heps():
    require_auth(["PlatformAdmin", "Therapist", "CaseManager"])()
    limit, offset = paginate_params(request.args)
    items = list(db.home_exercise_programs.values())
    for key in ("plan_of_care_id", "prescribed_by_therapist_id", "status"):
        if key in request.args:
            items = [h for h in items if h.get(key) == request.args.get(key)]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
