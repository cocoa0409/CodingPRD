"""Calculation: diligent_search_sufficiency (PRD 3.4)."""

from datetime import timedelta

import clock
import store

DILIGENT_SEARCH_LOOKBACK_DAYS = 90


def valid_declination_count(placement):
    """A declination counts only when all four conditions hold:
    status RECORDED, reason_code other than NOT_LICENSED_FOR_CLASS,
    state_code equal to the placement's home_state, and declined_on at or
    after the cutoff (clock now minus 90 calendar days) - inclusive.
    """
    cutoff = clock.now() - timedelta(days=DILIGENT_SEARCH_LOOKBACK_DAYS)
    home_state = placement.get("home_state")
    count = 0
    for row in store.declinations_of(placement["id"]):
        if row.get("status") != "RECORDED":
            continue
        if row.get("reason_code") == "NOT_LICENSED_FOR_CLASS":
            continue
        if row.get("state_code") != home_state:
            continue
        declined_at = row.get("_declined_at")
        if declined_at is None or declined_at < cutoff:
            continue
        count += 1
    return count


def evaluate(placement, program):
    """Returns (valid_count, sufficient)."""
    count = valid_declination_count(placement)
    if placement.get("is_export_list_risk") and program.get("export_list_exempts_search"):
        return count, True
    minimum = int(program.get("diligent_search_min_declinations") or 0)
    return count, count >= minimum
