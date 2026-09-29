"""Deterministic calculations (PRD 3.3, 3.5, 3.7, 3.8, 3.9)."""
import math
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

import db
from errors import fail

# ---- career_eligibility_assessment ----
POSTHUMOUS_WAITING_YEARS = 1
VETERANS_MIN_YEARS = 25
VETERANS_COOLDOWN_YEARS = 3
SPECIAL_MAX_PER_CYCLE = 1

# ---- max_votes_per_elector_for_round ----
MAX_VOTES_CAP = 5
MIN_VOTES_FLOOR = 1
VOTES_DIVISOR = 2

# ---- election_outcome_resolution ----
MAX_ROUNDS = 3
MIN_RUNOFF_CONTENDERS = 2

# ---- screening ----
MAX_INFO_REQUESTS = 2

# ---- roster maintenance ----
LAPSE_MISSED_CYCLES = 2

# ---- travel_grant_award_cents ----
NIGHTLY_PER_DIEM_CENTS = 18333
AIRFARE_CAP_CENTS = 95000
POSTHUMOUS_TRAVELER_COUNT = 2
POSTHUMOUS_PER_DIEM_FACTOR = Decimal("0.75")

TIER_FACTORS = {"FULL": Decimal("1.00"), "REDUCED": Decimal("0.80"), "MINIMAL": Decimal("0.60")}


def dec(value):
    return Decimal(str(value))


def ceil_votes(denominator, pct):
    """Threshold votes: the product is rounded UP to the next whole vote."""
    product = Decimal(denominator) * dec(pct)
    return int(product.to_integral_value(rounding=ROUND_CEILING))


def rule_for(category, pathway):
    for row in db.eligibility_rules.values():
        if row["category"] == category and row["pathway"] == pathway:
            return row
    return None


def house_threshold_pct():
    """The house threshold row: PLAYER paired with MODERN (PRD 3.1)."""
    rule = rule_for("PLAYER", "MODERN")
    if rule is None:
        fail(
            "ERR_ELIGIBILITY_RULE_NOT_FOUND",
            "The house threshold row (PLAYER / MODERN) has not been published.",
        )
    return rule["election_threshold_pct"]


# ------------------------------------------------- career eligibility assessment


def assess_career_eligibility(cycle, candidate, pathway, justification, rule):
    """Runs the nomination eligibility ladder in the PRD 3.3 order and returns
    the computed eligible_from_year."""
    # 1. candidate standing
    if candidate["hof_status"] != "NOT_INDUCTED":
        fail("ERR_CANDIDATE_INELIGIBLE", "Candidate is not in play.")

    # 2. baseline year and effective waiting period, per pathway
    if pathway == "POSTHUMOUS":
        if not candidate["is_deceased"] or candidate["death_year"] is None:
            fail(
                "ERR_POSTHUMOUS_PATHWAY_REQUIRES_DECEASED",
                "The posthumous pathway requires a deceased candidate with a death year.",
            )
        baseline_year = max(candidate["retirement_year"], candidate["death_year"])
        effective_waiting_years = POSTHUMOUS_WAITING_YEARS
    elif pathway == "SPECIAL":
        baseline_year = candidate["retirement_year"]
        effective_waiting_years = 0
    else:
        baseline_year = candidate["retirement_year"]
        effective_waiting_years = rule["waiting_period_years"]

    eligible_from_year = baseline_year + effective_waiting_years

    # 3. waiting period, inclusive at the boundary
    if cycle["cycle_year"] < eligible_from_year:
        fail("ERR_WAITING_PERIOD_NOT_MET", "The cycle year is below the candidacy eligibility year.")

    # 4. veterans long-gap floor
    if pathway == "VETERANS":
        stored = candidate["veterans_eligible_from_year"]
        floor_year = (
            stored if stored is not None else candidate["retirement_year"] + VETERANS_MIN_YEARS
        )
        if cycle["cycle_year"] < floor_year:
            fail("ERR_WAITING_PERIOD_NOT_MET", "The veterans long-gap floor has not been reached.")

    # 5. career thresholds, inclusive at both boundaries, never waived
    if candidate["career_seasons"] < rule["min_career_seasons"]:
        fail("ERR_CAREER_THRESHOLD_NOT_MET", "Career seasons below the published minimum.")
    if dec(candidate["career_metric_value"]) < dec(rule["min_career_metric"]):
        fail("ERR_CAREER_THRESHOLD_NOT_MET", "Career metric below the published minimum.")

    # 6. appearance budget
    if candidate["ballot_appearances_used"] >= rule["max_ballot_appearances"]:
        fail("ERR_APPEARANCE_LIMIT_REACHED", "Every ballot appearance this pathway allows is used.")

    # 7. special election gates
    if pathway == "SPECIAL":
        if justification is None or not str(justification).strip():
            fail("ERR_JUSTIFICATION_REQUIRED", "A SPECIAL nomination requires a justification.")
        if cycle["special_election_used"] >= SPECIAL_MAX_PER_CYCLE:
            fail(
                "ERR_SPECIAL_ELECTION_QUOTA_EXHAUSTED",
                "The special election slot for this cycle is already taken.",
            )

    return eligible_from_year


