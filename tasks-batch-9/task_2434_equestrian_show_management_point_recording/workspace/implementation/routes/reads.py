"""Every GET endpoint (PRD section 4 reads)."""

from flask import Blueprint, request

import serializers as ser
import services
from auth import endpoint, resolve_actor
from core import (
    ALL_ROLES,
    class_entries_of_class,
    classes_of_show,
    coverage_of_show,
    db,
    divisions_of_show,
    find,
    rings_of_show,
    sorted_rows,
    submissions_of_class,
)
from response import object_response, paginated

bp = Blueprint("reads", __name__)


def _filtered(rows, spec):
    """Apply exact-match query filters named in ``spec`` (field -> query param)."""
    out = rows
    for field, param in spec.items():
        value = request.args.get(param)
        if value is None:
            continue
        out = [r for r in out if str(r.get(field)) == value]
    return out


# ------------------------------------------------------------------ shows ---
@bp.get("/shows/<show_id>")
@endpoint(*ALL_ROLES)
def get_show(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_show(show))


@bp.get("/shows/<show_id>/rings")
@endpoint(*ALL_ROLES)
def list_show_rings(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    resolve_actor()
    rows = _filtered(rings_of_show(show["id"]), {"status": "status"})
    return paginated(sorted_rows(rows), ser.ser_ring)


@bp.get("/shows/<show_id>/divisions")
@endpoint(*ALL_ROLES)
def list_show_divisions(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    resolve_actor()
    rows = _filtered(
        divisions_of_show(show["id"]), {"status": "status", "discipline": "discipline"}
    )
    return paginated(sorted_rows(rows), ser.ser_division)


@bp.get("/shows/<show_id>/coverage-shifts")
@endpoint(*ALL_ROLES)
def list_show_coverage(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    resolve_actor()
    rows = _filtered(
        coverage_of_show(show["id"]), {"coverage_type": "coverage_type", "status": "status"}
    )
    return paginated(sorted_rows(rows), ser.ser_coverage)


@bp.get("/shows/<show_id>/schedule-projection")
@endpoint(*ALL_ROLES)
def get_schedule_projection(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    resolve_actor()
    return object_response(services.schedule_projection(show))


# ------------------------------------------------------------------ rings ---
@bp.get("/rings/<ring_id>")
@endpoint(*ALL_ROLES)
def get_ring(ring_id):
    ring = find(db.rings, ring_id, "ERR_RING_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_ring(ring))


# ---------------------------------------------------------------- classes ---
@bp.get("/classes/<class_id>")
@endpoint(*ALL_ROLES)
def get_class(class_id):
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_class(cls))


@bp.get("/classes")
@endpoint(*ALL_ROLES)
def list_classes():
    resolve_actor()
    rows = _filtered(
        list(db.classes.values()),
        {
            "division_id": "division_id",
            "qualifier_for_class_id": "qualifier_for_class_id",
            "status": "status",
        },
    )
    return paginated(sorted_rows(rows), ser.ser_class)


@bp.get("/classes/<class_id>/point-submissions")
@endpoint(*ALL_ROLES)
def list_class_submissions(class_id):
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    resolve_actor()
    rows = _filtered(submissions_of_class(cls["id"]), {"status": "status"})
    return paginated(sorted_rows(rows), ser.ser_submission)


# ------------------------------------------------------------- ring slots ---
@bp.get("/ring-slots/<slot_id>")
@endpoint(*ALL_ROLES)
def get_slot(slot_id):
    slot = find(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_slot(slot))


@bp.get("/ring-slots")
@endpoint(*ALL_ROLES)
def list_slots():
    resolve_actor()
    rows = _filtered(
        list(db.slots.values()),
        {
            "ring_id": "ring_id",
            "class_id": "class_id",
            "slot_type": "slot_type",
            "status": "status",
        },
    )
    return paginated(sorted_rows(rows), ser.ser_slot)


# -------------------------------------------------------------- officials ---
@bp.get("/officials/<official_id>")
@endpoint(*ALL_ROLES)
def get_official(official_id):
    official = find(db.officials, official_id, "ERR_OFFICIAL_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_official(official))


@bp.get("/official-assignments/<assignment_id>")
@endpoint(*ALL_ROLES)
def get_assignment(assignment_id):
    assignment = find(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_assignment(assignment))


@bp.get("/official-assignments")
@endpoint(*ALL_ROLES)
def list_assignments():
    resolve_actor()
    rows = _filtered(
        list(db.assignments.values()),
        {
            "official_id": "official_id",
            "slot_id": "slot_id",
            "official_role": "official_role",
            "status": "status",
        },
    )
    return paginated(sorted_rows(rows), ser.ser_assignment)


# ---------------------------------------------------- riders and horses ----
@bp.get("/riders/<rider_id>")
@endpoint(*ALL_ROLES)
def get_rider(rider_id):
    rider = find(db.riders, rider_id, "ERR_RIDER_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_rider(rider))


@bp.get("/riders/<rider_id>/standings")
@endpoint(*ALL_ROLES)
def get_rider_standings(rider_id):
    rider = find(db.riders, rider_id, "ERR_RIDER_NOT_FOUND")
    resolve_actor()
    show_id = request.args.get("show_id")
    return object_response(services.rider_standings(rider, show_id))


@bp.get("/horses/<horse_id>")
@endpoint(*ALL_ROLES)
def get_horse(horse_id):
    horse = find(db.horses, horse_id, "ERR_HORSE_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_horse(horse))


# -------------------------------------------------- entries / class entries -
@bp.get("/entries/<entry_id>")
@endpoint(*ALL_ROLES)
def get_entry(entry_id):
    entry = find(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_entry(entry))


@bp.get("/entries")
@endpoint(*ALL_ROLES)
def list_entries():
    resolve_actor()
    rows = _filtered(
        list(db.entries.values()),
        {
            "show_id": "show_id",
            "rider_id": "rider_id",
            "horse_id": "horse_id",
            "verification_status": "verification_status",
            "settlement_status": "settlement_status",
        },
    )
    return paginated(sorted_rows(rows), ser.ser_entry)


@bp.get("/class-entries/<class_entry_id>")
@endpoint(*ALL_ROLES)
def get_class_entry(class_entry_id):
    class_entry = find(db.class_entries, class_entry_id, "ERR_CLASS_ENTRY_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_class_entry(class_entry))


@bp.get("/class-entries")
@endpoint(*ALL_ROLES)
def list_class_entries():
    resolve_actor()
    rows = _filtered(
        list(db.class_entries.values()),
        {"entry_id": "entry_id", "class_id": "class_id", "status": "status"},
    )
    return paginated(sorted_rows(rows), ser.ser_class_entry)


# ------------------------------------------------------- compliance cases ---
@bp.get("/compliance-cases/<case_id>")
@endpoint(*ALL_ROLES)
def get_case(case_id):
    case = find(db.cases, case_id, "ERR_COMPLIANCE_CASE_NOT_FOUND")
    resolve_actor()
    return object_response(ser.ser_case(case))


@bp.get("/compliance-cases")
@endpoint(*ALL_ROLES)
def list_cases():
    resolve_actor()
    rows = _filtered(
        list(db.cases.values()),
        {
            "entry_id": "entry_id",
            "opened_by_official_id": "opened_by_official_id",
            "case_type": "case_type",
            "status": "status",
        },
    )
    return paginated(sorted_rows(rows), ser.ser_case)
