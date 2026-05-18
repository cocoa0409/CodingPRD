"""Shared route helpers: body parsing, pagination, ownership."""
from __future__ import annotations

import json

from flask import g, request

from config import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
)
from db import store
from errors import (
    err_forbidden,
    err_invalid_pagination,
    err_not_found,
    err_validation,
)


# ── Body parsing ────────────────────────────────────────────────────────────


def get_json() -> dict:
    """Return the request JSON body as a dict; raise ERR_VALIDATION if the
    payload is malformed JSON or non-object.

    A completely empty body is treated as {} (some endpoints accept no body).
    """
    raw = request.get_data(as_text=True) or ""
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except Exception:
        raise err_validation("Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    return body


def require_string(body: dict, name: str, *, min_len=None, max_len=None) -> str:
    if name not in body or body[name] is None:
        raise err_validation(f"Missing required field: {name}")
    val = body[name]
    if not isinstance(val, str):
        raise err_validation(f"Field {name} must be a string.")
    if min_len is not None and len(val) < min_len:
        raise err_validation(f"Field {name} must be at least {min_len} characters.")
    if max_len is not None and len(val) > max_len:
        raise err_validation(f"Field {name} must be at most {max_len} characters.")
    return val


def require_enum(body: dict, name: str, allowed) -> str:
    val = require_string(body, name)
    if val not in allowed:
        raise err_validation(f"Field {name} must be one of {sorted(allowed)}.")
    return val


def require_bool(body: dict, name: str) -> bool:
    if name not in body or body[name] is None:
        raise err_validation(f"Missing required field: {name}")
    val = body[name]
    if not isinstance(val, bool):
        raise err_validation(f"Field {name} must be a boolean.")
    return val


def require_int(body: dict, name: str, *, min_value=None) -> int:
    if name not in body or body[name] is None:
        raise err_validation(f"Missing required field: {name}")
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_validation(f"Field {name} must be an integer.")
    if min_value is not None and val < min_value:
        raise err_validation(f"Field {name} must be >= {min_value}.")
    return val


# ── Pagination ──────────────────────────────────────────────────────────────


def parse_pagination():
    """Return (limit, offset). Raises ERR_INVALID_PAGINATION on out-of-range."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_pagination()
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_pagination()

    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_pagination()
        if offset < 0:
            raise err_invalid_pagination()

    return limit, offset


def paginate_and_sort(items, limit: int, offset: int, *, sort_key=None):
    """Sort by created_at ASC (PRD §2.3) and slice."""
    if sort_key is None:
        sort_key = lambda x: x["created_at"]
    ordered = sorted(items, key=sort_key)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total


# ── Path resource lookups (existence; left-to-right per PRD §2.4) ────────────


def get_petitioner_or_404(petitioner_id: str) -> dict:
    p = store.petitioners.get(petitioner_id)
    if p is None:
        raise err_not_found(f"Petitioner {petitioner_id} not found.")
    return p


def get_beneficiary_or_404(beneficiary_id: str) -> dict:
    b = store.beneficiaries.get(beneficiary_id)
    if b is None:
        raise err_not_found(f"Beneficiary {beneficiary_id} not found.")
    return b


def get_case_or_404(case_id: str) -> dict:
    c = store.cases.get(case_id)
    if c is None:
        raise err_not_found(f"Case {case_id} not found.")
    return c


def get_biometrics_or_404(biometrics_id: str) -> dict:
    b = store.biometrics.get(biometrics_id)
    if b is None:
        raise err_not_found(f"Biometrics {biometrics_id} not found.")
    return b


def get_rfe_or_404(rfe_id: str) -> dict:
    r = store.rfes.get(rfe_id)
    if r is None:
        raise err_not_found(f"RFE {rfe_id} not found.")
    return r


def get_interview_or_404(interview_id: str) -> dict:
    i = store.interviews.get(interview_id)
    if i is None:
        raise err_not_found(f"Interview {interview_id} not found.")
    return i


# ── Ownership enforcement (PRD §2.1) ────────────────────────────────────────


def enforce_case_ownership(case: dict):
    """Petitioner: can only act on cases whose petitioner_id == X-User-ID.
    Beneficiary: can only act on cases whose beneficiary_id == X-User-ID.
    Officer / Supervisor: unrestricted.
    """
    role = getattr(g, "role", "")
    uid = getattr(g, "user_id", "")
    if role == "Petitioner":
        if case.get("petitioner_id") != uid:
            raise err_forbidden("Petitioner may only act on own cases.")
    elif role == "Beneficiary":
        if case.get("beneficiary_id") != uid:
            raise err_forbidden("Beneficiary may only act on own cases.")


def enforce_petitioner_ownership(petitioner: dict):
    """Petitioner can only read/act on their own petitioner record."""
    role = getattr(g, "role", "")
    uid = getattr(g, "user_id", "")
    if role == "Petitioner":
        if petitioner["id"] != uid:
            raise err_forbidden("Petitioner may only access own petitioner record.")


def enforce_beneficiary_ownership(beneficiary: dict):
    """Beneficiary may only fetch their own record."""
    role = getattr(g, "role", "")
    uid = getattr(g, "user_id", "")
    if role == "Beneficiary":
        if beneficiary["id"] != uid:
            raise err_forbidden("Beneficiary may only access own beneficiary record.")
    if role == "Petitioner":
        if beneficiary["petitioner_id"] != uid:
            raise err_forbidden("Petitioner may only access own beneficiaries.")
