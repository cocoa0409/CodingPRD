"""Pure calculations (PRD 2.7 rounding discipline, SCAFFOLD calculations)."""
from decimal import Decimal, ROUND_HALF_UP

from db import end_of_day

LEVELS = ["STAFF_WRITER", "STORY_EDITOR", "EXEC_STORY_EDITOR", "CO_PRODUCER", "PRODUCER"]
LEVELS_ABOVE_STAFF = ["STORY_EDITOR", "EXEC_STORY_EDITOR", "CO_PRODUCER", "PRODUCER"]
LENGTH_FORMATS = ["HALF_HOUR", "ONE_HOUR"]
ASSIGNMENT_TYPES = ["STORY", "TELEPLAY", "STORY_AND_TELEPLAY", "REWRITE", "PRODUCTION_POLISH"]
ROOM_FORMATS = ["IN_PERSON", "REMOTE", "MINI_ROOM"]
FACILITY_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
TIER_BOUND_KEYS = ["TIER_1_MAX", "TIER_2_MAX"]
CLEARANCE_ITEM_TYPES = ["NAME", "TRADEMARK", "DEPICTION"]
PRODUCTION_UNITS = ["UNIT_A", "UNIT_B"]
COMMITMENT_TYPES = ["EXCLUSIVE", "NON_EXCLUSIVE"]
CLAIM_BASES = ["WRITTEN_BY", "STORY_BY", "TELEPLAY_BY"]
GUARANTEE_MODES = ["FORWARD_COMMIT", "CHRONOLOGICAL_ON_ACCEPTANCE"]

MILESTONE_CHAINS = {
    "STORY": ["OUTLINE"],
    "TELEPLAY": ["OUTLINE", "FIRST_DRAFT", "SECOND_DRAFT"],
    "STORY_AND_TELEPLAY": ["OUTLINE", "FIRST_DRAFT", "SECOND_DRAFT"],
    "REWRITE": ["FIRST_DRAFT"],
    "PRODUCTION_POLISH": ["PRODUCTION_POLISH"],
}

LEAD_DAY_FIELD = {
    "OUTLINE": "outline_lead_days",
    "FIRST_DRAFT": "first_draft_lead_days",
    "SECOND_DRAFT": "second_draft_lead_days",
    "PRODUCTION_POLISH": "polish_lead_days",
}

DUE_DATE_FIELD = {
    "OUTLINE": "outline_due_date",
    "FIRST_DRAFT": "first_draft_due_date",
    "SECOND_DRAFT": "second_draft_due_date",
    "PRODUCTION_POLISH": "polish_due_date",
}

DECISION_MULTIPLIER = {"CLEARED": 0, "CONDITIONAL": 1, "BLOCKED": 4}


def D(value):
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole unit (cents)."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_places(value, places):
    quant = Decimal("1").scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- writer level
def determine_level(agreement, credits):
    thresholds = agreement["level_credit_thresholds"]
    for level in reversed(LEVELS_ABOVE_STAFF):
        if credits >= thresholds[level]:
            return level
    return "STAFF_WRITER"


# ------------------------------------------------------- seat weekly figures
def seat_weekly_compensation(seat, room, writer, agreement):
    level_min = D(agreement["min_weekly_cents_by_level"][seat["level_at_hire"]])
    fmt_mult = D(agreement["mini_room_floor_multiplier"]) if room["format"] == "MINI_ROOM" else D(1)
    if room["duration_weeks_committed"] < agreement["short_commitment_weeks_threshold"]:
        uplift = D(agreement["short_commitment_uplift_pct"])
    else:
        uplift = D(0)
    # ONE rounding only, applied to the single product.
    guild_floor = rhu(level_min * fmt_mult * (D(1) + uplift))
    weekly = max(seat["offered_weekly_compensation_cents"], guild_floor)
    if seat["diversity_program_funded"] and writer["diversity_program_participant"]:
        subsidy = min(rhu(D(weekly) * D(agreement["diversity_subsidy_pct"])),
                      agreement["diversity_subsidy_cap_weekly_cents"])
    else:
        subsidy = 0
    seat["guild_floor_weekly_cents"] = guild_floor
    seat["weekly_compensation_cents"] = weekly
    seat["diversity_subsidy_weekly_cents"] = subsidy
    seat["studio_charge_weekly_cents"] = weekly - subsidy
    return seat


