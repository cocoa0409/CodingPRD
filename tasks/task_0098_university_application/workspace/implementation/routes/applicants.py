"""Applicant routes."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import clock
from core.errors import raise_error
from core.response import success_object
from core.store import store
from services.engine import check_version, get_applicant
from services.serializers import applicant_out
from services.time_utils import age_years_at, is_valid_iso_date

bp = Blueprint("applicants", __name__)


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _validate_gpa(value) -> Decimal:
    try:
        gpa = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise_error("ERR_VALIDATION", "high_school_gpa must be numeric.")
    if gpa < Decimal("0") or gpa > Decimal("4.00"):
        raise_error("ERR_VALIDATION", "high_school_gpa must be in [0.00, 4.00].")
    # Normalize to two decimal places.
    return gpa.quantize(Decimal("0.01"))


def _validate_int(value, field: str, *, minimum: int | None = None, allow_none: bool = False) -> int | None:
    if value is None:
        if allow_none:
            return None
        raise_error("ERR_VALIDATION", f"{field} is required.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error("ERR_VALIDATION", f"{field} must be an integer.")
    if minimum is not None and value < minimum:
        raise_error("ERR_VALIDATION", f"{field} must be >= {minimum}.")
    return value


@bp.post("/applicants")
@require_roles("Applicant", "PlatformAdmin")
def create_applicant():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")

    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not (1 <= len(full_name) <= 200):
        raise_error("ERR_VALIDATION", "full_name must be a string of 1..200 chars.")
    email = body.get("email")
    if not isinstance(email, str) or not EMAIL_RE.match(email):
        raise_error("ERR_VALIDATION", "email must be a valid RFC 5322-ish address.")
    # Uniqueness check
    for ap in store.applicants.values():
        if ap["email"].lower() == email.lower():
            raise_error("ERR_VALIDATION", "email must be unique across applicants.")

    dob = body.get("date_of_birth")
    if not isinstance(dob, str) or not is_valid_iso_date(dob):
        raise_error("ERR_VALIDATION", "date_of_birth must be ISO date YYYY-MM-DD.")
    # Must be >= 14 years before now()
    if age_years_at(clock.now(), dob) < 14:
        raise_error("ERR_VALIDATION", "date_of_birth must be at least 14 years before now.")

    gpa = _validate_gpa(body.get("high_school_gpa"))
    income = _validate_int(body.get("household_income_cents"), "household_income_cents", minimum=0)
    fafsa = _validate_int(body.get("fafsa_efc_cents"), "fafsa_efc_cents", minimum=0, allow_none=True)
    css = _validate_int(body.get("css_profile_efc_cents"), "css_profile_efc_cents", minimum=0, allow_none=True)

    rec = store.stamp_create()
    rec.update(
        {
            "full_name": full_name,
            "email": email,
            "date_of_birth": dob,
            "high_school_gpa": gpa,
            "household_income_cents": income,
            "fafsa_efc_cents": fafsa,
            "css_profile_efc_cents": css,
            "ed_commitment_application_id": None,
        }
    )
    store.applicants[rec["id"]] = rec
    return success_object(applicant_out(rec), 201)


@bp.get("/applicants/<applicant_id>")
@require_roles("Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin")
def read_applicant(applicant_id: str):
    rec = get_applicant(applicant_id)
    return success_object(applicant_out(rec), 200)


@bp.patch("/applicants/<applicant_id>")
@require_roles("Applicant", "PlatformAdmin")
def patch_applicant(applicant_id: str):
    rec = get_applicant(applicant_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    check_version(rec, body.get("version"))

    if "high_school_gpa" in body and body["high_school_gpa"] is not None:
        rec["high_school_gpa"] = _validate_gpa(body["high_school_gpa"])
    if "household_income_cents" in body and body["household_income_cents"] is not None:
        rec["household_income_cents"] = _validate_int(body["household_income_cents"], "household_income_cents", minimum=0)
    if "fafsa_efc_cents" in body:
        if body["fafsa_efc_cents"] is None:
            rec["fafsa_efc_cents"] = None
        else:
            rec["fafsa_efc_cents"] = _validate_int(body["fafsa_efc_cents"], "fafsa_efc_cents", minimum=0)
    if "css_profile_efc_cents" in body:
        if body["css_profile_efc_cents"] is None:
            rec["css_profile_efc_cents"] = None
        else:
            rec["css_profile_efc_cents"] = _validate_int(body["css_profile_efc_cents"], "css_profile_efc_cents", minimum=0)

    store.bump(rec)
    return success_object(applicant_out(rec), 200)
