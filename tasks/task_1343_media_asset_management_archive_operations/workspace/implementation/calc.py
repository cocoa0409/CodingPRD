"""Calculation rules: rights posture, hold status, royalty accrual,
statement totals, storage cost, delivery fee, preservation priority,
retention eligibility. All money is integer cents, ROUND_HALF_UP at the
finest grain before any summation.
"""
import calendar
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from db import STORE, now

# --- constants -------------------------------------------------------------
MARKET_RATE = {"SMALL": 100, "MEDIUM": 250, "LARGE": 500}  # cents per 30s unit
MARKET_TIER_SMALL_MAX = 1_000_000     # market_size < 1e6 -> SMALL
MARKET_TIER_MEDIUM_MAX = 5_000_000    # < 5e6 -> MEDIUM; else LARGE
USAGE_MULTIPLIER = {
    "BROADCAST": Decimal("1.0"),
    "REBROADCAST": Decimal("0.5"),
    "STREAMING": Decimal("0.75"),
    "PROMO": Decimal("0.25"),
}
MIN_PER_EVENT_CENTS = 25
MIN_PAYOUT_CENTS = 1000
TIER_1_THRESHOLD_SECONDS = 3600
TIER_2_THRESHOLD_SECONDS = 36000
VOLUME_DISCOUNT = {
    "TIER_0": Decimal("0.0"),
    "TIER_1": Decimal("0.10"),
    "TIER_2": Decimal("0.20"),
}
TIER_RATE = {
    "ONLINE": Decimal("4"),
    "NEARLINE": Decimal("1.5"),
    "DEEP_ARCHIVE": Decimal("0.25"),
}  # cents per GB per day
TIER_BASE = {"ONLINE": 0, "NEARLINE": 500, "DEEP_ARCHIVE": 1500}
PER_GB_CENTS = 10
EXPEDITE_MULTIPLIER = 2
DECAY_RISK = {
    "BETACAM_SP": 90, "UMATIC": 85, "VHS": 70, "FILM_16MM": 95,
    "AUDIO_REEL": 80, "AUDIO_DAT": 75, "DIGITAL_FILE": 10, "PRORES_FILE": 5,
}
DEMAND_WEIGHT = 10
DEFAULT_RETENTION_YEARS = 7
MAX_PROXY_RETRIES = 3
MAX_MIGRATION_RETRIES = 2
MAX_QC_REWORKS = 2
STAGE_HOLD = timedelta(hours=72)
TURNAROUND = timedelta(minutes=30)
AUTO_ASSIGN_SLOT = timedelta(hours=4)


