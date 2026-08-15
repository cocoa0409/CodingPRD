"""Domain helpers: lookups, computed fields, lay curve, posture, cascades.

Implements PRD §2.10 conserved ledgers, §3.2 lay curve, §3.8 posture
derivation and the shared cascade primitives used by several routes.
"""
from datetime import timedelta
from decimal import Decimal

from db import STORE, today, touch, new_record, next_tick
from errors import not_found
from util import D, rhu


# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------
SHELF_LIFE_DAYS = {"CONVENTIONAL": 45, "CAGE_FREE": 30, "PASTURE": 30}
SIZE_ORDER = ["JUMBO", "XLARGE", "LARGE", "MEDIUM", "SMALL", "PEEWEE"]
SIZE_COUNT_FIELD = {
    "JUMBO": "jumbo_count",
    "XLARGE": "xlarge_count",
    "LARGE": "large_count",
    "MEDIUM": "medium_count",
    "SMALL": "small_count",
    "PEEWEE": "peewee_count",
}
SIZE_RANK = {name: len(SIZE_ORDER) - i for i, name in enumerate(SIZE_ORDER)}  # JUMBO highest
SIZE_WEIGHT_G = {"PEEWEE": 42, "SMALL": 49, "MEDIUM": 56, "LARGE": 63, "XLARGE": 70, "JUMBO": 77}
SIZE_PREMIUM_PCT = {
    "JUMBO": D("0.20"), "XLARGE": D("0.10"), "LARGE": D("0"),
    "MEDIUM": D("-0.05"), "SMALL": D("-0.10"), "PEEWEE": D("-0.15"),
}
GRADE_UPLIFT_PCT = {"AA": D("0.05"), "A": D("0"), "B": D("-0.08")}
AMORTIZATION_DAYS = 420
STANDARD_FEED_G_PER_HEN_DAY = 115
MAX_MOLTS = 1
MOLT_MIN_AGE_WEEKS = 60
MOLT_REST_MIN_DAYS = 14
COLLECT_MIN_GAP_DAYS = 7
HOUSE_CLEANING_DAYS = 7
HOUSE_RESTING_DAYS = 14

CLAIM_ACCEPTS = {
    "NONE": {"CONVENTIONAL", "CAGE_FREE", "PASTURE"},
    "CAGE_FREE": {"CAGE_FREE", "PASTURE"},
    "PASTURE": {"PASTURE"},
}


# ---------------------------------------------------------------------------
# Lookups (tier 4 existence)
# ---------------------------------------------------------------------------
def get_entity(kind, entity_id, label="Resource"):
    rec = STORE[kind].get(entity_id) if isinstance(entity_id, str) else None
    if rec is None:
        raise not_found(label)
    return rec


# ---------------------------------------------------------------------------
# Relationship traversal
# ---------------------------------------------------------------------------
def farm_id_of_flock(flock):
    house = STORE["houses"].get(flock["house_id"])
    return house["farm_id"] if house else None


def farm_of_flock(flock):
    fid = farm_id_of_flock(flock)
    return STORE["farms"].get(fid)


def houses_of_farm(farm_id):
    return [h for h in STORE["houses"].values() if h["farm_id"] == farm_id]


def flocks_of_farm(farm_id):
    hids = {h["id"] for h in houses_of_farm(farm_id)}
    return [f for f in STORE["flocks"].values() if f["house_id"] in hids]


def production_days_of_flock(flock_id):
    return [p for p in STORE["production_days"].values() if p["flock_id"] == flock_id]


def dispositions_of_flock(flock_id):
    return [d for d in STORE["dispositions"].values() if d["flock_id"] == flock_id]


def grading_runs_of_flock(flock_id):
    return [g for g in STORE["grading_runs"].values() if g["flock_id"] == flock_id]


# ---------------------------------------------------------------------------
# Flock computed fields (PRD §3.2, §2.10)
# ---------------------------------------------------------------------------
def flock_age_weeks(flock):
    return (today() - flock["placement_date"]).days // 7


