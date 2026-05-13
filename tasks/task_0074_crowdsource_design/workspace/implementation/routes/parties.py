"""Client, Designer, ReviewerPool registration routes."""
import re

from flask import Blueprint

from common import get_json_body, stamp_new
from db import db
from errors import api_error
from middleware import require_roles
from response import success


bp = Blueprint("parties", __name__)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/clients", methods=["POST"])
def create_client():
    require_roles({"PlatformOps"})
    body = get_json_body()
    company_name = body.get("company_name")
    contact_email = body.get("contact_email")
    tax_jurisdiction = body.get("tax_jurisdiction")
    if not isinstance(company_name, str) or not (1 <= len(company_name) <= 200):
        raise api_error("ERR_VALIDATION", "company_name length 1..200")
    if not isinstance(contact_email, str) or not _EMAIL_RE.match(contact_email):
        raise api_error("ERR_VALIDATION", "contact_email must be a valid RFC-5322 address")
    if tax_jurisdiction not in {"RESIDENT", "NON_RESIDENT"}:
        raise api_error("ERR_VALIDATION", "tax_jurisdiction must be RESIDENT or NON_RESIDENT")
    client = stamp_new({
        "company_name": company_name,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "tax_jurisdiction": tax_jurisdiction,
    })
    db.clients[client["id"]] = client
    return success(client, status=201)


@bp.route("/designers", methods=["POST"])
def create_designer():
    require_roles({"PlatformOps"})
    body = get_json_body()
    display_name = body.get("display_name")
    qualification_level = body.get("qualification_level", "NOVICE")
    categories = body.get("categories")
    tax_residency = body.get("tax_residency")

    if not isinstance(display_name, str) or not (1 <= len(display_name) <= 80):
        raise api_error("ERR_VALIDATION", "display_name length 1..80")
    if display_name in db.designers_by_display_name:
        raise api_error("ERR_VALIDATION", "display_name must be unique")
    if qualification_level not in {"NOVICE", "JUNIOR", "SENIOR", "EXPERT"}:
        raise api_error("ERR_VALIDATION", "qualification_level invalid")
    if (not isinstance(categories, list) or not categories
            or not all(isinstance(c, str) for c in categories)):
        raise api_error("ERR_VALIDATION", "categories must be a non-empty list of codes")
    # FK check: every category code must exist
    for code in categories:
        if code not in db.design_categories_by_code:
            raise api_error("ERR_FK_NOT_FOUND", f"design category {code} not found")
    if tax_residency not in {"RESIDENT", "NON_RESIDENT"}:
        raise api_error("ERR_VALIDATION", "tax_residency must be RESIDENT or NON_RESIDENT")

    designer = stamp_new({
        "display_name": display_name,
        "qualification_level": qualification_level,
        "categories": list(categories),
        "tax_residency": tax_residency,
        "status": "ACTIVE",
        "trust_score": 100.0,
    })
    db.designers[designer["id"]] = designer
    db.designers_by_display_name[display_name] = designer["id"]
    return success(designer, status=201)


@bp.route("/designers/<designer_id>", methods=["GET"])
def get_designer(designer_id):
    user_id, role = require_roles({"PlatformOps", "Designer"})
    designer = db.designers.get(designer_id)
    if not designer:
        raise api_error("ERR_NOT_FOUND", "designer not found")
    if role == "Designer" and user_id != designer_id:
        raise api_error("ERR_FORBIDDEN", "Designers can only fetch their own profile")
    return success(designer)


@bp.route("/reviewer-pool", methods=["POST"])
def add_reviewer():
    require_roles({"PlatformOps"})
    body = get_json_body()
    reviewer_id = body.get("reviewer_id")
    name = body.get("name")
    categories = body.get("categories")
    max_concurrent = body.get("max_concurrent_assignments", 20)
    conflict = body.get("conflict_designer_ids", [])

    if not isinstance(reviewer_id, str) or not reviewer_id:
        raise api_error("ERR_VALIDATION", "reviewer_id is required")
    if reviewer_id in db.reviewers:
        raise api_error("ERR_VALIDATION", "reviewer_id must be unique")
    if not isinstance(name, str) or not name:
        raise api_error("ERR_VALIDATION", "name is required")
    if (not isinstance(categories, list) or not categories
            or not all(isinstance(c, str) for c in categories)):
        raise api_error("ERR_VALIDATION", "categories must be non-empty list of codes")
    for code in categories:
        if code not in db.design_categories_by_code:
            raise api_error("ERR_FK_NOT_FOUND", f"design category {code} not found")
    try:
        max_concurrent = int(max_concurrent)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "max_concurrent_assignments must be integer")
    if not (1 <= max_concurrent <= 100):
        raise api_error("ERR_VALIDATION", "max_concurrent_assignments 1..100")
    if not isinstance(conflict, list) or not all(isinstance(c, str) for c in conflict):
        raise api_error("ERR_VALIDATION", "conflict_designer_ids must be a list of strings")
    for did in conflict:
        if did not in db.designers:
            raise api_error("ERR_FK_NOT_FOUND", f"designer {did} not found")

    record = {
        "id": reviewer_id,
        "reviewer_id": reviewer_id,
        "name": name,
        "categories": list(categories),
        "max_concurrent_assignments": max_concurrent,
        "conflict_designer_ids": list(conflict),
    }
    # AuditEvent-like entities have no version/updated_at, but reviewer pool record only has id+created_at.
    from clock import format_iso, get_now
    record["created_at"] = format_iso(get_now())
    db.reviewers[reviewer_id] = record
    return success(record, status=201)
