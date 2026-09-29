"""Shared validation-ladder rungs that several endpoints reuse."""

import clock
import util
from constants import OPEN_REVIEW_STATUSES
from db import store
from errors import ApiError
from services import lookup


def require_term_status(term, allowed):
    """Rung 10 — ERR_TERM_LOCKED."""
    if term is None or term["status"] not in allowed:
        raise ApiError("ERR_TERM_LOCKED")


def require_roster_not_certified(program_id, term_id):
    """Rung 11 — ERR_ROSTER_CERTIFIED."""
    if lookup.certified_roster(program_id, term_id) is not None:
        raise ApiError("ERR_ROSTER_CERTIFIED")


def require_no_review_lockout(program_id):
    """Rung 12 — ERR_ACCREDITOR_REVIEW_LOCKOUT."""
    today = clock.current_date()
    for review in lookup.reviews_of_program(program_id):
        if review["status"] not in OPEN_REVIEW_STATUSES:
            continue
        start = util.parse_date(review["window_start_date"])
        end = util.parse_date(review["window_end_date"])
        if start is None or end is None:
            continue
        if start <= today <= end:
            raise ApiError("ERR_ACCREDITOR_REVIEW_LOCKOUT")


def require_not_separated(faculty):
    """Rung 14 — ERR_FACULTY_SEPARATED."""
    if faculty["appointment_status"] == "SEPARATED":
        raise ApiError("ERR_FACULTY_SEPARATED")


def require_appointable(faculty):
    """Rung 15 — ERR_FACULTY_NOT_APPOINTABLE."""
    if faculty["appointment_status"] not in ("CREDENTIALED_ELIGIBLE", "CONTRACTED"):
        raise ApiError("ERR_FACULTY_NOT_APPOINTABLE")


def require_dossier_verified(faculty):
    """Rung 16 — ERR_DOSSIER_NOT_VERIFIED."""
    if faculty["dossier_status"] != "VERIFIED":
        raise ApiError("ERR_DOSSIER_NOT_VERIFIED")


def require_program_clean(program):
    """Rung 34 — ERR_PROGRAM_ADEQUACY_INSUFFICIENT."""
    if (program["adequacy_status"] != "ADEQUATE"
            or program.get("unqualified_assignment_count", 0) != 0):
        raise ApiError("ERR_PROGRAM_ADEQUACY_INSUFFICIENT")


def invalid_state(message=None):
    raise ApiError("ERR_INVALID_STATE", message)


def section_term(section):
    return store.terms.get(section["term_id"])
