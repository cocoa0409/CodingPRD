"""Student routes."""

from flask import Blueprint, g, request

from config import ACCOUNT_TYPES, DISPLAY_NAME_MAX, DISPLAY_NAME_MIN
from db import db, init_common_fields, init_link_or_batch_fields
from errors import APIError
from middleware import require_auth
from response import success_response
from services.validators import (
    optional_string,
    require_body,
    require_email,
    require_enum,
    require_string,
)

student_bp = Blueprint("student", __name__)


def _student_accessible_by(student, user_id, user_role):
    if user_role == "PlatformAdmin":
        return True
    if user_role == "Student" and user_id == student["id"]:
        return True
    if user_role == "Parent":
        # Linked parent (any link, even pending — but only ACTIVE per PRD context;
        # PRD: "linked parent" — interpret as ACTIVE link)
        for link in db.parent_child_links.values():
            if (
                link["parent_id"] == user_id
                and link["student_id"] == student["id"]
                and link["link_status"] == "ACTIVE"
            ):
                return True
    return False


@student_bp.route("/students", methods=["POST"])
@require_auth({"Student", "Parent", "PlatformAdmin"})
def create_student():
    body = request.get_json(silent=True) or {}
    require_body(body)
    display_name = require_string(body, "display_name", DISPLAY_NAME_MIN, DISPLAY_NAME_MAX)
    email = require_email(body, "email")
    account_type = require_enum(body, "account_type", ACCOUNT_TYPES)
    parent_id = optional_string(body, "parent_id")

    if email in db.student_emails:
        raise APIError("ERR_VALIDATION", "Email already in use.")

    if account_type == "ADULT" and parent_id is not None:
        raise APIError("ERR_MINOR_REQUIRES_PARENT")
    if account_type == "MINOR" and parent_id is None:
        raise APIError("ERR_MINOR_REQUIRES_PARENT")

    if account_type == "MINOR":
        if parent_id not in db.parents:
            raise APIError("ERR_NOT_FOUND")

    student = init_common_fields({
        "display_name": display_name,
        "email": email,
        "account_type": account_type,
        "parent_id": parent_id,
        "credit_balance_cents": 0,
    })
    db.students[student["id"]] = student
    db.student_emails.add(email)

    # If MINOR, auto-create a PENDING_PARENT_APPROVAL link
    if account_type == "MINOR":
        link = init_link_or_batch_fields({
            "parent_id": parent_id,
            "student_id": student["id"],
            "link_status": "PENDING_PARENT_APPROVAL",
            "approved_at": None,
        })
        db.parent_child_links[link["id"]] = link

    return success_response(student, status=201)


@student_bp.route("/students/<student_id>", methods=["GET"])
@require_auth({"Student", "Parent", "PlatformAdmin"})
def get_student(student_id):
    student = db.students.get(student_id)
    if student is None:
        raise APIError("ERR_NOT_FOUND")
    if not _student_accessible_by(student, g.user_id, g.user_role):
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    return success_response(student, status=200)
