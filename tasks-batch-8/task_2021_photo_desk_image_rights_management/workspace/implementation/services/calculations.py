"""Business-logic calculations per PRD section 3 and SCAFFOLD section 1.3.

All monetary arithmetic uses Decimal with ROUND_HALF_UP. Integer cents in,
integer cents out.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import (
    logical_now, parse_iso, iso_now_str, now_iso,
    photographers, assignments, images, licenses, usage_runs, claims,
    story_requests,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCOPE_MULTIPLIER = {"PRINT": Decimal("1.0"), "DIGITAL": Decimal("1.2"), "SOCIAL": Decimal("0.8"), "SYNDICATION": Decimal("1.5")}
TERRITORY_MULTIPLIER = {"DOMESTIC": Decimal("1.0"), "INTERNATIONAL": Decimal("1.3"), "GLOBAL": Decimal("1.6")}
EXCLUSIVITY_MULTIPLIER = Decimal("2.0")
REUSE_DISCOUNT_PCT = Decimal("0.40")

CHANNEL_ROYALTY_MULTIPLIER = {"PRINT": Decimal("1.0"), "DIGITAL": Decimal("1.25"), "SOCIAL": Decimal("0.5"), "SYNDICATION": Decimal("2.0")}
TIER_THRESHOLD = 10
TIER_MULTIPLIER_HIGH = Decimal("1.5")

PHOTOGRAPHER_LIABILITY_PCT = Decimal("0.30")
KILL_FEE_PCT = Decimal("0.5")


def _round_half_up(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# license_fee_quote
# ---------------------------------------------------------------------------

def compute_license_fee(image: dict, usage_scope: str, territory: str, exclusive: bool) -> tuple:
    """Returns (fee_cents, pricing_variant)."""
    base = Decimal(image["base_license_fee_cents"])
    scoped = base * SCOPE_MULTIPLIER[usage_scope]
    terr = scoped * TERRITORY_MULTIPLIER[territory]
    pre_discount = terr * (EXCLUSIVITY_MULTIPLIER if exclusive else Decimal("1.0"))
    pricing_variant = "REUSE" if image["times_used"] > 0 else "FIRST_USE"
    if pricing_variant == "REUSE":
        fee = _round_half_up(pre_discount * (Decimal("1") - REUSE_DISCOUNT_PCT))
    else:
        fee = _round_half_up(pre_discount)
    return fee, pricing_variant


# ---------------------------------------------------------------------------
# usage_ordinal_and_tier
# ---------------------------------------------------------------------------

def compute_usage_royalty(image: dict, channel: str) -> int:
    """Compute per-line royalty for a new usage run. Does NOT mutate."""
    if image["photographer_id"] is None:
        return 0
    photog = photographers.get(image["photographer_id"])
    if photog is None:
        return 0
    ordinal = image["times_used"] + 1
    tier = TIER_MULTIPLIER_HIGH if ordinal >= TIER_THRESHOLD else Decimal("1.0")
    rate = Decimal(photog["royalty_rate_per_use_cents"])
    ch_mult = CHANNEL_ROYALTY_MULTIPLIER[channel]
    return _round_half_up(rate * ch_mult * tier)


# ---------------------------------------------------------------------------
# rights_reversion_date
# ---------------------------------------------------------------------------

def compute_rights_reversion(first_published_at_iso: str, photographer: dict) -> str:
    """first_published_at + photographer.rights_reversion_months calendar months.

    Returns ISO string.
    """
    dt = parse_iso(first_published_at_iso)
    months = photographer["rights_reversion_months"]
    # Add calendar months
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    # Handle day overflow (e.g., Jan 31 + 1 month -> Feb 28/29)
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)
    result = dt.replace(year=year, month=month, day=day)
    return iso_now_str(result)


# ---------------------------------------------------------------------------
# assignment_kill_fee
# ---------------------------------------------------------------------------

def compute_kill_fee(photographer: dict, assignment: dict) -> int:
    """round_half_up(day_rate_cents * day_count * 0.5)"""
    rate = Decimal(photographer["day_rate_cents"])
    days = Decimal(assignment["day_count"])
    return _round_half_up(rate * days * KILL_FEE_PCT)


# ---------------------------------------------------------------------------
# settlement_split
# ---------------------------------------------------------------------------

def compute_settlement_split(settlement_amount_cents: int, image: dict) -> int:
    """Returns photographer_clawback_cents."""
    if image["source_type"] == "ASSIGNMENT":
        return _round_half_up(Decimal(settlement_amount_cents) * PHOTOGRAPHER_LIABILITY_PCT)
    return 0


# ---------------------------------------------------------------------------
# photographer_payout
# ---------------------------------------------------------------------------

def compute_payout(photographer: dict, period_start_iso: str, period_end_iso: str) -> dict:
    """Compute guarantee, royalty, clawback, method, total.

    Returns dict with keys: method, guarantee_amount_cents, royalty_amount_cents,
    clawback_cents, total_cents.
    """
    ps = parse_iso(period_start_iso)
    pe = parse_iso(period_end_iso)
    pid = photographer["id"]

    # Guarantee: day-rate for ACCEPTED assignments accepted in period
    # + per-image fee for images cleared by those in-period acceptances
    guarantee = 0
    accepted_in_period = []
    for a in assignments.values():
        if a["photographer_id"] != pid:
            continue
        if a["status"] != "ACCEPTED":
            continue
        if a["accepted_at"] is None:
            continue
        aa = parse_iso(a["accepted_at"])
        if aa is not None and ps <= aa < pe:
            accepted_in_period.append(a)
            guarantee += photographer["day_rate_cents"] * a["day_count"]

    # Per-image fees: one per image cleared by in-period acceptances
    for a in accepted_in_period:
        for img in images.values():
            if img.get("assignment_id") == a["id"] and img["status"] in ("CLEARED", "PUBLISHED", "ARCHIVED"):
                # This image was cleared by this assignment's acceptance
                # (all INGESTED images on the assignment clear at accept time)
                guarantee += photographer["per_image_fee_cents"]

    # Royalty: sum of per-line royalty_cents for runs published in period
    royalty = 0
    for ur in usage_runs.values():
        img = images.get(ur["image_id"])
        if img is None or img.get("photographer_id") != pid:
            continue
        pa = parse_iso(ur["published_at"])
        if pa is not None and ps <= pa < pe:
            royalty += ur["royalty_cents"]

    # Clawback: UPHELD-resolved claims resolved in period
    clawback = 0
    for c in claims.values():
        if c["status"] != "RESOLVED" or c["resolution_outcome"] != "UPHELD":
            continue
        img = images.get(c["image_id"])
        if img is None or img.get("photographer_id") != pid:
            continue
        ra = parse_iso(c["resolved_at"])
        if ra is not None and ps <= ra < pe:
            clawback += c["photographer_clawback_cents"]

    method = "GUARANTEE" if photographer["photographer_type"] == "STAFF" else "ROYALTY"
    chosen = guarantee if method == "GUARANTEE" else royalty
    total = max(0, chosen - clawback)

    return {
        "method": method,
        "guarantee_amount_cents": guarantee,
        "royalty_amount_cents": royalty,
        "clawback_cents": clawback,
        "total_cents": total,
    }


# ---------------------------------------------------------------------------
# Lazy expiry processing
# ---------------------------------------------------------------------------

def process_license_lazy_expiry(lic: dict) -> bool:
    """Check whether a stored-ACTIVE license has lazily expired.

    If so, mutate the stored record to EXPIRED, release the story budget,
    and return True. Otherwise return False.
    """
    if lic["status"] != "ACTIVE":
        return False
    vt = parse_iso(lic["valid_to"])
    if vt is None:
        return False
    if logical_now() < vt:
        return False
    # Lazy expiry fires
    now = now_iso()
    lic["status"] = "EXPIRED"
    lic["updated_at"] = now
    lic["version"] += 1
    # Release story budget
    if lic.get("story_request_id"):
        sr = story_requests.get(lic["story_request_id"])
        if sr:
            sr["committed_cents"] -= lic["fee_cents"]
            sr["updated_at"] = now
            sr["version"] += 1
    return True


def process_release_lazy_expiry(rel: dict) -> bool:
    """Check whether a stored-ACTIVE release has lazily expired.

    If so, mutate the stored record to EXPIRED and return True.
    """
    if rel["status"] != "ACTIVE":
        return False
    if rel.get("expires_at") is None:
        return False
    ea = parse_iso(rel["expires_at"])
    if ea is None:
        return False
    if logical_now() < ea:
        return False
    rel["status"] = "EXPIRED"
    rel["updated_at"] = now_iso()
    rel["version"] += 1
    return True
