"""Borrower service (PRD §3.1)."""

import re

import db
from errors import ERR_VALIDATION, raise_error
from services.common import init_common
from services.validation import require_int, require_string


_SSN_RE = re.compile(r"^[0-9]{4}$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")


def create(body: dict) -> dict:
    full_name = require_string(body, "full_name")
    ssn_last4 = require_string(body, "ssn_last4")
    if not _SSN_RE.match(ssn_last4):
        raise_error(ERR_VALIDATION, "ssn_last4 must be exactly 4 digits.")
    annual_income_cents = require_int(body, "annual_income_cents", min_value=0)
    credit_score = require_int(body, "credit_score", min_value=300, max_value=850)
    state_code = require_string(body, "state_code")
    if not _STATE_RE.match(state_code):
        raise_error(ERR_VALIDATION, "state_code must be exactly two uppercase letters.")

    borrower = init_common(
        {
            "full_name": full_name,
            "ssn_last4": ssn_last4,
            "annual_income_cents": int(annual_income_cents),
            "credit_score": int(credit_score),
            "state_code": state_code,
        }
    )
    db.borrowers[borrower["id"]] = borrower
    return borrower


def get(borrower_id: str):
    return db.borrowers.get(borrower_id)