# ----------------------------------------------- max votes per elector for round


def max_votes_per_elector_for_round(listed_slots, round_number):
    slot_count = len(listed_slots)
    veterans_slot_count = len([s for s in listed_slots if s["pathway_snapshot"] == "VETERANS"])

    base = min(MAX_VOTES_CAP, max(MIN_VOTES_FLOOR, slot_count // VOTES_DIVISOR))
    if round_number > 1:
        base = max(MIN_VOTES_FLOOR, int(math.ceil(base / 2.0)))
    if veterans_slot_count >= 1:
        base = min(base + 1, MAX_VOTES_CAP)
    return base


# ------------------------------------------------------ travel grant award cents


def travel_award(tier, delegation_type, nights, requested_airfare_cents):
    tier_factor = TIER_FACTORS[tier]
    if delegation_type == "POSTHUMOUS_DELEGATION":
        traveler_count = POSTHUMOUS_TRAVELER_COUNT
        per_diem_factor = POSTHUMOUS_PER_DIEM_FACTOR
    else:
        traveler_count = 1
        per_diem_factor = Decimal("1.00")

    raw = Decimal(NIGHTLY_PER_DIEM_CENTS) * Decimal(nights) * tier_factor * per_diem_factor
    per_traveler_per_diem = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    per_traveler_airfare = min(requested_airfare_cents, AIRFARE_CAP_CENTS)
    per_traveler_total = per_traveler_per_diem + per_traveler_airfare
    return traveler_count * per_traveler_total, traveler_count


# ---------------------------------------------------------- escort pool overlap


def escort_pool_check(cycle, grant):
    """Closed intervals on both ends; capacity is aggregate."""
    if grant["escort_from"] is None or grant["escort_to"] is None:
        return
    new_from = grant["escort_from"]
    new_to = grant["escort_to"]
    occupied = []
    for other in db.travel_grants.values():
        if other["id"] == grant["id"]:
            continue
        if other["cycle_id"] != cycle["id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        if other["escort_from"] is None or other["escort_to"] is None:
            continue
        if other["escort_from"] <= new_to and new_from <= other["escort_to"]:
            occupied.append(other)

    probes = set([new_from, new_to])
    for other in occupied:
        probes.add(other["escort_from"])
        probes.add(other["escort_to"])
    clipped = sorted(t for t in probes if new_from <= t <= new_to)
    pool = cycle["escort_pool_size"] or 0
    for instant in clipped:
        concurrent = len(
            [o for o in occupied if o["escort_from"] <= instant <= o["escort_to"]]
        )
        if concurrent + 1 > pool:
            fail(
                "ERR_ESCORT_POOL_EXHAUSTED",
                "The ceremony escort pool is exhausted for the requested interval.",
            )


# -------------------------------------------------------- exhibit window conflict


def exhibit_window_check(case, induction_id, starts_on, ends_on):
    """Half-open display windows; a changeover buffer applies across inductions."""
    buffer = timedelta(days=case["changeover_buffer_days"])
    for other in db.exhibit_installations.values():
        if other["exhibit_case_id"] != case["id"] or other["status"] != "INSTALLED":
            continue
        if other["induction_id"] == induction_id:
            if starts_on < other["display_ends_on"] and other["display_starts_on"] < ends_on:
                fail("ERR_CASE_WINDOW_CONFLICT", "The display window overlaps an installed window.")
        else:
            if (
                starts_on < other["display_ends_on"] + buffer
                and other["display_starts_on"] < ends_on + buffer
            ):
                fail(
                    "ERR_CASE_WINDOW_CONFLICT",
                    "The display window falls inside another induction's changeover buffer.",
                )
