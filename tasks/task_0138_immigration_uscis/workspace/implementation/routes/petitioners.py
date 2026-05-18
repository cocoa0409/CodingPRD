"""Petitioner and Beneficiary endpoints."""
from __future__ import annotations

from datetime import timedelta, date

from flask import Blueprint, g

from config import PREFERENCE_CATEGORIES, RELATIONSHIPS
from db import store
from errors import err_forbidden, err_validation
from middleware import require_auth
from response import success
from services.case_engine import stamp_create
from services.serializers import serialize_beneficiary, serialize_petitioner
from utils import (
    is_valid_a_number,
    is_valid_country_code,
    is_valid_email,
    parse_iso_date,
)

from routes._helpers import (
    enforce_beneficiary_ownership,
    enforce_petitioner_ownership,
    get_beneficiary_or_404,
    get_json,
    get_petitioner_or_404,
    require_enum,
    require_string,
)


bp = Blueprint("petitioners", __name__)


# ── POST /petitioners ───────────────────────────────────────────────────────


@bp.post("/petitioners")
@require_auth(["Petitioner", "Officer", "Supervisor"])
def create_petitioner():
    body = get_json()

    full_name = require_string(body, "full_name", min_len=1, max_len=120)

    dob_str = require_string(body, "date_of_birth")
    dob = parse_iso_date(dob_str)
    if dob is None:
        raise err_validation("date_of_birth must be a valid YYYY-MM-DD date.")
    # Must be >= 14 years before today (logical clock).
    today = store.clock.logical_now().date()
    fourteen_years_ago = today.replace(year=today.year - 14)
    if dob > fourteen_years_ago:
        raise err_validation("Petitioner must be at least 14 years old.")

    country = require_string(body, "country_of_citizenship")
    if not is_valid_country_code(country):
        raise err_validation("country_of_citizenship must be 3 uppercase letters.")

    email = require_string(body, "email")
    if not is_valid_email(email):
        raise err_validation("email is not RFC 5322 compliant.")

    a_number = body.get("a_number")
    if a_number is not None:
        if not is_valid_a_number(a_number):
            raise err_validation("a_number must match ^A\\d{9}$ when supplied.")

    with store.lock:
        now = store.now()
        # If the caller is a Petitioner, the new petitioner's id becomes
        # their X-User-ID so subsequent ownership checks line up.
        petitioner_id = g.user_id if g.role == "Petitioner" else None
        if petitioner_id and petitioner_id in store.petitioners:
            raise err_forbidden("Petitioner already has a petitioner record under this X-User-ID.")
        entity = {
            "full_name": full_name,
            "date_of_birth": dob_str,
            "country_of_citizenship": country,
            "email": email,
            "a_number": a_number,
        }
        if petitioner_id:
            entity["id"] = petitioner_id
        stamp_create(entity, now)
        store.petitioners[entity["id"]] = entity

    return success(serialize_petitioner(entity), 201)


# ── GET /petitioners/{petitioner_id} ────────────────────────────────────────


@bp.get("/petitioners/<petitioner_id>")
@require_auth(["Petitioner", "Officer", "Supervisor"])
def get_petitioner(petitioner_id: str):
    p = get_petitioner_or_404(petitioner_id)
    enforce_petitioner_ownership(p)
    return success(serialize_petitioner(p), 200)


# ── POST /petitioners/{petitioner_id}/beneficiaries ─────────────────────────


@bp.post("/petitioners/<petitioner_id>/beneficiaries")
@require_auth(["Petitioner", "Officer", "Supervisor"])
def create_beneficiary(petitioner_id: str):
    p = get_petitioner_or_404(petitioner_id)
    # Petitioner ownership: can only create beneficiaries under own petitioner.
    enforce_petitioner_ownership(p)

    body = get_json()

    full_name = require_string(body, "full_name", min_len=1, max_len=120)

    dob_str = require_string(body, "date_of_birth")
    if parse_iso_date(dob_str) is None:
        raise err_validation("date_of_birth must be a valid YYYY-MM-DD date.")

    country = require_string(body, "country_of_chargeability")
    if not is_valid_country_code(country):
        raise err_validation("country_of_chargeability must be 3 uppercase letters.")

    preference = require_enum(body, "preference_category", PREFERENCE_CATEGORIES)
    relationship = require_enum(body, "relationship_to_petitioner", RELATIONSHIPS)

    with store.lock:
        now = store.now()
        entity = {
            "petitioner_id": petitioner_id,
            "full_name": full_name,
            "date_of_birth": dob_str,
            "country_of_chargeability": country,
            "preference_category": preference,
            "relationship_to_petitioner": relationship,
        }
        stamp_create(entity, now)
        store.beneficiaries[entity["id"]] = entity

    return success(serialize_beneficiary(entity), 201)


# ── GET /beneficiaries/{beneficiary_id} ─────────────────────────────────────


@bp.get("/beneficiaries/<beneficiary_id>")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def get_beneficiary(beneficiary_id: str):
    b = get_beneficiary_or_404(beneficiary_id)
    enforce_beneficiary_ownership(b)
    return success(serialize_beneficiary(b), 200)
