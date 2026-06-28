"""Enrollment endpoints + placement/billing transitions (PRD §3.5, §3.7)."""
from flask import Blueprint

import errors
from db import db, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from services import compliance
from services.common import (
    parse_pagination, sort_created_asc, paginate, serialize, serialize_list,
    str_arg, optional_enum,
)

bp = Blueprint("enrollments", __name__)

READ_ROLES = {"Registrar", "Guide", "ComplianceOfficer", "Parent"}
PLACEMENT_STATUSES = {"PLACED", "ON_LEAVE", "WITHDRAWN"}
BILLING_STATUSES = {"DEPOSIT_DUE", "ACTIVE", "PAST_DUE", "SETTLED"}


def _get_enr_or_404(enrollment_id):
    enr = db.enrollments.get(enrollment_id)
    if enr is None:
        raise errors.not_found("Enrollment not found.")
    return enr


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    return object_response(serialize(_get_enr_or_404(enrollment_id)), 200)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    _, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    student_id = str_arg("student_id")
    application_id = str_arg("application_id")
    classroom_id = str_arg("classroom_id")
    tier_id = str_arg("tier_id")
    placement = optional_enum(str_arg("placement_status"), PLACEMENT_STATUSES, "placement_status")
    billing = optional_enum(str_arg("billing_status"), BILLING_STATUSES, "billing_status")

    records = list(db.enrollments.values())
    if student_id is not None:
        records = [e for e in records if e["student_id"] == student_id]
    if application_id is not None:
        records = [e for e in records if e["application_id"] == application_id]
    if classroom_id is not None:
        records = [e for e in records if e["classroom_id"] == classroom_id]
    if tier_id is not None:
        records = [e for e in records if e["tier_id"] == tier_id]
    if placement is not None:
        records = [e for e in records if e["placement_status"] == placement]
    if billing is not None:
        records = [e for e in records if e["billing_status"] == billing]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/enrollments/<enrollment_id>/leave", methods=["POST"])
def leave(enrollment_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    enr = _get_enr_or_404(enrollment_id)
    if enr["placement_status"] != "PLACED":
        raise errors.invalid_state()
    enr["placement_status"] = "ON_LEAVE"
    touch(enr)
    classroom = db.classrooms[enr["classroom_id"]]
    compliance.recompute_and_touch(classroom)  # decrements placed_count, recomputes
    return object_response(serialize(enr), 200)


@bp.route("/enrollments/<enrollment_id>/return", methods=["POST"])
def return_from_leave(enrollment_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    enr = _get_enr_or_404(enrollment_id)
    if enr["placement_status"] != "ON_LEAVE":
        raise errors.invalid_state()
    classroom = db.classrooms[enr["classroom_id"]]
    # §2.10 order: not-compliant (9) before classroom-full (13).
    if classroom["compliance_status"] != "COMPLIANT":
        raise errors.classroom_not_compliant()
    if classroom["placed_count"] >= classroom["capacity"]:
        raise errors.classroom_full()
    enr["placement_status"] = "PLACED"
    touch(enr)
    compliance.recompute_and_touch(classroom)  # increments placed_count, recomputes
    return object_response(serialize(enr), 200)


@bp.route("/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw(enrollment_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    enr = _get_enr_or_404(enrollment_id)
    if enr["placement_status"] not in ("PLACED", "ON_LEAVE"):
        raise errors.invalid_state()

    was_placed = enr["placement_status"] == "PLACED"
    enr["placement_status"] = "WITHDRAWN"
    touch(enr)

    classroom = db.classrooms[enr["classroom_id"]]
    if was_placed:
        # decrements placed_count, recomputes compliance (cascade hop 1).
        compliance.recompute_and_touch(classroom)

    # Set the linked application's status to WITHDRAWN.
    linked_app = db.applications.get(enr["application_id"])
    if linked_app is not None and linked_app["status"] not in (
        "WITHDRAWN", "DECLINED",
    ):
        linked_app["status"] = "WITHDRAWN"
        touch(linked_app)

    # Auto-promotion: select top-ranked WAITLISTED app and OFFER it (hops 2-3),
    # provided the freed room can take a placement.
    if (
        classroom["compliance_status"] == "COMPLIANT"
        and classroom["placed_count"] < classroom["capacity"]
    ):
        promoted = compliance.select_top_waitlisted(classroom["id"])
        if promoted is not None:
            promoted["status"] = "OFFERED"
            touch(promoted)

    return object_response(serialize(enr), 200)


@bp.route("/enrollments/<enrollment_id>/mark-past-due", methods=["POST"])
def mark_past_due(enrollment_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    enr = _get_enr_or_404(enrollment_id)
    if enr["billing_status"] != "ACTIVE":
        raise errors.invalid_state()
    enr["billing_status"] = "PAST_DUE"
    touch(enr)
    return object_response(serialize(enr), 200)
