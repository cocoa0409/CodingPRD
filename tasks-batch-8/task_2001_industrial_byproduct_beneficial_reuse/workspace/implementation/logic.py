"""Business logic: logical clock, lazy reconciliation, calculations, cascades."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from common import now_ts
from store import db, next_seq

D0 = Decimal("0")

MATERIALS = {"FLY_ASH", "SLAG", "GYPSUM", "FOUNDRY_SAND", "BIOSOLIDS"}
USE_CASES = {"CEMENT_ADDITIVE", "ROAD_BASE", "SOIL_AMENDMENT", "MINE_RECLAMATION"}
REGIMES = {"PERMIT", "NOTIFICATION"}

# freight_cost_allocation constants
BASE_FEE_CENTS = 15000
TIER1_LIMIT_MI = 100
TIER1_RATE = 450
TIER2_LIMIT_MI = 300
TIER2_RATE = 320
TIER3_RATE = 210
MAX_GENERATOR_FREIGHT_SHARE_CENTS = 60000

# shipment_settlement constants
MOISTURE_TOLERANCE_PCT = Decimal("2.0")

# sustainability_credit_accrual constants
STANDARD_CREDIT_PER_TON = Decimal("1.0")
ATTESTED_FACTOR = Decimal("0.92")

# credit_tier_assignment thresholds
SILVER_THRESHOLD = Decimal("100")
GOLD_THRESHOLD = Decimal("250")

# rejection_tolerance_posture
REJECTION_TOLERANCE_PCT = Decimal("0.20")


def D(x):
    return Decimal(str(x))


def rhu(x, places=0):
    """round_half_up to the given number of decimal places."""
    return x.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def current_date():
    return db.clock.date()


def current_month():
    return f"{db.clock.year:04d}-{db.clock.month:02d}"


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_record():
    ts = now_ts()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def new_ledger_record():
    return {"id": str(uuid.uuid4()), "created_at": now_ts(), "_seq": next_seq()}


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_ts()


def sorted_items(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Lazy reconciliation (section 2.4)
# ---------------------------------------------------------------------------

def rollover_agreement(ag):
    """monthly_counter_rollover: derived-field refresh, no version/updated_at bump."""
    m = current_month()
    if ag["counter_month"] != m:
        ag["counter_month"] = m
        ag["booked_month_to_date_tons"] = D0
        ag["delivered_month_to_date_tons"] = D0
        ag["fulfillment_status"] = "UNMET"


def rollover_commitment(cm):
    m = current_month()
    if cm["counter_month"] != m:
        cm["counter_month"] = m
        cm["accepted_month_to_date_tons"] = D0


def lazy_expire_determination(d):
    if d["status"] in ("APPROVED", "SUSPENDED") and current_date() >= d["valid_until"]:
        d["status"] = "EXPIRED"
        touch(d)


def lazy_expire_permit(p):
    if p["status"] == "ACTIVE" and current_date() > p["expires_on"]:
        p["status"] = "EXPIRED"
        touch(p)


# ---------------------------------------------------------------------------
# market_price_selection
# ---------------------------------------------------------------------------

def select_price(material_type, region_code, on_date):
    cands = [e for e in db.price_entries.values()
             if e["material_type"] == material_type
             and e["region_code"] == region_code
             and e["effective_from"] <= on_date]
    if not cands:
        return None
    cands.sort(key=lambda e: (e["effective_from"], e["created_at"], e["_seq"]),
               reverse=True)
    return cands[0]


# ---------------------------------------------------------------------------
# freight_cost_allocation
# ---------------------------------------------------------------------------

def freight_total_cents(distance_miles):
    d = distance_miles
    return (BASE_FEE_CENTS
            + min(d, TIER1_LIMIT_MI) * TIER1_RATE
            + max(0, min(d, TIER2_LIMIT_MI) - TIER1_LIMIT_MI) * TIER2_RATE
            + max(0, d - TIER2_LIMIT_MI) * TIER3_RATE)


def freight_shares(total_cents, freight_share_pct):
    gen = int(rhu(D(total_cents) * freight_share_pct, 0))
    gen = min(gen, MAX_GENERATOR_FREIGHT_SHARE_CENTS)
    return gen, total_cents - gen


# ---------------------------------------------------------------------------
# supply agreement helpers
# ---------------------------------------------------------------------------

def fulfillment_for(ag):
    return ("MET" if ag["delivered_month_to_date_tons"] >= ag["committed_monthly_tons"]
            else "UNMET")


# ---------------------------------------------------------------------------
# sustainability credits
# ---------------------------------------------------------------------------

def recompute_generator(gen_id):
    gen = db.generators.get(gen_id)
    if gen is None:
        return
    accr = sum((e["credits"] for e in db.credit_entries.values()
                if e["generator_id"] == gen_id and e["entry_type"] == "ACCRUAL"), D0)
    rev = sum((e["credits"] for e in db.credit_entries.values()
               if e["generator_id"] == gen_id and e["entry_type"] == "REVERSAL"), D0)
    total = rhu(accr - rev, 2)
    gen["total_credits"] = total
    if total >= GOLD_THRESHOLD:
        gen["credit_tier"] = "GOLD"
    elif total >= SILVER_THRESHOLD:
        gen["credit_tier"] = "SILVER"
    else:
        gen["credit_tier"] = "STANDARD"
    touch(gen)


# ---------------------------------------------------------------------------
# eligibility helpers
# ---------------------------------------------------------------------------

def stream_has_verified_characterization(stream_id):
    return any(c["stream_id"] == stream_id and c["status"] == "VERIFIED"
               for c in db.characterizations.values())


def eligibility_window_overlaps(stream_id, state_code, exclude_id, v_from, v_until):
    """Half-open overlap among {SUBMITTED, APPROVED, SUSPENDED} peers."""
    for d in db.determinations.values():
        if d["stream_id"] != stream_id or d["state_code"] != state_code:
            continue
        lazy_expire_determination(d)
        if d["id"] == exclude_id:
            continue
        if d["status"] not in ("SUBMITTED", "APPROVED", "SUSPENDED"):
            continue
        if d["valid_from"] < v_until and v_from < d["valid_until"]:
            return True
    return False
