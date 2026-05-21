"""Pay credit calculations — scheduled (forward) and actual (close-time) variants."""
import math

import store
from clock import parse_iso
from services import pairing_service


DEADHEAD_PAY_RATIO_NUM = 1
DEADHEAD_PAY_RATIO_DEN = 2
MIN_PAY_CREDIT_FLOOR_MINUTES = 240


def compute_scheduled(pairing_id):
    """Scheduled variant: every leg in the pairing as if flown; no minimum floor."""
    revenue = 0
    deadhead = 0
    for fl in pairing_service.get_flight_legs_of_pairing(pairing_id):
        if fl["leg_type"] == "REVENUE":
            revenue += int(fl["block_minutes"])
        elif fl["leg_type"] == "DEADHEAD":
            deadhead += int(fl["block_minutes"])
    # aggregate-then-floor: floor(deadhead * 1/2) = deadhead // 2
    dh_credit = (deadhead * DEADHEAD_PAY_RATIO_NUM) // DEADHEAD_PAY_RATIO_DEN
    raw = revenue + dh_credit
    return raw  # No floor on scheduled estimate


def compute_actual(pairing_id, pairing_end_at):
    """Actual variant: filter legs by chronological + assignment-was-active criteria.

    For simplicity, this implementation includes all legs of the pairing whose duty
    period's release_at <= pairing.end_at; legs that did not occur (because of an
    intra-pairing sick call dropping the assignment) are inherently excluded if the
    duty_period itself was beyond the assignment's IN_PROGRESS scope. In the absence
    of explicit per-leg cancellation, this reduces to all legs of the pairing.

    Then applies the MIN_PAY_CREDIT_FLOOR_MINUTES floor.
    """
    end_dt = parse_iso(pairing_end_at) if pairing_end_at else None

    revenue = 0
    deadhead = 0
    for fl in pairing_service.get_flight_legs_of_pairing(pairing_id):
        dp = store.duty_periods.get(fl["duty_period_id"])
        if dp is None:
            continue
        rel = parse_iso(dp["release_at"])
        if end_dt is not None and rel > end_dt:
            continue
        if fl["leg_type"] == "REVENUE":
            revenue += int(fl["block_minutes"])
        elif fl["leg_type"] == "DEADHEAD":
            deadhead += int(fl["block_minutes"])
    dh_credit = (deadhead * DEADHEAD_PAY_RATIO_NUM) // DEADHEAD_PAY_RATIO_DEN
    raw = revenue + dh_credit
    return max(raw, MIN_PAY_CREDIT_FLOOR_MINUTES)


def compute_actual_block_minutes(pairing_id, pairing_end_at):
    """Sum of REVENUE block minutes that count toward actual_block_minutes."""
    end_dt = parse_iso(pairing_end_at) if pairing_end_at else None
    revenue = 0
    for fl in pairing_service.get_flight_legs_of_pairing(pairing_id):
        dp = store.duty_periods.get(fl["duty_period_id"])
        if dp is None:
            continue
        rel = parse_iso(dp["release_at"])
        if end_dt is not None and rel > end_dt:
            continue
        if fl["leg_type"] == "REVENUE":
            revenue += int(fl["block_minutes"])
    return revenue
