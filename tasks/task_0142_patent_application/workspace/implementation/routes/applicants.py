"""Applicant endpoints (SCAFFOLD §1.5).

POST   /applicants            -> USPTOAdmin
GET    /applicants/{id}       -> USPTOAdmin, Applicant, Examiner
PATCH  /applicants/{id}       -> USPTOAdmin
GET    /applicants            -> USPTOAdmin, Examiner
"""

from flask import Blueprint, g, request

from config import (
    APPLICANT_STATUSES,
    ENTITY_SIZES,
    ROLE_APPLICANT,
    ROLE_EXAMINER,
    ROLE_USPTO_ADMIN,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import build_pagination_meta, parse_pagination, slice_and_sort
from services.patent_engine import (
    create_applicant,
    get_applicant_with_risk_eval,
    update_applicant,
)
from services.serializers import serialize_applicant


applicants_bp = Blueprint("applicants", __name__)


@applicants_bp.post("/applicants")
@require_auth(allowed_roles=[ROLE_USPTO_ADMIN])
def create_applicant_route():
    body = parse_json_body(required_fields=["name", "entity_size"])
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise make_error("ERR_VALIDATION", "name must be a non-empty string.")
    with store.lock:
        applicant = create_applicant(
            name=name,
            entity_size=body["entity_size"],
            gross_income_cents=body.get("gross_income_cents"),
            prior_filings_count=body.get("prior_filings_count"),
        )
    return success(serialize_applicant(applicant, recompute_score=False), status=201)


@applicants_bp.get("/applicants/<applicant_id>")
@require_auth(allowed_roles=[ROLE_USPTO_ADMIN, ROLE_APPLICANT, ROLE_EXAMINER])
def get_applicant_route(applicant_id: str):
    # Existence
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        raise make_error("ERR_NOT_FOUND", f"Applicant {applicant_id} not found.")
    # Ownership: Applicant role may only read their own applicant record
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    if role == ROLE_APPLICANT and user_id != applicant_id:
        raise make_error("ERR_FORBIDDEN", "Applicants may only view their own record.")
    with store.lock:
        applicant = get_applicant_with_risk_eval(applicant_id)
    return success(serialize_applicant(applicant, recompute_score=False))


@applicants_bp.patch("/applicants/<applicant_id>")
@require_auth(allowed_roles=[ROLE_USPTO_ADMIN])
def update_applicant_route(applicant_id: str):
    body = parse_json_body()
    with store.lock:
        applicant = update_applicant(
            applicant_id,
            name=body.get("name"),
            entity_size=body.get("entity_size"),
            gross_income_cents=body.get("gross_income_cents"),
            prior_filings_count=body.get("prior_filings_count"),
            version=body.get("version"),
        )
    return success(serialize_applicant(applicant, recompute_score=False))


@applicants_bp.get("/applicants")
@require_auth(allowed_roles=[ROLE_USPTO_ADMIN, ROLE_EXAMINER])
def list_applicants_route():
    limit, offset = parse_pagination()
    entity_size = request.args.get("entity_size")
    status = request.args.get("status")
    if entity_size is not None and entity_size not in ENTITY_SIZES:
        raise make_error("ERR_VALIDATION", "Unknown entity_size filter.")
    if status is not None and status not in APPLICANT_STATUSES:
        raise make_error("ERR_VALIDATION", "Unknown status filter.")
    rows = []
    for a in store.applicants.values():
        if entity_size is not None and a["entity_size"] != entity_size:
            continue
        if status is not None and a["status"] != status:
            continue
        rows.append(a)
    total = len(rows)
    page = slice_and_sort(rows, limit, offset)
    return success(
        [serialize_applicant(a, recompute_score=False) for a in page],
        pagination=build_pagination_meta(limit, offset, total),
    )
