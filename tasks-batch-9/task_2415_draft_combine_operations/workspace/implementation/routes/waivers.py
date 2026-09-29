"""The bounded eligibility-waiver review loop (PRD 3.2, 2.10)."""

from flask import Blueprint

import auth
import constants as K
import derive
import logic
import respond
import validate
from db import db
from errors import ApiError

bp = Blueprint("waivers", __name__)

REVIEW_ROLES = {
    "OPEN_REVIEW": ("EligibilityCommittee",),
    "REQUEST_INFO": ("EligibilityCommittee",),
    "GRANT": ("EligibilityCommittee",),
    "DENY": ("EligibilityCommittee",),
    "WITHDRAW": ("ProspectAgent",),
}

ACTIONS = ("OPEN_REVIEW", "REQUEST_INFO", "GRANT", "DENY", "WITHDRAW")


def _sod(detail):
    raise ApiError("ERR_SEGREGATION_OF_DUTIES", detail)


@bp.post("/eligibility-waivers/<waiver_id>/review")
def review(waiver_id):
    user_id, role = auth.actor()
    auth.require(role, ["EligibilityCommittee", "ProspectAgent"])
    auth.require_action_role(role, validate.peek("action"), REVIEW_ROLES)

    data = validate.body()
    action = validate.enum(data, "action", ACTIONS)
    decision_note = None
    if action in ("GRANT", "DENY"):
        decision_note = validate.string(data, "decision_note")

    waiver = logic.path_lookup(db.eligibility_waivers, waiver_id)
    prospect = db.prospects.get(waiver["prospect_id"])

    if action == "WITHDRAW" and role == "ProspectAgent":
        logic.own_prospect(role, user_id, waiver["prospect_id"])

    if prospect is not None:
        logic.require_unfrozen(derive.prospect_cycle(prospect))

    current = waiver["status"]

    if action == "OPEN_REVIEW":
        if current not in ("SUBMITTED", "INFO_REQUESTED"):
            raise logic.invalid_transition(
                "Review may only be opened from SUBMITTED or INFO_REQUESTED."
            )
        if current == "SUBMITTED" and user_id == waiver["submitted_by_user_id"]:
            _sod("The filer of a waiver may not open review of it.")
        waiver["status"] = "UNDER_REVIEW"
        waiver["opened_by_user_id"] = user_id
        return respond.ok(waiver)

    if action == "REQUEST_INFO":
        if current != "UNDER_REVIEW":
            raise logic.invalid_transition(
                "Information may only be requested from UNDER_REVIEW."
            )
        if waiver["info_request_count"] >= K.WAIVER_MAX_INFO_REQUESTS:
            raise ApiError(
                "ERR_WAIVER_ROUNDS_EXHAUSTED",
                "This waiver has exhausted its information requests.",
            )
        waiver["status"] = "INFO_REQUESTED"
        waiver["info_request_count"] += 1
        return respond.ok(waiver)

    if action in ("GRANT", "DENY"):
        if current != "UNDER_REVIEW":
            raise logic.invalid_transition(
                "A waiver may only be decided from UNDER_REVIEW."
            )
        if user_id == waiver["opened_by_user_id"]:
            _sod("The reviewer who opened this waiver may not decide it.")
        waiver["status"] = "GRANTED" if action == "GRANT" else "DENIED"
        waiver["decided_by_user_id"] = user_id
        waiver["decision_note"] = decision_note
        waiver["decided_at"] = db.now
        if action == "GRANT" and prospect is not None:
            if waiver["waiver_type"] == "LATE_DECLARATION":
                prospect["late_declaration_waived"] = True
            elif waiver["waiver_type"] == "EARLY_ENTRY":
                prospect["early_entry_waived"] = True
        return respond.ok(waiver)

    # WITHDRAW
    if current != "SUBMITTED":
        raise logic.invalid_transition("Only a SUBMITTED waiver may be withdrawn.")
    waiver["status"] = "WITHDRAWN"
    return respond.ok(waiver)
