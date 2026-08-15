"""Application and ReviewAssignment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from clock import clock
from db import db
from errors import (err_duplicate_reviewer, err_invalid_request, err_invalid_state,
                    err_ladder_rung, err_no_active_criterion, err_not_found,
                    err_not_owner, err_quorum_exceeded, err_review_cycle_exhausted,
                    err_review_window_expired, err_segregation, err_stale_reference,
                    err_stale_version)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from serializers import application_view, assignment_view, decision_view
from services.budget import recompute_budgets_for_unit
from services.calculations import (QUORUM, REVIEW_WINDOW_DAYS, TRACK_ORDER,
                                   active_criterion_for, calc_committee_score,
                                   calc_participation_window, record_risk_event,
                                   recompute_risk)
from util import require_fields, require_int, require_string, require_enum

bp = Blueprint("applications", __name__)

NEXT_RUNG = {"CN_I": "CN_II", "CN_II": "CN_III", "CN_III": "CN_IV"}
TARGET_LEVELS = {"CN_II", "CN_III", "CN_IV"}
DIMENSIONS = ("leadership", "clinical_expertise", "professional_development", "outcomes")


def _get_nurse_or_404(nid):
    nurse = db.nurses.get(nid)
    if nurse is None:
        raise err_not_found("Nurse not found")
    return nurse


def _get_app_or_404(aid):
    app = db.applications.get(aid)
    if app is None:
        raise err_not_found("Application not found")
    return app


def _get_assignment_or_404(aid):
    asg = db.review_assignments.get(aid)
    if asg is None:
        raise err_not_found("ReviewAssignment not found")
    return asg


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.route("/clinical-ladder/applications", methods=["POST"])
def create_application():
    user_id, _ = require_roles("Nurse")
    payload = request.get_json(silent=True)
    require_fields(payload, ["nurse_id", "target_level", "portfolio_narrative", "expected_nurse_version"])
    nurse_id = payload.get("nurse_id")
    if not isinstance(nurse_id, str):
        raise err_invalid_request("nurse_id must be a string")
    target_level = require_enum(payload, "target_level", TARGET_LEVELS)
    narrative = require_string(payload, "portfolio_narrative")
    expected_version = require_int(payload, "expected_nurse_version")

    nurse = _get_nurse_or_404(nurse_id)

    # Pinned order (PRD 2.8): stale version, then ownership, then one-rung, then active criterion
    if expected_version != nurse["version"]:
        raise err_stale_version()
    if user_id != nurse_id:
        raise err_not_owner()
    if NEXT_RUNG.get(nurse["current_level"]) != target_level:
        raise err_ladder_rung()
    if active_criterion_for(target_level) is None:
        raise err_no_active_criterion()

    now = clock.now()
    app = {
        "id": db.new_id(),
        "nurse_id": nurse_id,
        "target_level": target_level,
        "portfolio_narrative": narrative,
        "criterion_id": None,
        "status": "DRAFT",
        "submitted_at": None,
        "review_cycle": 0,
        "aggregate_score": None,
        "participation_snapshot_points": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.applications[app["id"]] = app

    # Drafting itself advances the nurse's version by one
    nurse["version"] += 1
    nurse["updated_at"] = now

    return success_object(application_view(app), status=201)


@bp.route("/clinical-ladder/applications", methods=["GET"])
def list_applications():
    require_roles("ProgramAdmin", "Nurse")
    limit, offset = parse_pagination(request.args)
    nurse_id = request.args.get("nurse_id")
    criterion_id = request.args.get("criterion_id")
    status = request.args.get("status")
    rows = sorted(db.applications.values(), key=lambda a: a["created_at"])
    if nurse_id is not None:
        rows = [a for a in rows if a["nurse_id"] == nurse_id]
    if criterion_id is not None:
        rows = [a for a in rows if a["criterion_id"] == criterion_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([application_view(a) for a in page], limit, offset, total)


@bp.route("/clinical-ladder/applications/<aid>", methods=["GET"])
def get_application(aid):
    require_roles("ProgramAdmin", "Nurse")
    app = _get_app_or_404(aid)
    return success_object(application_view(app))


@bp.route("/clinical-ladder/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    user_id, _ = require_roles("Nurse")
    app = _get_app_or_404(aid)
    if app["status"] != "DRAFT":
        raise err_invalid_state("Application is not in DRAFT")
    nurse = _get_nurse_or_404(app["nurse_id"])

    # Ownership, then the eligibility gauntlet in order: one-rung, active criterion,
    # live participation window, certification track
    if user_id != app["nurse_id"]:
        raise err_not_owner()
    if NEXT_RUNG.get(nurse["current_level"]) != app["target_level"]:
        raise err_ladder_rung()
    criterion = active_criterion_for(app["target_level"])
    if criterion is None:
        raise err_no_active_criterion()
    live_points = calc_participation_window(nurse["id"])
    if live_points < criterion["min_participation_points"]:
        # No dedicated error in the catalog for a failed submit precondition;
        # the transition's preconditions are unmet, so ERR_INVALID_STATE applies.
        raise err_invalid_state(
            "Participation points in the 24-month lookback below criterion minimum")
    required = criterion["required_certification_track"]
    if required != "NONE":
        holds = any(
            c["nurse_id"] == nurse["id"] and c["status"] == "CURRENT"
            and TRACK_ORDER[c["track"]] >= TRACK_ORDER[required]
            for c in db.certifications.values())
        if not holds:
            raise err_invalid_state(
                "Nurse lacks a CURRENT certification at or above the required track")

    now = clock.now()
    app["criterion_id"] = criterion["id"]
    app["criterion_version_pinned"] = criterion["version"]
    app["submitted_at"] = now
    app["participation_snapshot_points"] = live_points
    app["status"] = "SUBMITTED"
    app["updated_at"] = now
    app["version"] += 1
    return success_object(application_view(app))


@bp.route("/clinical-ladder/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    user_id, _ = require_roles("Nurse")
    app = _get_app_or_404(aid)
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise err_invalid_state("Application cannot be withdrawn from its current state")
    if user_id != app["nurse_id"]:
        raise err_not_owner()
    app["status"] = "WITHDRAWN"
    app["updated_at"] = clock.now()
    app["version"] += 1
    return success_object(application_view(app))


@bp.route("/clinical-ladder/applications/<aid>/assignments", methods=["POST"])
def create_assignment(aid):
    require_roles("ProgramAdmin")
    app = _get_app_or_404(aid)
    payload = request.get_json(silent=True)
    require_fields(payload, ["reviewer_nurse_id"])
    reviewer_id = payload.get("reviewer_nurse_id")
    if not isinstance(reviewer_id, str):
        raise err_invalid_request("reviewer_nurse_id must be a string")

    reviewer = db.nurses.get(reviewer_id)
    if reviewer is None:
        raise err_not_found("Reviewer nurse not found")

    # First assignment moves SUBMITTED -> IN_REVIEW; further staffing happens
    # while the application is already IN_REVIEW.
    if app["status"] not in ("SUBMITTED", "IN_REVIEW"):
        raise err_invalid_state("Application is not SUBMITTED or IN_REVIEW")

    # Pinned order: segregation of duties, then quorum headroom, then reviewer duplication
    if reviewer_id == app["nurse_id"]:
        raise err_segregation("Reviewer may not be the applicant")

    assignments = [a for a in db.review_assignments.values() if a["application_id"] == app["id"]]
    live = [a for a in assignments if a["status"] in ("PENDING", "SCORED")]
    has_terminal_replacement = any(a["status"] in ("RECUSED", "EXPIRED") for a in assignments)
    if len(live) >= QUORUM and not has_terminal_replacement:
        raise err_quorum_exceeded()

    for a in live:
        if a["reviewer_nurse_id"] == reviewer_id:
            raise err_duplicate_reviewer()

    now = clock.now()
    asg = {
        "id": db.new_id(),
        "application_id": app["id"],
        "reviewer_nurse_id": reviewer_id,
        "dimension_scores": None,
        "submitted_at": None,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.review_assignments[asg["id"]] = asg

    # First assignment moves the application SUBMITTED -> IN_REVIEW
    app["status"] = "IN_REVIEW"
    app["updated_at"] = now
    app["version"] += 1

    return success_object(assignment_view(asg), status=201)


@bp.route("/clinical-ladder/applications/<aid>/assignments", methods=["GET"])
def list_app_assignments(aid):
    require_roles("ProgramAdmin", "Nurse")
    app = _get_app_or_404(aid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = sorted([a for a in db.review_assignments.values() if a["application_id"] == app["id"]],
                  key=lambda a: a["created_at"])
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([assignment_view(a) for a in page], limit, offset, total)


@bp.route("/clinical-ladder/applications/<aid>/decisions", methods=["GET"])
def list_app_decisions(aid):
    require_roles("ProgramAdmin", "Nurse")
    app = _get_app_or_404(aid)
    limit, offset = parse_pagination(request.args)
    rows = sorted([d for d in db.advancement_decisions.values() if d["application_id"] == app["id"]],
                  key=lambda d: d["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([decision_view(d) for d in page], limit, offset, total)


@bp.route("/clinical-ladder/applications/<aid>/return-for-revision", methods=["POST"])
def return_for_revision(aid):
    require_roles("ProgramAdmin")
    app = _get_app_or_404(aid)
    if app["status"] != "IN_REVIEW":
        raise err_invalid_state("Application is not IN_REVIEW")
    if app["review_cycle"] >= 3:
        raise err_review_cycle_exhausted()

    now = clock.now()
    # Cascade: every still-PENDING assignment -> EXPIRED (SCORED remain for audit)
    for a in db.review_assignments.values():
        if a["application_id"] == app["id"] and a["status"] == "PENDING":
            a["status"] = "EXPIRED"
            a["updated_at"] = now
            a["version"] += 1
    app["review_cycle"] += 1
    # Auto-transition RETURNED_FOR_REVISION -> DRAFT: clear submitted_at, bump version
    app["status"] = "DRAFT"
    app["submitted_at"] = None
    app["updated_at"] = now
    app["version"] += 1
    return success_object(application_view(app))


@bp.route("/clinical-ladder/applications/<aid>/decide", methods=["POST"])
def decide_application(aid):
    user_id, _ = require_roles("ProgramAdmin")
    app = _get_app_or_404(aid)
    payload = request.get_json(silent=True)
    require_fields(payload, ["outcome", "expected_application_version"])
    outcome = require_enum(payload, "outcome", {"APPROVE", "DENY"})
    expected_version = require_int(payload, "expected_application_version")

    if app["status"] != "IN_REVIEW":
        raise err_invalid_state("Application is not IN_REVIEW")

    # OCC first, before anything else is examined
    if expected_version != app["version"]:
        raise err_stale_version()

    assignments = [a for a in db.review_assignments.values() if a["application_id"] == app["id"]]
    scored = [a for a in assignments if a["status"] == "SCORED"]
    pending = [a for a in assignments if a["status"] == "PENDING"]
    if len(scored) < QUORUM or len(pending) > 0:
        raise err_invalid_state("Quorum not reached or PENDING assignments remain")

    nurse = _get_nurse_or_404(app["nurse_id"])
    now = clock.now()

    if outcome == "APPROVE":
        # Segregation of duties: decider may not be a scored reviewer
        if any(a["reviewer_nurse_id"] == user_id for a in scored):
            raise err_segregation("A scorer may not decide")
        # Reference staleness: pinned criterion version must be unchanged
        criterion = db.ladder_criteria.get(app["criterion_id"])
        if criterion is None or criterion["version"] != app.get("criterion_version_pinned"):
            raise err_stale_reference("Pinned criterion modified since submission")
        # Score threshold, boundary inclusive
        aggregate = app["aggregate_score"]
        if aggregate is None:
            aggregate = calc_committee_score(app["id"])
        if aggregate is None or aggregate < criterion["min_portfolio_score"]:
            raise err_invalid_state("Aggregate score below the criterion minimum")

    # Both outcomes: append-only AdvancementDecision row
    criterion = db.ladder_criteria.get(app["criterion_id"])
    decision = {
        "id": db.new_id(),
        "application_id": app["id"],
        "decided_by_admin_id": user_id,
        "outcome": outcome,
        "criterion_version_snapshot": criterion["version"] if criterion else None,
        "decided_at": now,
        "created_at": now,
    }
    db.advancement_decisions[decision["id"]] = decision

    app["review_cycle"] += 1
    app["updated_at"] = now
    app["version"] += 1

    if outcome == "APPROVE":
        app["status"] = "APPROVED"
        nurse["current_level"] = app["target_level"]
        nurse["differential_status"] = "ACTIVE"
        nurse["differential_activated_at"] = now
        nurse["updated_at"] = now
        nurse["version"] += 1
        record_risk_event(nurse["id"], "advancement")
        recompute_risk(nurse["id"])
        recompute_budgets_for_unit(nurse["home_unit"])
    else:
        app["status"] = "DENIED"
        record_risk_event(nurse["id"], "application_denial")
        recompute_risk(nurse["id"])

    return success_object(application_view(app))


# ---------------------------------------------------------------------------
# Review assignments (top-level)
# ---------------------------------------------------------------------------

@bp.route("/clinical-ladder/review-assignments", methods=["GET"])
def list_assignments():
    require_roles("ProgramAdmin", "Nurse")
    limit, offset = parse_pagination(request.args)
    application_id = request.args.get("application_id")
    reviewer_nurse_id = request.args.get("reviewer_nurse_id")
    status = request.args.get("status")
    rows = sorted(db.review_assignments.values(), key=lambda a: a["created_at"])
    if application_id is not None:
        rows = [a for a in rows if a["application_id"] == application_id]
    if reviewer_nurse_id is not None:
        rows = [a for a in rows if a["reviewer_nurse_id"] == reviewer_nurse_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([assignment_view(a) for a in page], limit, offset, total)


@bp.route("/clinical-ladder/review-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_roles("ProgramAdmin", "Nurse")
    asg = _get_assignment_or_404(aid)
    return success_object(assignment_view(asg))


@bp.route("/clinical-ladder/review-assignments/<aid>/score", methods=["POST"])
def score_assignment(aid):
    user_id, _ = require_roles("Nurse")
    asg = _get_assignment_or_404(aid)
    payload = request.get_json(silent=True)
    require_fields(payload, ["dimension_scores"])
    ds = payload.get("dimension_scores")
    if not isinstance(ds, dict):
        raise err_invalid_request("dimension_scores must be an object")
    for dim in DIMENSIONS:
        v = ds.get(dim)
        if isinstance(v, bool) or not isinstance(v, int) or not (0 <= v <= 100):
            raise err_invalid_request(f"dimension_scores.{dim} must be an integer in [0, 100]")

    if asg["status"] != "PENDING":
        raise err_invalid_state("Assignment is not PENDING")
    if user_id != asg["reviewer_nurse_id"]:
        raise err_not_owner()
    app = _get_app_or_404(asg["application_id"])
    if app["status"] != "IN_REVIEW":
        raise err_invalid_state("Parent application is not IN_REVIEW")
    now = clock.now()
    if now > asg["created_at"] + timedelta(days=REVIEW_WINDOW_DAYS):
        raise err_review_window_expired()

    asg["dimension_scores"] = {dim: ds[dim] for dim in DIMENSIONS}
    asg["submitted_at"] = now
    asg["status"] = "SCORED"
    asg["updated_at"] = now
    asg["version"] += 1

    # Bubble up: quorum reached and no PENDING remain -> aggregate score computed
    siblings = [a for a in db.review_assignments.values() if a["application_id"] == app["id"]]
    scored = [a for a in siblings if a["status"] == "SCORED"]
    still_pending = [a for a in siblings if a["status"] == "PENDING"]
    if len(scored) >= QUORUM and len(still_pending) == 0:
        app["aggregate_score"] = calc_committee_score(app["id"])
        app["updated_at"] = now
        app["version"] += 1

    return success_object(assignment_view(asg))


@bp.route("/clinical-ladder/review-assignments/<aid>/recuse", methods=["POST"])
def recuse_assignment(aid):
    user_id, _ = require_roles("Nurse")
    asg = _get_assignment_or_404(aid)
    if asg["status"] != "PENDING":
        raise err_invalid_state("Assignment is not PENDING")
    if user_id != asg["reviewer_nurse_id"]:
        raise err_not_owner()
    asg["status"] = "RECUSED"
    asg["updated_at"] = clock.now()
    asg["version"] += 1
    return success_object(assignment_view(asg))
