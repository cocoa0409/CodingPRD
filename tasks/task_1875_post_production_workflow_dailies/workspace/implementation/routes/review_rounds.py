"""ReviewRound routes (PRD §3.6)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_string,
    check_enum,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from services.transitions import guard_transition
from services.derived import recompute_round_counters, recompute_conform_ready

bp = Blueprint("review_rounds", __name__)

TARGET_KINDS = ("DAILIES", "CUT", "VENDOR_RETURN", "DELIVERABLE")
ROUND_TERMINAL = ("APPROVED", "REJECTED", "VOID")
LIST_ROLES = ("PostSupervisor", "ReviewerLead", "ConformEditor", "DailiesCoordinator")
GET_ROLES = ("PostSupervisor", "ReviewerLead", "ConformEditor")


def serialize(review_round):
    return dict(review_round)


def get_round_or_404(project, round_id):
    rr = db.review_rounds.get(round_id)
    if rr is None or rr["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"ReviewRound {round_id} does not exist", 404)
    return rr


def _target_exists(project_id, target_kind, target_ref_id):
    """Resolve target_ref_id against the entity class implied by target_kind.

    DAILIES -> DailiesPackage; CUT/VENDOR_RETURN -> TurnoverPackage;
    DELIVERABLE -> Deliverable.
    """
    if target_kind == "DAILIES":
        target = db.dailies_packages.get(target_ref_id)
    elif target_kind == "DELIVERABLE":
        target = db.deliverables.get(target_ref_id)
    else:  # CUT, VENDOR_RETURN
        target = db.turnovers.get(target_ref_id)
    if target is None:
        return False
    return target.get("project_id") == project_id


@bp.route("/post-production/projects/<project_id>/review-rounds", methods=["POST"])
def create_round(project_id):
    require_roles(("ReviewerLead",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("round_label", "target_kind", "target_ref_id"))
    round_label = check_string(body, "round_label")
    target_kind = check_enum(body, "target_kind", TARGET_KINDS)
    target_ref_id = check_string(body, "target_ref_id")
    for existing in db.review_rounds.values():
        if (
            existing["project_id"] == project_id
            and existing["round_label"] == round_label
        ):
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"round_label '{round_label}' already exists in this project",
                400,
            )
    # FK resolution: target_ref_id must name an existing entity.
    if not _target_exists(project_id, target_kind, target_ref_id):
        raise ApiError(
            ERR_NOT_FOUND,
            f"target_ref_id {target_ref_id} does not resolve for target_kind "
            f"{target_kind}",
            404,
        )
    review_round = new_entity(
        {
            "project_id": project_id,
            "round_label": round_label,
            "target_kind": target_kind,
            "target_ref_id": target_ref_id,
            "status": "OPEN",
            "unresolved_critical": False,
            "open_note_count": 0,
        }
    )
    db.review_rounds[review_round["id"]] = review_round
    return success_object(serialize(review_round), 201)


@bp.route("/post-production/projects/<project_id>/review-rounds", methods=["GET"])
def list_rounds(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [r for r in db.review_rounds.values() if r["project_id"] == project_id]
    target_kind = get_filter("target_kind")
    if target_kind is not None:
        items = [r for r in items if r["target_kind"] == target_kind]
    status = get_filter("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(r) for r in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/review-rounds/<round_id>", methods=["GET"]
)
def get_round(project_id, round_id):
    require_roles(GET_ROLES)
    project = get_project_or_404(project_id)
    review_round = get_round_or_404(project, round_id)
    return success_object(serialize(review_round))


@bp.route(
    "/post-production/projects/<project_id>/review-rounds/<round_id>/close-notes",
    methods=["POST"],
)
def close_notes(project_id, round_id):
    require_roles(("ReviewerLead",))
    project = get_project_or_404(project_id)
    review_round = get_round_or_404(project, round_id)
    guard_transition(review_round, "OPEN", ROUND_TERMINAL, "review round")
    review_round["status"] = "NOTES_CLOSED"
    touch(review_round)
    # Recompute counters so the approval decision sees fresh figures.
    recompute_round_counters(review_round)
    return success_object(serialize(review_round))


@bp.route(
    "/post-production/projects/<project_id>/review-rounds/<round_id>/approve",
    methods=["POST"],
)
def approve_round(project_id, round_id):
    require_roles(("ReviewerLead",))
    project = get_project_or_404(project_id)
    review_round = get_round_or_404(project, round_id)
    guard_transition(review_round, "NOTES_CLOSED", ROUND_TERMINAL, "review round")
    # Approval requires unresolved_critical false and open_note_count zero.
    if review_round.get("unresolved_critical") or review_round.get(
        "open_note_count", 0
    ) != 0:
        raise ApiError(
            ERR_INVALID_STATE,
            "A round with any outstanding note, or any unresolved critical "
            "one, cannot be approved",
            409,
        )
    review_round["status"] = "APPROVED"
    touch(review_round)
    if review_round["target_kind"] in ("CUT", "DELIVERABLE"):
        recompute_conform_ready(project)
    return success_object(serialize(review_round))


@bp.route(
    "/post-production/projects/<project_id>/review-rounds/<round_id>/reject",
    methods=["POST"],
)
def reject_round(project_id, round_id):
    require_roles(("ReviewerLead",))
    project = get_project_or_404(project_id)
    review_round = get_round_or_404(project, round_id)
    guard_transition(review_round, "NOTES_CLOSED", ROUND_TERMINAL, "review round")
    review_round["status"] = "REJECTED"
    touch(review_round)
    # When target_kind is DELIVERABLE, the linked deliverable transitions to
    # REJECTED.
    if review_round["target_kind"] == "DELIVERABLE":
        deliverable = db.deliverables.get(review_round["target_ref_id"])
        if deliverable is not None and deliverable["status"] not in (
            "REJECTED",
            "DELIVERED",
            "SUPERSEDED",
        ):
            deliverable["status"] = "REJECTED"
            touch(deliverable)
            from services.derived import recompute_deliverable_counters

            recompute_deliverable_counters(deliverable)
    return success_object(serialize(review_round))


# ---------------------------------------------------------------------------
# Flat alias + reverse reachability
# ---------------------------------------------------------------------------


@bp.route("/post-production/review-rounds/<round_id>", methods=["GET"])
def get_round_flat(round_id):
    require_roles(GET_ROLES)
    review_round = db.review_rounds.get(round_id)
    if review_round is None:
        raise ApiError(ERR_NOT_FOUND, f"ReviewRound {round_id} does not exist", 404)
    return success_object(serialize(review_round))


@bp.route("/post-production/review-rounds/<round_id>/notes", methods=["GET"])
def list_round_notes(round_id):
    require_roles(GET_ROLES)
    review_round = db.review_rounds.get(round_id)
    if review_round is None:
        raise ApiError(ERR_NOT_FOUND, f"ReviewRound {round_id} does not exist", 404)
    from routes.review_notes import serialize as serialize_note

    limit, offset = get_pagination()
    items = [n for n in db.review_notes.values() if n.get("round_id") == round_id]
    severity = get_filter("severity")
    if severity is not None:
        items = [n for n in items if n["severity"] == severity]
    status = get_filter("status")
    if status is not None:
        items = [n for n in items if n["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_note(n) for n in window], limit, offset, total)
