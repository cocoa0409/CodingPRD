"""Enrollment routes. PRD 3.6 + 2.9 OCC."""
from flask import Blueprint, request

from clock import clock
from db import store, iso, common_fields_on_create, touch
from errors import (
    err, ERR_REFERENCE_MISMATCH, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_SESSION_NOT_OPEN, ERR_AGE_OUT_OF_RANGE, ERR_SESSION_FULL,
    ERR_ACCOUNT_PAST_DUE, ERR_STALE_VERSION,
    ERR_STUDENT_NOT_FOUND, ERR_CLASS_SESSION_NOT_FOUND,
)
from helpers import (
    get_body, require_str, require_int, parse_pagination, paginate,
)
from middleware import get_principal, require_roles
from response import object_response, array_response
from domain import (
    serialize_enrollment, reconcile_session_counts, recompute_parent_ledger,
    compute_age_months, promote_waitlist, withdraw_enrollment, issue_makeup_credit,
    _is_prorated_first_cycle,
)
from lookups import (
    get_student, get_class_session, get_enrollment, get_level,
    entity_exists_anywhere,
)

bp = Blueprint("enrollments", __name__)

ALL_ROLES = ["SchoolAdmin", "BillingAdmin", "Instructor", "Parent"]


def _age_in_window(student, level):
    from helpers import parse_datetime
    age = compute_age_months(parse_datetime(student["birthdate"], "birthdate"))
    return level["min_age_months"] <= age < level["max_age_months"]


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    body = get_body()
    # priority 5: required fields present/typed.
    student_id = require_str(body, "student_id")
    class_session_id = require_str(body, "class_session_id")
    expected_version = require_int(body, "expected_class_session_version")
    # priority 3: existence, body FKs left to right. An id that names some
    # persisted entity resolves the existence check; an id that names nothing at
    # all is a not-found. (PRD 2.6 / 2.10)
    if student_id not in store.students:
        if not entity_exists_anywhere(student_id):
            err(ERR_STUDENT_NOT_FOUND)
    if class_session_id not in store.class_sessions:
        if not entity_exists_anywhere(class_session_id):
            err(ERR_CLASS_SESSION_NOT_FOUND)
    # priority 4: reference/type consistency — each FK must point at the right
    # kind of entity; an id that resolves to a wrong-type entity is a mismatch
    # (PRD 3.6: "checked for type and ownership consistency").
    if student_id not in store.students or class_session_id not in store.class_sessions:
        err(ERR_REFERENCE_MISMATCH, "Body foreign key points at the wrong kind of entity")
    student = get_student(student_id)
    session = get_class_session(class_session_id)
    # student belongs to acting parent (a parent enrolling another family's child
    # is enforced as ownership below).
    parent = store.parents.get(student["parent_id"])
    # priority 6: ownership for entity-backed Parent.
    if principal.role == "Parent" and principal.user_id != student["parent_id"]:
        err(ERR_NOT_RESOURCE_OWNER, "Parent may only enroll its own student")
    # priority 8: cross-entity state — session must be OPEN.
    if session["status"] != "OPEN":
        err(ERR_SESSION_NOT_OPEN, "ClassSession is not OPEN")
    level = store.levels.get(session["level_id"])
    # priority 9: age window.
    if not _age_in_window(student, level):
        err(ERR_AGE_OUT_OF_RANGE, "Student age outside the level's window")
    # priority 14: account standing for client-initiated activation (CURRENT required).
    recompute_parent_ledger(parent)
    account_current = parent["account_standing"] == "CURRENT"
    # priority 15: OCC — expected_class_session_version must match.
    if expected_version != session["version"]:
        err(ERR_STALE_VERSION, "Stale class session version")

    reconcile_session_counts(session)
    free_seat = session["enrolled_count"] < session["capacity"]

    rec = common_fields_on_create()
    rec.update({
        "student_id": student["id"],
        "class_session_id": session["id"],
        "tuition_basis_cents": level["monthly_tuition_cents"],
        "is_prorated_first_cycle": False,
        "joined_at": None,
        "status": "WAITLISTED",
    })

    # PRD 3.6: if a free seat and account CURRENT -> ACTIVE; else WAITLISTED.
    # priority 14: a PAST_DUE account that would otherwise activate is rejected.
    if free_seat:
        if not account_current:
            err(ERR_ACCOUNT_PAST_DUE, "Parent account is PAST_DUE")
        rec["status"] = "ACTIVE"
        rec["joined_at"] = iso(clock.now())
        rec["is_prorated_first_cycle"] = _is_prorated_first_cycle(rec)
        store.enrollments[rec["id"]] = rec
        reconcile_session_counts(session)
        touch(session)  # version++ on activation.
    else:
        # No free seat -> WAITLISTED. joined_at set to current instant (the
        # waitlist ordering key); waitlist_count rises.
        rec["joined_at"] = iso(clock.now())
        store.enrollments[rec["id"]] = rec
        reconcile_session_counts(session)
        touch(session)  # creation increments the session version by 1.
    return object_response(serialize_enrollment(rec), 201)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.enrollments.values())
    for f in ("student_id", "class_session_id", "status"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_enrollment(r) for r in window], limit, offset, total)


