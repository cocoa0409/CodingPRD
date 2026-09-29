"""Committee composition, seats and the dean's ruling (PRD section 3.3)."""

import lookup
import serializers
import validate
from db import by_created_at, db, new_row, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import array_response, object_response
from routes import common
from routes.common import ALL_ROLES, PREFIX
from services import calc, counters
from services.clearance import recompute_for_thesis

bp = Blueprint("committees", __name__, url_prefix=PREFIX)

SEAT_ROLES = ("CHAIR", "CO_CHAIR", "MEMBER", "EXTERNAL_MEMBER", "GRADUATE_REPRESENTATIVE")
SEAT_STATUSES = ("CONFIRMED", "WITHDRAWN")
COMMITTEE_DECISIONS = ("APPROVE", "REJECT")

RELEASE_ALLOWED_COMMITTEE = ("DRAFT", "REJECTED", "SUBMITTED", "APPROVED")


def _thesis_of(committee):
    return db.theses.get(committee["thesis_id"])


def _apply_seat_change(committee, thesis):
    """Recompute the composition counters and fire the revert cascade if needed."""
    counts = calc.committee_composition_counts(committee["id"])
    fields = {
        "member_count": counts["member_count"],
        "external_member_count": counts["external_member_count"],
    }
    cascade = committee["status"] == "APPROVED" and thesis is not None and thesis[
        "workflow_state"
    ] in ("COMMITTEE_APPROVED", "DEFENSE_SCHEDULED", "DEFENSE_ANNOUNCED")
    if cascade:
        fields.update(
            status="SUBMITTED", approved_by_user_id=None, approved_at=None
        )
    write(committee, **fields)

    if cascade:
        write(thesis, workflow_state="COMMITTEE_PENDING")
        touched_rooms = []
        for event in lookup.events_of_thesis(thesis["id"]):
            if event["status"] in ("DRAFT", "ANNOUNCED"):
                write(
                    event,
                    status="CANCELLED",
                    cancellation_reason=calc.COMMITTEE_CHANGE_REASON,
                )
                touched_rooms.append(event["room_id"])
        counters.recompute_rooms(touched_rooms)

    counters.recompute_all_chair_loads()
    if thesis is not None:
        recompute_for_thesis(thesis)


# --------------------------------------------------------------------- reads


@bp.get("/committee-members/<member_id>")
@endpoint(ALL_ROLES)
def read_seat(user_id, role, member_id):
    return object_response(
        serializers.committee_member(lookup.get_committee_member(member_id))
    )


@bp.get("/committee-members")
@endpoint(ALL_ROLES)
def list_seats(user_id, role):
    limit, offset = validate.pagination()
    committee_id = validate.query_str("committee_id")
    faculty_id = validate.query_str("faculty_id")
    status = validate.query_enum("status", SEAT_STATUSES)

    rows = list(db.committee_members.values())
    if committee_id is not None:
        rows = [r for r in rows if r["committee_id"] == committee_id]
    if faculty_id is not None:
        rows = [r for r in rows if r["faculty_id"] == faculty_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    else:
        rows = [r for r in rows if r["status"] != "WITHDRAWN"]

    rows = by_created_at(rows)
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.committee_member(row) for row in page], limit, offset, total
    )


# -------------------------------------------------------------------- writes


@bp.post("/committees")
@endpoint(["Student"])
def create_committee(user_id, role):
    body = validate.get_body()
    thesis_id = validate.req_str(body, "thesis_id")
    thesis = lookup.get_thesis(thesis_id)
    common.require_owner(role, user_id, thesis)
    common.require_term_open(thesis)

    if lookup.committee_of_thesis(thesis["id"]) is not None:
        fail(
            "ERR_INVALID_REQUEST",
            "A committee already exists for thesis '%s'" % thesis["id"],
        )

    row = new_row(
        thesis_id=thesis["id"],
        status="DRAFT",
        member_count=0,
        external_member_count=0,
        approved_by_user_id=None,
        approved_at=None,
        rejection_note=None,
    )
    db.committees[row["id"]] = row
    return object_response(serializers.committee(row), 201)


@bp.post("/committees/<committee_id>/members")
@endpoint(["Student", "Registrar"])
def seat_member(user_id, role, committee_id):
    committee = lookup.get_committee(committee_id)
    body = validate.get_body()
    faculty_id = validate.req_str(body, "faculty_id")
    seat_role = validate.req_enum(body, "role", SEAT_ROLES)
    faculty = lookup.get_faculty(faculty_id)

    thesis = _thesis_of(committee)
    if thesis is not None:
        common.require_owner(role, user_id, thesis)
        common.require_term_open(thesis)

    if committee["status"] == "DISSOLVED":
        fail(
            "ERR_COMMITTEE_STATE_INVALID",
            "A DISSOLVED committee cannot gain seats",
        )

    if seat_role in calc.CHAIR_ROLES:
        if faculty["appointment_type"] not in ("TENURED", "TENURE_TRACK"):
            fail(
                "ERR_CHAIR_NOT_ELIGIBLE",
                "Only TENURED or TENURE_TRACK faculty may chair",
            )
        if not faculty["graduate_faculty_certified"]:
            fail(
                "ERR_CHAIR_NOT_ELIGIBLE",
                "A chair must be graduate-faculty certified",
            )
        if calc.faculty_active_chair_load(faculty["id"]) >= calc.MAX_CHAIR_LOAD:
            fail(
                "ERR_CHAIR_NOT_ELIGIBLE",
                "The faculty member already carries the maximum chair load",
            )

    seats = lookup.confirmed_seats(committee["id"])
    if any(seat["faculty_id"] == faculty["id"] for seat in seats):
        fail(
            "ERR_COMMITTEE_SEAT_CONFLICT",
            "The faculty member already holds a confirmed seat on this committee",
        )
    if seat_role == "CHAIR" and any(seat["role"] == "CHAIR" for seat in seats):
        fail("ERR_COMMITTEE_SEAT_CONFLICT", "The committee already has a CHAIR seat")
    if seat_role == "GRADUATE_REPRESENTATIVE" and any(
        seat["role"] == "GRADUATE_REPRESENTATIVE" for seat in seats
    ):
        fail(
            "ERR_COMMITTEE_SEAT_CONFLICT",
            "The committee already has a GRADUATE_REPRESENTATIVE seat",
        )
    if seat_role == "EXTERNAL_MEMBER" and faculty["appointment_type"] != "EXTERNAL":
        fail(
            "ERR_COMMITTEE_SEAT_CONFLICT",
            "An EXTERNAL_MEMBER seat requires an EXTERNAL appointment",
        )

    row = new_row(
        committee_id=committee["id"],
        faculty_id=faculty["id"],
        role=seat_role,
        status="CONFIRMED",
        withdrawal_reason=None,
    )
    db.committee_members[row["id"]] = row

    _apply_seat_change(committee, thesis)
    return object_response(serializers.committee_member(row), 201)


