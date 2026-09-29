"""DesignPackage, ReviewRound and ReviewVote endpoints (PRD §3.2, §3.3)."""

from flask import Blueprint

import calc
import cascades
import helpers
import serializers
from auth import (ALL_ROLES, PANEL_ELIGIBLE_ROLES, ROLE_ACCESSIBILITY, ROLE_CONSERVATOR,
                  ROLE_CURATOR, ROLE_PROJECT_MANAGER, caller_id, caller_role, check_segregation,
                  endpoint)
from envelope import list_response, object_response, pagination, query_filter
from errors import ApiError
from helpers import touch
from store import db, new_row, order_created
from validate import (body_object, v_datetime, v_enum, v_int, v_num, v_str, v_string_list)

bp = Blueprint("packages", __name__)

PACKAGE_STAGES = ("SCHEMATIC", "DESIGN_DEV")
VOTE_DECISIONS = ("APPROVE", "REVISE", "VETO")


@bp.route("/exhibit-projects/<pid>/design-packages", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER, ROLE_ACCESSIBILITY])
def create_package(pid):
    project = helpers.get_project(pid)
    body = body_object()
    expected_project_version = v_int(body, "expected_project_version")
    stage = v_enum(body, "stage", PACKAGE_STAGES)
    egress = v_num(body, "egress_clear_width_cm", gt=0)
    turning = v_num(body, "wheelchair_turning_radius_cm", gt=0)
    peak = v_int(body, "peak_visitors_per_hour", minimum=1)
    circulation = v_num(body, "circulation_area_sqm", gt=0)

    # Step 7: optimistic concurrency on the project version.
    if expected_project_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    helpers.require_phase(project, ("SCHEMATIC", "DESIGN_DEV", "FABRICATION"))
    helpers.require_not_frozen(project)

    score, passes = calc.package_flow(peak, circulation, egress, turning)
    if not passes:
        # The package is rejected outright and is not stored at all.
        raise ApiError("ERR_ACCESSIBILITY_REQUIREMENTS_UNMET")

    package = new_row("packages", {
        "project_id": project["id"],
        "superseded_by_package_id": None,
        "stage": stage,
        "status": "DRAFT",
        "egress_clear_width_cm": egress,
        "wheelchair_turning_radius_cm": turning,
        "peak_visitors_per_hour": peak,
        "circulation_area_sqm": circulation,
        "flow_capacity_score": score,
        "accessibility_pass": True,
        "review_round_count": 0,
        "revision_count": 0,
        "submitted_by_user_id": caller_id(),
        "approved_at": None,
    })
    db.packages[package["id"]] = package
    cascades.supersede_same_stage_packages(project, package)
    touch(project)
    return object_response(serializers.package_json(package), 201)