@bp.route("/enrollments/<id>", methods=["GET"])
def get_enrollment_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_enrollment(id)
    return object_response(serialize_enrollment(rec), 200)


def _check_parent_owns_enrollment(principal, enrollment):
    if principal.role == "Parent":
        student = store.students.get(enrollment["student_id"])
        if student is None or principal.user_id != student["parent_id"]:
            err(ERR_NOT_RESOURCE_OWNER, "Parent may only act on its own enrollment")


@bp.route("/enrollments/<id>/pause", methods=["POST"])
def pause_enrollment(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    enrollment = get_enrollment(id)
    _check_parent_owns_enrollment(principal, enrollment)
    # State legality: only ACTIVE -> PAUSED.
    if enrollment["status"] != "ACTIVE":
        err(ERR_INVALID_STATE, "Only an ACTIVE enrollment may be paused")
    enrollment["status"] = "PAUSED"
    touch(enrollment)
    session = store.class_sessions.get(enrollment["class_session_id"])
    reconcile_session_counts(session)
    touch(session)  # enrolled_count--; version++.
    # Issue a SKIP makeup credit for the paused interval.
    issue_makeup_credit(enrollment["student_id"], enrollment["id"], "SKIP")
    # Freed seat promotes the earliest waitlisted enrollment.
    promote_waitlist(session)
    return object_response(serialize_enrollment(enrollment), 200)


@bp.route("/enrollments/<id>/resume", methods=["POST"])
def resume_enrollment(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    enrollment = get_enrollment(id)
    _check_parent_owns_enrollment(principal, enrollment)
    # State legality: only PAUSED -> ACTIVE.
    if enrollment["status"] != "PAUSED":
        err(ERR_INVALID_STATE, "Only a PAUSED enrollment may be resumed")
    student = store.students.get(enrollment["student_id"])
    session = store.class_sessions.get(enrollment["class_session_id"])
    level = store.levels.get(session["level_id"])
    # priority 9: age re-check.
    if not _age_in_window(student, level):
        err(ERR_AGE_OUT_OF_RANGE, "Student age outside the level's window")
    # priority 12: capacity re-check.
    reconcile_session_counts(session)
    if session["enrolled_count"] >= session["capacity"]:
        err(ERR_SESSION_FULL, "ClassSession is full")
    enrollment["status"] = "ACTIVE"
    touch(enrollment)
    reconcile_session_counts(session)
    touch(session)  # enrolled_count++; version++.
    return object_response(serialize_enrollment(enrollment), 200)


@bp.route("/enrollments/<id>/withdraw", methods=["POST"])
def withdraw_single_enrollment(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    enrollment = get_enrollment(id)
    _check_parent_owns_enrollment(principal, enrollment)
    # State legality: withdraw reachable from WAITLISTED/ACTIVE/PAUSED; WITHDRAWN terminal.
    if enrollment["status"] not in ("WAITLISTED", "ACTIVE", "PAUSED"):
        err(ERR_INVALID_STATE, "Enrollment is already terminal")
    withdraw_enrollment(enrollment)
    return object_response(serialize_enrollment(enrollment), 200)
