"""Panel assignment, superseding and the transfer handshake (PRD 3.4)."""

from flask import Blueprint

import db
import derive
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("assignments", __name__)

ASSIGNMENT_SOURCES = ("MANUAL", "ENROLLMENT_FILE", "PANEL_TRANSFER")
ASSIGNMENT_STATES = ("ACTIVE", "TRANSFER_PROPOSED", "TRANSFER_ACCEPTED", "TRANSFERRED",
                     "TERMINATED")
TERMINAL_STATES = ("TRANSFERRED", "TERMINATED")

TRANSITION_ROLES = {
    "ACTIVE": ("PhysicianUser",),
    "TRANSFER_ACCEPTED": ("PhysicianUser",),
    "TRANSFER_PROPOSED": ("NetworkManager",),
    "TRANSFERRED": ("NetworkManager",),
    "TERMINATED": ("NetworkManager",),
}

READ_ROLES = ("IpaAdmin", "NetworkManager", "ClaimsExaminer", "PayerRepresentative",
              "PhysicianUser")


def _specialty_ok(enrollee, physician):
    if enrollee["age_band"] == "PEDIATRIC":
        return physician["specialty"] in ("PEDIATRICS", "PRIMARY_CARE")
    if enrollee["age_band"] == "SENIOR":
        return physician["specialty"] in ("INTERNAL_MEDICINE", "PRIMARY_CARE")
    return True


def _overlaps_open_ended(assignment, effective):
    """Half-open [effective_date, term_date) against [effective, +inf)."""
    term = assignment.get("term_date")
    if term is not None and term.dt <= effective.dt:
        return False
    return True


@bp.post("/ipa/member-assignments")
def create_assignment():
    middleware.require("IpaAdmin", "NetworkManager")
    body = validate.body()
    enrollee_id = validate.req_str(body, "enrollee_id")
    physician_id = validate.req_str(body, "physician_id")
    effective_date = validate.req_instant(body, "effective_date")
    assignment_source = validate.req_enum(body, "assignment_source", ASSIGNMENT_SOURCES)
    expected_enrollee_version = validate.req_int(body, "expected_enrollee_version")
    supersede_prior = validate.opt_bool(body, "supersede_prior", default=False)

    # check 5 — body references in declared input order
    enrollee = resolve.enrollee(enrollee_id)
    physician = resolve.physician(physician_id)

    # check 7 — optimistic concurrency on the parent enrollee
    if expected_enrollee_version != enrollee["version"]:
        fail("ERR_STALE_ENROLLEE_VERSION")

    agreement = db.agreement_of_enrollee(enrollee)
    # check 8
    if agreement is None or agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")
    # check 9
    if physician["credential_status"] != "ACTIVE":
        fail("ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS")
    # check 10
    if physician["panel_status"] != "OPEN":
        fail("ERR_PANEL_CLOSED_TO_NEW")
    # check 12
    if physician["agreement_id"] != enrollee["agreement_id"]:
        fail("ERR_AGREEMENT_MISMATCH")
    # check 13
    if not _specialty_ok(enrollee, physician):
        fail("ERR_SPECIALTY_AGE_BAND_MISMATCH")
    # check 15 — the temporal rule outranks the overlap rule
    if effective_date.dt < enrollee["coverage_start_date"].dt:
        fail("ERR_ASSIGNMENT_BEFORE_COVERAGE")
    coverage_end = enrollee.get("coverage_end_date")
    if coverage_end is not None and effective_date.dt > coverage_end.dt:
        fail("ERR_ASSIGNMENT_BEFORE_COVERAGE")

    # check 18 — half-open interval overlap, with the supersede carve-out
    to_supersede = []
    for existing in db.assignments_of_enrollee(enrollee["id"]):
        if existing["status"] in TERMINAL_STATES:
            continue
        if not _overlaps_open_ended(existing, effective_date):
            continue
        if (supersede_prior and existing["status"] == "ACTIVE"
                and effective_date.dt > existing["effective_date"].dt):
            to_supersede.append(existing)
            continue
        fail("ERR_ASSIGNMENT_PERIOD_OVERLAP")

    # check 27
    if physician["panel_size"] >= agreement["max_panel_size"]:
        fail("ERR_PANEL_CAPACITY_EXCEEDED")

    assignment = db.create(
        db.assignments,
        enrollee_id=enrollee["id"],
        physician_id=physician["id"],
        pending_to_physician_id=None,
        effective_date=effective_date,
        term_date=None,
        status="ACTIVE",
        assignment_source=assignment_source,
        continuity_of_care_until=None,
        superseded_by_assignment_id=None,
    )

    touched_physicians = {physician["id"]: physician}
    for prior in to_supersede:
        prior["status"] = "TERMINATED"
        prior["term_date"] = effective_date
        prior["superseded_by_assignment_id"] = assignment["id"]
        db.touch(prior)
        prior_physician = db.physicians.get(prior["physician_id"])
        if prior_physician is not None:
            touched_physicians[prior_physician["id"]] = prior_physician

    for member in touched_physicians.values():
        derive.sync_panel_size(member)
    # the enrollee's assigned_physician_id moved, so its version always advances
    derive.sync_enrollee_assignment(enrollee, force_touch=True)
    derive.sync_total_assigned_members(agreement)
    derive.close_panel_at_capacity(physician, agreement)

    return response.ok(serialize.assignment(assignment), 201)