@bp.route("/exhibit-projects/<pid>/design-packages", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_packages(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    stage = query_filter("stage")
    status = query_filter("status")
    rows = helpers.packages_of_project(project["id"])
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serializers.package_json, limit, offset)


@bp.route("/design-packages/<package_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_package(package_id):
    package = helpers.get_package(package_id)
    return object_response(serializers.package_json(package))


@bp.route("/design-packages/<package_id>/superseded-packages", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_superseded(package_id):
    package = helpers.get_package(package_id)
    limit, offset = pagination()
    rows = sorted((p for p in db.packages.values()
                   if p["superseded_by_package_id"] == package["id"]), key=order_created)
    return list_response(rows, serializers.package_json, limit, offset)


@bp.route("/design-packages/<package_id>/review-rounds", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def create_round(package_id):
    # Step 4 (request-body shape) precedes step 5 (existence of every referenced row).
    body = body_object()
    panel_roles = v_string_list(body, "panel_roles")
    deadline = v_datetime(body, "decision_deadline_at")

    # Step 5.
    package = helpers.get_package(package_id)
    project = helpers.owning_project(package)

    # Step 8: a package carries at most one live round.
    for existing in helpers.rounds_of_package(package["id"]):
        if existing["status"] == "OPEN":
            raise ApiError("ERR_ROUND_ALREADY_OPEN")
    # Step 9: the deadline must fall strictly after the current logical clock.
    if deadline <= db.now():
        raise ApiError("ERR_DEADLINE_IN_PAST")
    # Step 11.
    helpers.require_not_frozen(project)
    # Step 12: package state.
    if package["superseded_by_package_id"] is not None or package["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_PACKAGE_STATE")
    # Step 13: panel composition.
    _validate_panel(panel_roles)

    required = (2 * len(panel_roles) + 2) // 3
    review_round = new_row("rounds", {
        "package_id": package["id"],
        "round_number": package["review_round_count"] + 1,
        "panel_roles": list(panel_roles),
        "required_vote_count": required,
        "cast_vote_count": 0,
        "approve_count": 0,
        "revise_count": 0,
        "veto_count": 0,
        "status": "OPEN",
        "decision_deadline_at": deadline,
        "decided_at": None,
        "swept_by_deadline": False,
    })
    db.rounds[review_round["id"]] = review_round
    package["review_round_count"] = package["review_round_count"] + 1
    package["status"] = "IN_REVIEW"
    touch(package)
    touch(project)
    return object_response(serializers.round_json(review_round), 201)


def _validate_panel(panel_roles):
    if len(panel_roles) < 3 or len(panel_roles) > 5:
        raise ApiError("ERR_INVALID_PANEL_COMPOSITION",
                       "A panel must seat between 3 and 5 roles.")
    for role in panel_roles:
        if not isinstance(role, str) or role not in PANEL_ELIGIBLE_ROLES:
            raise ApiError("ERR_INVALID_PANEL_COMPOSITION",
                           "A panel seat must name a panel-eligible role.")
    if len(set(panel_roles)) != len(panel_roles):
        raise ApiError("ERR_INVALID_PANEL_COMPOSITION", "Panel seats must be unique.")
    if ROLE_CURATOR not in panel_roles or ROLE_CONSERVATOR not in panel_roles:
        raise ApiError("ERR_INVALID_PANEL_COMPOSITION",
                       "A panel must include both Curator and Conservator.")


@bp.route("/design-packages/<package_id>/review-rounds", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_rounds(package_id):
    package = helpers.get_package(package_id)
    limit, offset = pagination()
    status = query_filter("status")
    rows = helpers.rounds_of_package(package["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # A package's review rounds are ordered by round_number ascending (PRD §2.3).
    rows.sort(key=lambda r: (r["round_number"], r["_seq"]))
    return list_response(rows, serializers.round_json, limit, offset)


@bp.route("/review-rounds/<round_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_round(round_id):
    review_round = helpers.get_round(round_id)
    return object_response(serializers.round_json(review_round))


@bp.route("/review-rounds/<round_id>/votes", methods=["POST"])
@endpoint(roles=list(PANEL_ELIGIBLE_ROLES))
def cast_vote(round_id):
    review_round = helpers.get_round(round_id)
    package = db.packages[review_round["package_id"]]
    project = helpers.owning_project(package)

    # Step 3: the caller may not be the author of the package under review.
    check_segregation(package["submitted_by_user_id"])

    body = body_object()
    decision = v_enum(body, "decision", VOTE_DECISIONS)
    comment = v_str(body, "comment", None, 500, required=False, default=None)

    # Step 8: one vote per caller, then panel seating.
    for existing in helpers.votes_of_round(review_round["id"]):
        if existing["voter_role"] == caller_role() or existing["voter_user_id"] == caller_id():
            raise ApiError("ERR_DUPLICATE_VOTE")
    if caller_role() not in review_round["panel_roles"]:
        raise ApiError("ERR_VOTER_NOT_ON_PANEL")

    # Step 12: round state, then the round deadline.
    if review_round["status"] != "OPEN":
        raise ApiError("ERR_INVALID_ROUND_STATE")
    if db.now() >= review_round["decision_deadline_at"]:
        raise ApiError("ERR_ROUND_DEADLINE_PASSED")

    vote = new_row("votes", {
        "round_id": review_round["id"],
        "voter_role": caller_role(),
        "voter_user_id": caller_id(),
        "decision": decision,
        "comment": comment,
    }, versioned=False)
    db.votes[vote["id"]] = vote

    review_round["cast_vote_count"] = review_round["cast_vote_count"] + 1
    if decision == "APPROVE":
        review_round["approve_count"] = review_round["approve_count"] + 1
    elif decision == "REVISE":
        review_round["revise_count"] = review_round["revise_count"] + 1
    else:
        review_round["veto_count"] = review_round["veto_count"] + 1
    touch(review_round)

    if decision == "VETO":
        # A veto ends the round at once; quorum is not required.
        review_round["status"] = "VETOED"
        review_round["decided_at"] = db.now()
        if caller_role() == ROLE_CONSERVATOR:
            project["conservation_veto_count"] = project["conservation_veto_count"] + 1
        cascades.package_to_revision_requested(package)
    elif review_round["cast_vote_count"] == review_round["required_vote_count"]:
        if review_round["approve_count"] == review_round["required_vote_count"]:
            review_round["status"] = "APPROVED"
            review_round["decided_at"] = db.now()
            cascades.package_to_approved(package)
        elif review_round["revise_count"] >= 1:
            review_round["status"] = "REVISION_REQUESTED"
            review_round["decided_at"] = db.now()
            cascades.package_to_revision_requested(package)

    # The response to a vote is the UPDATED ROUND, not the vote row (PRD §3.3).
    return object_response(serializers.round_json(review_round), 201)


@bp.route("/review-rounds/<round_id>/votes", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_votes(round_id):
    review_round = helpers.get_round(round_id)
    limit, offset = pagination()
    rows = helpers.votes_of_round(review_round["id"])
    return list_response(rows, serializers.vote_json, limit, offset)
