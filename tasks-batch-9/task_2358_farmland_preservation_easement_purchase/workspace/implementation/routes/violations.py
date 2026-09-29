"""Violation endpoints (PRD 3.8)."""

from flask import Blueprint

from db import db, touch
from errors import ApiError
from middleware import authenticate
from response import created, ok
from services import cascade, lookup, serialize
from validation import Payload, body_fk, raw_body

bp = Blueprint("violations", __name__)

VIOLATION_TYPES = (
    "IMPERVIOUS_EXCEEDANCE",
    "UNAUTHORIZED_SUBDIVISION",
    "PROHIBITED_USE",
    "EXCESS_DWELLING",
)


@bp.post("/violations")
def open_violation():
    authenticate(("StewardshipMonitor", "ProgramAdmin"))
    body = raw_body()
    easement = lookup.get_easement(body_fk(body, "easement_id"))
    visit = None
    if body_fk(body, "monitoring_visit_id") is not None:
        visit = lookup.get_visit(body_fk(body, "monitoring_visit_id"))
    payload = Payload(
        body,
        (
            "easement_id",
            "violation_type",
            "excess_sqft",
            "monitoring_visit_id",
            "notes",
        ),
    )
    payload.string("easement_id", min_len=1)
    violation_type = payload.enum("violation_type", VIOLATION_TYPES)
    excess_sqft = payload.integer("excess_sqft", required=False, default=0, minimum=0)
    payload.string(
        "monitoring_visit_id", required=False, default=None, min_len=1
    )
    payload.string("notes", required=False, default=None, min_len=1, max_len=2000)

    if violation_type == "IMPERVIOUS_EXCEEDANCE":
        if excess_sqft <= 0:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "excess_sqft must be strictly positive on an IMPERVIOUS_EXCEEDANCE",
            )
    else:
        excess_sqft = 0

    # rung 9 -- deed dimension.
    if easement["status"] not in ("RECORDED", "AMENDED"):
        raise ApiError(
            "ERR_INVALID_EASEMENT_STATE",
            "only a RECORDED or AMENDED easement can be found in violation",
        )

    # rung 16 -- referential scope.
    if visit is not None and visit["easement_id"] != easement["id"]:
        raise ApiError(
            "ERR_VISIT_EASEMENT_MISMATCH",
            "the monitoring visit belongs to a different easement",
        )

    row = cascade.open_violation(
        easement,
        violation_type,
        excess_sqft,
        visit["id"] if visit is not None else None,
    )
    return created(serialize.violation(row))


@bp.get("/violations/<violation_id>")
def read_violation(violation_id):
    authenticate(("ProgramAdmin", "StewardshipMonitor", "Landowner"))
    return ok(serialize.violation(lookup.get_violation(violation_id)))


@bp.post("/violations/<violation_id>/cure-plan")
def accept_cure_plan(violation_id):
    authenticate(("StewardshipMonitor",))
    violation = lookup.get_violation(violation_id)
    payload = Payload(raw_body(), ("cure_plan_note",))
    note = payload.string("cure_plan_note", min_len=1, max_len=2000)

    if violation["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_VIOLATION_STATE",
            "a cure plan is only accepted on an OPEN violation",
        )
    if db.clock > violation["cure_deadline_on"]:
        raise ApiError(
            "ERR_INVALID_VIOLATION_STATE",
            "the cure deadline has already passed",
        )

    violation["status"] = "CURE_PLAN_ACCEPTED"
    violation["cure_plan_note"] = note
    touch(violation)
    return ok(serialize.violation(violation))


@bp.post("/violations/<violation_id>/cure-verification")
def verify_cure(violation_id):
    authenticate(("StewardshipMonitor",))
    violation = lookup.get_violation(violation_id)
    payload = Payload(raw_body(), ("verification_note",))
    payload.string(
        "verification_note", required=False, default=None, min_len=1, max_len=2000
    )

    if violation["status"] not in ("CURE_PLAN_ACCEPTED", "ESCALATED"):
        raise ApiError(
            "ERR_INVALID_VIOLATION_STATE",
            "a cure is only verified from CURE_PLAN_ACCEPTED or ESCALATED",
        )
    if (
        violation["status"] == "CURE_PLAN_ACCEPTED"
        and db.clock > violation["cure_deadline_on"]
    ):
        raise ApiError(
            "ERR_INVALID_VIOLATION_STATE", "the cure deadline has already passed"
        )

    violation["status"] = "CURED"
    violation["cured_on"] = db.clock
    touch(violation)

    easement = db.easements[violation["easement_id"]]
    if violation["violation_type"] == "IMPERVIOUS_EXCEEDANCE":
        easement["impervious_used_sqft"] = min(
            int(easement["impervious_used_sqft"] or 0),
            int(easement["impervious_allowance_sqft"]),
        )
    if lookup.easement_open_violation_count(easement["id"]) == 0:
        easement["compliance_status"] = "VIOLATION_CURED"
        easement["stewardship_hold"] = False
    touch(easement)
    return ok(serialize.violation(violation))
