"""Candidate service."""

import db
from errors import err_candidate_not_found, err_invalid_request


def get_candidate_or_404(candidate_id: str) -> dict:
    c = db.candidates.get(candidate_id)
    if c is None:
        raise err_candidate_not_found()
    return c


def create_candidate(body: dict) -> dict:
    legal_name = body.get("legal_name")
    email = body.get("email")
    date_of_birth = body.get("date_of_birth")
    home_state_code = body.get("home_state_code")
    has_iep_or_504 = body.get("has_iep_or_504", False)

    for v, label in (
        (legal_name, "legal_name"),
        (email, "email"),
        (date_of_birth, "date_of_birth"),
        (home_state_code, "home_state_code"),
    ):
        if not isinstance(v, str) or not v:
            raise err_invalid_request(f"{label} is required")
    if len(home_state_code) != 2:
        raise err_invalid_request("home_state_code must be a two-letter US state code")
    if not isinstance(has_iep_or_504, bool):
        raise err_invalid_request("has_iep_or_504 must be a boolean")

    # Uniqueness on email
    for existing in db.candidates.all():
        if existing["email"] == email:
            raise err_invalid_request("email already registered")

    c = db.common_create()
    c.update(
        {
            "legal_name": legal_name,
            "email": email,
            "date_of_birth": date_of_birth,
            "home_state_code": home_state_code,
            "has_iep_or_504": has_iep_or_504,
        }
    )
    db.candidates.insert(c)
    return c
