"""Voter eligibility checks (PRD §3.3 + §3.6 cure-grace window)."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional, Tuple

from ..errors import (
    err_deadline_passed,
    err_no_precinct_match,
    err_not_citizen,
    err_residency_insufficient,
    err_under_age,
)
from ..store import store

ELIGIBLE_AGE = 18
MIN_RESIDENCY_DAYS = 30


def _age_years(voter: dict, election: dict) -> int:
    delta_days = (election["election_date"] - voter["date_of_birth"]).days
    return int(delta_days // 365.25)


def _residency_days(voter: dict, election: dict) -> int:
    return (election["election_date"] - voter["residency_since"]).days


def check_strict_eligibility(voter: dict, election: dict) -> None:
    """Raise the first failing eligibility error per priority order.

    PRD §2.9 puts (6) deadline-window checks BEFORE (9) eligibility
    checks; within the eligibility group PRD §3.3 lists
    citizenship -> age -> residency -> precinct.
    """
    s = store()
    now = s.now()

    if now > election["registration_deadline"]:
        raise err_deadline_passed("registration_deadline has passed")
    if not voter.get("is_citizen", False):
        raise err_not_citizen()
    if _age_years(voter, election) < ELIGIBLE_AGE:
        raise err_under_age()
    if _residency_days(voter, election) < MIN_RESIDENCY_DAYS:
        raise err_residency_insufficient()
    if voter.get("precinct_id") is None:
        raise err_no_precinct_match()


def passes_strict(voter: dict, election: dict) -> Tuple[bool, Optional[str]]:
    """Boolean variant; returns (ok, failing_error_id) without raising."""
    s = store()
    now = s.now()

    if now > election["registration_deadline"]:
        return False, "ERR_DEADLINE_PASSED"
    if not voter.get("is_citizen", False):
        return False, "ERR_NOT_CITIZEN"
    if _age_years(voter, election) < ELIGIBLE_AGE:
        return False, "ERR_UNDER_AGE"
    if _residency_days(voter, election) < MIN_RESIDENCY_DAYS:
        return False, "ERR_RESIDENCY_INSUFFICIENT"
    if voter.get("precinct_id") is None:
        return False, "ERR_NO_PRECINCT_MATCH"
    return True, None


def passes_cure_grace(voter: dict, election: dict) -> bool:
    """Cure-grace variant: waives residency_days; keeps citizenship + age."""
    if not voter.get("is_citizen", False):
        return False
    if _age_years(voter, election) < ELIGIBLE_AGE:
        return False
    if voter.get("precinct_id") is None:
        return False
    return True


def in_cure_grace_window(election: dict) -> bool:
    """True iff election is EARLY_VOTING and now within 7 days of registration_deadline."""
    if election["state"] != "EARLY_VOTING":
        return False
    s = store()
    now = s.now()
    deadline = election["registration_deadline"]
    if now < deadline:
        return False
    return (now - deadline) <= timedelta(days=7)
