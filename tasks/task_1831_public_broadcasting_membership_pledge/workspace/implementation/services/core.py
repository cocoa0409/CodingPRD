"""Core business logic: calculations, cascades, clock-driven transitions."""

from datetime import datetime, timedelta

import db
from errors import ApiError, ERR_INVALID_STATE


# ---------------------------------------------------------------------------
# Serializers (public view of entities — all fields are stored directly)
# ---------------------------------------------------------------------------

def serialize(entity):
    return dict(entity)


# ---------------------------------------------------------------------------
# Membership level ranking (membership_level_for_amount)
# ---------------------------------------------------------------------------

def level_rank(level):
    """Rank by min_annual_cents, tie-break code ASC. Returns a sortable tuple."""
    return (level["min_annual_cents"], level["code"])


def get_level_by_code(code):
    lid = db.membership_levels_by_code.get(code)
    if lid is None:
        return None
    return db.membership_levels[lid]


# ---------------------------------------------------------------------------
# Pledge net collected (calculation pledge_net_collected)
# ---------------------------------------------------------------------------

def active_reservation_for_pledge(pledge_id):
    """Active reservation = status HELD or COMMITTED for the pledge."""
    for r in db.reservations.values():
        if r["pledge_id"] == pledge_id and r["status"] in ("HELD", "COMMITTED"):
            return r
    return None


def compute_fmv_deduction(pledge):
    """FMV deduction per pledge_net_collected."""
    if pledge.get("premium_id") is None:
        return 0
    if pledge["fulfillment_status"] not in ("RESERVED", "SHIPPED"):
        return 0
    if pledge.get("premium_waived"):
        return 0
    premium = db.premiums.get(pledge["premium_id"])
    if premium is None:
        return 0
    reservation = active_reservation_for_pledge(pledge["id"])
    qty = reservation["quantity"] if reservation is not None else 0
    return premium["fair_market_value_cents"] * qty


def compute_net_collected(pledge):
    deduction = compute_fmv_deduction(pledge)
    return max(0, pledge["collected_cents"] - deduction)


# ---------------------------------------------------------------------------
# Cascading resync: pledge net_collected -> drive.collected_cents + donor.lifetime_given_cents
# ---------------------------------------------------------------------------

def resync_pledge_net(pledge):
    """Recompute pledge.net_collected_cents; propagate delta to drive + donor.

    Drive collected counts pledges with payment_status PAID/PARTIAL only.
    Donor lifetime_given counts pledges with payment_status PAID/PARTIAL only.
    """
    old_net = pledge["net_collected_cents"]
    new_net = compute_net_collected(pledge)
    if new_net == old_net:
        return
    delta = new_net - old_net
    pledge["net_collected_cents"] = new_net
    db.touch(pledge)
    if pledge["payment_status"] in ("PAID", "PARTIAL"):
        drive = db.drives.get(pledge["drive_id"])
        if drive is not None:
            drive["collected_cents"] += delta
            db.touch(drive)
        donor = db.donors.get(pledge["donor_id"])
        if donor is not None:
            donor["lifetime_given_cents"] += delta
            db.touch(donor)


# ---------------------------------------------------------------------------
# Drive totals rollup (drive_totals_rollup) — incremental application
# ---------------------------------------------------------------------------

def drive_pledged_add(drive, amount):
    drive["pledged_cents"] += amount
    db.touch(drive)


def drive_pledged_sub(drive, amount):
    drive["pledged_cents"] -= amount
    db.touch(drive)


def drive_collected_add(drive, amount):
    drive["collected_cents"] += amount
    db.touch(drive)


def drive_collected_sub(drive, amount):
    drive["collected_cents"] -= amount
    db.touch(drive)


def donor_lifetime_add(donor, amount):
    donor["lifetime_given_cents"] += amount
    db.touch(donor)


def donor_lifetime_sub(donor, amount):
    donor["lifetime_given_cents"] -= amount
    db.touch(donor)


# ---------------------------------------------------------------------------
# Matching challenge progress (matching_challenge_progress, >= comparator, latched)
# ---------------------------------------------------------------------------

def challenge_progress_add(challenge, amount):
    challenge["progress_cents"] += amount
    db.touch(challenge)
    if challenge["status"] == "OPEN" and challenge["progress_cents"] >= challenge["goal_cents"]:
        challenge["status"] = "MET"
        db.touch(challenge)


def challenge_progress_sub(challenge, amount):
    # Latched: MET/EXPIRED never revert; progress still decrements.
    challenge["progress_cents"] -= amount
    db.touch(challenge)


# ---------------------------------------------------------------------------
# Membership period extension helpers
# ---------------------------------------------------------------------------

def add_months(dt, months):
    """Add whole calendar months to a datetime (clamp day to month length)."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    prev = nxt - timedelta(days=1)
    return prev.day


def extend_membership_on_payment(membership, pledge_kind, donor):
    """Membership period extension cascade after a successful payment.

    - Extends current_period_end by 12 months (ONE_TIME) or 1 month (SUSTAINER)
      from max(current_period_end, now).
    - LAPSED -> REINSTATED_PENDING -> ACTIVE with donor.lapse_count reset to 0.
    - REINSTATED_PENDING -> ACTIVE: current_period_start = now, end = now + 12 months.
    """
    now = db.now()
    status = membership["status"]
    if status == "REINSTATED_PENDING":
        membership["status"] = "ACTIVE"
        membership["current_period_start"] = db.iso(now)
        membership["current_period_end"] = db.iso(add_months(now, 12))
        db.touch(membership)
        if donor["lapse_count"] != 0:
            donor["lapse_count"] = 0
            db.touch(donor)
        return
    if status == "LAPSED":
        # Through REINSTATED_PENDING to ACTIVE
        membership["status"] = "ACTIVE"
        membership["current_period_start"] = db.iso(now)
        membership["current_period_end"] = db.iso(add_months(now, 12))
        db.touch(membership)
        if donor["lapse_count"] != 0:
            donor["lapse_count"] = 0
            db.touch(donor)
        return
    # ACTIVE or GRACE: extend period
    base = db.parse_dt(membership["current_period_end"])
    if base is None or now > base:
        base = now
    months = 12 if pledge_kind == "ONE_TIME" else 1
    membership["current_period_end"] = db.iso(add_months(base, months))
    if status == "GRACE":
        # Payment during grace returns membership to ACTIVE (paid up).
        membership["status"] = "ACTIVE"
        membership["current_period_start"] = db.iso(now)
    db.touch(membership)


# ---------------------------------------------------------------------------
# Clock-driven membership transitions (ACTIVE -> GRACE -> LAPSED)
# ---------------------------------------------------------------------------

def apply_clock_transitions(new_time):
    """Evaluate all memberships against the new clock time."""
    for m in db.memberships.values():
        end = db.parse_dt(m["current_period_end"])
        if end is None:
            continue
        grace_boundary = end + timedelta(days=30)
        if m["status"] == "ACTIVE":
            if new_time >= grace_boundary:
                m["status"] = "LAPSED"
                db.touch(m)
                donor = db.donors.get(m["donor_id"])
                if donor is not None:
                    donor["lapse_count"] += 1
                    db.touch(donor)
            elif new_time >= end:
                m["status"] = "GRACE"
                db.touch(m)
        elif m["status"] == "GRACE":
            if new_time >= grace_boundary:
                m["status"] = "LAPSED"
                db.touch(m)
                donor = db.donors.get(m["donor_id"])
                if donor is not None:
                    donor["lapse_count"] += 1
                    db.touch(donor)
