"""ReviewNote routes (PRD §3.6)."""

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
from services.derived import recompute_round_counters

bp = Blueprint("review_notes", __name__)

SEVERITIES = ("INFO", "MINOR", "MAJOR", "CRITICAL")
NOTE_TERMINAL = ("RESOLVED", "VOID")
LIST_ROLES = ("PostSupervisor", "ReviewerLead", "ConformEditor")


def serialize(note):
    return dict(note)


def get_note_or_404(project, note_id):
    note = db.review_notes.get(note_id)
    if note is None or note["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"ReviewNote {note_id} does not exist", 404)
    return note


@bp.route("/post-production/projects/<project_id>/review-notes", methods=["POST"])
def create_note(project_id):
    require_roles(("ReviewerLead", "ConformEditor", "PostSupervisor"))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("round_id", "author_email", "severity", "body"))
    round_id = body["round_id"]
    if not isinstance(round_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'round_id' must be a string", 400)
    # FK resolution (priority 3)
    review_round = db.review_rounds.get(round_id)
    if review_round is None or review_round["project_id"] != project_id:
        raise ApiError(ERR_NOT_FOUND, f"ReviewRound {round_id} does not exist", 404)
    author_email = check_string(body, "author_email")
    if author_email != author_email.lower():
        raise ApiError(
            ERR_INVALID_REQUEST, "Field 'author_email' must be lowercase", 400
        )
    severity = check_enum(body, "severity", SEVERITIES)
    note_body = check_string(body, "body", min_len=1, max_len=2000)
    note = new_entity(
        {
            "project_id": project_id,
            "round_id": round_id,
            "author_email": author_email,
            "severity": severity,
            "body": note_body,
            "status": "OPEN",
        }
    )
    db.review_notes[note["id"]] = note
    # Adding a note recomputes both counters on the parent round.
    recompute_round_counters(review_round)
    return success_object(serialize(note), 201)


@bp.route("/post-production/projects/<project_id>/review-notes", methods=["GET"])
def list_notes(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [n for n in db.review_notes.values() if n["project_id"] == project_id]
    round_id = get_filter("round_id")
    if round_id is not None:
        items = [n for n in items if n.get("round_id") == round_id]
    severity = get_filter("severity")
    if severity is not None:
        items = [n for n in items if n["severity"] == severity]
    status = get_filter("status")
    if status is not None:
        items = [n for n in items if n["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(n) for n in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/review-notes/<note_id>/ack",
    methods=["POST"],
)
def ack_note(project_id, note_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    note = get_note_or_404(project, note_id)
    guard_transition(note, "OPEN", NOTE_TERMINAL, "review note")
    review_round = db.review_rounds.get(note["round_id"])
    if review_round is None:
        raise ApiError(
            ERR_NOT_FOUND, f"ReviewRound {note['round_id']} does not exist", 404
        )
    # Note may be acknowledged only while its parent round is OPEN.
    if review_round["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE,
            "A note may be acknowledged only while its parent round is OPEN",
            409,
        )
    note["status"] = "ACKED"
    touch(note)
    return success_object(serialize(note))


@bp.route(
    "/post-production/projects/<project_id>/review-notes/<note_id>/resolve",
    methods=["POST"],
)
def resolve_note(project_id, note_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    note = get_note_or_404(project, note_id)
    guard_transition(note, ("OPEN", "ACKED"), NOTE_TERMINAL, "review note")
    review_round = db.review_rounds.get(note["round_id"])
    if review_round is None:
        raise ApiError(
            ERR_NOT_FOUND, f"ReviewRound {note['round_id']} does not exist", 404
        )
    # Resolution permitted while the parent round is OPEN or NOTES_CLOSED.
    if review_round["status"] not in ("OPEN", "NOTES_CLOSED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "A note may be resolved only while its parent round is OPEN or "
            "NOTES_CLOSED",
            409,
        )
    note["status"] = "RESOLVED"
    touch(note)
    recompute_round_counters(review_round)
    return success_object(serialize(note))


# ---------------------------------------------------------------------------
# Flat alias
# ---------------------------------------------------------------------------


@bp.route("/post-production/review-notes/<note_id>", methods=["GET"])
def get_note_flat(note_id):
    require_roles(LIST_ROLES)
    note = db.review_notes.get(note_id)
    if note is None:
        raise ApiError(ERR_NOT_FOUND, f"ReviewNote {note_id} does not exist", 404)
    return success_object(serialize(note))
