"""Mass ledger, charge projection, leak-rate calculation (PRD 3.3, 3.4, 3.8)."""
from decimal import Decimal

import constants
import db
import util

ZERO = Decimal("0")


def system_records(system_id, include_voided=False):
    """Non-voided service records of a system, replayed in ledger order.

    PRD 3.3: ascending performed_at, with ascending created_at as the
    tie-breaker; the id is never consulted.
    """
    records = [
        record for record in db.values("service_records")
        if record["system_id"] == system_id
        and (include_voided or not record["voided"])
    ]
    records.sort(key=lambda r: (r["performed_at"], r["created_at"], r["_seq"]))
    return records


def store_records(store_id):
    system_ids = {
        system["id"] for system in db.values("systems")
        if system["store_id"] == store_id
    }
    records = [
        record for record in db.values("service_records")
        if record["system_id"] in system_ids and not record["voided"]
    ]
    records.sort(key=lambda r: (r["performed_at"], r["created_at"], r["_seq"]))
    return records


def charge_at(system, instant, extra=None):
    """initial_charge_lbs plus every non-voided movement up to `instant`."""
    total = system["initial_charge_lbs"]
    records = system_records(system["id"])
    if extra is not None:
        records = records + [extra]
    for record in records:
        if record["performed_at"] <= instant:
            total = (total
                     + record["refrigerant_added_lbs"]
                     - record["refrigerant_recovered_lbs"]
                     - record["refrigerant_lost_lbs"])
    return util.q1(total)


def projected_charge(system, extra=None):
    """The system charge implied by the ledger as of the logical clock."""
    return charge_at(system, db.now(), extra=extra)


def recompute_charge(system):
    system["current_charge_lbs"] = projected_charge(system)
    return system["current_charge_lbs"]


def leak_rate_numerator(system, window_start, window_end, exclusive_start=True):
    """Sum of refrigerant_added_lbs over the qualifying records in a window."""
    total = ZERO
    for record in system_records(system["id"]):
        if record["service_type"] not in constants.LEAK_RATE_SERVICE_TYPES:
            continue
        if record["refrigerant_added_lbs"] <= ZERO:
            continue
        performed_at = record["performed_at"]
        if exclusive_start:
            if not performed_at > window_start:
                continue
        else:
            if not performed_at >= window_start:
                continue
        if performed_at > window_end:
            continue
        total = total + record["refrigerant_added_lbs"]
    return total


def leak_rate(system, method=None, as_of=None):
    """Return (rate, added_in_window, window_start, window_end).

    PRD 3.4 ROLLING_AVERAGE: added over the trailing 365 days divided by the
    nameplate charge, times 100. ANNUALIZING: added since the baseline divided
    by the nameplate charge, annualised by 365/days_elapsed, times 100.
    """
    method = method or system["leak_rate_method"]
    as_of = as_of or db.now()
    full_charge = system["full_charge_lbs"]
    if method == "ANNUALIZING":
        window_start = system["leak_rate_baseline_at"]
        window_end = as_of
        added = leak_rate_numerator(system, window_start, window_end)
        elapsed = util.whole_days_between(window_start, as_of)
        days = elapsed if elapsed > 1 else 1
        if full_charge <= ZERO:
            rate = util.q1(ZERO)
        else:
            rate = util.q1((added / full_charge)
                           * (Decimal(constants.LEAK_RATE_WINDOW_DAYS) / Decimal(days))
                           * Decimal(100))
    else:
        window_start = util.add_days(as_of, -constants.LEAK_RATE_WINDOW_DAYS)
        window_end = as_of
        added = leak_rate_numerator(system, window_start, window_end)
        if full_charge <= ZERO:
            rate = util.q1(ZERO)
        else:
            rate = util.q1((added / full_charge) * Decimal(100))
    return rate, util.q1(added), window_start, window_end


def recompute_baseline(system):
    """PRD 3.4: the latest of installation, newest follow-up PASS, newest
    COMPLETED retrofit plan."""
    baseline = system["installed_on"]
    event_ids = {
        event["id"] for event in db.values("leak_events")
        if event["system_id"] == system["id"]
    }
    for test in db.values("verification_tests"):
        if test["leak_event_id"] not in event_ids:
            continue
        if test["result"] != "PASS":
            continue
        if test["test_sequence"] != "FOLLOWUP_VERIFICATION":
            continue
        if test["performed_at"] > baseline:
            baseline = test["performed_at"]
    for plan in db.values("retrofit_plans"):
        if plan["system_id"] != system["id"] or plan["status"] != "COMPLETED":
            continue
        if plan["completed_at"] is not None and plan["completed_at"] > baseline:
            baseline = plan["completed_at"]
    system["leak_rate_baseline_at"] = baseline
    return baseline


def recompute_leak_rate(system):
    recompute_baseline(system)
    rate, _added, _start, _end = leak_rate(system)
    system["leak_rate_pct"] = rate
    return rate


def system_events(system_id):
    events = [
        event for event in db.values("leak_events")
        if event["system_id"] == system_id
    ]
    events.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return events


def non_terminal_event(system_id):
    for event in system_events(system_id):
        if event["status"] not in constants.TERMINAL_LEAK_EVENT_STATUSES:
            return event
    return None


def recompute_exceedance(system):
    """PRD 3.4: leak events on the system, not VOIDED, detected inside the
    trailing 365 days (exclusive lower bound, inclusive upper bound)."""
    clock = db.now()
    window_start = util.add_days(clock, -constants.LEAK_RATE_WINDOW_DAYS)
    count = 0
    for event in system_events(system["id"]):
        if event["status"] == "VOIDED":
            continue
        detected_at = event["detected_at"]
        if detected_at > window_start and detected_at <= clock:
            count += 1
    system["exceedance_count_12mo"] = count
    return count


def retention_from(instant):
    return util.add_calendar_years_midnight(instant, constants.RETENTION_YEARS)
