"""Professions and reciprocal agreements (PRD §3.1)."""
from decimal import Decimal

from flask import Blueprint

import db
import response
import serializers
import validators as v
from constants import ROLE_ADMIN, ALL_ROLES
from errors import invalid
from middleware import authenticate
from services import lookups

bp = Blueprint("professions", __name__)


@bp.post("/licensure/professions")
def create_profession():
    authenticate([ROLE_ADMIN])
    body = v.body()
    profession_code = v.f_string(body, "profession_code",
                                 pattern=v.PROFESSION_CODE_RE)
    title = v.f_string(body, "title")
    required_scope_elements = v.f_code_array(body, "required_scope_elements",
                                            min_items=1, max_items=12)
    critical_scope_elements = v.f_code_array(body, "critical_scope_elements",
                                             required=False, default=[],
                                             min_items=0, max_items=12)
    required_practice_hours = v.f_int(body, "required_practice_hours", minimum=1)
    requirement_hours_total = v.f_number(body, "requirement_hours_total",
                                        exclusive_minimum=0, places=1)
    exam_waiver_min_score = v.f_number(body, "exam_waiver_min_score",
                                       minimum=0, maximum=100, places=2)
    jurisprudence_exam_required = v.f_bool(body, "jurisprudence_exam_required",
                                           required=False, default=True)
    universal_recognition_min_residency_months = v.f_int(
        body, "universal_recognition_min_residency_months", minimum=0)
    standard_processing_days = v.f_int(body, "standard_processing_days", minimum=1)
    base_fee_cents = v.f_int(body, "base_fee_cents", minimum=0)
    endorsement_fee_cents = v.f_int(body, "endorsement_fee_cents", minimum=0)
    exam_fee_cents = v.f_int(body, "exam_fee_cents", minimum=0)
    jurisprudence_fee_cents = v.f_int(body, "jurisprudence_fee_cents", minimum=0)
    permit_fee_cents = v.f_int(body, "permit_fee_cents", minimum=0)
    expedite_surcharge_pct = v.f_number(body, "expedite_surcharge_pct",
                                        minimum=0, maximum=1, places=2)

    for element in critical_scope_elements:
        if element not in required_scope_elements:
            invalid("critical_scope_elements must be a subset of "
                    "required_scope_elements.")
    for existing in db.professions.values():
        if existing["profession_code"] == profession_code:
            invalid("profession_code must be unique across professions.")

    row = db.make_row({
        "profession_code": profession_code,
        "title": title,
        "required_scope_elements": required_scope_elements,
        "critical_scope_elements": critical_scope_elements,
        "required_practice_hours": required_practice_hours,
        "requirement_hours_total": requirement_hours_total,
        "exam_waiver_min_score": exam_waiver_min_score,
        "jurisprudence_exam_required": jurisprudence_exam_required,
        "universal_recognition_min_residency_months":
            universal_recognition_min_residency_months,
        "standard_processing_days": standard_processing_days,
        "base_fee_cents": base_fee_cents,
        "endorsement_fee_cents": endorsement_fee_cents,
        "exam_fee_cents": exam_fee_cents,
        "jurisprudence_fee_cents": jurisprudence_fee_cents,
        "permit_fee_cents": permit_fee_cents,
        "expedite_surcharge_pct": expedite_surcharge_pct,
    })
    db.professions[row["id"]] = row
    return response.object_response(serializers.profession(row), 201)


@bp.get("/licensure/professions/<profession_id>")
def read_profession(profession_id):
    authenticate(ALL_ROLES)
    row = lookups.profession(profession_id)
    return response.object_response(serializers.profession(row))


@bp.post("/licensure/professions/<profession_id>/reciprocal-agreements")
def create_reciprocal_agreement(profession_id):
    authenticate([ROLE_ADMIN])
    body = v.body()
    partner_state = v.f_string(body, "partner_state", pattern=v.TWO_LETTER_RE)
    fee_waiver_pct = v.f_number(body, "fee_waiver_pct", minimum=0, maximum=1,
                                places=2)
    exam_waiver_allowed = v.f_bool(body, "exam_waiver_allowed", required=False,
                                   default=False)
    jurisprudence_waiver_allowed = v.f_bool(body, "jurisprudence_waiver_allowed",
                                            required=False, default=False)
    expires_on = v.f_datetime(body, "expires_on")

    profession = lookups.profession(profession_id)

    for existing in db.reciprocal_agreements.values():
        if (existing["profession_id"] == profession["id"]
                and existing["partner_state"] == partner_state):
            invalid("Only one reciprocal agreement may exist for a profession "
                    "and partner state.")

    row = db.make_row({
        "profession_id": profession["id"],
        "partner_state": partner_state,
        "fee_waiver_pct": fee_waiver_pct,
        "exam_waiver_allowed": exam_waiver_allowed,
        "jurisprudence_waiver_allowed": jurisprudence_waiver_allowed,
        "expires_on": expires_on,
    })
    db.reciprocal_agreements[row["id"]] = row
    return response.object_response(serializers.reciprocal_agreement(row), 201)


@bp.get("/licensure/professions/<profession_id>/reciprocal-agreements")
def list_reciprocal_agreements(profession_id):
    authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    profession = lookups.profession(profession_id)
    rows = db.ordered([r for r in db.reciprocal_agreements.values()
                       if r["profession_id"] == profession["id"]])
    return response.paginate(rows, limit, offset,
                             serializers.reciprocal_agreement)
