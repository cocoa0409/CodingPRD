"""In-memory data store, logical clock, constants, and computation helpers."""
import uuid
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculations)
# ---------------------------------------------------------------------------
ROLES = {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"}

STORAGE_BASE_RATE_CENTS = {"SMALL": 2000, "MEDIUM": 3500, "LARGE": 6000}
CLIMATE_MULTIPLIER = {"RED": "1.00", "WHITE": "1.15", "SPARKLING": "1.30"}
FULL_OCCUPANCY_SURCHARGE = "0.10"
MIN_MONTHLY_FEE_CENTS = 2500
MAX_MONTHLY_FEE_CENTS = 9000

INSURANCE_BASE_RATE = {"DOCUMENTED": "0.015", "UNVERIFIED": "0.025", "DISPUTED": "0.040"}
COVERAGE_TIER_FACTOR = {"BASIC": "0.5", "FULL": "1.0"}

REPLACEMENT_UPLIFT = "1.20"

COMMISSION_TIER_1_CENTS = 5000000
COMMISSION_TIER_2_CENTS = 20000000
PLATFORM_FEE_PCT = "0.03"

WALLET_FLOOR_CENTS = -100000
MAINTENANCE_BUFFER_MINUTES = 120

TEMP_MIN_C = 10.0
TEMP_MAX_C = 16.0
HUMID_MIN_PCT = 60.0
HUMID_MAX_PCT = 80.0

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
members = {}
lockers = {}
bottles = {}
appraisals = {}
policies = {}
movement_requests = {}
delivery_orders = {}
consignments = {}
waitlist_entries = {}
maintenance_windows = {}
ledger_entries = {}
climate_readings = {}

logical_clock = DEFAULT_CLOCK

_seq_counter = 0
_last_ms = 0
_lock = threading.Lock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def _fmt(dt):
    # ISO 8601 UTC with milliseconds and trailing Z
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Strictly monotonic wall-clock timestamp (unique per call)."""
    global _last_ms
    with _lock:
        ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if ms <= _last_ms:
            ms = _last_ms + 1
        _last_ms = ms
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return _fmt(dt)


def meta_timestamp():
    return _fmt(datetime.now(timezone.utc))


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def clock_iso():
    return _fmt(logical_clock)


def set_clock(dt):
    global logical_clock
    logical_clock = dt


def parse_iso(s):
    """Parse an ISO 8601 string into an aware datetime (UTC)."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value):
    """Round half-up to integer cents. Accepts Decimal/int/float/str."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def stamp_new(row):
    ts = now_iso()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def stamp_event(row):
    row["created_at"] = now_iso()
    row["_seq"] = next_seq()
    return row


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Derived quantity computations
# ---------------------------------------------------------------------------
def occupied_bottles(locker_id):
    return sum(1 for b in bottles.values()
               if b["locker_id"] == locker_id and b["status"] == "STORED")


def reserved_bottles(locker_id):
    return sum(mr["quantity"] for mr in movement_requests.values()
              if mr["locker_id"] == locker_id
              and mr["request_type"] == "INTAKE"
              and mr["status"] in ("REQUESTED", "APPROVED"))


def occupancy_status(occupied, capacity):
    if occupied == 0:
        return "VACANT"
    if occupied >= capacity:
        return "FULL"
    return "PARTIAL"


def storage_fee(size_tier, climate_zone, occ_status):
    base = Decimal(STORAGE_BASE_RATE_CENTS[size_tier])
    climate = Decimal(CLIMATE_MULTIPLIER[climate_zone])
    surcharge = Decimal(FULL_OCCUPANCY_SURCHARGE) if occ_status == "FULL" else Decimal("0")
    raw = base * climate * (Decimal("1") + surcharge)
    fee = rhu(raw)
    return min(MAX_MONTHLY_FEE_CENTS, max(MIN_MONTHLY_FEE_CENTS, fee))


def wallet_balance(member_id):
    total = 0
    for e in ledger_entries.values():
        if e["member_id"] == member_id:
            total += e["signed_amount_cents"]
    return total


def drink_window_status(b):
    y = logical_clock.year
    if y < b["drink_window_start_year"]:
        return "TOO_YOUNG"
    if y > b["drink_window_end_year"]:
        return "PAST_PEAK"
    return "IN_WINDOW"


def waitlist_position(entry):
    if entry["status"] != "WAITING":
        return None
    peers = [w for w in waitlist_entries.values()
             if w["status"] == "WAITING"
             and w["requested_size_tier"] == entry["requested_size_tier"]
             and w["requested_climate_zone"] == entry["requested_climate_zone"]]
    peers.sort(key=lambda w: (w["created_at"], w["_seq"]))
    for i, w in enumerate(peers, start=1):
        if w["id"] == entry["id"]:
            return i
    return None


# ---------------------------------------------------------------------------
# Serialization (computed fields recomputed live)
# ---------------------------------------------------------------------------
def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_member(m):
    d = _common(m)
    d.update({
        "full_name": m["full_name"],
        "email": m["email"],
        "membership_tier": m["membership_tier"],
        "status": m["status"],
        "wallet_balance_cents": wallet_balance(m["id"]),
    })
    return d


def ser_locker(l):
    occ = occupied_bottles(l["id"])
    res = reserved_bottles(l["id"])
    free = l["capacity_bottles"] - occ - res
    occ_status = occupancy_status(occ, l["capacity_bottles"])
    d = _common(l)
    d.update({
        "label": l["label"],
        "size_tier": l["size_tier"],
        "climate_zone": l["climate_zone"],
        "capacity_bottles": l["capacity_bottles"],
        "member_id": l["member_id"],
        "occupied_bottles": occ,
        "reserved_bottles": res,
        "free_bottles": free,
        "occupancy_status": occ_status,
        "climate_status": l["climate_status"],
        "monthly_fee_cents": storage_fee(l["size_tier"], l["climate_zone"], occ_status),
        "status": l["status"],
    })
    return d


def ser_bottle(b):
    d = _common(b)
    d.update({
        "member_id": b["member_id"],
        "locker_id": b["locker_id"],
        "wine_name": b["wine_name"],
        "vintage_year": b["vintage_year"],
        "varietal": b["varietal"],
        "format_ml": b["format_ml"],
        "provenance_status": b["provenance_status"],
        "drink_window_start_year": b["drink_window_start_year"],
        "drink_window_end_year": b["drink_window_end_year"],
        "drink_window_status": drink_window_status(b),
        "appraised_value_cents": b["appraised_value_cents"],
        "status": b["status"],
    })
    return d


def ser_appraisal(a):
    d = _common(a)
    d.update({
        "bottle_id": a["bottle_id"],
        "method": a["method"],
        "base_value_cents": a["base_value_cents"],
        "assessed_value_cents": a["assessed_value_cents"],
        "created_by_user_id": a["created_by_user_id"],
        "effective_date": a["effective_date"],
        "status": a["status"],
    })
    return d


def ser_policy(p):
    d = _common(p)
    d.update({
        "member_id": p["member_id"],
        "coverage_tier": p["coverage_tier"],
        "covered_bottle_ids": p["covered_bottle_ids"],
        "insured_value_cents": p["insured_value_cents"],
        "premium_cents": p["premium_cents"],
        "bound_at": p["bound_at"],
        "status": p["status"],
    })
    return d


def ser_movement(mr):
    d = _common(mr)
    d.update({
        "member_id": mr["member_id"],
        "locker_id": mr["locker_id"],
        "request_type": mr["request_type"],
        "quantity": mr["quantity"],
        "bottle_ids": mr["bottle_ids"],
        "status": mr["status"],
    })
    return d


def ser_delivery(do):
    d = _common(do)
    d.update({
        "member_id": do["member_id"],
        "bottle_ids": do["bottle_ids"],
        "courier_ref": do["courier_ref"],
        "slot_start": do["slot_start"],
        "slot_end": do["slot_end"],
        "status": do["status"],
    })
    return d


def ser_consignment(c):
    d = _common(c)
    d.update({
        "bottle_id": c["bottle_id"],
        "member_id": c["member_id"],
        "reserve_price_cents": c["reserve_price_cents"],
        "offer_price_cents": c["offer_price_cents"],
        "counter_price_cents": c["counter_price_cents"],
        "hammer_price_cents": c["hammer_price_cents"],
        "commission_pct": c["commission_pct"],
        "net_proceeds_cents": c["net_proceeds_cents"],
        "estimated_proceeds_cents": c["estimated_proceeds_cents"],
        "status": c["status"],
    })
    return d


def ser_waitlist(w):
    d = _common(w)
    d.update({
        "member_id": w["member_id"],
        "requested_size_tier": w["requested_size_tier"],
        "requested_climate_zone": w["requested_climate_zone"],
        "position": waitlist_position(w),
        "offered_locker_id": w["offered_locker_id"],
        "status": w["status"],
    })
    return d


def ser_maintenance(mw):
    d = _common(mw)
    d.update({
        "locker_id": mw["locker_id"],
        "window_start": mw["window_start"],
        "window_end": mw["window_end"],
        "reason": mw["reason"],
        "status": mw["status"],
    })
    return d


def ser_ledger(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "member_id": e["member_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "signed_amount_cents": e["signed_amount_cents"],
        "reason": e["reason"],
        "related_entity_type": e["related_entity_type"],
        "related_entity_id": e["related_entity_id"],
    }


def ser_climate(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "locker_id": r["locker_id"],
        "temperature_c": r["temperature_c"],
        "humidity_pct": r["humidity_pct"],
        "in_band": r["in_band"],
    }
