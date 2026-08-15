"""Family and Student endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import invalid_request, ownership_mismatch, not_found
from services.core import base_record, public, get_family

bp = Blueprint("families", __name__)


@bp.route("/school/families", methods=["POST"])
def create_family():
    require_roles(["SchoolAdmin"])
    body = request.get_json(silent=True) or {}
    family_name = body.get("family_name")
    primary_email = body.get("primary_email")
    membership_status = body.get("membership_status")
    if not isinstance(family_name, str) or not family_name:
        raise invalid_request("family_name is required")
    if not isinstance(primary_email, str) or not primary_email:
        raise invalid_request("primary_email is required")
    if membership_status not in ("MEMBER", "NON_MEMBER"):
        raise invalid_request("membership_status must be MEMBER or NON_MEMBER")

    rec = base_record()
    rec.update({
        "family_name": family_name,
        "primary_email": primary_email,
        "membership_status": membership_status,
        "outstanding_balance_cents": 0,
        "credit_balance_cents": 0,
    })
    store.families[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/school/families/<family_id>", methods=["GET"])
def get_family_endpoint(family_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    if role == "Parent" and user_id != family_id:
        raise ownership_mismatch()
    rec = get_family(family_id)
    return success_object(public(rec))


@bp.route("/school/families/<family_id>/students", methods=["POST"])
def create_student(family_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    if role == "Parent" and user_id != family_id:
        raise ownership_mismatch()
    family = get_family(family_id)
    body = request.get_json(silent=True) or {}
    full_name = body.get("full_name")
    grade = body.get("grade")
    hebrew_level = body.get("hebrew_level")
    if not isinstance(full_name, str) or not full_name:
        raise invalid_request("full_name is required")
    if grade not in ("K", "G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        raise invalid_request("grade must be one of K, G1..G7")
    if hebrew_level not in ("BEGINNER", "INTERMEDIATE", "ADVANCED"):
        raise invalid_request("hebrew_level must be BEGINNER, INTERMEDIATE, or ADVANCED")

    rec = base_record()
    rec.update({
        "family_id": family["id"],
        "full_name": full_name,
        "grade": grade,
        "hebrew_level": hebrew_level,
    })
    store.students[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/school/families/<family_id>/students", methods=["GET"])
def list_students(family_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    if role == "Parent" and user_id != family_id:
        raise ownership_mismatch()
    family = get_family(family_id)
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.students.values() if s["family_id"] == family["id"]]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(s) for s in page], limit, offset, total)
