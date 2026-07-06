"""Cross-cutting business logic: safety posture, trust score, feed score,
ad impression charge, and clock-driven auto-transitions."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from clock import CLOCK, iso_format, parse_iso
from db import DB, bump, insert_order_of


SUSPENSION_FLOOR = 60
MOD_UPHOLD_PENALTY = 25
REJECTION_PENALTY = 10
FLAG_HIDE_THRESHOLD = 3
RESERVATION_HOURS = 48
EMERGENCY_INCIDENT_COUNT = 3
ELEVATED_INCIDENT_COUNT = 1
ELEVATED_AGE_SECONDS = 3600
RECENCY_WEIGHT = Decimal("0.5")
CATEGORY_WEIGHT = Decimal("0.4")
RECENCY_HALF_LIFE_HOURS = Decimal("72")

CATEGORY_MAP = {
    "SAFETY": Decimal("1.5"),
    "ANNOUNCEMENT": Decimal("1.3"),
    "LOST_FOUND": Decimal("1.2"),
    "RECOMMENDATION": Decimal("1.0"),
    "QUESTION": Decimal("0.9"),
    "FREE_ITEM": Decimal("0.9"),
    "GENERAL": Decimal("0.8"),
}


# --------------------------------------------------------------------------
# Neighborhood safety posture
# --------------------------------------------------------------------------

def _neighborhood_incidents(neighborhood_id: str) -> list[dict]:
    return [i for i in DB.incidents.values() if i["neighborhood_id"] == neighborhood_id]


def compute_unresolved_critical_count(neighborhood_id: str) -> int:
    return sum(
        1
        for i in _neighborhood_incidents(neighborhood_id)
        if i["severity"] == "CRITICAL" and i["status"] in ("OPEN", "ACKNOWLEDGED")
    )


def compute_verified_resident_count(neighborhood_id: str) -> int:
    return sum(
        1
        for m in DB.resident_memberships.values()
        if m["neighborhood_id"] == neighborhood_id and m["status"] == "VERIFIED"
    )


def compute_safety_posture(neighborhood_id: str) -> str:
    unresolved = compute_unresolved_critical_count(neighborhood_id)
    now = CLOCK.now()
    open_criticals = [
        i for i in _neighborhood_incidents(neighborhood_id)
        if i["severity"] == "CRITICAL" and i["status"] == "OPEN"
    ]
    oldest_open_age_seconds = 0
    if open_criticals:
        earliest_occ = min(parse_iso(i["occurred_at"]) for i in open_criticals)
        oldest_open_age_seconds = (now - earliest_occ).total_seconds()

    if unresolved >= EMERGENCY_INCIDENT_COUNT:
        return "EMERGENCY"
    if unresolved >= ELEVATED_INCIDENT_COUNT:
        return "ELEVATED"
    if oldest_open_age_seconds >= ELEVATED_AGE_SECONDS:
        return "ELEVATED"
    return "OPEN"


def refresh_neighborhood_derived(neighborhood_id: str) -> None:
    """Recompute cached counters and safety posture; bump neighborhood on any change."""
    n = DB.neighborhoods.get(neighborhood_id)
    if n is None:
        return
    new_unresolved = compute_unresolved_critical_count(neighborhood_id)
    new_verified = compute_verified_resident_count(neighborhood_id)
    new_posture = compute_safety_posture(neighborhood_id)
    changed = (
        n.get("unresolved_critical_count") != new_unresolved
        or n.get("verified_resident_count") != new_verified
        or n.get("safety_posture") != new_posture
    )
    prev_posture = n.get("safety_posture")
    n["unresolved_critical_count"] = new_unresolved
    n["verified_resident_count"] = new_verified
    n["safety_posture"] = new_posture
    if changed:
        bump(n)
    # If the posture transitioned, the derived post feed scores must be recomputed
    # for every affected post.
    if prev_posture != new_posture:
        for p in DB.posts.values():
            if p["neighborhood_id"] == neighborhood_id and p["state"] in ("PUBLISHED", "FLAGGED"):
                recompute_post_score(p, bump_row=True)


# --------------------------------------------------------------------------
# Post feed score
# --------------------------------------------------------------------------

def _round_half_up_2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_post_feed_score(post: dict) -> float:
    neighborhood = DB.neighborhoods.get(post["neighborhood_id"])
    posture = neighborhood.get("safety_posture", "OPEN") if neighborhood else "OPEN"

    created_at = parse_iso(post["created_at"])
    now = CLOCK.now()
    age_hours = Decimal(str((now - created_at).total_seconds())) / Decimal("3600")
    raw_recency = Decimal("1.0") - (age_hours / RECENCY_HALF_LIFE_HOURS)
    if raw_recency < 0:
        recency = Decimal("0.0")
    else:
        recency = raw_recency
    category_weight = CATEGORY_MAP.get(post["category"], Decimal("0.8"))
    if posture == "EMERGENCY" and post["category"] == "SAFETY":
        posture_mult = Decimal("2.0")
    elif posture == "ELEVATED" and post["category"] == "SAFETY":
        posture_mult = Decimal("1.5")
    else:
        posture_mult = Decimal("1.0")
    flag_penalty = Decimal("-0.30") * Decimal(int(post.get("flag_count", 0)))
    raw = (
        RECENCY_WEIGHT * recency
        + CATEGORY_WEIGHT * category_weight
        + posture_mult
        + flag_penalty
    )
    return float(_round_half_up_2(raw))


def recompute_post_score(post: dict, *, bump_row: bool = True) -> None:
    new_score = compute_post_feed_score(post)
    if post.get("local_relevance_score") != new_score:
        post["local_relevance_score"] = new_score
        if bump_row:
            bump(post)


def recompute_post_flag_count(post_id: str) -> int:
    """Recompute a Post's flag_count against reports in {OPEN, UPHELD}."""
    return sum(
        1
        for f in DB.flag_reports.values()
        if f["target_type"] == "POST"
        and f["target_id"] == post_id
        and f["status"] in ("OPEN", "UPHELD")
    )


