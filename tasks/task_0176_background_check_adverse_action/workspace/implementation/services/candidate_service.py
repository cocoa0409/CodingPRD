"""Candidate CRUD service."""
from __future__ import annotations

import re
from typing import Optional

from core.errors import (
    err_candidate_email_taken,
    err_validation_failed,
)
from core.store import store
from services.timestamps import stamp_create, stamp_update
from services.validations import enforce_salary_history_ban


_VALID_JURISDICTIONS = {"CA", "NY", "IL", "TX", "FL", "MA", "WA"}
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_dob(value: str) -> str:
    if not isinstance(value, str) or not _DATE_RX.match(value):
        raise err_validation_failed(
            "date_of_birth must be an ISO date YYYY-MM-DD string."
        )
    return value


def _email_taken(email: str, *, exclude_id: Optional[str] = None) -> bool:
    for c in store.candidates.values():
        if c["id"] == exclude_id:
            continue
        if c.get("archived_at") is not None:
            continue
        if c.get("email") == email:
            return True
    return False


def create_candidate(body: dict) -> dict:
    # Required fields.
    full_name = body.get("full_name")
    email = body.get("email")
    residence = body.get("residence_jurisdiction")
    dob = body.get("date_of_birth")

    if not isinstance(full_name, str) or full_name == "":
        raise err_validation_failed("full_name is required.")
    if not isinstance(email, str) or email == "":
        raise err_validation_failed("email is required.")
    if not isinstance(residence, str) or residence not in _VALID_JURISDICTIONS:
        raise err_validation_failed(
            "residence_jurisdiction must be one of CA, NY, IL, TX, FL, MA, WA."
        )
    if not isinstance(dob, str):
        raise err_validation_failed("date_of_birth is required.")
    _validate_dob(dob)

    # Salary-history ban check fires BEFORE email uniqueness (priority 8 vs 409 collision).
    # We need a synthetic "candidate context" with the requested jurisdiction.
    enforce_salary_history_ban(
        body=body,
        candidate=None,
        jurisdiction_code=residence,
    )

    if _email_taken(email):
        raise err_candidate_email_taken()

    # PRD §2.9: "Once `salary_history_disclosed` becomes true on a
    # candidate (because a value was recorded at any point)". If the
    # registration body carries a `salary_history` value, the candidate
    # row's `salary_history_disclosed` is set to True.
    disclosed = "salary_history" in body and body.get("salary_history") is not None
    row = {
        "full_name": full_name,
        "email": email,
        "residence_jurisdiction": residence,
        "date_of_birth": dob,
        "eligibility_posture": "ELIGIBLE",
        "salary_history_disclosed": bool(disclosed),
        "archived_at": None,
    }
    stamp_create(row)
    store.candidates[row["id"]] = row
    return row


def update_candidate(candidate: dict, body: dict) -> dict:
    # OCC handled by caller (route) so the priority order matches the spec.
    # Salary-history ban (priority 8) before structural updates.
    enforce_salary_history_ban(
        body=body,
        candidate=candidate,
        jurisdiction_code=candidate.get("residence_jurisdiction"),
    )

    if "full_name" in body:
        v = body["full_name"]
        if not isinstance(v, str) or v == "":
            raise err_validation_failed("full_name must be a non-empty string.")
        candidate["full_name"] = v
    if "email" in body:
        v = body["email"]
        if not isinstance(v, str) or v == "":
            raise err_validation_failed("email must be a non-empty string.")
        if v != candidate.get("email") and _email_taken(v, exclude_id=candidate["id"]):
            raise err_candidate_email_taken()
        candidate["email"] = v

    stamp_update(candidate)
    return candidate
