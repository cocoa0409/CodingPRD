"""FAA duty-rest check: 4 inequalities (crew rest + 3 caps).

faa_duty_rest_check raises:
  - ERR_FAA_CREW_REST_VIOLATION if crew rest interval insufficient
  - ERR_FAA_DUTY_VIOLATION for the other three caps
The first failure in the prescribed order is reported.
"""
from clock import parse_iso
from errors import raise_error
import store
from services import pairing_service


CREW_REST_MIN_MINUTES = 600          # 10 hours
MAX_DUTY_MINUTES_7D = 3600           # 60 hours
MAX_BLOCK_MINUTES_30D = 6000         # 100 hours
MAX_DUTY_MINUTES_SINGLE = 840        # 14 hours


def _earliest_report_at(pairing_id):
    dps = pairing_service.get_duty_periods_of(pairing_id)
    if not dps:
        return None
    return min(parse_iso(dp["report_at"]) for dp in dps)


def faa_duty_rest_check(crew_member, pairing, raise_on_fail=True):
    """Returns None if passes; raises ERR_FAA_* on first failure.

    If raise_on_fail=False, returns the error_id (or None) without raising.
    """
    # 1) Crew rest: candidate.report_at - last_duty_end_at >= CREW_REST_MIN_MINUTES
    last_end = crew_member.get("last_duty_end_at")
    earliest = _earliest_report_at(pairing["id"])
    if last_end is not None and earliest is not None:
        from clock import parse_iso as _p
        prev_end = _p(last_end)
        gap_min = (earliest - prev_end).total_seconds() / 60.0
        if gap_min < CREW_REST_MIN_MINUTES:
            if raise_on_fail:
                raise_error("ERR_FAA_CREW_REST_VIOLATION",
                            "Crew rest interval less than minimum.")
            return "ERR_FAA_CREW_REST_VIOLATION"

    # 2) 7-day duty cap
    if (crew_member.get("cumulative_duty_minutes_7d", 0)
            + pairing.get("total_duty_minutes", 0)) > MAX_DUTY_MINUTES_7D:
        if raise_on_fail:
            raise_error("ERR_FAA_DUTY_VIOLATION",
                        "7-day duty cap would be exceeded.")
        return "ERR_FAA_DUTY_VIOLATION"

    # 3) 30-day block cap
    if (crew_member.get("cumulative_block_minutes_30d", 0)
            + pairing.get("total_block_minutes", 0)) > MAX_BLOCK_MINUTES_30D:
        if raise_on_fail:
            raise_error("ERR_FAA_DUTY_VIOLATION",
                        "30-day block cap would be exceeded.")
        return "ERR_FAA_DUTY_VIOLATION"

    # 4) Single-period duty cap
    dps = pairing_service.get_duty_periods_of(pairing["id"])
    for dp in dps:
        if dp["duty_minutes"] > MAX_DUTY_MINUTES_SINGLE:
            if raise_on_fail:
                raise_error("ERR_FAA_DUTY_VIOLATION",
                            "Single duty period exceeds 14h cap.")
            return "ERR_FAA_DUTY_VIOLATION"

    return None
