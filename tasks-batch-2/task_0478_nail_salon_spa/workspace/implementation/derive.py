"""Read-time derived fields and domain constants (PRD §2.8, §3.2, §3.4).

These are pure view computations against the logical clock. A GET never mutates
stored state, so none of these bump version — they only project the stored raw
fields into their derived public values.
"""
from datetime import timedelta

from db import db
from clock import clock
from datetime_util import parse_iso8601

# ---- Domain constants (PRD §3) --------------------------------------------
SANITATION_VALID_HOURS = 24
NO_SHOW_STRIKE_DEPOSIT_THRESHOLD = 2
DEPOSIT_FLAT_CENTS = 2000
STRIKE_DECAY_DAYS = 30
LOYALTY_POINT_VALUE_CENTS = 10
NO_SHOW_GRACE_MINUTES = 15
CANCEL_FREE_WINDOW_MINUTES = 120
STATION_TURNOVER_MINUTES = 10


# ---- Station sanitation freshness (PRD §2.8, §3.2) ------------------------

def _station_logs(station_id):
    return [lg for lg in db.sanitation_logs.values() if lg["station_id"] == station_id]


def station_sanitation(station):
    """Return (sanitation_status, last_pass_sanitation_at, in_service_appointment_id).

    sanitation_status (PRD §3.2): take the station's logs ordered by created_at
    DESC and consider the single most recent log. No log or latest FAIL => DIRTY.
    Latest PASS with age < 24h => CLEAN. Latest PASS with age >= 24h => DIRTY
    (strict boundary: exactly 24h old is stale).
    last_pass_sanitation_at: created_at of the most recent PASS log regardless of
    staleness, else null.
    in_service_appointment_id: the appointment occupying this station, else null.
    """
    logs = _station_logs(station["id"])
    # ordered newest-first; tie-break by _seq (append-only, deterministic)
    logs_sorted = sorted(logs, key=lambda lg: (lg["created_at"], lg["_seq"]), reverse=True)

    sanitation_status = "DIRTY"
    if logs_sorted:
        latest = logs_sorted[0]
        if latest["cycle_result"] == "PASS":
            age = clock.now() - parse_iso8601(latest["created_at"])
            if age < timedelta(hours=SANITATION_VALID_HOURS):
                sanitation_status = "CLEAN"
            else:
                sanitation_status = "DIRTY"
        else:
            sanitation_status = "DIRTY"

    # most recent PASS regardless of staleness
    last_pass_at = None
    for lg in logs_sorted:
        if lg["cycle_result"] == "PASS":
            last_pass_at = lg["created_at"]
            break

    # station occupancy: appointment currently IN_SERVICE on this station
    in_service_id = None
    for ap in db.appointments.values():
        if ap["station_id"] == station["id"] and ap["booking_status"] == "IN_SERVICE":
            in_service_id = ap["id"]
            break

    return sanitation_status, last_pass_at, in_service_id


def station_sanitation_status(station):
    return station_sanitation(station)[0]


def station_in_service_appointment_id(station_id):
    for ap in db.appointments.values():
        if ap["station_id"] == station_id and ap["booking_status"] == "IN_SERVICE":
            return ap["id"]
    return None


# ---- Client strike decay (PRD §3.4, §1.3 strike_decay) --------------------

def client_effective_strikes(client):
    """Return (effective_active_no_show_strikes, deposit_required).

    Decays the stored raw strike count one full step per STRIKE_DECAY_DAYS since
    last_no_show_at (step decay; floor of elapsed days then floor / window).
    deposit_required is true exactly when effective strikes >= threshold (2).
    """
    raw = client["_raw_strikes"]
    last = client["last_no_show_at"]
    if last is None:
        effective = raw
    else:
        elapsed = clock.now() - parse_iso8601(last)
        elapsed_days = int(elapsed.total_seconds() // 86400)
        decayed = elapsed_days // STRIKE_DECAY_DAYS
        effective = max(0, raw - decayed)
    deposit_required = effective >= NO_SHOW_STRIKE_DEPOSIT_THRESHOLD
    return effective, deposit_required
