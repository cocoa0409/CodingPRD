"""Calculation rules (SCAFFOLD §1.3 / PRD §3): estimates, per-diem, penalties,
rest floor, attrition, chargeback, actual rollup, season budget."""
from datetime import timedelta

from state import STORE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TIER_RATE = {
    "TIER_A": {"TRAVEL_DAY": 12000, "GAME_DAY": 15000, "OFF_DAY": 9000, "PARTIAL_DAY": 6000},
    "TIER_B": {"TRAVEL_DAY": 9000, "GAME_DAY": 11000, "OFF_DAY": 7000, "PARTIAL_DAY": 4500},
    "TIER_C": {"TRAVEL_DAY": 6500, "GAME_DAY": 8000, "OFF_DAY": 5000, "PARTIAL_DAY": 3250},
}
MEAL_DEDUCTION_CENTS = 2500
MAX_MEALS_PER_DAY = 3

BASE_REST_MINUTES = {"STANDARD": 600, "STRINGENT": 720}
DELAY_COMPOUND_MINUTES = {"STANDARD": 60, "STRINGENT": 90}

TIER2_RATE_CENTS_PER_LB = 350
TIER3_RATE_CENTS_PER_LB = 900

# party_role -> weight_class (PRD gives no mapping; interpretation decision)
HEAVY_ROLES = {"PLAYER", "EQUIPMENT"}

# party_role -> roommate group (PRD gives no table; interpretation decision)
ROOM_GROUP = {
    "PLAYER": "ATHLETE",
    "COACH": "COACH",
    "STAFF": "STAFF",
    "MEDICAL": "STAFF",
    "SECURITY": "STAFF",
    "EQUIPMENT": "STAFF",
    "EXECUTIVE": "EXECUTIVE",
}

PARTY_ROLES = ["PLAYER", "COACH", "STAFF", "MEDICAL", "SECURITY", "EQUIPMENT", "EXECUTIVE"]
TRAVEL_CLASSES = ["CHARTER_FIRST", "CHARTER_STANDARD", "COMMERCIAL_PREMIUM", "COMMERCIAL_COACH"]
PER_DIEM_TIERS = ["TIER_A", "TIER_B", "TIER_C"]
DAY_KINDS = ["TRAVEL_DAY", "GAME_DAY", "OFF_DAY", "PARTIAL_DAY"]
SHIPMENT_KINDS = ["TEAM_GEAR", "MEDICAL", "BROADCAST", "PERSONAL_BAGGAGE"]
EVENT_KINDS = ["WEATHER", "MECHANICAL", "ATC_DELAY", "VENUE_CHANGE", "SECURITY_INCIDENT"]
SEVERITIES = ["MINOR", "MAJOR", "CRITICAL"]
RESOLUTION_ACTIONS = ["REBOOK", "REROUTE", "OVERNIGHT", "CANCEL_TRIP", "NONE"]
ACCESS_LEVELS = ["FIELD", "LOCKER_ROOM", "PRESS", "BACK_OF_HOUSE", "ALL_ACCESS"]
BUMP_REASONS = ["OVERBOOK", "WEIGHT_BALANCE", "SECURITY_DENIAL", "MEDICAL_SCRATCH"]
REST_POLICIES = ["STANDARD", "STRINGENT"]


def weight_class_for(party_role):
    return "HEAVY" if party_role in HEAVY_ROLES else "LIGHT"


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def children(coll, **fk):
    out = []
    for r in STORE[coll].values():
        if all(r.get(k) == v for k, v in fk.items()):
            out.append(r)
    out.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return out


def trip_members(trip):
    return children("members", trip_id=trip["id"])


def in_members(trip):
    return [m for m in trip_members(trip) if m["status"] == "IN"]


def trip_legs(trip):
    return children("legs", trip_id=trip["id"])


def trip_contracts(trip):
    return children("contracts", trip_id=trip["id"])


def trip_blocks(trip):
    return children("blocks", trip_id=trip["id"])


def trip_shipments(trip):
    return children("shipments", trip_id=trip["id"])


def trip_events(trip):
    return children("events", trip_id=trip["id"])


def trip_credentials(trip):
    return children("credentials", trip_id=trip["id"])


