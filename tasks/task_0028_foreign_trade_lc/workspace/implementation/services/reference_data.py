"""Banks, applicants, beneficiaries CRUD."""

from flask import g
import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN_FOR_ROLE,
)

BANK_ROLES = {"ISSUING", "ADVISING", "CONFIRMING", "NEGOTIATING"}


def _require_str(payload, key):
    v = payload.get(key)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"{key} required")
    return v.strip()


def create_bank(payload):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    bank_role = payload.get("bank_role")
    if bank_role not in BANK_ROLES:
        raise_error(ERR_INVALID_REQUEST, "bank_role must be ISSUING|ADVISING|CONFIRMING|NEGOTIATING")
    swift_bic = _require_str(payload, "swift_bic")
    if len(swift_bic) not in (8, 11):
        raise_error(ERR_INVALID_REQUEST, "swift_bic must be 8 or 11 chars")
    name = _require_str(payload, "name")
    country_code = _require_str(payload, "country_code")
    if len(country_code) != 2:
        raise_error(ERR_INVALID_REQUEST, "country_code must be ISO 3166-1 alpha-2")
    # Global BIC uniqueness across all bank rows
    existing = db.find_one("banks", swift_bic=swift_bic)
    if existing is not None:
        raise_error(ERR_INVALID_REQUEST, "swift_bic already registered")
    return db.insert("banks", {
        "bank_role": bank_role,
        "swift_bic": swift_bic,
        "name": name,
        "country_code": country_code,
        "status": "ACTIVE",
    })


def get_bank(bank_id):
    bank = db.get_by_id("banks", bank_id)
    if bank is None:
        raise_error(ERR_NOT_FOUND, "bank not found")
    return bank


def create_applicant(payload):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    name = _require_str(payload, "name")
    country_code = _require_str(payload, "country_code")
    if len(country_code) != 2:
        raise_error(ERR_INVALID_REQUEST, "country_code must be ISO 3166-1 alpha-2")
    return db.insert("applicants", {
        "name": name,
        "country_code": country_code,
        "status": "ACTIVE",
    })


def create_beneficiary(payload):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    name = _require_str(payload, "name")
    country_code = _require_str(payload, "country_code")
    if len(country_code) != 2:
        raise_error(ERR_INVALID_REQUEST, "country_code must be ISO 3166-1 alpha-2")
    return db.insert("beneficiaries", {
        "name": name,
        "country_code": country_code,
        "status": "ACTIVE",
    })