def seat_prorated_commitment(seat):
    total_days = (seat["end_date"] - seat["start_date"]).days
    if total_days < 0:
        total_days = 0
    full_weeks = total_days // 7
    residual_days = total_days - 7 * full_weeks
    weekly = seat["weekly_compensation_cents"]
    # PINNED ORDER: round the daily rate first, then multiply.
    daily_rate = rhu(D(weekly) / D(7))
    seat["prorated_commitment_cents"] = full_weeks * weekly + residual_days * daily_rate
    return seat


def facility_tier_for(subtotal, agreement):
    bounds = agreement["facility_tier_subtotal_bounds"]
    if subtotal <= bounds["TIER_1_MAX"]:
        return "TIER_1"
    if subtotal <= bounds["TIER_2_MAX"]:
        return "TIER_2"
    return "TIER_3"


def room_weekly_burn(room, room_seats, agreement):
    subtotal = sum(s["weekly_compensation_cents"] for s in room_seats
                   if s["status"] == "CONFIRMED")
    tier = facility_tier_for(subtotal, agreement)
    surcharge = rhu(D(agreement["facility_fee_tiers"][tier])
                    * D(agreement["format_surcharge_pct"][room["format"]]))
    room["seat_subtotal_weekly_cents"] = subtotal
    room["facility_tier"] = tier
    room["facility_surcharge_weekly_cents"] = surcharge
    room["weekly_burn_cents"] = subtotal + surcharge
    return room


def script_fee(agreement, episode, assignment_type):
    base = D(agreement["script_fee_cents_by_length"][episode["length_format"]])
    share = D(agreement["type_share_pct_by_assignment_type"][assignment_type])
    return rhu(base * share)


# --------------------------------------------------------- share normalisation
def normalize_shares(entries):
    """entries: list of (key, weight, tiebreak). Returns {key: whole percent}."""
    if not entries:
        return {}
    denominator = sum(D(w) for _, w, _ in entries)
    if denominator == 0:
        return {key: 0 for key, _, _ in entries}
    computed = []
    for key, weight, tiebreak in entries:
        raw = D(weight) / denominator * D(100)
        floor_share = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
        computed.append([key, raw, floor_share, raw - D(floor_share), tiebreak])
    remainder = 100 - sum(item[2] for item in computed)
    ranked = sorted(computed, key=lambda item: (-item[3], item[4]))
    winners = set()
    for item in ranked[:max(0, remainder)]:
        winners.add(item[0])
    return {item[0]: item[2] + (1 if item[0] in winners else 0) for item in computed}


# ------------------------------------------------------------ clearance ladder
def clearance_posture(review, items, agreement):
    decided = [i for i in items if i["decision"] in ("CLEARED", "CONDITIONAL", "BLOCKED")]
    review["decided_item_count"] = len(decided)
    review["risk_score"] = min(100, sum(i["risk_weight"] for i in decided))
    review["item_count"] = len(items)
    if any(i["decision"] == "BLOCKED" for i in items):
        posture = "BLOCKED"
    elif review["risk_score"] > agreement["clearance_escalation_score"]:
        posture = "ESCALATED"
    elif review["risk_score"] > 0:
        posture = "CONDITIONAL"
    elif review["item_count"] >= 1 and review["decided_item_count"] == review["item_count"]:
        posture = "CLEARED"
    else:
        posture = "PENDING"
    return posture


# ----------------------------------------------------------- milestone due date
def due_date_for(episode_production_start, lead_days):
    target = episode_production_start.date() - _days(lead_days)
    return end_of_day(target)


def _days(count):
    from datetime import timedelta
    return timedelta(days=count)
