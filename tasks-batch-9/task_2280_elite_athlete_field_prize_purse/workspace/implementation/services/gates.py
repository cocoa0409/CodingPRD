"""Edition posture gate (priority 6) and the anti-doping / qualifying gates."""
from clock import clock, date_at_midnight_utc, parse_date, parse_dt, subtract_months
from constants import (
    MISSED_LOOKBACK_DAYS,
    MISSED_TEST_LIMIT,
)
from errors import err
from services import lookup


def gate_edition(edition, allowed=None):
    """Priority 6.  `allowed=None` means every posture except PURSE_SETTLED,
    which rejects every mutation in the edition's subtree (PRD 2.6)."""
    status = edition["status"]
    if allowed is None:
        if status == "PURSE_SETTLED":
            raise err(
                "ERR_EDITION_STATE_INVALID",
                "The edition is PURSE_SETTLED and no longer accepts mutations",
            )
        return
    if status not in allowed:
        raise err(
            "ERR_EDITION_STATE_INVALID",
            "The edition posture %s does not permit this operation" % status,
        )


def missed_recent_count(athlete, edition):
    """Missed tests of the athlete across every edition whose window_end_at
    falls on or after race_date - 365 days (PRD 3.5)."""
    race_date = parse_date(edition["race_date"], "race_date")
    cutoff = date_at_midnight_utc(race_date) - _days(MISSED_LOOKBACK_DAYS)
    count = 0
    for test in lookup.rows("doping_tests", athlete_id=athlete["id"], status="MISSED"):
        if parse_dt(test["window_end_at"]) >= cutoff:
            count += 1
    return count


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)


def is_doping_compliant(athlete, edition):
    if not athlete["whereabouts_filed"]:
        return False
    if missed_recent_count(athlete, edition) >= MISSED_TEST_LIMIT:
        return False
    for test in lookup.rows(
        "doping_tests", athlete_id=athlete["id"], race_edition_id=edition["id"]
    ):
        if test["status"] == "ADVERSE":
            return False
    return True


def require_doping_compliant(athlete, edition):
    if not is_doping_compliant(athlete, edition):
        raise err(
            "ERR_ATHLETE_NOT_DOPING_COMPLIANT",
            "The athlete is not compliant with the testing programme",
        )


def has_cleared_in_competition_test(athlete_id, edition_id):
    for test in lookup.rows(
        "doping_tests", athlete_id=athlete_id, race_edition_id=edition_id
    ):
        if test["test_type"] == "IN_COMPETITION" and test["status"] == "CLEARED":
            return True
    return False


def require_agent_active(agent):
    if agent["status"] == "SUSPENDED":
        raise err("ERR_AGENT_SUSPENDED", "The representing agent is SUSPENDED")


def require_deadline_not_passed(invitation):
    deadline = invitation.get("response_deadline_at")
    if deadline is None:
        return
    if clock.now() > parse_dt(deadline):
        raise err("ERR_OFFER_DEADLINE_PASSED", "The response deadline has passed")


def check_qualifying_standard(edition, invitation, athlete, performance):
    """Priority 14 half of calculations.qualifying_eligibility."""
    standard = lookup.find_standard(
        edition["id"], invitation["division"], athlete["gender"]
    )
    if standard is None:
        raise err(
            "ERR_QUALIFYING_STANDARD_MISSING",
            "No division standard for this edition, division and gender",
        )
    if performance["verification_status"] != "VERIFIED":
        raise err(
            "ERR_QUALIFYING_STANDARD_NOT_MET",
            "The pinned performance is not VERIFIED",
        )
    verified = performance["verified_seconds"]
    if verified is None or verified > standard["max_qualifying_seconds"]:
        raise err(
            "ERR_QUALIFYING_STANDARD_NOT_MET",
            "The verified time does not meet the qualifying standard",
        )
    race_date = parse_date(edition["race_date"], "race_date")
    performance_date = parse_date(performance["performance_date"], "performance_date")
    window_start = subtract_months(race_date, standard["window_months"])
    if performance_date < window_start or performance_date > race_date:
        raise err(
            "ERR_QUALIFYING_STANDARD_NOT_MET",
            "The performance falls outside the qualifying window",
        )
    if standard["requires_chip_timing"] and not performance["chip_timed"]:
        raise err(
            "ERR_QUALIFYING_STANDARD_NOT_MET",
            "The qualifying performance must be chip timed",
        )
    return standard


def check_performance_coherence(invitation, performance):
    """Priority 15 half of calculations.qualifying_eligibility."""
    if performance["athlete_id"] != invitation["athlete_id"]:
        raise err(
            "ERR_PERFORMANCE_DIVISION_MISMATCH",
            "The pinned performance belongs to another athlete",
        )
    if performance["division"] != invitation["division"]:
        raise err(
            "ERR_PERFORMANCE_DIVISION_MISMATCH",
            "The pinned performance was claimed against another division",
        )