# --------------------------------------------------------------------------
# Resident trust score (recompute from scratch every time it changes)
# --------------------------------------------------------------------------

def _order_key(row: dict) -> tuple:
    # PRD §2.8: the row's `id` is a strictly tie-breaking ordering key that
    # "never on its own decides an observable outcome". We therefore tiebreak
    # on the monotonic insertion counter first (recovering causal server-side
    # order when two rows share `created_at`), and only then fall back to the
    # UUID lexical order — which will now never fire in practice because the
    # insertion counter is unique per row.
    return (row.get("created_at", ""), insert_order_of(row.get("id", "")),
            row.get("id", ""))


def _post_or_listing_author(target_type: str, target_id: str) -> str | None:
    if target_type == "POST":
        p = DB.posts.get(target_id)
        return p.get("author_resident_id") if p else None
    if target_type == "MARKETPLACE_LISTING":
        ml = DB.marketplace_listings.get(target_id)
        return ml.get("seller_resident_id") if ml else None
    return None


def _decision_target(decision: dict) -> tuple[str | None, str | None]:
    fr = DB.flag_reports.get(decision.get("flag_report_id", ""))
    if fr is None:
        return None, None
    return fr.get("target_type"), fr.get("target_id")


def compute_trust_score(resident_id: str) -> int:
    score = 100
    # Iterate the resident's mod decisions in chronological order
    resident_decisions: list[tuple[dict, str, str]] = []
    for d in DB.moderation_decisions.values():
        ttype, tid = _decision_target(d)
        if ttype is None:
            continue
        author = _post_or_listing_author(ttype, tid)
        if author == resident_id:
            resident_decisions.append((d, ttype, tid))
    resident_decisions.sort(key=lambda t: _order_key(t[0]))

    prior_upheld_by_target: dict[str, bool] = {}
    for d, ttype, tid in resident_decisions:
        decision = d["decision"]
        key = f"{ttype}:{tid}"
        if decision == "UPHOLD":
            score -= MOD_UPHOLD_PENALTY
            prior_upheld_by_target[key] = True
        elif decision == "REVERSE":
            if prior_upheld_by_target.get(key):
                score += MOD_UPHOLD_PENALTY
                prior_upheld_by_target[key] = False
        elif decision == "DISMISS":
            pass

    rejected = [
        v for v in DB.verification_requests.values()
        if v.get("resident_id") == resident_id and v.get("state") == "REJECTED"
    ]
    rejected.sort(key=_order_key)
    for _ in rejected:
        score -= REJECTION_PENALTY
    return max(0, score)