@bp.get("/ipa/member-assignments")
def list_assignments():
    middleware.require(*READ_ROLES)
    enrollee_id = validate.query_str("enrollee_id")
    physician_id = validate.query_str("physician_id")
    pending_to_physician_id = validate.query_str("pending_to_physician_id")
    status = validate.query_enum("status", ASSIGNMENT_STATES)
    limit, offset = validate.pagination()

    items = db.ordered(db.assignments.values())
    if enrollee_id is not None:
        items = [a for a in items if a["enrollee_id"] == enrollee_id]
    if physician_id is not None:
        items = [a for a in items if a["physician_id"] == physician_id]
    if pending_to_physician_id is not None:
        items = [a for a in items
                 if a["pending_to_physician_id"] == pending_to_physician_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.assignment(a) for a in window], limit, offset,
                            len(items))


@bp.get("/ipa/member-assignments/<assignment_id>")
def read_assignment(assignment_id):
    user_id, role = middleware.require(*READ_ROLES)
    assignment = resolve.assignment(assignment_id)
    middleware.check_ownership(
        role, user_id,
        physician_ids=[assignment["physician_id"],
                       assignment["pending_to_physician_id"]],
        agreement=db.agreement_of_assignment(assignment))
    return response.ok(serialize.assignment(assignment))


