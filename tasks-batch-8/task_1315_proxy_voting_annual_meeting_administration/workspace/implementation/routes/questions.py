"""QuestionSubmission endpoints (PRD §3.5): submit / moderate / resubmit."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_CROSS_MEETING_REFERENCE,
    ERR_FORBIDDEN,
    ERR_INVALID_MEETING_STATE,
    ERR_INVALID_QUESTION_STATE,
    ERR_MEETING_MODE_INCOMPATIBLE,
    ERR_MEETING_NOT_FOUND,
    ERR_QUESTION_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("questions", __name__)

MODERATE_ACTIONS = {"APPROVE", "REJECT", "RETURN"}
_ACTION_TO_STATUS = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "RETURN": "RETURNED"}
QUESTION_OPEN_STATES = {"VOTING_OPEN", "MEETING_IN_PROGRESS"}


def get_question_or_404(question_id: str) -> dict:
    question = db.questions.get(question_id)
    if question is None:
        raise_err(ERR_QUESTION_NOT_FOUND, "QuestionSubmission id does not exist")
    return question


@bp.route("/proxy/question-submissions", methods=["POST"])
@require_roles("Shareholder")
def create_question(_user_id: str, _role: str):
    body = get_json_body()

    # Authorization (precedence 2): the shareholder asks on its own account.
    account_id_raw = body.get("account_id")
    if account_id_raw is not None and account_id_raw != _user_id:
        raise_err(ERR_FORBIDDEN, "Shareholder may submit questions only on its own account")

    # Existence (precedence 3).
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    account_id = require_field(body, "account_id")
    account = db.accounts.get(account_id)
    if account is None:
        raise_err(ERR_ACCOUNT_NOT_FOUND, "ShareholderAccount id does not exist")

    # State (precedence 4).
    if meeting["status"] not in QUESTION_OPEN_STATES:
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Questions are accepted only while VOTING_OPEN or MEETING_IN_PROGRESS",
        )

    # Cross-meeting referential integrity (precedence 7).
    if account["meeting_id"] != meeting_id:
        raise_err(
            ERR_CROSS_MEETING_REFERENCE,
            "account_id must belong to the request's meeting",
        )

    # Domain (precedence 8): virtual-platform meetings only.
    if meeting["meeting_mode"] == "IN_PERSON":
        raise_err(
            ERR_MEETING_MODE_INCOMPATIBLE,
            "Question submission requires a VIRTUAL or HYBRID meeting",
        )

    # Shape (precedence 10).
    question_text = require_string(body, "question_text")

    question = {
        "meeting_id": meeting_id,
        "account_id": account_id,
        "question_text": question_text,
        "moderation_note": None,
        "status": "SUBMITTED",
    }
    db.stamp_new(question)
    db.questions[question["id"]] = question
    return success_object(serialize(question), 201)


@bp.route("/proxy/question-submissions", methods=["GET"])
@require_roles("ProxyAdministrator", "InspectorOfElection", "Shareholder")
def list_questions(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.questions.values()))
    if _role == "Shareholder":
        items = [q for q in items if q["account_id"] == _user_id]
    items = apply_filters(items, ["meeting_id", "account_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/question-submissions/<question_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "InspectorOfElection", "Shareholder")
def get_question(question_id: str, _user_id: str, _role: str):
    question = get_question_or_404(question_id)
    if _role == "Shareholder" and question["account_id"] != _user_id:
        raise_err(ERR_FORBIDDEN, "Shareholder may read only its own questions")
    return success_object(serialize(question))


@bp.route("/proxy/question-submissions/<question_id>/moderate", methods=["POST"])
@require_roles("ProxyAdministrator")
def moderate_question(question_id: str, _user_id: str, _role: str):
    question = get_question_or_404(question_id)
    if question["status"] != "SUBMITTED":
        raise_err(
            ERR_INVALID_QUESTION_STATE,
            "Only a SUBMITTED question may be moderated",
        )
    body = get_json_body()
    action = require_enum(body, "action", MODERATE_ACTIONS)
    moderation_note = optional_string(body, "moderation_note")
    question["status"] = _ACTION_TO_STATUS[action]
    question["moderation_note"] = moderation_note
    db.touch(question)
    return success_object(serialize(question))


@bp.route("/proxy/question-submissions/<question_id>/resubmit", methods=["POST"])
@require_roles("Shareholder")
def resubmit_question(question_id: str, _user_id: str, _role: str):
    question = get_question_or_404(question_id)
    if question["account_id"] != _user_id:
        raise_err(ERR_FORBIDDEN, "Shareholder may resubmit only its own questions")
    if question["status"] != "RETURNED":
        raise_err(
            ERR_INVALID_QUESTION_STATE,
            "Only a RETURNED question may be resubmitted",
        )
    body = get_json_body()
    question_text = require_string(body, "question_text")
    question["question_text"] = question_text
    question["moderation_note"] = None
    question["status"] = "SUBMITTED"
    db.touch(question)
    return success_object(serialize(question))