def lay_curve(age_weeks, lay_cycle, peak, status):
    """lay_curve_projection (scaffold §1.3): 2dp round-half-up; 0.00 unless LAYING."""
    if status != "LAYING":
        return Decimal("0.00")
    peak = D(peak)
    if age_weeks < 18:
        base = Decimal("0")
    elif age_weeks <= 20:
        base = peak * D(age_weeks - 17) / D(4)
    elif age_weeks <= 30:
        base = peak
    else:
        factor = Decimal("1") - D("0.015") * D(age_weeks - 30)
        if factor < D("0.40"):
            factor = D("0.40")
        base = peak * factor
    if lay_cycle == "SECOND":
        base = base * D("0.85")
    return rhu(base, 2)


def flock_cumulative_mortality(flock):
    return sum(p["mortality_count"] for p in production_days_of_flock(flock["id"]))


def flock_cumulative_eggs(flock):
    return sum(p["eggs_collected"] for p in production_days_of_flock(flock["id"]))


def flock_current_hen_count(flock):
    completed = sum(
        d["hen_count"]
        for d in dispositions_of_flock(flock["id"])
        if d["status"] == "COMPLETED"
    )
    return flock["initial_hen_count"] - flock_cumulative_mortality(flock) - completed


def flock_ungraded_pool(flock):
    produced = sum(
        p["eggs_collected"] - p["rejected_eggs"] for p in production_days_of_flock(flock["id"])
    )
    drawn = sum(
        g["eggs_to_grade"]
        for g in grading_runs_of_flock(flock["id"])
        if g["status"] == "CONFIRMED"
    )
    return produced - drawn


def flock_loose_pool(flock):
    total = 0
    for g in grading_runs_of_flock(flock["id"]):
        if g["status"] != "CONFIRMED":
            continue
        for field in SIZE_COUNT_FIELD.values():
            total += (g.get(field) or 0) % 12
    return total


def serialize_flock(flock):
    out = dict(flock)
    age = flock_age_weeks(flock)
    out["age_weeks"] = age
    out["current_lay_rate_pct"] = float(
        lay_curve(age, flock["lay_cycle"], flock["breed_peak_rate_pct"], flock["status"])
    )
    out["current_hen_count"] = flock_current_hen_count(flock)
    out["cumulative_mortality"] = flock_cumulative_mortality(flock)
    out["cumulative_eggs"] = flock_cumulative_eggs(flock)
    out["ungraded_egg_pool"] = flock_ungraded_pool(flock)
    out["loose_egg_pool"] = flock_loose_pool(flock)
    return out


# ---------------------------------------------------------------------------
# Contract computed counters (PRD §3.6)
# ---------------------------------------------------------------------------
def lots_of_contract(contract_id):
    return [l for l in STORE["lots"].values() if l.get("contract_id") == contract_id]


def contract_allocated_dozen(contract):
    return sum(
        l["dozen_count"] for l in lots_of_contract(contract["id"])
        if l["lifecycle_status"] == "ALLOCATED"
    )


def contract_shipped_dozen(contract):
    return sum(
        l["dozen_count"] for l in lots_of_contract(contract["id"])
        if l["lifecycle_status"] in ("SHIPPED", "CLOSED")
    )


def contract_held_allocated_dozen(contract):
    return sum(
        l["dozen_count"] for l in lots_of_contract(contract["id"])
        if l["lifecycle_status"] == "ALLOCATED" and l["hold_status"] == "HELD"
    )


def serialize_contract(contract):
    out = dict(contract)
    out["allocated_dozen"] = contract_allocated_dozen(contract)
    out["shipped_dozen"] = contract_shipped_dozen(contract)
    out["held_allocated_dozen"] = contract_held_allocated_dozen(contract)
    return out


# ---------------------------------------------------------------------------
# Farm computed fields (PRD §3.1)
# ---------------------------------------------------------------------------
def farm_active_flock_count(farm):
    return sum(1 for f in flocks_of_farm(farm["id"]) if f["status"] != "DEPLETED")


