"""AgeScreen endpoints (PRD §3.3)."""
from flask import Blueprint, g

import calculations as calc
from constants import (
    AGE_SCREEN_MECHANISMS,
    AGE_SCREEN_STATUSES,
    MAX_SCREEN_REVISION_ROUNDS,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PRIVACY_ENGINEER,
)
from db import db, now, touch
from errors import fail
from helpers import base_row, resolve, resolve_body_fk
from middleware import authenticate, body, opt_bool, opt_int, opt_string, req_enum
from response import created, ok
from serializers import age_screen_out

bp = Blueprint("age_screens", __name__)

# from -> to : the single role permitted for that transition (PRD §3.3)
TRANSITION_ACTOR = {
    ("DRAFT", "IN_REVIEW"): ROLE_PRIVACY_ENGINEER,
    ("IN_REVIEW", "ACTIVE"): ROLE_COMPLIANCE_OFFICER,
    ("IN_REVIEW", "REJECTED"): ROLE_COMPLIANCE_OFFICER,
    ("REJECTED", "DRAFT"): ROLE_PRIVACY_ENGINEER,
    ("ACTIVE", "RETIRED"): ROLE_COMPLIANCE_OFFICER,
}


@bp.post("/age-screens")
@authenticate(ROLE_PRIVACY_ENGINEER)
def create_age_screen():
    data = body()
    service = resolve_body_fk("service", data, "service_id")
    mechanism = req_enum(data, "mechanism", AGE_SCREEN_MECHANISMS)

    screen = base_row()
    screen.update(
        {
            "service_id": service["id"],
            "mechanism": mechanism,
            "default_prefilled_age": opt_int(data, "default_prefilled_age", None),
            "retry_allowed_on_fail": opt_bool(data, "retry_allowed_on_fail", False),
            "outcome_session_persisted": opt_bool(data, "outcome_session_persisted", True),
            "inherited_from_verified_account": opt_bool(
                data, "inherited_from_verified_account", False
            ),
            "status": "DRAFT",
            "revision_round": 0,
            "activated_at": None,
            "review_note": None,
        }
    )
    db.age_screens[screen["id"]] = screen
    return created(age_screen_out(screen))


@bp.post("/age-screens/<screen_id>/status")
@authenticate(ROLE_PRIVACY_ENGINEER, ROLE_COMPLIANCE_OFFICER)
def set_age_screen_status(screen_id):
    screen = resolve("age_screen", screen_id)
    data = body()
    to_status = req_enum(data, "to_status", AGE_SCREEN_STATUSES)
    review_note = opt_string(data, "review_note")

    transition = (screen["status"], to_status)
    if transition not in TRANSITION_ACTOR:
        fail("ERR_INVALID_STATE")
    if g.role != TRANSITION_ACTOR[transition]:
        fail("ERR_TRANSITION_ROLE_NOT_PERMITTED")

    if transition == ("IN_REVIEW", "ACTIVE"):
        if calc.age_screen_neutrality(screen):
            fail("ERR_AGE_SCREEN_NOT_NEUTRAL")
    elif transition == ("REJECTED", "DRAFT"):
        if screen["revision_round"] >= MAX_SCREEN_REVISION_ROUNDS:
            fail("ERR_SCREEN_REVISIONS_EXHAUSTED")

    if review_note is not None:
        screen["review_note"] = review_note

    screen["status"] = to_status

    if transition == ("IN_REVIEW", "ACTIVE"):
        screen["activated_at"] = now()
        # At most one live screen per service.
        for other in db.age_screens.values():
            if (
                other["id"] != screen["id"]
                and other["service_id"] == screen["service_id"]
                and other["status"] == "ACTIVE"
            ):
                other["status"] = "RETIRED"
                touch(other)
    elif transition == ("REJECTED", "DRAFT"):
        screen["revision_round"] += 1

    touch(screen)
    return ok(age_screen_out(screen))
