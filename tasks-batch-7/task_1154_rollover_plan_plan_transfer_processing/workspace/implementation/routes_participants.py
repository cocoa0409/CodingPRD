"""Participants (PRD §3.2)."""

from flask import Blueprint, g

import errors
from db import create_entity, store
from middleware import ALL_ROLES, body, opt_str, req_enum, req_str, require_roles
from response import ok
from services import EMPLOYMENT_STATUSES, MARITAL_STATUSES, parse_date, req_date, serialize_participant

bp = Blueprint("participants", __name__)


@bp.post("/v1/participants")
@require_roles("PlanSponsorAdmin")
def create_participant():
    data = body()
    full_name = req_str(data, "full_name")
    dob = req_date(data, "date_of_birth")
    employment_status = req_enum(data, "employment_status", EMPLOYMENT_STATUSES)
    marital_status = req_enum(data, "marital_status", MARITAL_STATUSES)
    separation_date = opt_str(data, "separation_date")
    if employment_status in ("SEPARATED", "RETIRED") and not separation_date:
        raise errors.err_validation("separation_date is required when employment_status is SEPARATED or RETIRED")
    if separation_date is not None and parse_date(separation_date) is None:
        raise errors.err_validation("separation_date must be an ISO date YYYY-MM-DD")
    participant = create_entity(
        store.participants,
        {
            "full_name": full_name,
            "date_of_birth": dob.isoformat(),
            "employment_status": employment_status,
            "separation_date": separation_date,
            "marital_status": marital_status,
        },
    )
    return ok(serialize_participant(participant), status=201)


@bp.get("/v1/participants/<participant_id>")
@require_roles(*ALL_ROLES)
def get_participant(participant_id):
    p = store.participants.get(participant_id)
    if p is None:
        raise errors.err_participant_not_found()
    if g.role == "Participant" and g.user_id != participant_id:
        # Ownership scoping masked as not-found (PRD §2.1).
        raise errors.err_participant_not_found()
    return ok(serialize_participant(p))
