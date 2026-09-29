"""Appeal endpoints: filing and adjudication."""
from flask import Blueprint

from db import db, new_row, now, now_iso, parse_instant, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.ledger import (
    applicant_of_project,
    cascade_applicant,
    recompute_project_deobligations,
)
from validate import body, v_enum, v_id, v_int, v_str

bp = Blueprint("appeals", __name__)

DECISIONS = ("GRANT", "PARTIALLY_GRANT", "DENY", "REMAND")


def _appeals_of(deobligation_id):
    return [a for a in db.appeals.values() if a["deobligation_id"] == deobligation_id]


def _applicant_of_deobligation(deob):
    project = find("projects", deob["project_id"]) if deob else None
    return applicant_of_project(project)


@bp.route(PREFIX + "/appeals", methods=["POST"])
def create_appeal():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_deob = payload.get("deobligation_id")
    if isinstance(raw_deob, str):
        deob = find("deobligations", raw_deob)
        if deob is not None:
            project = find("projects", deob["project_id"])
            if project is not None:
                check_scope(actor, project["applicant_id"])

    deobligation_id = v_id(payload, "deobligation_id")
    grounds = v_str(payload, "grounds")
    relief_requested_cents = v_int(payload, "relief_requested_cents", minimum=1)
    prior_appeal_id = v_id(payload, "prior_appeal_id", required=False, default=None)

    deobligation = require("deobligations", deobligation_id)
    prior = require("appeals", prior_appeal_id) if prior_appeal_id else None

    if deobligation["status"] != "FINAL":
        fail("ERR_DEOBLIGATION_NOT_FINAL",
             "only a FINAL determination may be appealed")

    filed_at = now_iso()
    deadline = deobligation["appeal_deadline_at"]
    parsed = parse_instant(deadline)
    if parsed is None or now() > parsed:
        fail("ERR_APPEAL_WINDOW_EXPIRED",
             "the sixty-day appeal window has closed")

    level = "SECOND" if prior_appeal_id else "FIRST"

    siblings = _appeals_of(deobligation_id)

    if level == "SECOND":
        if prior["deobligation_id"] != deobligation_id \
                or prior["status"] not in ("DENIED", "PARTIALLY_GRANTED"):
            fail("ERR_SECOND_APPEAL_REQUIRES_FIRST_DENIED",
                 "prior_appeal_id must reference a lost first-level appeal on this"
                 " determination")

    if any(a["status"] == "SUBMITTED" for a in siblings):
        fail("ERR_DUPLICATE_APPEAL",
             "another appeal on this determination is still SUBMITTED")

    if any(a["level"] == "SECOND" for a in siblings):
        fail("ERR_APPEAL_LEVEL_EXHAUSTED",
             "this determination already carries a SECOND-level appeal")

    if relief_requested_cents > deobligation["amount_cents"]:
        fail("ERR_RELIEF_EXCEEDS_DEOBLIGATION",
             "relief_requested_cents exceeds the determination amount")

    row = new_row("appeals", {
        "deobligation_id": deobligation_id,
        "prior_appeal_id": prior_appeal_id,
        "level": level,
        "grounds": grounds,
        "relief_requested_cents": relief_requested_cents,
        "relief_granted_cents": 0,
        "status": "SUBMITTED",
        "filed_at": filed_at,
        "decided_at": None,
        "decided_by_user_id": None,
        "decision_rationale": None,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/appeals", methods=["GET"])
def list_appeals():
    authenticate(ALL_ROLES)
    return render_list("appeals", {
        "deobligation_id": "deobligation_id",
        "prior_appeal_id": "prior_appeal_id",
        "status": "status",
        "level": "level",
    })


@bp.route(PREFIX + "/appeals/<appeal_id>", methods=["GET"])
def get_appeal(appeal_id):
    actor = authenticate(ALL_ROLES)
    row = find("appeals", appeal_id)
    if row is not None:
        applicant = _applicant_of_deobligation(find("deobligations",
                                                    row["deobligation_id"]))
        if applicant is not None:
            check_scope(actor, applicant["id"])
    row = require("appeals", appeal_id)
    return respond(row)


@bp.route(PREFIX + "/appeals/<appeal_id>/decide", methods=["POST"])
def decide_appeal(appeal_id):
    actor = authenticate(("AppealsAdjudicator",))
    appeal = require("appeals", appeal_id)
    payload = body()

    decision = v_enum(payload, "decision", DECISIONS)
    rationale = v_str(payload, "decision_rationale", non_empty=False)
    granted_input = v_int(payload, "relief_granted_cents", required=False,
                          default=None, minimum=0)
    if decision == "REMAND" and appeal["level"] != "FIRST":
        fail("ERR_INVALID_REQUEST",
             "REMAND is available only on a FIRST-level appeal")

    if appeal["status"] != "SUBMITTED":
        fail("ERR_APPEAL_ALREADY_DECIDED", "this appeal has already been decided")

    deobligation = find("deobligations", appeal["deobligation_id"])

    if deobligation is not None \
            and deobligation["determined_by_user_id"] == actor.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the user who made the determination may not decide its appeal")

    if decision == "GRANT":
        granted = appeal["relief_requested_cents"]
    elif decision == "PARTIALLY_GRANT":
        if granted_input is None or granted_input <= 0 \
                or granted_input >= appeal["relief_requested_cents"]:
            fail("ERR_RELIEF_EXCEEDS_DEOBLIGATION",
                 "relief_granted_cents must be strictly between 0 and"
                 " relief_requested_cents")
        granted = granted_input
    else:
        granted = 0

    status_map = {
        "GRANT": "GRANTED",
        "PARTIALLY_GRANT": "PARTIALLY_GRANTED",
        "DENY": "DENIED",
        "REMAND": "REMANDED",
    }
    setf(appeal, "relief_granted_cents", granted)
    setf(appeal, "status", status_map[decision])
    setf(appeal, "decided_at", now_iso())
    setf(appeal, "decided_by_user_id", actor.user_id)
    setf(appeal, "decision_rationale", rationale)
    touch(appeal)

    if decision in ("GRANT", "PARTIALLY_GRANT") and deobligation is not None:
        reversed_total = deobligation["reversed_cents"] + granted
        setf(deobligation, "reversed_cents", reversed_total)
        if reversed_total >= deobligation["amount_cents"]:
            setf(deobligation, "status", "REVERSED")
        touch(deobligation)
        _cascade_from(deobligation)
    elif decision == "REMAND" and deobligation is not None:
        setf(deobligation, "status", "PROPOSED")
        setf(deobligation, "finalized_at", None)
        setf(deobligation, "appeal_deadline_at", None)
        touch(deobligation)
        _cascade_from(deobligation)

    return respond(appeal)


def _cascade_from(deobligation):
    project = find("projects", deobligation["project_id"])
    if project is None:
        return
    recompute_project_deobligations(project)
    touch(project)
    applicant = applicant_of_project(project)
    disaster = cascade_applicant(applicant)
    if applicant is not None:
        touch(applicant)
    if disaster is not None:
        touch(disaster)