@bp.post("/ipa/member-assignments/<assignment_id>/state")
def assignment_state(assignment_id):
    user_id, role = middleware.require("NetworkManager", "PhysicianUser")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", ASSIGNMENT_STATES)
    if to_state == "TRANSFER_PROPOSED":
        to_physician_id = validate.req_str(body, "to_physician_id")
        transfer_effective_date = validate.req_instant(body, "transfer_effective_date")
    else:
        to_physician_id = validate.opt_str(body, "to_physician_id")
        transfer_effective_date = validate.opt_instant(body, "transfer_effective_date")

    assignment = resolve.assignment(assignment_id)
    middleware.require_transition_role(role, TRANSITION_ROLES[to_state])

    source_physician = db.physicians.get(assignment["physician_id"])
    agreement = db.agreement_of_assignment(assignment)
    current = assignment["status"]

    if to_state == "TRANSFER_PROPOSED":
        # check 5 — the transfer target
        target = resolve.physician(to_physician_id)
        # check 9
        if target["credential_status"] != "ACTIVE":
            fail("ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS")
        # check 11
        if current != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        if transfer_effective_date.dt < db.clock().dt:
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 12
        if source_physician is None or target["agreement_id"] != source_physician["agreement_id"]:
            fail("ERR_AGREEMENT_MISMATCH")
        # check 13
        enrollee = db.enrollees.get(assignment["enrollee_id"])
        if enrollee is not None and not _specialty_ok(enrollee, target):
            fail("ERR_SPECIALTY_AGE_BAND_MISMATCH")
        # check 27 — a transfer proposal is judged on capacity, not on panel_status
        if target["panel_size"] >= agreement["max_panel_size"]:
            fail("ERR_PANEL_CAPACITY_EXCEEDED")

        assignment["status"] = "TRANSFER_PROPOSED"
        assignment["pending_to_physician_id"] = target["id"]
        assignment["_transfer_effective_date"] = transfer_effective_date
        db.touch(assignment)
        source_physician["panel_status"] = "TRANSFER_PENDING"
        db.touch(source_physician)
        derive.sync_panel_size(source_physician)
        derive.sync_total_assigned_members(agreement)

    elif to_state == "ACTIVE":
        # ownership: only the transfer target may answer
        middleware.check_ownership(
            role, user_id, physician_ids=[assignment["pending_to_physician_id"]])
        if current != "TRANSFER_PROPOSED":
            fail("ERR_INVALID_STATE_TRANSITION")
        assignment["status"] = "ACTIVE"
        assignment["pending_to_physician_id"] = None
        assignment.pop("_transfer_effective_date", None)
        db.touch(assignment)
        # the compensating action restores both count quantities exactly
        if source_physician is not None:
            derive.sync_panel_size(source_physician)
            derive.resolve_transfer_pending(source_physician)
        if agreement is not None:
            derive.sync_total_assigned_members(agreement)

    elif to_state == "TRANSFER_ACCEPTED":
        middleware.check_ownership(
            role, user_id, physician_ids=[assignment["pending_to_physician_id"]])
        target = db.physicians.get(assignment["pending_to_physician_id"])
        # check 9
        if target is not None and target["credential_status"] != "ACTIVE":
            fail("ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS")
        if current != "TRANSFER_PROPOSED":
            fail("ERR_INVALID_STATE_TRANSITION")
        assignment["status"] = "TRANSFER_ACCEPTED"
        db.touch(assignment)

    elif to_state == "TRANSFERRED":
        if current != "TRANSFER_ACCEPTED":
            fail("ERR_INVALID_STATE_TRANSITION")
        effective = assignment.get("_transfer_effective_date")
        if effective is None or db.clock().dt < effective.dt:
            fail("ERR_INVALID_STATE_TRANSITION")
        target = db.physicians.get(assignment["pending_to_physician_id"])

        # L1 — this row terms
        assignment["status"] = "TRANSFERRED"
        assignment["term_date"] = effective
        assignment["pending_to_physician_id"] = None
        db.touch(assignment)

        # L2 — a successor row carries the member forward without a gap
        db.create(
            db.assignments,
            enrollee_id=assignment["enrollee_id"],
            physician_id=target["id"] if target is not None else None,
            pending_to_physician_id=None,
            effective_date=effective,
            term_date=None,
            status="ACTIVE",
            assignment_source="PANEL_TRANSFER",
            continuity_of_care_until=db.add_days(
                effective, agreement["continuity_of_care_days"]),
            superseded_by_assignment_id=None,
        )

        # L3 — both panel sizes and the enrollee pointer follow
        if source_physician is not None:
            derive.sync_panel_size(source_physician)
        if target is not None:
            derive.sync_panel_size(target)
        enrollee = db.enrollees.get(assignment["enrollee_id"])
        if enrollee is not None:
            derive.sync_enrollee_assignment(enrollee, force_touch=True)

        # L4 — the target's panel closes once it is full
        if target is not None:
            derive.close_panel_at_capacity(target, agreement)
        if source_physician is not None:
            derive.resolve_transfer_pending(source_physician)
        derive.sync_total_assigned_members(agreement)

    elif to_state == "TERMINATED":
        if current != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 14 — the holding physician's continuity window must have elapsed
        if source_physician is not None:
            window = source_physician.get("continuity_of_care_until")
            if window is not None and db.clock().dt < window.dt:
                fail("ERR_CONTINUITY_OF_CARE_ACTIVE")
        assignment["status"] = "TERMINATED"
        assignment["term_date"] = db.clock()
        db.touch(assignment)
        if source_physician is not None:
            derive.sync_panel_size(source_physician)
        enrollee = db.enrollees.get(assignment["enrollee_id"])
        if enrollee is not None:
            derive.sync_enrollee_assignment(enrollee, force_touch=True)
        if agreement is not None:
            derive.sync_total_assigned_members(agreement)

    else:  # pragma: no cover - every declared member is handled above
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.assignment(assignment))