def serialize_farm(farm):
    out = dict(farm)
    out["active_flock_count"] = farm_active_flock_count(farm)
    return out


# ---------------------------------------------------------------------------
# Contract suspension cascade (PRD §3.6: suspend auto-voids DRAFT settlements)
# ---------------------------------------------------------------------------
def void_draft_settlements(contract):
    for s in STORE["settlements"].values():
        if s["contract_id"] == contract["id"] and s["status"] == "DRAFT":
            s["status"] = "VOIDED"
            touch(s)


def suspend_contract(contract):
    """ACTIVE -> SUSPENDED with DRAFT-settlement cascade. No-op otherwise."""
    if contract["status"] != "ACTIVE":
        return
    contract["status"] = "SUSPENDED"
    touch(contract)
    void_draft_settlements(contract)


# ---------------------------------------------------------------------------
# Sampling windows (PRD §3.7) and missed-window detection
# ---------------------------------------------------------------------------
def _env_collected_in_window(flock, window_start, window_end):
    for t in STORE["salmonella_tests"].values():
        if t["flock_id"] != flock["id"] or t["test_type"] != "ENVIRONMENTAL":
            continue
        cd = t.get("collected_date")
        if cd is not None and window_start <= cd <= window_end:
            return True
    return False


def w1_window(flock):
    """Window 1 in dates: age_weeks 40..45 -> placement + [280, 321] days."""
    p = flock["placement_date"]
    return p + timedelta(days=280), p + timedelta(days=321)


def w2_window(flock):
    """Post-molt window: weeks 4..6 after molt_started -> + [28, 48] days."""
    m = flock["molt_started_date"]
    return m + timedelta(days=28), m + timedelta(days=48)


def flock_missed_sampling_window(flock):
    today_d = today()
    w1s, w1e = w1_window(flock)
    if today_d > w1e and not _env_collected_in_window(flock, w1s, w1e):
        return True
    if flock.get("molt_count", 0) >= 1 and flock.get("molt_started_date"):
        w2s, w2e = w2_window(flock)
        if today_d > w2e and not _env_collected_in_window(flock, w2s, w2e):
            return True
    return False


# ---------------------------------------------------------------------------
# Compliance posture derivation (PRD §3.8) with SUSPENDED-transition cascade
# ---------------------------------------------------------------------------
def derive_posture(farm_id):
    flocks = flocks_of_farm(farm_id)
    flock_ids = {f["id"] for f in flocks}
    today_d = today()

    for t in STORE["salmonella_tests"].values():
        if t["flock_id"] in flock_ids and t.get("result") == "POSITIVE" and t["status"] != "RESOLVED":
            return "SUSPENDED"

    audits = [a for a in STORE["compliance_audits"].values() if a["farm_id"] == farm_id]
    for a in audits:
        if a.get("outcome") == "FAILED" and a.get("closed_date") is not None:
            if 0 <= (today_d - a["closed_date"]).days <= 30:
                later_passed = any(
                    b["status"] == "CLOSED_PASSED"
                    and b.get("_closed_tick", 0) > a.get("_closed_tick", 0)
                    for b in audits
                )
                if not later_passed:
                    return "SUSPENDED"

    for a in audits:
        if a["status"] == "FINDINGS_RECORDED" and (a.get("corrective_actions_open") or 0) > 0:
            return "WATCH"

    for f in flocks:
        if f["status"] == "LAYING" and flock_missed_sampling_window(f):
            return "WATCH"

    return "CLEAR"


def recompute_posture(farm):
    """Recompute stored posture; transition into SUSPENDED cascades (PRD §3.8)."""
    new = derive_posture(farm["id"])
    old = farm["compliance_posture"]
    if new != old:
        farm["compliance_posture"] = new
        farm["_tick"] = next_tick()
        if new == "SUSPENDED":
            for c in STORE["contracts"].values():
                if c["farm_id"] == farm["id"] and c["status"] == "ACTIVE":
                    suspend_contract(c)
