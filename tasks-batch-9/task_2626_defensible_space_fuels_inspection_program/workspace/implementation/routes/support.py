"""Compliance-support programs, cost-share awards and enrollments (section 3.8)."""

from flask import Blueprint, g, request

import calc
import domain
from auth import auth, owner_must_match
from db import db, insert, sort_created
from errors import fail
from response import created, jsonable, ok, ok_list, touch
from validate import (
    body, check_window, get_bool, get_dt, get_enum, get_int, get_str, lookup, page,
    pagination, resolve_fks,
)

bp = Blueprint("support", __name__, url_prefix="/fire-district")

PROGRAM_TYPES = ("CHIPPER_DAY", "CURBSIDE_COLLECTION", "COST_SHARE_GRANT")


def _program(program_id):
    return lookup("programs", program_id, "ERR_PROGRAM_NOT_FOUND")


def _enrollment(enrollment_id):
    return lookup("enrollments", enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


@bp.post("/support-programs")
def create_program():
    auth("ProgramAdmin")
    b = body()
    resolved = resolve_fks(b, ["cycle_id"])
    cycle = resolved.get("cycle_id")
    if cycle is None:
        fail("ERR_INVALID_REQUEST", "Field 'cycle_id' is required.")
    program_type = get_enum(b, "program_type", PROGRAM_TYPES)
    budget_total = get_int(b, "budget_total_cents", minimum=0)
    capacity_slots = get_int(b, "capacity_slots", minimum=1)
    start = get_dt(b, "service_window_start_utc")
    end = get_dt(b, "service_window_end_utc")
    check_window(start, end)
    domain.require_active_cycle(cycle)
    program = insert(db.programs, {
        "cycle_id": cycle["id"],
        "program_type": program_type,
        "budget_total_cents": budget_total,
        "budget_remaining_cents": budget_total,
        "capacity_slots": capacity_slots,
        "reserved_slots": 0,
        "service_window_start_utc": start,
        "service_window_end_utc": end,
    })
    return created(jsonable(program))


@bp.get("/support-programs/<support_program_id>")
def read_program(support_program_id):
    auth("ProgramAdmin", "FireMarshal", "PropertyOwner", "CommunityOrganizer")
    return ok(jsonable(_program(support_program_id)))


@bp.get("/support-programs")
def list_programs():
    auth("ProgramAdmin", "FireMarshal", "PropertyOwner", "CommunityOrganizer")
    limit, offset = pagination()
    records = sort_created(list(db.programs.values()))
    for field in ("cycle_id", "program_type"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.post("/support-enrollments")
def create_enrollment():
    auth("ProgramAdmin", "PropertyOwner")
    b = body()
    # PRD section 2.6 declaration order puts parcel_id ahead of support_program_id.
    resolved = resolve_fks(b, ["parcel_id", "support_program_id"])
    parcel = resolved.get("parcel_id")
    program = resolved.get("support_program_id")
    if parcel is None:
        fail("ERR_INVALID_REQUEST", "Field 'parcel_id' is required.")
    if program is None:
        fail("ERR_INVALID_REQUEST", "Field 'support_program_id' is required.")
    owner_must_match(parcel["id"])
    expected = get_int(b, "expected_program_version")
    vendor_invoice = get_int(b, "vendor_invoice_cents", required=False, minimum=0)

    # Rung 7 — the cost-share invoice is strictly conditional.
    is_grant = program["program_type"] == "COST_SHARE_GRANT"
    if is_grant and vendor_invoice is None:
        fail("ERR_MISSING_VENDOR_INVOICE", "A cost-share grant requires vendor_invoice_cents.")
    if not is_grant and vendor_invoice is not None:
        fail(
            "ERR_MISSING_VENDOR_INVOICE",
            "vendor_invoice_cents applies only to a COST_SHARE_GRANT program.",
        )
    if expected != program["version"]:
        fail(
            "ERR_STALE_PROGRAM_VERSION",
            "The program has moved on since version %s." % expected,
        )
    for existing in domain.program_enrollments(program["id"]):
        if (
            existing["parcel_id"] == parcel["id"]
            and existing["status"] in domain.LIVE_ENROLLMENT_STATUSES
        ):
            fail("ERR_DUPLICATE_ENROLLMENT", "This parcel already holds a live enrollment.")
    domain.require_active_cycle(db.cycles.get(program["cycle_id"]))
    if not (
        program["service_window_start_utc"] <= db.clock < program["service_window_end_utc"]
    ):
        fail("ERR_PROGRAM_WINDOW_CLOSED", "The program's service window is closed.")
    if is_grant and vendor_invoice > calc.COST_SHARE_INVOICE_CAP_CENTS:
        fail(
            "ERR_COST_SHARE_CAP_EXCEEDED",
            "The vendor invoice exceeds the ceiling of %d cents."
            % calc.COST_SHARE_INVOICE_CAP_CENTS,
        )

    if is_grant:
        award = calc.cost_share_award(parcel, vendor_invoice)
    else:
        award = {
            "award_before_bonus_cents": None,
            "bonus_pct": None,
            "hardship_bonus_cents": None,
            "award_cents": None,
        }

    fields = {
        "support_program_id": program["id"],
        "parcel_id": parcel["id"],
        "vendor_invoice_cents": vendor_invoice,
        "status": "REQUESTED",
        "reserved_amount_cents": 0,
        "reimbursed_cents": 0,
        "waitlist_position": None,
    }
    fields.update(award)
    enrollment = insert(db.enrollments, fields)

    # Admission is decided inside this request; partial funding is never granted.
    slot_free = program["reserved_slots"] < program["capacity_slots"]
    funded = (not is_grant) or program["budget_remaining_cents"] >= enrollment["award_cents"]
    if slot_free and funded:
        enrollment["status"] = "APPROVED"
        if is_grant:
            enrollment["reserved_amount_cents"] = enrollment["award_cents"]
        domain.recount_program_reservations(program)
        touch(program)
    else:
        enrollment["status"] = "WAITLISTED"
        enrollment["reserved_amount_cents"] = 0
        already = sum(
            1 for e in domain.program_enrollments(program["id"])
            if e["status"] == "WAITLISTED" and e["id"] != enrollment["id"]
        )
        enrollment["waitlist_position"] = already + 1
    return created(jsonable(enrollment))


@bp.get("/support-enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    auth("ProgramAdmin", "FireMarshal", "PropertyOwner")
    return ok(jsonable(_enrollment(enrollment_id)))


@bp.get("/support-enrollments")
def list_enrollments():
    auth("ProgramAdmin", "FireMarshal", "PropertyOwner")
    limit, offset = pagination()
    records = sort_created(list(db.enrollments.values()))
    for field in ("support_program_id", "parcel_id", "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.post("/support-enrollments/<enrollment_id>/complete")
def complete_enrollment(enrollment_id):
    auth("ProgramAdmin")
    enrollment = _enrollment(enrollment_id)
    b = body()
    attended = get_bool(b, "attended")
    if enrollment["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED enrollment can be closed out.")
    program = db.programs.get(enrollment["support_program_id"])
    if attended:
        if program["program_type"] == "COST_SHARE_GRANT":
            # The reservation stays put: reimbursement disburses what was reserved.
            enrollment["status"] = "REIMBURSED"
            enrollment["reimbursed_cents"] = enrollment["award_cents"]
        else:
            enrollment["status"] = "COMPLETED"
        touch(enrollment)
    else:
        enrollment["status"] = "NO_SHOW"
        enrollment["reserved_amount_cents"] = 0
        touch(enrollment)
        domain.recount_program_reservations(program)
        touch(program)
    return ok(jsonable(enrollment))


@bp.post("/support-enrollments/<enrollment_id>/cancel")
def cancel_enrollment(enrollment_id):
    auth("ProgramAdmin", "PropertyOwner")
    enrollment = _enrollment(enrollment_id)
    owner_must_match(enrollment["parcel_id"])
    b = body()
    get_str(b, "reason")
    if enrollment["status"] not in ("APPROVED", "WAITLISTED"):
        fail("ERR_INVALID_STATE", "Only an APPROVED or WAITLISTED enrollment can be cancelled.")
    was_approved = enrollment["status"] == "APPROVED"
    program = db.programs.get(enrollment["support_program_id"])
    enrollment["status"] = "CANCELLED"
    if was_approved:
        enrollment["reserved_amount_cents"] = 0
        touch(enrollment)
        domain.recount_program_reservations(program)
        touch(program)
    else:
        enrollment["waitlist_position"] = None
        touch(enrollment)
        domain.renumber_waitlist(program)
    return ok(jsonable(enrollment))