def refresh_resident_trust(resident_id: str) -> int:
    """Recompute trust; flip suspension; bump row if any field changed."""
    r = DB.residents.get(resident_id)
    if r is None:
        return 0
    new_score = compute_trust_score(resident_id)
    new_suspended = new_score < SUSPENSION_FLOOR
    changed = r.get("trust_score") != new_score or r.get("is_suspended") != new_suspended
    r["trust_score"] = new_score
    r["is_suspended"] = new_suspended
    if changed:
        bump(r)
    return new_score


# --------------------------------------------------------------------------
# Clock-driven auto-transitions
# --------------------------------------------------------------------------

def apply_time_gated_transitions() -> int:
    """Fire every time-gated auto-transition whose precondition now holds.
    Returns the count of transitions applied."""
    now = CLOCK.now()
    count = 0

    # VerificationRequest SUBMITTED -> EXPIRED
    for v in list(DB.verification_requests.values()):
        if v["state"] == "SUBMITTED":
            expires = parse_iso(v["expires_at"])
            if now >= expires:
                v["state"] = "EXPIRED"
                bump(v)
                r = DB.residents.get(v["resident_id"])
                if r is not None:
                    r["verification_status"] = "REJECTED"
                    bump(r)
                count += 1

    # MarketplaceListing RESERVED -> ACTIVE (reservation expired)
    for m in list(DB.marketplace_listings.values()):
        if m["state"] == "RESERVED" and m.get("reserved_until"):
            if now >= parse_iso(m["reserved_until"]):
                m["state"] = "ACTIVE"
                m["reserved_for_resident_id"] = None
                m["reserved_until"] = None
                bump(m)
                count += 1

    # CivicNotice SCHEDULED -> ACTIVE, ACTIVE -> EXPIRED
    for n in list(DB.civic_notices.values()):
        if n["state"] == "SCHEDULED":
            eff_from = parse_iso(n["effective_from"])
            eff_until = parse_iso(n["effective_until"])
            if now >= eff_until:
                # jump SCHEDULED -> ACTIVE -> EXPIRED (state history irrelevant here — end state EXPIRED)
                n["state"] = "EXPIRED"
                bump(n)
                count += 1
            elif now >= eff_from:
                n["state"] = "ACTIVE"
                bump(n)
                count += 1
        elif n["state"] == "ACTIVE":
            eff_until = parse_iso(n["effective_until"])
            if now >= eff_until:
                n["state"] = "EXPIRED"
                bump(n)
                count += 1

    # LocalAd RUNNING/PAUSED -> ENDED at end_at
    for ad in list(DB.local_ads.values()):
        if ad["state"] in ("RUNNING", "PAUSED"):
            if now >= parse_iso(ad["end_at"]):
                ad["state"] = "ENDED"
                bump(ad)
                count += 1

    # Event SCHEDULED -> COMPLETED at ends_at
    for e in list(DB.events.values()):
        if e["state"] == "SCHEDULED":
            if now >= parse_iso(e["ends_at"]):
                e["state"] = "COMPLETED"
                bump(e)
                count += 1

    # Recompute neighborhood safety posture (age-based transitions may now hold)
    for n in DB.neighborhoods.values():
        refresh_neighborhood_derived(n["id"])

    return count