def trip_ledgers(trip):
    out = []
    member_ids = {m["id"] for m in trip_members(trip)}
    for l in STORE["ledgers"].values():
        if l["member_id"] in member_ids:
            out.append(l)
    out.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return out


def leg_entries(leg):
    return children("entries", flight_leg_id=leg["id"])


def block_rooms(block):
    return children("rooms", hotel_block_id=block["id"])


def occupied_rooms(block):
    return len(
        [
            r
            for r in block_rooms(block)
            if r["status"] in ("CONFIRMED", "CHECKED_IN", "CHECKED_OUT")
        ]
    )


# ---------------------------------------------------------------------------
# Per-diem
# ---------------------------------------------------------------------------
def per_diem_amounts(tier, day_kind, meals):
    base = TIER_RATE[tier][day_kind]
    deduction = meals * MEAL_DEDUCTION_CENTS
    return base, deduction, max(0, base - deduction)


# ---------------------------------------------------------------------------
# Trip estimated cost (forward-looking, recomputed on every booking change)
# ---------------------------------------------------------------------------
def compute_estimate(trip):
    tid = trip["id"]
    est = 0
    # Charter contracts: executed/active at full exposure; cancelled keep penalty.
    for c in trip_contracts(trip):
        if c["status"] in ("TEAM_EXECUTED", "ACTIVE"):
            est += c["base_price_cents"] + c["fuel_surcharge_cap_cents"]
        elif c["status"] == "CANCELLED":
            est += c.get("cancellation_penalty_cents") or 0
    # Hotel blocks
    for b in trip_blocks(trip):
        if b["posture"] in ("HOLDING", "NAME_LIST_DUE", "LOCKED", "ATTRITION_EXPOSED"):
            est += (b["room_count"] - b["rooms_released"]) * b["rate_cents_per_night"] * b["night_count"]
            est += b.get("_attrition_penalty_cents", 0)
    # Equipment shipments
    for s in trip_shipments(trip):
        if s["status"] in ("STAGED", "LOADED", "IN_TRANSIT", "DELAYED", "LOST"):
            est += s["chargeback_cents"]
    # Per-diem rows of IN members: DRAFT at base (provisional, zero-meals
    # assumption); APPROVED/PAID at net.
    for l in trip_ledgers(trip):
        m = STORE["members"].get(l["member_id"])
        if not m or m["status"] != "IN":
            continue
        if l["status"] == "DRAFT":
            est += l["base_amount_cents"]
        elif l["status"] in ("APPROVED", "PAID"):
            est += l["net_amount_cents"]
    # Contingency events
    for e in trip_events(trip):
        if e["status"] in ("OPEN", "MITIGATING", "RESOLVED"):
            est += e["recovery_cost_cents"]
    return est


def recalc_party_size(trip):
    trip["party_size"] = len(in_members(trip))


# ---------------------------------------------------------------------------
# Season budget counters (derived — SCAFFOLD season_budget_remaining)
# ---------------------------------------------------------------------------
def season_counters(season):
    committed = 0
    draft_estimates = 0
    for t in children("trips", season_id=season["id"]):
        if t["posture"] in ("LOCKED", "IN_FLIGHT", "DISRUPTED", "RECOVERING"):
            committed += t["estimated_cost_cents"]
        elif t["posture"] == "CLOSED":
            committed += t["actual_cost_cents"]
        elif t["posture"] == "CANCELLED":
            # Trips cancelled from DISRUPTED retain already-incurred costs
            # (charter penalties, recovery costs, losses, paid per-diem).
            committed += t.get("_incurred_loss_cents", 0)
        elif t["posture"] == "DRAFT":
            draft_estimates += t["estimated_cost_cents"]
    return committed, committed + draft_estimates


def season_remaining(season):
    committed, _ = season_counters(season)
    return season["travel_budget_cents"] - committed


