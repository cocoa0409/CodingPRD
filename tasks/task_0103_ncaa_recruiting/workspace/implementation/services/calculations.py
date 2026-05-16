"""Core calculation rules: FMV, pay-for-play, penalty score, immediate eligibility.

These are pure functions over already-fetched entities/values; storage updates
happen in cascades.py.
"""

from datetime import timedelta
from services.money import round_half_up_int


# --- nil_deal_fair_market_value ---------------------------------------------

CAT_MULT = {
    "ENDORSEMENT": 1.20,
    "APPEARANCE": 1.10,
    "SOCIAL_MEDIA_POST": 1.00,
    "AUTOGRAPH_SIGNING": 0.90,
    "CAMP_INSTRUCTION": 1.05,
}


def compute_fmv_cents(deal: dict) -> int:
    base = float(deal["deliverables_hours"]) * float(deal["market_rate_cents_per_hour"])
    mult = CAT_MULT[deal["deal_category"]]
    booster_factor = 0.80 if deal.get("sponsor_is_booster") else 1.00
    raw = base * mult * booster_factor
    return round_half_up_int(raw)


# --- nil_deal_pay_for_play --------------------------------------------------

def compute_pay_for_play(deal: dict, athlete: dict) -> bool:
    sponsor_is_booster = bool(deal.get("sponsor_is_booster"))
    stated = int(deal["stated_value_cents"])
    fmv = int(deal["fmv_calculated_cents"])
    deliverables_hours = float(deal["deliverables_hours"])
    category = deal["deal_category"]

    # Booster ratio test
    if sponsor_is_booster:
        ratio = stated / max(fmv, 1)
        if ratio >= 3.0:
            return True

    # Booster + camp instruction token deliverable
    if (
        sponsor_is_booster
        and category == "CAMP_INSTRUCTION"
        and deliverables_hours <= 1.0
        and stated >= 1_000_000
    ):
        return True

    # Uncommitted inducement
    if athlete is not None:
        if athlete.get("current_program_id") is None and stated >= 5_000_000:
            return True

    return False


# --- violation_penalty_score ------------------------------------------------

SEVERITY_POINTS = {
    "LEVEL_I": 10,
    "LEVEL_II": 5,
    "LEVEL_III": 2,
    "LEVEL_IV": 1,
}


def compute_penalty_points(violation: dict, all_violations: list) -> int:
    """Compute penalty_points for `violation` at the moment it transitions to SUSTAINED.

    Recidivism multiplier counts prior SUSTAINED violations on the same program
    in the trailing 730 days (strictly before this violation's created_at).
    """
    from core.clock import parse_iso

    sev = SEVERITY_POINTS[violation["severity"]]
    this_created = parse_iso(violation["created_at"])
    window_start = this_created - timedelta(days=730)
    pid = violation["program_id"]
    this_id = violation["id"]
    prior = 0
    for v in all_violations:
        if v["id"] == this_id:
            continue
        if v.get("program_id") != pid:
            continue
        if v.get("outcome") != "SUSTAINED":
            continue
        vc = parse_iso(v["created_at"])
        if vc >= this_created:
            continue
        if vc < window_start:
            continue
        prior += 1

    if prior == 0:
        mult = 1.0
    elif prior == 1:
        mult = 1.5
    else:
        mult = 2.0

    return round_half_up_int(sev * mult)


# --- transfer_immediate_eligibility ----------------------------------------

def compute_immediate_eligibility(entry: dict, athlete: dict, all_entries: list) -> bool:
    """Compute immediate_eligibility for a portal entry committing now."""
    from core.clock import parse_iso

    this_id = entry["id"]
    this_created = parse_iso(entry["created_at"])
    aid = entry["athlete_id"]
    prior_transfers = 0
    for e in all_entries:
        if e["id"] == this_id:
            continue
        if e.get("athlete_id") != aid:
            continue
        if e.get("status") != "COMMITTED":
            continue
        ec = parse_iso(e["created_at"])
        if ec >= this_created:
            continue
        prior_transfers += 1

    years_attended = 4 - int(athlete.get("years_of_eligibility_remaining", 4))
    if prior_transfers == 0 and years_attended >= 0:
        return True
    if prior_transfers == 1 and years_attended >= 3:
        return True
    return False


# --- transfer_window_close --------------------------------------------------

WINDOW_DAYS_AMATEUR = 45
WINDOW_DAYS_AT_RISK = 30


def transfer_window_hours(amateur_status: str):
    """Return window length in hours given the athlete's amateur_status.

    None means FORFEITED (cannot enter portal).
    """
    if amateur_status == "AMATEUR":
        return WINDOW_DAYS_AMATEUR * 24
    if amateur_status == "AT_RISK":
        return WINDOW_DAYS_AT_RISK * 24
    if amateur_status == "FORFEITED":
        return 0
    return None