def rhu(x: Decimal) -> int:
    """Round half up to integer cents."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(v) -> Decimal:
    return Decimal(str(v))


# --- derived postures --------------------------------------------------------
def rights_posture(asset):
    """CLEARED | RESTRICTED | EXPIRED against the logical clock.

    Effective grants: ACTIVE, window_start <= now < window_end (end-exclusive).
    Empty -> EXPIRED; any effective grant with no restriction flags -> CLEARED;
    otherwise RESTRICTED.
    """
    t = now()
    effective = [
        g for g in STORE.grants.values()
        if g["asset_id"] == asset["id"]
        and g["status"] == "ACTIVE"
        and g["window_start"] <= t < g["window_end"]
    ]
    if not effective:
        return "EXPIRED"
    if any(len(g["restriction_flags"]) == 0 for g in effective):
        return "CLEARED"
    return "RESTRICTED"


def effective_grants(asset):
    t = now()
    return [
        g for g in STORE.grants.values()
        if g["asset_id"] == asset["id"]
        and g["status"] == "ACTIVE"
        and g["window_start"] <= t < g["window_end"]
    ]


def hold_status(asset):
    """HELD iff any ACTIVE LegalHold exists for the asset, else CLEAR."""
    for h in STORE.holds.values():
        if h["asset_id"] == asset["id"] and h["status"] == "ACTIVE":
            return "HELD"
    return "CLEAR"


def purpose_allowed(purpose, posture):
    """BROADCAST requires CLEARED; INTERNAL_REVIEW/EXHIBITION allow CLEARED or
    RESTRICTED; EXPIRED rejects every purpose."""
    if posture == "EXPIRED":
        return False
    if purpose == "BROADCAST":
        return posture == "CLEARED"
    return posture in ("CLEARED", "RESTRICTED")


# --- royalty accrual ---------------------------------------------------------
def market_tier(market_size):
    if market_size < MARKET_TIER_SMALL_MAX:
        return "SMALL"
    if market_size < MARKET_TIER_MEDIUM_MAX:
        return "MEDIUM"
    return "LARGE"


def event_raw_accrual(event) -> Decimal:
    """units * market rate * usage multiplier, before rounding/floor."""
    units = (event["duration_seconds_used"] + 29) // 30  # ceil 30-second units
    base = MARKET_RATE[market_tier(event["market_size"])]
    return Decimal(units * base) * USAGE_MULTIPLIER[event["usage_type"]]


def accrual_provisional(event) -> int:
    return max(MIN_PER_EVENT_CENTS, rhu(event_raw_accrual(event)))


def accrual_final(event, volume_tier) -> int:
    raw = event_raw_accrual(event) * (Decimal("1") - VOLUME_DISCOUNT[volume_tier])
    return max(MIN_PER_EVENT_CENTS, rhu(raw))


def volume_tier_for(total_seconds):
    if total_seconds >= TIER_2_THRESHOLD_SECONDS:
        return "TIER_2"
    if total_seconds >= TIER_1_THRESHOLD_SECONDS:
        return "TIER_1"
    return "TIER_0"


# --- storage cost --------------------------------------------------------------
def _month_start(t):
    return t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def storage_cost(asset):
    """Return (projected_cost_cents, actual_cost_cents) for the current UTC
    calendar month of the logical clock."""
    t = now()
    size = dec(asset["size_gb"])
    days_in_month = calendar.monthrange(t.year, t.month)[1]
    days_remaining = days_in_month - t.day + 1  # today inclusive
    projected = rhu(size * TIER_RATE[asset["storage_tier"]] * Decimal(days_remaining))

    # ACTUAL: replay COMPLETED migrations in created_at order, building
    # tier-residency intervals intersected with [month_start, now).
    month_start = _month_start(t)
    open_time = max(asset["created_at"], month_start)
    completed = [
        j for j in STORE.jobs.values()
        if j["asset_id"] == asset["id"] and j["status"] == "COMPLETED"
        and j.get("_completed_at") is not None
    ]
    completed.sort(key=lambda j: (j["created_at"], j["_seq"]))

    tier = "ONLINE"
    for j in completed:
        if j["_completed_at"] <= open_time:
            tier = j["target_tier"]

    actual = 0
    cursor = open_time
    for j in completed:
        ct = j["_completed_at"]
        if ct <= open_time:
            continue
        if ct >= t:
            continue
        if ct > cursor:
            secs = Decimal(str((ct - cursor).total_seconds()))
            hours = secs / Decimal(3600)
            actual += rhu(size * TIER_RATE[tier] * hours / Decimal(24))
        cursor = ct
        tier = j["target_tier"]
    if t > cursor:
        secs = Decimal(str((t - cursor).total_seconds()))
        hours = secs / Decimal(3600)
        actual += rhu(size * TIER_RATE[tier] * hours / Decimal(24))

    return projected, actual


# --- delivery fee --------------------------------------------------------------
def delivery_fee_cents(asset, delivery_tier):
    whole_gb = int(dec(asset["size_gb"]).to_integral_value(rounding=ROUND_CEILING))
    fee = TIER_BASE[asset["storage_tier"]] + whole_gb * PER_GB_CENTS
    if delivery_tier == "EXPEDITE":
        fee *= EXPEDITE_MULTIPLIER
    return fee


# --- preservation priority -------------------------------------------------------
def priority_score(ticket):
    """decay_risk(format) * age_years + delivered_retrievals_365d * 10."""
    asset = STORE.assets.get(ticket["asset_id"])
    if asset is None:
        return 0
    t = now()
    age_days = math.floor((t - asset["created_at"]).total_seconds() / 86400)
    age_years = age_days // 365
    window_start = t - timedelta(days=365)
    delivered = 0
    for r in STORE.requests.values():
        if (
            r["asset_id"] == asset["id"]
            and r["status"] == "DELIVERED"
            and r["delivered_at"] is not None
            and window_start < r["delivered_at"] <= t
        ):
            delivered += 1
    return DECAY_RISK[asset["format_class"]] * age_years + delivered * DEMAND_WEIGHT


# --- retention ---------------------------------------------------------------------
def retention_years_for(asset):
    for p in STORE.policies.values():
        if p["media_type"] == asset["media_type"]:
            return p["min_retention_years"]
    return DEFAULT_RETENTION_YEARS


def retention_eligible(asset):
    """now >= asset.created_at + years * 365 days (inclusive boundary)."""
    years = retention_years_for(asset)
    eligible_at = asset["created_at"] + timedelta(days=years * 365)
    return now() >= eligible_at
