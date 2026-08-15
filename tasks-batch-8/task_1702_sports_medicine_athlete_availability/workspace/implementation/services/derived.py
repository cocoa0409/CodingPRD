"""Availability tier derivation, ACWR (ROLLING/EWMA), load flag threshold."""
from decimal import Decimal, ROUND_HALF_UP, getcontext
from datetime import timedelta

from db import STORE, clock_date, touch
from services.common import (current_entries_for_case, protocol_for_case,
                             find_all, today_current_entry)

getcontext().prec = 40

TIER_RANK = {"OUT": 0, "LIMITED": 1, "MODIFIED": 2, "FULL": 3}  # lower = worse
ACTIVE_CASE_STATES = {"OPEN", "REHAB", "RTP", "LONG_TERM"}

ELEVATED_THRESHOLD = Decimal("1.300")
SPIKE_THRESHOLD = Decimal("1.500")

ACWR_MIN_SESSIONS = 8
EWMA_DECAY = Decimal("0.8")  # L = 1 - 0.2


def effective_designation(case):
    """Raw effective designation (pre-override) per derivation step 2."""
    today = clock_date()
    cur = current_entries_for_case(case["id"])
    if not cur:
        return "OUT"
    today_entry = None
    for e in cur:
        if e["_entry_date"] == today:
            today_entry = e
            break
    if today_entry is not None:
        return today_entry["designation"]
    cur.sort(key=lambda e: (e["_entry_date"], e["created_at"]))
    return cur[-1]["designation"]


def case_contribution(case):
    """Tier contribution of one candidate case after state overrides."""
    desig = effective_designation(case)
    status = case["status"]
    if status == "OPEN":
        # at least LIMITED severity (never FULL)
        if TIER_RANK[desig] > TIER_RANK["LIMITED"]:
            desig = "LIMITED"
    elif status == "LONG_TERM":
        desig = "OUT"
    elif status == "RTP":
        proto = protocol_for_case(case["id"])
        if proto is not None and proto["status"] == "AWAITING_CLEARANCE":
            # at most LIMITED availability (MODIFIED/FULL -> LIMITED)
            if TIER_RANK[desig] > TIER_RANK["LIMITED"]:
                desig = "LIMITED"
    return desig


def candidate_cases(athlete_id):
    return find_all("injury_cases",
                    lambda c: c["athlete_id"] == athlete_id
                    and c["status"] in ACTIVE_CASE_STATES)


def driving_case(athlete_id):
    """The candidate case contributing the worst tier (tie: earliest created)."""
    cands = candidate_cases(athlete_id)
    if not cands:
        return None
    cands.sort(key=lambda c: (TIER_RANK[case_contribution(c)], c["created_at"]))
    return cands[0]


def derive_tier(athlete):
    cands = candidate_cases(athlete["id"])
    if not cands:
        tier = "FULL"
    else:
        tier = min((case_contribution(c) for c in cands),
                   key=lambda t: TIER_RANK[t])
    # load overlay: SPIKE downgrades FULL -> MODIFIED only
    if athlete.get("load_flag") == "SPIKE" and tier == "FULL":
        tier = "MODIFIED"
    return tier


def _qualifying_sessions(athlete_id):
    return find_all("workload_sessions",
                    lambda s: s["athlete_id"] == athlete_id
                    and s["session_type"] != "REHAB_SESSION")


def compute_acwr(athlete, team):
    """Returns Decimal ratio rounded to 3dp half-up, or None."""
    today = clock_date()
    sessions = _qualifying_sessions(athlete["id"])
    chronic_lo = today - timedelta(days=27)
    in_chronic = [s for s in sessions
                  if chronic_lo <= s["_session_date"] <= today]
    if len(in_chronic) < ACWR_MIN_SESSIONS:
        return None
    if team.get("acwr_variant", "ROLLING") == "EWMA":
        daily = {}
        for s in in_chronic:
            daily[s["_session_date"]] = daily.get(s["_session_date"], 0) + s["session_load"]
        acute_num = Decimal(0)
        acute_den = Decimal(0)
        for k in range(0, 7):
            w = EWMA_DECAY ** k
            acute_den += w
            acute_num += w * Decimal(daily.get(today - timedelta(days=k), 0))
        chronic_num = Decimal(0)
        chronic_den = Decimal(0)
        for k in range(0, 28):
            w = EWMA_DECAY ** k
            chronic_den += w
            chronic_num += w * Decimal(daily.get(today - timedelta(days=k), 0))
        if chronic_num == 0:
            return None
        acute = acute_num / acute_den
        chronic = chronic_num / chronic_den
        ratio = acute / chronic
    else:
        acute_lo = today - timedelta(days=6)
        acute_load = sum(s["session_load"] for s in sessions
                         if acute_lo <= s["_session_date"] <= today)
        chronic_load_sum = sum(s["session_load"] for s in in_chronic)
        if chronic_load_sum == 0:
            return None
        chronic_load = Decimal(chronic_load_sum) / Decimal(4)
        ratio = Decimal(acute_load) / chronic_load
    return ratio.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def load_flag_for(ratio):
    if ratio is None:
        return "NONE"
    if ratio >= SPIKE_THRESHOLD:
        return "SPIKE"
    if ratio >= ELEVATED_THRESHOLD:
        return "ELEVATED"
    return "NONE"


def recompute_athlete(athlete, bump=True):
    """Recompute availability_tier (uses stored load_flag); optionally bump version."""
    athlete["availability_tier"] = derive_tier(athlete)
    if bump:
        touch(athlete)


def recompute_load_and_tier(athlete, team):
    """On workload ingest: ACWR + load_flag + tier overlay; one version bump."""
    ratio = compute_acwr(athlete, team)
    athlete["acute_chronic_workload_ratio"] = float(ratio) if ratio is not None else None
    athlete["load_flag"] = load_flag_for(ratio)
    athlete["availability_tier"] = derive_tier(athlete)
    touch(athlete)
