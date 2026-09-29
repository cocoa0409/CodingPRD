"""Medical screenings and the medical dimension they drive."""
from flask import Blueprint

import calc
import domain
import store
import web
from core import Field, authenticate, parse_body
from web import PREFIX

bp = Blueprint("medical", __name__)

SCREENING_FIELDS = [
    Field("athlete_id", "id"),
    Field("screened_by_user_id", "str"),
    Field("systolic_bp", "int", minimum=60, maximum=260),
    Field("resting_hr", "int", minimum=30, maximum=200),
    Field("prior_cardiac_event", "bool"),
]

MEDICAL_TARGET = {
    "CLEARED": "SCREENED_CLEARED",
    "CLEARED_WITH_RESTRICTION": "SCREENED_RESTRICTED",
    "HOLD_PENDING_PHYSICIAN_REVIEW": "SCREENED_HOLD",
}


def _apply_recommendation(athlete, recommendation):
    """The dimension moves out of NOT_SCREENED; the branches differ in their pull-back."""
    if athlete["medical_status"] != "NOT_SCREENED":
        return
    athlete["medical_status"] = MEDICAL_TARGET[recommendation]
    store.touch(athlete)
    if recommendation == "CLEARED":
        return
    for entry in domain.entries_of_athlete(athlete["id"], ("ACCEPTED",)):
        if recommendation == "CLEARED_WITH_RESTRICTION":
            event = domain.event_of_entry(entry)
            sport = domain.sport_of_event(event) if event is not None else None
            if sport is None or sport["contact_class"] != "HIGH":
                continue
        domain.hold_entry(entry)


@bp.post(PREFIX + "/medical-screenings")
def create_medical_screening():
    authenticate("MedicalDirector")
    body = parse_body(SCREENING_FIELDS)
    athlete = store.must_get("athlete", body["athlete_id"])
    contact_count = domain.contact_sport_count(athlete["id"])
    score = calc.risk_score(
        athlete["age_at_reference"],
        body["systolic_bp"],
        body["resting_hr"],
        body["prior_cardiac_event"],
        contact_count,
    )
    recommendation = calc.recommendation_for(score)
    row = store.insert(
        "medical_screening",
        {
            "athlete_id": athlete["id"],
            "screened_by_user_id": body["screened_by_user_id"],
            "systolic_bp": body["systolic_bp"],
            "resting_hr": body["resting_hr"],
            "prior_cardiac_event": body["prior_cardiac_event"],
            "contact_sport_count": contact_count,
            "risk_score": float(score),
            "recommendation": recommendation,
            "screened_at_utc": store.now_iso(),
        },
        versioned=False,
    )
    _apply_recommendation(athlete, recommendation)
    return web.obj(row, 201)


@bp.get(PREFIX + "/medical-screenings/<medical_screening_id>")
def read_medical_screening(medical_screening_id):
    return web.single("medical_screening", medical_screening_id)


@bp.get(PREFIX + "/medical-screenings")
def list_medical_screenings():
    return web.collection("medical_screening", ("athlete_id", "recommendation"))
