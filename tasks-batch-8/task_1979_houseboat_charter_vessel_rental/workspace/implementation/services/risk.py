"""Renter qualification recompute, suspension cascade, and risk scores."""

from datetime import date

import db
from services import booking_ops, pricing

SEVERITY_WEIGHT = {
    "MINOR": 10,
    "MAJOR": 25,
    "TOTAL_LOSS": 60,
}
WINDOW_MONTHS = 24


def _covering_certificate_exists(renter_id):
    """A renter is QUALIFIED while at least one of their certificates is
    VERIFIED with expires_on on or after the current date (inclusive)."""
    today = db.current_date()
    for c in db.all_of("certificates"):
        if c["renter_id"] != renter_id:
            continue
        if c["status"] == "VERIFIED" and c["expires_on"] >= today:
            return True
    return False


def suspension_cascade(renter):
    """Cancel every HELD/CONFIRMED booking of the renter starting after the
    current date, with reason RENTER_SUSPENDED and the 100% refund path."""
    today = db.current_date()
    targets = [
        b
        for b in db.all_of("bookings")
        if b["renter_id"] == renter["id"]
        and b["status"] in ("HELD", "CONFIRMED")
        and b["start_date"] > today
    ]
    for b in db.sorted_created(targets):
        booking_ops.cancel_booking(b, "RENTER_SUSPENDED", system=True)
    return len(targets)


def recompute_qualification(renter):
    """Derived from certificate states after every certificate transition.
    Returns (newly_suspended, cascade_cancelled_count)."""
    if _covering_certificate_exists(renter["id"]):
        if renter["qualification_status"] != "QUALIFIED":
            renter["qualification_status"] = "QUALIFIED"
            db.touch(renter)
        return False, 0
    if renter["qualification_status"] == "QUALIFIED":
        renter["qualification_status"] = "SUSPENDED"
        db.touch(renter)
        cancelled = suspension_cascade(renter)
        return True, cancelled
    # UNVERIFIED with no covering certificate stays UNVERIFIED; SUSPENDED
    # with no covering certificate stays SUSPENDED.
    return False, 0


def _months_ago(d, months):
    """The date exactly `months` before d (day clamped when out of range)."""
    year = d.year - (months // 12)
    month = d.month - (months % 12)
    while month <= 0:
        month += 12
        year -= 1
    try:
        return date(year, month, d.day)
    except ValueError:
        # e.g. Feb 29 -> Feb 28 in a non-leap target year
        return date(year, month, 28)


def recompute_risk(renter):
    """renter_risk_score: both variants recomputed eagerly on incident
    resolve (RESOLVED only; REJECTED incidents never count)."""
    resolved = []
    for inc in db.all_of("incidents"):
        if inc["status"] != "RESOLVED":
            continue
        if inc["severity"] not in SEVERITY_WEIGHT:
            # A resolved incident without a recorded severity (only possible
            # for DAMAGE_ASSESSED, where severity is optional) contributes
            # no weight to either variant.
            continue
        booking = db.get("bookings", inc["booking_id"])
        if booking is not None and booking["renter_id"] == renter["id"]:
            resolved.append(inc)

    lifetime = sum(SEVERITY_WEIGHT[i["severity"]] for i in resolved)

    cutoff = _months_ago(db.current_date(), WINDOW_MONTHS)
    rolling = sum(
        SEVERITY_WEIGHT[i["severity"]]
        for i in resolved
        if i["occurred_at"].date() >= cutoff
    )

    renter["risk_score_lifetime"] = lifetime
    renter["risk_score_rolling_24m"] = rolling
    renter["deposit_multiplier"] = pricing.deposit_multiplier_for(rolling)
    db.touch(renter)
