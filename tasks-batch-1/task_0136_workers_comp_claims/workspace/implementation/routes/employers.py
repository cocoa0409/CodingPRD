"""Employer endpoints + employer-scoped list endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str
from routes._common import get_employer, assert_employer_owns_employer

bp = Blueprint("employers", __name__)


@bp.post("/employers")
def create_employer():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    state_code = require_str(body, "state_code")

    emp = {
        "legal_name": legal_name,
        "state_code": state_code,
        "open_claim_count": 0,
        "current_emr": 1.00,
    }
    db.stamp_common(emp)
    db.employers[emp["id"]] = emp
    return ok_object(emp, 201)


@bp.get("/employers/<rid>")
def get_employer_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer", "Employer"])()
    emp = get_employer(rid)
    assert_employer_owns_employer(emp["id"])
    return ok_object(emp, 200)


@bp.get("/employers/<rid>/policies")
def list_employer_policies(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "Employer"])()
    emp = get_employer(rid)
    assert_employer_owns_employer(emp["id"])
    limit, offset = paginate_params(request.args)
    items = [p for p in db.policies.values() if p["employer_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/employers/<rid>/workers")
def list_employer_workers(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "Employer"])()
    emp = get_employer(rid)
    assert_employer_owns_employer(emp["id"])
    limit, offset = paginate_params(request.args)
    items = [w for w in db.workers.values() if w["employer_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/employers/<rid>/experience-mods")
def list_employer_experience_mods(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "Employer"])()
    emp = get_employer(rid)
    assert_employer_owns_employer(emp["id"])
    limit, offset = paginate_params(request.args)
    items = [e for e in db.experience_mods.values() if e["employer_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
