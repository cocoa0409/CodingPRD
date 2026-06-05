"""Course endpoints (PRD §3.1).

A course is created by the owning Provider (acting on its own provider_id) or by
a BoardAdmin. Provider ownership is enforced after existence (PRD §2.10).
"""

from flask import Blueprint, g, request

import errors
import serialize
from common import (
    get_json_body,
    require_string,
    require_number,
    enum_field,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record
from response import success_object, success_list
from routes.providers import get_provider_or_404
from util import round_half_up_1

bp = Blueprint("courses", __name__)

CATEGORIES = {"ETHICS", "SUBSTANCE", "GENERAL"}


def get_course_or_404(course_id):
    c = db.courses.get(course_id)
    if c is None:
        raise errors.not_found(f"Course '{course_id}' not found.")
    return c


@bp.route("/courses", methods=["POST"])
@require_roles("Provider", "BoardAdmin")
def create_course():
    body = get_json_body()
    provider_id = require_string(body, "provider_id")
    title = require_string(body, "title")
    category = enum_field(body, "category", CATEGORIES)
    credit_hours = require_number(body, "credit_hours")

    # credit_hours strictly > 0 — a non-positive value is a malformed body.
    if credit_hours <= 0:
        raise errors.invalid_request("credit_hours must be greater than 0.")

    # Existence (404) before ownership (403), per validation ordering.
    provider = get_provider_or_404(provider_id)

    # Ownership: a Provider may only create a course under its own provider_id.
    if g.user_role == "Provider" and g.user_id != provider_id:
        raise errors.not_resource_owner(
            "Provider may only create courses under its own provider_id."
        )

    with db.lock:
        rec = new_full_record()
        rec.update({
            "provider_id": provider_id,
            "title": title,
            "category": category,
            "credit_hours": round_half_up_1(credit_hours),
            "status": "ACTIVE",
        })
        db.courses[rec["id"]] = rec

    return success_object(serialize.course(rec), status=201)


@bp.route("/courses/<course_id>", methods=["GET"])
@require_roles("BoardAdmin", "Provider", "Licensee", "Auditor")
def get_course(course_id):
    c = get_course_or_404(course_id)
    return success_object(serialize.course(c), status=200)


@bp.route("/providers/<provider_id>/courses", methods=["GET"])
@require_roles("BoardAdmin", "Provider", "Licensee", "Auditor")
def list_provider_courses(provider_id):
    get_provider_or_404(provider_id)
    limit, offset = parse_pagination()
    items = [c for c in db.courses.values() if c["provider_id"] == provider_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.course(c) for c in page], limit, offset, total, status=200,
    )
