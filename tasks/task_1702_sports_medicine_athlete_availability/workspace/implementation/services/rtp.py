"""RTP readiness gate (rtp_stage_readiness calculation)."""
from datetime import timedelta

from db import clock_date, parse_iso_dt, STORE
from errors import conflict, ERR_READINESS_NOT_MET, ERR_CONCUSSION_MIN_DAYS
from services.common import latest_current_entry

BASE_MIN_DAYS_PER_STAGE = 2
SEVERE_EXTRA_DAYS = 2
CONCUSSION_EXTRA_DAYS = 1
MIN_CONCUSSION_DAYS_PER_STAGE = 3
FUNCTIONAL_SCORE_MIN = 80
REGRESSION_LOOKBACK_DAYS = 14


def evaluate_readiness(protocol, case):
    """Raises ERR_CONCUSSION_MIN_DAYS / ERR_READINESS_NOT_MET on failure.
    Returns the readiness snapshot dict on success."""
    today = clock_date()
    entered = protocol["_current_stage_entered_on"]
    days_in_stage = (today - entered).days

    # Concussion hard floor evaluated FIRST (independent of min_days sum)
    if case["is_concussion_snapshot"] and days_in_stage < MIN_CONCUSSION_DAYS_PER_STAGE:
        raise conflict(ERR_CONCUSSION_MIN_DAYS,
                       "Concussion case advanced before minimum days per stage")

    min_days = BASE_MIN_DAYS_PER_STAGE
    if case["severity_class_snapshot"] == "SEVERE":
        min_days += SEVERE_EXTRA_DAYS
    if case["is_concussion_snapshot"]:
        min_days += CONCUSSION_EXTRA_DAYS

    regression_in_window = False
    for adv in STORE["rtp_stage_advances"].values():
        if adv["rtp_protocol_id"] != protocol["id"] or adv["kind"] != "REGRESSION":
            continue
        adv_date = parse_iso_dt(adv["created_at"]).date()
        delta = (today - adv_date).days
        if 0 <= delta <= REGRESSION_LOOKBACK_DAYS:
            regression_in_window = True
            break

    latest = latest_current_entry(case["id"])

    ready = (
        days_in_stage >= min_days
        and latest is not None
        and latest["symptom_free"] is True
        and latest["functional_test_score"] >= FUNCTIONAL_SCORE_MIN
        and not regression_in_window
        and latest["_entry_date"] >= entered
    )
    if not ready:
        raise conflict(ERR_READINESS_NOT_MET, "RTP readiness gate not met")

    return {
        "days_in_stage": days_in_stage,
        "symptom_free": latest["symptom_free"],
        "functional_test_score": latest["functional_test_score"],
        "regression_in_window": regression_in_window,
    }