@bp.delete("/committee-members/<member_id>")
@endpoint(["Student", "Registrar"])
def release_seat(user_id, role, member_id):
    seat = lookup.get_committee_member(member_id)
    body = validate.get_body()
    reason = validate.opt_str(body, "withdrawal_reason")

    committee = db.committees.get(seat["committee_id"])
    thesis = _thesis_of(committee) if committee is not None else None
    if thesis is not None:
        common.require_owner(role, user_id, thesis)
        common.require_term_open(thesis)

    if seat["status"] != "CONFIRMED":
        fail("ERR_COMMITTEE_STATE_INVALID", "The seat has already been released")
    if committee is None or committee["status"] not in RELEASE_ALLOWED_COMMITTEE:
        fail(
            "ERR_COMMITTEE_STATE_INVALID",
            "Seats cannot be released from a DISSOLVED committee",
        )

    write(seat, status="WITHDRAWN", withdrawal_reason=reason)
    _apply_seat_change(committee, thesis)
    return object_response(serializers.committee_member(seat))


@bp.post("/committees/<committee_id>/submit")
@endpoint(["Student"])
def submit_committee(user_id, role, committee_id):
    committee = lookup.get_committee(committee_id)
    thesis = _thesis_of(committee)
    if thesis is not None:
        common.require_owner(role, user_id, thesis)
        common.require_term_open(thesis)

    if thesis is None or thesis["workflow_state"] != "DRAFT":
        fail(
            "ERR_THESIS_STATE_INVALID",
            "A composition may only be submitted while the document is DRAFT",
        )
    if committee["status"] not in ("DRAFT", "REJECTED"):
        fail(
            "ERR_COMMITTEE_STATE_INVALID",
            "Only a DRAFT or REJECTED committee may be submitted",
        )

    counts = calc.committee_composition_counts(committee["id"])
    if not calc.composition_satisfies(thesis["document_type"], counts):
        fail(
            "ERR_COMMITTEE_COMPOSITION_INVALID",
            "The composition does not satisfy the minimums for a %s"
            % thesis["document_type"],
        )

    write(
        committee,
        status="SUBMITTED",
        member_count=counts["member_count"],
        external_member_count=counts["external_member_count"],
    )
    write(thesis, workflow_state="COMMITTEE_PENDING")
    counters.recompute_all_chair_loads()
    recompute_for_thesis(thesis)
    return object_response(serializers.committee(committee))


@bp.post("/committees/<committee_id>/decision")
@endpoint(["GraduateDean"])
def decide_committee(user_id, role, committee_id):
    committee = lookup.get_committee(committee_id)
    body = validate.get_body()
    decision = validate.req_enum(body, "decision", COMMITTEE_DECISIONS)
    rejection_note = validate.opt_str(body, "rejection_note")

    thesis = _thesis_of(committee)
    if thesis is not None:
        common.require_term_open(thesis)

    if committee["status"] != "SUBMITTED":
        fail(
            "ERR_COMMITTEE_STATE_INVALID",
            "Only a SUBMITTED committee may be ruled on",
        )

    counts = calc.committee_composition_counts(committee["id"])
    if decision == "APPROVE":
        if thesis is not None and not calc.composition_satisfies(
            thesis["document_type"], counts
        ):
            fail(
                "ERR_COMMITTEE_COMPOSITION_INVALID",
                "The composition no longer satisfies the minimums for a %s"
                % thesis["document_type"],
            )
        write(
            committee,
            status="APPROVED",
            approved_by_user_id=user_id,
            approved_at=clock.now(),
            member_count=counts["member_count"],
            external_member_count=counts["external_member_count"],
        )
        if thesis is not None:
            write(thesis, workflow_state="COMMITTEE_APPROVED")
    else:
        write(
            committee,
            status="REJECTED",
            rejection_note=rejection_note,
            member_count=counts["member_count"],
            external_member_count=counts["external_member_count"],
        )
        if thesis is not None:
            write(thesis, workflow_state="DRAFT")

    counters.recompute_all_chair_loads()
    if thesis is not None:
        recompute_for_thesis(thesis)
    return object_response(serializers.committee(committee))