# ---------------------------------------------------------------------------
# Charter cancellation penalty (round half up)
# ---------------------------------------------------------------------------
def cancellation_penalty(contract, trip, now):
    from decimal import ROUND_HALF_UP, Decimal

    tipoff = trip["_tipoff"]
    days_before = (tipoff - now).days  # floor toward past for positive deltas
    # floor on whole days, discarding partial day
    total_seconds = (tipoff - now).total_seconds()
    days_before = int(total_seconds // 86400)
    bands = sorted(contract["penalty_bands"], key=lambda b: b["days_before"], reverse=True)
    pct = 100
    for band in bands:
        if days_before >= band["days_before"]:
            pct = band["penalty_pct"]
            break
    amount = (contract["base_price_cents"] + contract["fuel_surcharge_cap_cents"]) * pct
    penalty = int(Decimal(amount / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return penalty


# ---------------------------------------------------------------------------
# Rest floor
# ---------------------------------------------------------------------------
def prior_leg(trip, leg):
    """Highest leg_seq below this leg's among non-cancelled legs."""
    cands = [
        l
        for l in trip_legs(trip)
        if l["leg_seq"] < leg["leg_seq"] and l["status"] != "CANCELLED"
    ]
    if not cands:
        return None
    return max(cands, key=lambda l: l["leg_seq"])


def effective_delay_minutes(leg):
    if leg["status"] == "ARRIVED":
        return leg["delay_minutes"]
    return leg.get("_reported_delay_minutes", 0)


def rest_required_minutes(policy, prior):
    base = BASE_REST_MINUTES[policy]
    comp = DELAY_COMPOUND_MINUTES[policy]
    delay = effective_delay_minutes(prior)
    extra = (max(0, delay - 60) // 60) * comp
    return base + extra


def rest_floor_ok(team, trip, leg, new_depart):
    """True if new_depart satisfies the rest floor against the prior leg."""
    if leg["leg_seq"] <= 1:
        return True
    prior = prior_leg(trip, leg)
    if prior is None:
        return True
    req = rest_required_minutes(team["league_rest_policy"], prior)
    earliest = prior["_sched_arrive"] + timedelta(minutes=req)
    return new_depart >= earliest


# ---------------------------------------------------------------------------
# Hotel attrition
# ---------------------------------------------------------------------------
def allowed_slippage_rooms(block):
    return (block["room_count"] * block["attrition_allowance_pct"]) // 100


def attrition_penalty_rooms(block):
    occ = occupied_rooms(block)
    return max(
        0,
        block["room_count"] - block["rooms_released"] - occ - allowed_slippage_rooms(block),
    )


def attrition_penalty_cents(block):
    return attrition_penalty_rooms(block) * block["rate_cents_per_night"] * block["night_count"]


# ---------------------------------------------------------------------------
# Equipment weight chargeback
# ---------------------------------------------------------------------------
def committed_weight_lb(contract, extra_shipment=None):
    total = 0
    for s in children("shipments", assigned_contract_id=contract["id"]):
        if s["status"] == "LOST":
            continue
        total += s["gross_weight_lb"]
    if extra_shipment is not None and extra_shipment["assigned_contract_id"] != contract["id"]:
        total += extra_shipment["gross_weight_lb"]
    return total


def weight_chargeback_cents(committed_lb, capacity_lb):
    tier1_ceiling = (85 * capacity_lb) // 100
    tier2 = max(0, min(committed_lb, capacity_lb) - tier1_ceiling) * TIER2_RATE_CENTS_PER_LB
    tier3 = max(0, committed_lb - capacity_lb) * TIER3_RATE_CENTS_PER_LB
    return tier2 + tier3


# ---------------------------------------------------------------------------
# Trip actual cost (chronological replay) and already-incurred loss
# ---------------------------------------------------------------------------
def actual_cost_from_log(trip):
    events = sorted(trip["_event_log"], key=lambda e: (e["ts"], e["seq"]))
    return sum(e["amount"] for e in events)


def incurred_loss_cents(trip):
    """Actual costs already incurred that survive cancellation:
    charter penalties + resolved/closed contingency recovery + LOST shipment
    chargebacks + PAID per-diem rows."""
    total = 0
    for c in trip_contracts(trip):
        if c["status"] == "CANCELLED":
            total += c.get("cancellation_penalty_cents") or 0
    for e in trip_events(trip):
        if e["status"] in ("RESOLVED", "CLOSED"):
            total += e["recovery_cost_cents"]
    for s in trip_shipments(trip):
        if s["status"] == "LOST":
            total += s["chargeback_cents"]
    for l in trip_ledgers(trip):
        if l["status"] == "PAID":
            total += l["net_amount_cents"]
    return total


def log_financial_event(trip, ts, amount):
    from state import next_seq

    trip["_event_log"].append({"ts": ts, "seq": next_seq(), "amount": amount})
