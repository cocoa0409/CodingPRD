"""DependentEnrollment resource (PRD §3.10)."""

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_DEPENDENT_SLOTS_EXHAUSTED,
    ERR_SEP_WINDOW_CLOSED,
    invalid_request,
    invalid_state,
    not_found,
    stale_version,
)
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("dependent_enrollments", __name__)

ENROLLMENT_STATUSES = {"PENDING", "ENROLLED", "SEP_EXPIRED", "DENIED", "TERMINATED"}


def _get_enrollment(enrollment_id):
    e = db.dependent_enrollments.get(enrollment_id)
    if e is None:
        raise not_found("Dependent enrollment not found.")
    return e


def _refresh_sep_deadline(enrollment):
    """sep_deadline is computed from the newborn's birth_datetime + plan variant
    and is recomputed on read (SCAFFOLD §1.3 trigger)."""
    newborn = db.newborns.get(enrollment["newborn_id"])
    policy = db.insurance_policies.get(enrollment["policy_id"])
    if newborn is not None and policy is not None:
        enrollment["sep_deadline"] = services.compute_sep_deadline(
            newborn["birth_datetime"], policy["plan_type"])


@bp.post("/dependent-enrollments")
def create_enrollment():
    require_roles("BenefitsCoordinator")
    body = get_body()
    newborn_id = require_field(body, "newborn_id", str)
    newborn = db.newborns.get(newborn_id)
    if newborn is None:
        raise not_found("newborn_id does not resolve to a newborn.")
    policy_id = require_field(body, "policy_id", str)
    policy = db.insurance_policies.get(policy_id)
    if policy is None:
        raise not_found("policy_id does not resolve to an insurance policy.")
    requested_at = require_field(body, "requested_at", str)
    try:
        db.parse_iso(requested_at)
    except ValueError as e:
        raise invalid_request(str(e))
    sep_deadline = services.compute_sep_deadline(newborn["birth_datetime"],
                                                 policy["plan_type"])
    row = {
        "id": db.new_id(),
        "newborn_id": newborn_id,
        "policy_id": policy_id,
        "requested_at": requested_at,
        "sep_deadline": sep_deadline,
        "status": "PENDING",
        "retroactive_effective_date": None,
    }
    db.stamp_create(row)
    db.dependent_enrollments[row["id"]] = row
    return ok_object(db.public(row), 201)


@bp.get("/dependent-enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    require_roles("BenefitsCoordinator", "RegistrySupervisor")
    e = _get_enrollment(enrollment_id)
    _refresh_sep_deadline(e)
    return ok_object(db.public(e))


@bp.get("/dependent-enrollments")
def list_enrollments():
    require_roles("BenefitsCoordinator", "RegistrySupervisor")
    limit, offset = parse_pagination()
    newborn_id = request.args.get("newborn_id")
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    rows = list(db.dependent_enrollments.values())
    if newborn_id is not None:
        rows = [r for r in rows if r["newborn_id"] == newborn_id]
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if status is not None:
        require_enum(status, "status", ENROLLMENT_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/dependent-enrollments/<enrollment_id>/approve")
def approve_enrollment(enrollment_id):
    require_roles("BenefitsCoordinator")
    e = _get_enrollment(enrollment_id)
    body = get_body()
    expected_policy_version = require_field(body, "expected_policy_version", int)

    policy = db.insurance_policies.get(e["policy_id"])
    if policy is None:
        raise not_found("Governing insurance policy not found.")

    # State (priority 5): approve defined only from PENDING.
    if e["status"] != "PENDING":
        raise invalid_state("Only a PENDING enrollment may be approved.")

    # OCC (priority 6).
    if expected_policy_version != policy["version"]:
        raise stale_version("expected_policy_version does not match the policy's version.")

    # SEP window (priority 12): requested_at must be <= sep_deadline (inclusive).
    _refresh_sep_deadline(e)
    requested_dt = db.parse_iso(e["requested_at"])
    deadline_dt = db.parse_iso(e["sep_deadline"])
    if requested_dt > deadline_dt:
        raise APIError(ERR_SEP_WINDOW_CLOSED,
                       "requested_at is after the SEP deadline; window closed.", 422)

    # Slot exhaustion (priority 16).
    enrolled = services.recompute_dependents_added_count(e["policy_id"])
    if enrolled >= policy["dependent_slots_max"]:
        raise APIError(ERR_DEPENDENT_SLOTS_EXHAUSTED,
                       "Policy dependent slots are exhausted.", 422)

    # Commit: ENROLLED, backdate to birth date, bump policy version.
    newborn = db.newborns.get(e["newborn_id"])
    birth_date = db.parse_iso(newborn["birth_datetime"]).date().isoformat()
    e["status"] = "ENROLLED"
    e["retroactive_effective_date"] = birth_date
    db.stamp_update(e)
    services.recompute_dependents_added_count(e["policy_id"])
    db.stamp_update(policy)
    services.append_audit("DEPENDENT_ENROLLED", request.headers.get("X-User-Role"),
                          e["newborn_id"],
                          {"dependent_enrollment_id": e["id"], "policy_id": e["policy_id"]})
    return ok_object(db.public(e))


@bp.post("/dependent-enrollments/<enrollment_id>/deny")
def deny_enrollment(enrollment_id):
    require_roles("BenefitsCoordinator")
    e = _get_enrollment(enrollment_id)
    if e["status"] != "PENDING":
        raise invalid_state("Only a PENDING enrollment may be denied.")
    e["status"] = "DENIED"
    db.stamp_update(e)
    return ok_object(db.public(e))


@bp.post("/dependent-enrollments/<enrollment_id>/expire")
def expire_enrollment(enrollment_id):
    require_roles("BenefitsCoordinator")
    e = _get_enrollment(enrollment_id)
    if e["status"] != "PENDING":
        raise invalid_state("Only a PENDING enrollment may be expired.")
    # Precondition: requested_at strictly after sep_deadline.
    _refresh_sep_deadline(e)
    requested_dt = db.parse_iso(e["requested_at"])
    deadline_dt = db.parse_iso(e["sep_deadline"])
    if not (requested_dt > deadline_dt):
        raise invalid_state("Enrollment is still within its SEP window; cannot expire.")
    e["status"] = "SEP_EXPIRED"
    db.stamp_update(e)
    services.append_audit("SEP_EXPIRED", request.headers.get("X-User-Role"),
                          e["newborn_id"], {"dependent_enrollment_id": e["id"]})
    return ok_object(db.public(e))


@bp.post("/dependent-enrollments/<enrollment_id>/terminate")
def terminate_enrollment(enrollment_id):
    require_roles("BenefitsCoordinator")
    e = _get_enrollment(enrollment_id)
    if e["status"] != "ENROLLED":
        raise invalid_state("Only an ENROLLED enrollment may be terminated.")
    e["status"] = "TERMINATED"
    db.stamp_update(e)
    services.recompute_dependents_added_count(e["policy_id"])
    return ok_object(db.public(e))
