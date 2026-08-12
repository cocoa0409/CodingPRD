"""Business logic: mutations, cascades, calculations, sweeps."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store
from util import ApiError, pub

DELIVERY_TERMINAL = {"DELIVERED", "FAILED", "CANCELLED", "SPOILED"}

# Payer rate card (PRD section 3.7)
WAIVER_RATE_CENTS = 925
MA_RATE_CENTS = 1180
WAIVER_TIER2_FPL_MIN = 138
WAIVER_TIER2_FPL_MAX = 150
MA_COPAY_CENTS = 500
OOP_MAX_CENTS = 34000

EXCURSION_THRESHOLD_C = 8.0
SPOILAGE_LIMIT_MINUTES = 30

ADHERENCE_WINDOW_DAYS = 84
ADHERENCE_THRESHOLD = Decimal("80.00")
ASSESSMENT_WINDOW_DAYS = 90

GATES_BY_DIET = {
    "RENAL": ["sodium", "potassium", "phosphorus", "protein"],
    "DIABETIC": ["sodium", "carbs", "protein"],
    "RENAL_DIABETIC": ["sodium", "potassium", "phosphorus", "carbs", "protein"],
    "CARDIAC": ["sodium", "protein"],
}


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = db.now_iso()


# ---------------------------------------------------------------------------
# Views (computed fields injected at read time)
# ---------------------------------------------------------------------------

def member_view(m):
    d = pub(m)
    delivered_pct, confirmed_pct = compute_adherence(m["id"])
    d["adherence_delivered_pct"] = delivered_pct
    d["adherence_confirmed_pct"] = confirmed_pct
    return d


def reauth_view(a):
    d = pub(a)
    d["available_units"] = a["authorized_units"] - a["used_units"] - a["reserved_units"]
    return d


# ---------------------------------------------------------------------------
# Adherence (PRD section 3.6): trailing 84-day window, round-half-up 2dp
# ---------------------------------------------------------------------------

def _pct(num, den):
    if den == 0:
        return 100.0
    v = (Decimal(num * 100) / Decimal(den)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(v)


def compute_adherence(member_id):
    today = db.get_clock().date()
    start = today - timedelta(days=ADHERENCE_WINDOW_DAYS)
    ds = []
    for d in store["deliveries"].values():
        if d["member_id"] != member_id:
            continue
        sd = date.fromisoformat(d["service_date"])
        if start <= sd <= today:
            ds.append(d)
    denom = sum(1 for d in ds if d["status"] in ("DELIVERED", "FAILED", "SPOILED"))
    delivered = sum(1 for d in ds if d["status"] == "DELIVERED")
    confirmed = sum(1 for d in ds
                    if d["status"] == "DELIVERED" and d["confirmed_at"] is not None)
    delivered_pct = 100.0 if denom == 0 else _pct(delivered, denom)
    confirmed_pct = 100.0 if delivered == 0 else _pct(confirmed, delivered)
    return delivered_pct, confirmed_pct


# ---------------------------------------------------------------------------
# Menu cycle compliance (PRD section 3.4)
# ---------------------------------------------------------------------------

def cycle_lines(cycle_id):
    return [li for li in store["cycle_items"].values()
            if li["menu_cycle_id"] == cycle_id]


def compute_compliance(cycle):
    lines = sorted(cycle_lines(cycle["id"]), key=lambda l: l["created_at"])
    member = store["members"][cycle["member_id"]]
    rx = store["prescriptions"][cycle["prescription_id"]]

    totals = {"sodium": 0, "potassium": 0, "phosphorus": 0, "carbs": 0, "protein": 0}
    meals_count = 0
    blocked = set(member["allergies"]) | set(rx["excluded_allergens"])
    allergen_violations = []
    for li in lines:
        item = store["menu_items"][li["menu_item_id"]]
        qty = li["quantity"]
        meals_count += qty
        totals["sodium"] += item["sodium_mg"] * qty
        totals["potassium"] += item["potassium_mg"] * qty
        totals["phosphorus"] += item["phosphorus_mg"] * qty
        totals["carbs"] += item["carbs_g"] * qty
        totals["protein"] += item["protein_g"] * qty
        if set(item["allergen_codes"]) & blocked:
            allergen_violations.append((item["name"], li["created_at"]))
    allergen_violations.sort(key=lambda t: (t[0], t[1]))

    gates = GATES_BY_DIET[rx["diet_type"]]
    fails = []
    if "sodium" in gates and totals["sodium"] > 7 * rx["daily_sodium_mg_max"]:
        fails.append("sodium")
    if "potassium" in gates and totals["potassium"] > 7 * rx["daily_potassium_mg_max"]:
        fails.append("potassium")
    if "phosphorus" in gates and totals["phosphorus"] > 7 * rx["daily_phosphorus_mg_max"]:
        fails.append("phosphorus")
    if "carbs" in gates and totals["carbs"] > 7 * rx["daily_carbs_g_max"]:
        fails.append("carbs")
    if "protein" in gates and totals["protein"] < 7 * rx["daily_protein_g_min"]:
        fails.append("protein")

    return {
        "sodium_mg_total": totals["sodium"],
        "potassium_mg_total": totals["potassium"],
        "phosphorus_mg_total": totals["phosphorus"],
        "carbs_g_total": totals["carbs"],
        "protein_g_total": totals["protein"],
        "meals_count": meals_count,
        "allergen_violations": [name for name, _ in allergen_violations],
        "nutrient_violations": fails,
        "nutrition_compliant": len(fails) == 0,
        "allergen_ok": len(allergen_violations) == 0,
    }


def recompute_meals_count(cycle):
    cycle["meals_count"] = sum(li["quantity"] for li in cycle_lines(cycle["id"]))


# ---------------------------------------------------------------------------
# Unit ledger (PRD section 3.5 / 2.10)
# ---------------------------------------------------------------------------

def release_unit(delivery):
    a = store["reauthorizations"].get(delivery.get("authorization_id"))
    if a is not None:
        a["reserved_units"] -= 1
        bump(a)


def consume_unit(delivery):
    a = store["reauthorizations"].get(delivery.get("authorization_id"))
    if a is not None:
        a["reserved_units"] -= 1
        a["used_units"] += 1
        if a["used_units"] == a["authorized_units"]:
            a["status"] = "EXHAUSTED"
        bump(a)


def select_authorization(member_id, service_date):
    """Waterfall unit reservation: earliest end_date, tie created_at."""
    covering = []
    for a in store["reauthorizations"].values():
        if a["member_id"] != member_id or a["status"] != "APPROVED":
            continue
        if a["start_date"] <= service_date <= a["end_date"]:
            covering.append(a)
    if not covering:
        raise ApiError("ERR_SERVICE_DATE_OUT_OF_AUTHORIZATION", 422,
                       "No APPROVED authorization window covers the service_date")
    with_units = [a for a in covering
                  if a["authorized_units"] - a["used_units"] - a["reserved_units"] >= 1]
    if not with_units:
        raise ApiError("ERR_AUTHORIZATION_EXHAUSTED", 402,
                       "Covering authorizations exist but all are exhausted")
    with_units.sort(key=lambda a: (a["end_date"], a["created_at"]))
    return with_units[0]


# ---------------------------------------------------------------------------
# Delivery / cycle cascades
# ---------------------------------------------------------------------------

def maybe_fulfill_cycle(cycle_id):
    c = store["menu_cycles"].get(cycle_id)
    if c is None or c["status"] != "FROZEN":
        return
    ds = [d for d in store["deliveries"].values()
          if d["menu_cycle_id"] == c["id"]]
    if ds and all(d["status"] in DELIVERY_TERMINAL for d in ds) \
            and any(d["status"] == "DELIVERED" for d in ds):
        c["status"] = "FULFILLED"
        bump(c)


def cancel_delivery(d):
    d["status"] = "CANCELLED"
    bump(d)
    release_unit(d)


def cancel_cycle(c):
    c["status"] = "CANCELLED"
    bump(c)
    for d in store["deliveries"].values():
        if d["menu_cycle_id"] == c["id"] and d["status"] in ("SCHEDULED", "OUT_FOR_DELIVERY"):
            cancel_delivery(d)


def disenroll_cascade(member):
    """Depth-3 cascade: ACTIVE rx -> REVOKED; its PLANNED/FROZEN cycles ->
    CANCELLED; their open deliveries -> CANCELLED with unit release."""
    for p in store["prescriptions"].values():
        if p["member_id"] == member["id"] and p["status"] == "ACTIVE":
            p["status"] = "REVOKED"
            bump(p)
            for c in store["menu_cycles"].values():
                if (c["member_id"] == member["id"]
                        and c["status"] in ("PLANNED", "FROZEN")
                        and c["prescription_id"] == p["id"]):
                    cancel_cycle(c)


# ---------------------------------------------------------------------------
# Cold chain (PRD section 3.5): chronological replay, whole-minute truncation
# ---------------------------------------------------------------------------

def replay_cold_chain(delivery):
    readings = [r for r in store["readings"].values()
                if r["delivery_id"] == delivery["id"]]
    readings.sort(key=lambda r: (r["_recorded_dt"], r["created_at"]))
    cumulative = 0
    any_excursion = False
    for i, r in enumerate(readings):
        if float(r["temp_celsius"]) > EXCURSION_THRESHOLD_C:
            any_excursion = True
            if i + 1 < len(readings):
                gap = (readings[i + 1]["_recorded_dt"] - r["_recorded_dt"]).total_seconds()
                if gap > 0:
                    cumulative += int(gap // 60)
    if cumulative > SPOILAGE_LIMIT_MINUTES:
        status = "SPOILED"
    elif any_excursion:
        status = "EXCURSION"
    else:
        status = "INTACT"
    return cumulative, status


# ---------------------------------------------------------------------------
# Claim provisional pricing (PRD section 3.7): per-line round-half-up waiver
# cost share, or MA flat copay capped by OOP headroom
# ---------------------------------------------------------------------------

def compute_claim_amounts(member, cycle):
    payer = member["payer_type"]
    rate = WAIVER_RATE_CENTS if payer == "MEDICAID_WAIVER" else MA_RATE_CENTS
    lines = cycle_lines(cycle["id"])
    gross = 0
    share = 0
    if payer == "MEDICAID_WAIVER":
        fpl = member["income_fpl_percent"]
        if fpl < WAIVER_TIER2_FPL_MIN:
            pct = Decimal("0")
        elif fpl <= WAIVER_TIER2_FPL_MAX:
            pct = Decimal("0.05")
        else:
            pct = Decimal("0.10")
        for li in lines:
            line_gross = rate * li["quantity"]
            gross += line_gross
            share += int((Decimal(line_gross) * pct).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        for li in lines:
            gross += rate * li["quantity"]
        headroom = max(0, OOP_MAX_CENTS - member["oop_accumulator_cents"])
        share = min(MA_COPAY_CENTS, headroom)
    return gross, share, gross - share


# ---------------------------------------------------------------------------
# Expiry sweep (PRD section 2.4), fired when the logical clock is set
# ---------------------------------------------------------------------------

def expiry_sweep():
    today = db.get_clock().date()
    for r in store["referrals"].values():
        if r["status"] in ("SUBMITTED", "TRIAGED") \
                and date.fromisoformat(r["expires_at"]) < today:
            r["status"] = "EXPIRED"
            bump(r)
    for a in store["reauthorizations"].values():
        if a["status"] == "APPROVED" and date.fromisoformat(a["end_date"]) < today:
            a["status"] = "EXPIRED"
            bump(a)
