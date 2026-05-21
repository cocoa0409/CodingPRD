"""Pairing aggregate operations: totals, start/end, internal-overlap check."""
from datetime import timedelta

import store
from clock import parse_iso
from errors import raise_error


CREW_REST_MIN_MINUTES = 600


def get_duty_periods_of(pairing_id):
    """Return DutyPeriod rows for the given pairing, sorted by sequence_no asc."""
    rows = [dp for dp in store.duty_periods.values() if dp["pairing_id"] == pairing_id]
    rows.sort(key=lambda r: r["sequence_no"])
    return rows


def get_flight_legs_of_duty(duty_period_id):
    rows = [fl for fl in store.flight_legs.values()
            if fl["duty_period_id"] == duty_period_id]
    rows.sort(key=lambda r: r["leg_sequence_no"])
    return rows


def get_flight_legs_of_pairing(pairing_id):
    duty_ids = {dp["id"] for dp in store.duty_periods.values()
                if dp["pairing_id"] == pairing_id}
    rows = [fl for fl in store.flight_legs.values() if fl["duty_period_id"] in duty_ids]
    return rows


def recompute_duty_block_minutes(duty_period_id):
    """Sum block_minutes over REVENUE legs in this duty period."""
    total = 0
    for fl in store.flight_legs.values():
        if fl["duty_period_id"] == duty_period_id and fl["leg_type"] == "REVENUE":
            total += fl["block_minutes"]
    dp = store.duty_periods[duty_period_id]
    dp["block_minutes"] = total


def recompute_pairing_aggregates(pairing_id):
    """Re-derive total_block_minutes, total_duty_minutes, start_at, end_at on a pairing."""
    pairing = store.pairings[pairing_id]
    dps = get_duty_periods_of(pairing_id)

    total_duty = sum(dp["duty_minutes"] for dp in dps)
    pairing["total_duty_minutes"] = total_duty

    # Recompute total_block_minutes from REVENUE legs only
    total_block = 0
    for fl in store.flight_legs.values():
        dp_id = fl["duty_period_id"]
        dp = store.duty_periods.get(dp_id)
        if dp is None or dp["pairing_id"] != pairing_id:
            continue
        if fl["leg_type"] == "REVENUE":
            total_block += fl["block_minutes"]
    pairing["total_block_minutes"] = total_block

    if dps:
        starts = [parse_iso(dp["report_at"]) for dp in dps]
        ends = [parse_iso(dp["release_at"]) for dp in dps]
        from clock import format_iso
        pairing["start_at"] = format_iso(min(starts))
        pairing["end_at"] = format_iso(max(ends))
    else:
        pairing["start_at"] = None
        pairing["end_at"] = None

    store.touch(pairing)


def check_pairing_internal_overlap(pairing_id):
    """Validate that DutyPeriods don't overlap and inter-period rest >= 600 min.

    Raises ERR_PAIRING_INTERNAL_OVERLAP.
    """
    dps = get_duty_periods_of(pairing_id)
    if len(dps) < 2:
        return
    # Sort by report_at
    parsed = []
    for dp in dps:
        r = parse_iso(dp["report_at"])
        e = parse_iso(dp["release_at"])
        parsed.append((r, e))
    parsed.sort(key=lambda x: x[0])
    for i in range(len(parsed) - 1):
        prev_end = parsed[i][1]
        next_start = parsed[i + 1][0]
        if next_start < prev_end:
            raise_error("ERR_PAIRING_INTERNAL_OVERLAP",
                        "Duty periods overlap within the pairing.")
        gap = (next_start - prev_end).total_seconds() / 60.0
        if gap < CREW_REST_MIN_MINUTES:
            raise_error("ERR_PAIRING_INTERNAL_OVERLAP",
                        "Inter-period rest is less than the minimum.")
