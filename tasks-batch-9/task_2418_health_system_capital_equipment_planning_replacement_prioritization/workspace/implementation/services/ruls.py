"""asset_ruls_score — remaining useful life scoring (PRD section 3.2)."""

import math
from datetime import timedelta
from decimal import Decimal

from db import db, iso_ms, ordered, touch
from numeric import clamp2, dec, r2

DAYS_PER_YEAR = Decimal(365)
SERVICE_WINDOW_DAYS = 730
CORRECTIVE_POINTS = Decimal("3.00")
DOWNTIME_POINTS_PER_HOUR = Decimal("0.50")
SERVICE_PENALTY_CAP = Decimal("40.00")
EOS_ELAPSED_PENALTY = Decimal("20.00")
EOS_IMMINENT_PENALTY = Decimal("8.00")
EOS_IMMINENT_DAYS = 365
RECALL_PENALTY = Decimal("10.00")
DERATE_THRESHOLD = Decimal("15.00")
ELIGIBILITY_THRESHOLD = Decimal("30.00")


def asset_events(asset_id):
    return [e for e in ordered(db.service_events.values())
            if e["asset_id"] == asset_id]


def whole_days_between(start, end):
    return int(math.floor((end - start).total_seconds() / 86400.0))


def recompute(asset):
    """Rewrite every derived RULS field on the asset. Does not bump version."""
    now = db.now()
    asset["ruls_as_of"] = iso_ms(now)
    asset["_ruls_as_of"] = now

    # Step 1 — age in years, rounded half up to two decimals.
    days = whole_days_between(asset["_install_date"], now)
    age_years = r2(Decimal(days) / DAYS_PER_YEAR)
    asset["age_years"] = age_years

    # Steps 2-3 — nominal score from age and expected life alone.
    life = Decimal(asset["expected_life_years"])
    life_fraction_remaining = (life - age_years) / life
    nominal = clamp2(r2(life_fraction_remaining * Decimal(100)))
    asset["nominal_ruls_score"] = nominal

    # Step 4 — the closed trailing 730-day window ending at ruls_as_of.
    window_start = now - timedelta(days=SERVICE_WINDOW_DAYS)
    events = asset_events(asset["id"])
    corrective = 0
    downtime = Decimal("0.00")
    for event in events:
        when = event["_event_date"]
        if window_start <= when <= now:
            if event["category"] == "CORRECTIVE":
                corrective += 1
            downtime += dec(event["downtime_hours"])
    asset["corrective_count_24m"] = corrective
    asset["downtime_hours_24m"] = r2(downtime)

    # Step 5 — service penalty points, capped.
    penalty = r2(CORRECTIVE_POINTS * Decimal(corrective)
                 + DOWNTIME_POINTS_PER_HOUR * downtime)
    if penalty > SERVICE_PENALTY_CAP:
        penalty = SERVICE_PENALTY_CAP
    asset["service_penalty_points"] = penalty

    # Step 6 — end-of-support penalty.
    oem = asset["_oem_support_end_date"]
    if oem <= now:
        eos_penalty = EOS_ELAPSED_PENALTY
    elif oem <= now + timedelta(days=EOS_IMMINENT_DAYS):
        eos_penalty = EOS_IMMINENT_PENALTY
    else:
        eos_penalty = Decimal("0.00")

    # Step 7 — unresolved recall from the latest RECALL event of all history.
    recalls = [e for e in events if e["category"] == "RECALL"]
    unresolved = False
    if recalls:
        recalls.sort(key=lambda e: (e["_event_date"], e["_seq"]), reverse=True)
        unresolved = not bool(recalls[0]["recall_resolved"])
    asset["unresolved_recall"] = unresolved
    recall_penalty = RECALL_PENALTY if unresolved else Decimal("0.00")

    # Step 8 — the adjusted score: penalties subtracted, then clamped.
    adjusted = clamp2(r2(nominal - penalty - eos_penalty - recall_penalty))
    asset["adjusted_ruls_score"] = adjusted
    return asset


def apply_derate_gate(asset):
    """Step 9. Returns True when the status changed."""
    if asset["status"] not in ("IN_SERVICE", "DERATED"):
        return False
    target = "DERATED" if (asset["adjusted_ruls_score"] <= DERATE_THRESHOLD
                           or asset["unresolved_recall"]) else "IN_SERVICE"
    if target != asset["status"]:
        asset["status"] = target
        return True
    return False


def replacement_eligible(asset):
    """Step 10 — the submit-time eligibility gate."""
    return (asset["adjusted_ruls_score"] <= ELIGIBILITY_THRESHOLD
            or asset["status"] == "DERATED"
            or bool(asset["unresolved_recall"]))


def post_derate_status(asset):
    """The status an asset falls back to when replacement funding is released."""
    return "DERATED" if (asset["adjusted_ruls_score"] <= DERATE_THRESHOLD
                         or asset["unresolved_recall"]) else "IN_SERVICE"
