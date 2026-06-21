"""Scan-and-go access decision pipeline (PRD §3.3)."""
from db import db

ANTI_PASSBACK_MINUTES = 5


def decide(pass_rec, product, resort, presented_token, scan_at, scan_date):
    """Return (result, denial_reason). result in {GRANTED, DENIED}.

    Fixed evaluation order; first failing rule short-circuits.
    """
    # 1. Anti-counterfeit token (highest priority).
    if presented_token != pass_rec.get("magnetic_token"):
        return "DENIED", "TOKEN_MISMATCH"

    # 2. Pass must be ACTIVE.
    if pass_rec["status"] != "ACTIVE":
        return "DENIED", "NOT_ACTIVE"

    # 3. Resort must be OPEN.
    if resort["status"] != "OPEN":
        return "DENIED", "RESORT_SUSPENDED"

    # 4. Anti-passback: prior GRANTED scan for this pass+resort within the
    #    half-open cooldown window [last_grant, last_grant + 5min).
    for s in db.lift_scans.values():
        if (s["pass_id"] == pass_rec["id"] and s["resort_id"] == resort["id"]
                and s["result"] == "GRANTED"):
            elapsed_min = (scan_at - s["_scan_at_dt"]).total_seconds() / 60.0
            elapsed_whole = int(elapsed_min)  # whole minutes
            if 0 <= elapsed_whole < ANTI_PASSBACK_MINUTES:
                return "DENIED", "ANTI_PASSBACK"

    # 5. Interchange (IKON-home resorts only).
    if resort["home_network"] == "IKON":
        if not product.get("ikon_interchange_enabled"):
            return "DENIED", "NO_INTERCHANGE"
        agreement = _active_agreement(resort["id"])
        if agreement is None:
            return "DENIED", "NO_INTERCHANGE"
        distinct_days = _distinct_interchange_days(pass_rec["id"], resort["id"])
        if distinct_days >= agreement["max_interchange_days"]:
            return "DENIED", "NO_INTERCHANGE"
        return "GRANTED", None

    # 6. Blackout (EPIC-home resorts). FULL_EPIC ignores blackout entirely.
    if product["tier"] != "FULL_EPIC" and scan_date in (product.get("blackout_dates") or []):
        return "DENIED", "BLACKOUT"

    return "GRANTED", None


def _active_agreement(resort_id):
    for a in db.interchange_agreements.values():
        if a["resort_id"] == resort_id and a["status"] == "ACTIVE":
            return a
    return None


def _distinct_interchange_days(pass_id, resort_id):
    days = set()
    for s in db.lift_scans.values():
        if (s["pass_id"] == pass_id and s["resort_id"] == resort_id
                and s["result"] == "GRANTED"):
            days.add(s["scan_date"])
    return len(days)
