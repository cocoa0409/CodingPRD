"""Team seats: seating a visitor and releasing a seat."""

from datetime import date, timedelta

from flask import Blueprint

import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("assignments", __name__)

TRAVEL_BUFFER_DAYS = 2


@bp.get("/accreditation/visit-assignments/<assignment_id>")
def get_assignment(assignment_id):
    authenticate(("AccreditationOfficer", "Visitor"))
    return response.ok(helpers.public(helpers.assignment_or_404(assignment_id)))


@bp.get("/accreditation/visit-assignments")
def list_assignments():
    authenticate(("AccreditationOfficer", "Visitor"))
    return helpers.collection_response(db.assignments, helpers.ASSIGNMENT_FILTERS)


@bp.post("/accreditation/visit-assignments")
def seat_visitor():
    authenticate(("AccreditationOfficer",))
    data = validators.body()
    visit_id = validators.require(data, "visit_id")
    visitor_id = validators.require(data, "visitor_id")
    if not isinstance(visit_id, str) or not isinstance(visitor_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Identifier fields must be strings.")
    team_role = validators.req_enum(data, "team_role", domain.TEAM_ROLES)
    block_start = validators.req_date(data, "travel_block_start_date")
    block_end = validators.req_date(data, "travel_block_end_date")
    if block_end < block_start:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "travel_block_end_date may not precede travel_block_start_date.",
        )

    visitor = helpers.visitor_or_404(visitor_id)
    visit = helpers.visit_or_404(visit_id)
    cycle = db.cycles.get(visit["cycle_id"])
    camp = db.camps.get(cycle["camp_id"]) if cycle else None

    if visit["status"] != "DRAFT":
        raise api_error(
            "ERR_VISIT_INVALID_STATE", "Seats may only be added to a DRAFT visit."
        )
    if visitor["status"] != "ACTIVE":
        raise api_error("ERR_VISITOR_INACTIVE", "The visitor is not ACTIVE.")

    if visitor["employer_camp_id"] == camp["id"] or (
        team_role == "LEAD" and visitor["home_state_code"] == camp["state_code"]
    ):
        raise api_error(
            "ERR_VISITOR_CONFLICT_OF_INTEREST",
            "The visitor has a conflict of interest with the camp under review.",
        )

    buffer_days = timedelta(days=TRAVEL_BUFFER_DAYS)
    for seat in domain.visitor_assignments(visitor_id):
        if seat["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        stored_start = _as_date(seat["travel_block_start_date"]) - buffer_days
        stored_end = _as_date(seat["travel_block_end_date"]) + buffer_days
        if not (block_end < stored_start or block_start > stored_end):
            raise api_error(
                "ERR_VISITOR_TRAVEL_CONFLICT",
                "The visitor already holds an overlapping travel commitment.",
            )

    if visitor["trained_through_year"] < int(visit["window_start_date"][0:4]):
        raise api_error(
            "ERR_VISITOR_TRAINING_EXPIRED",
            "The visitor's training is not current for the visit year.",
        )

    if (
        block_start.isoformat() < visit["window_start_date"]
        or block_end.isoformat() > visit["window_end_date"]
    ):
        raise api_error(
            "ERR_TRAVEL_BLOCK_OUTSIDE_WINDOW",
            "The travel block must lie wholly inside the visit window.",
        )

    seat = db.common_fields()
    seat.update(
        {
            "visit_id": visit_id,
            "visitor_id": visitor_id,
            "team_role": team_role,
            "travel_block_start_date": block_start.isoformat(),
            "travel_block_end_date": block_end.isoformat(),
            "travel_days": (block_end - block_start).days + 1,
            "status": "ASSIGNED",
            "withdrawal_reason": None,
        }
    )
    db.assignments[seat["id"]] = seat

    domain.recompute_committed_travel_days(visitor)
    visit["team_size"] = visit["team_size"] + 1
    if team_role == "LEAD":
        visit["lead_visitor_id"] = visitor_id
    db.touch(visit)
    return response.created(helpers.public(seat))


def _as_date(value):
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


@bp.post("/accreditation/visit-assignments/<assignment_id>/withdraw")
def withdraw_assignment(assignment_id):
    authenticate(("AccreditationOfficer",))
    data = validators.body()
    reason = validators.opt_str(data, "withdrawal_reason", 0, 500)

    seat = helpers.assignment_or_404(assignment_id)
    visit = db.visits.get(seat["visit_id"])

    if visit is None or visit["status"] not in ("DRAFT", "SCHEDULED"):
        raise api_error(
            "ERR_VISIT_INVALID_STATE",
            "A seat may only be released while the visit is DRAFT or SCHEDULED.",
        )
    if seat["status"] != "ASSIGNED":
        raise api_error("ERR_VISIT_INVALID_STATE", "The seat is not ASSIGNED.")

    domain.withdraw_seat(seat, reason)
    domain.revert_visit_if_incomplete(visit)
    return response.ok(helpers.public(seat))
