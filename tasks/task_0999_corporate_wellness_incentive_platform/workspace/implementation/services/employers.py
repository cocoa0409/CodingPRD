"""Employer endpoints (PRD §3.1)."""
from flask import Blueprint

from db import DB
from middleware import require_roles
from response import success
from services import serializers
from services.common import (
    get_employer_or_404, list_response, parse_body, require_fields, stamp_new,
)

bp = Blueprint("employers", __name__)


@bp.post("/wellness/employers")
@require_roles("PlatformAdmin")
def create_employer():
    body = parse_body()
    vals = require_fields(body, [
        ("name", "string", True),
        ("annual_self_only_premium_cents", "int", True),
        ("tobacco_surcharge_cents", "int", True),
        ("pmpm_fee_cents", "int", True),
        ("coaching_session_fee_cents", "int", True),
        ("k_anonymity_threshold", "int", True),
        ("kiosk_capacity", "int", True),
        ("invoice_approval_limit_cents", "int", True),
    ])
    rec = stamp_new(dict(vals))
    DB.employers[rec["id"]] = rec
    return success(serializers.employer(rec), status=201)


@bp.get("/wellness/employers/<eid>")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def get_employer(eid):
    return success(serializers.employer(get_employer_or_404(eid)))


@bp.get("/wellness/employers/<eid>/employees")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_employer_employees(eid):
    get_employer_or_404(eid)
    items = [e for e in DB.employees.values() if e["employer_id"] == eid]
    return list_response(items, serializers.employee)


@bp.get("/wellness/employers/<eid>/programs")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_employer_programs(eid):
    get_employer_or_404(eid)
    items = [p for p in DB.programs.values() if p["employer_id"] == eid]
    return list_response(items, serializers.program)
