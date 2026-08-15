"""Business logic: logical-clock tick, hazard recompute, strike window,
permit take reconciliation, closure conflict, trends, training compliance."""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from util import now, touch, parse_date
from constants import (LEVEL_RANK, WINDOW_DAYS, CLOSURE_BUFFER_MINUTES,
                       EXPIRING_SOON_DAYS)


# ---------------------------------------------------------------- strike window
def window_counts(airport_id, ref, inclusive=True, upper_bound=False):
    """rolling_strike_window (SCAFFOLD §1.3): CONFIRMED strikes at airport with
    strike_at >= ref - 365d (inclusive) — prospective variant uses > (exclusive)
    and is bounded above by as_of."""
    threshold = ref - timedelta(days=WINDOW_DAYS)
    total = 0
    high = 0
    for s in store.strike_reports.values():
        if s["airport_id"] != airport_id or s["status"] != "CONFIRMED":
            continue
        sa = s["strike_at"]
        if inclusive:
            in_window = sa >= threshold
        else:
            in_window = sa > threshold
        if upper_bound and sa > ref:
            in_window = False
        if not in_window:
            continue
        total += 1
        if s["damage_class"] in ("SUBSTANTIAL", "DESTROYED"):
            high += 1
    return total, high


# ---------------------------------------------------------------- hazard level
def _mitigation_airport_id(m):
    a = store.habitat_assessments.get(m["habitat_assessment_id"])
    return a["airport_id"] if a else None


def compute_level(airport_id, strikes_total, strikes_high, ref_date):
    """airport_hazard_level (SCAFFOLD §1.3) bottom-up: strikes -> advisory bump
    -> overdue-mitigation bump -> clamp (implicit, enum bounded)."""
    if strikes_high >= 2:
        level = "CRITICAL"
    elif strikes_high == 1:
        level = "HIGH"
    elif strikes_total >= 10:
        level = "HIGH"
    elif strikes_total >= 5:
        level = "ELEVATED"
    else:
        level = "LOW"
    # bump from ACTIVE advisories on this airport
    for adv in store.operational_advisories.values():
        if adv["airport_id"] == airport_id and adv["status"] == "ACTIVE":
            if LEVEL_RANK[adv["hazard_level"]] > LEVEL_RANK[level]:
                level = adv["hazard_level"]
    # bump from overdue mitigations
    overdue = any(
        m["status"] in ("IN_PROGRESS", "VERIFIED")
        and _mitigation_airport_id(m) == airport_id
        and parse_date(m["target_completion_date"]) < ref_date
        for m in store.mitigation_actions.values()
    )
    if overdue and level == "LOW":
        level = "ELEVATED"
    return level


def recompute_airport(airport):
    """Authoritative variant: recompute window counts + hazard level, persist,
    bump airport version once per trigger event."""
    ts = now()
    cnt, high = window_counts(airport["id"], ts)
    airport["strikes_trailing_12m"] = cnt
    airport["strikes_trailing_12m_high_risk"] = high
    airport["current_hazard_level"] = compute_level(airport["id"], cnt, high, ts.date())
    airport["hazard_level_updated_at"] = ts
    touch(airport)


def hazard_is_critical(airport_id):
    ap = store.airports.get(airport_id)
    return bool(ap and ap["current_hazard_level"] == "CRITICAL")


# ---------------------------------------------------------------- permit take
def recompute_permit_take(permit):
    """permit_take_reconciliation authoritative variant: sum animals_taken_lethal
    over CLOSED dispersals referencing this permit; persist; EXHAUSTED check."""
    total = sum(
        d["animals_taken_lethal"]
        for d in store.dispersal_activities.values()
        if d.get("take_permit_id") == permit["id"] and d["status"] == "CLOSED"
    )
    permit["take_consumed"] = total
    touch(permit)
    if permit["status"] == "ACTIVE" and total >= permit["authorized_take_total"]:
        permit["status"] = "EXHAUSTED"
        touch(permit)


def projected_take(permit_id):
    """Provisional variant: CLOSED + REVIEWED dispersals."""
    return sum(
        d["animals_taken_lethal"]
        for d in store.dispersal_activities.values()
        if d.get("take_permit_id") == permit_id and d["status"] in ("CLOSED", "REVIEWED")
    )


# ---------------------------------------------------------------- closures
def closure_conflict(airport_id, runway, start, end):
    """closure_window_overlap: conflict iff a.start < buffered_b_end AND b.start < a.end
    against AUTHORIZED/ACTIVE closures on the same runway; buffer = +15 min on the
    existing closure's end, half-open semantics (adjacency does not conflict)."""
    buf = timedelta(minutes=CLOSURE_BUFFER_MINUTES)
    for c in store.runway_closures.values():
        if c["airport_id"] != airport_id or c["runway_designator"] != runway:
            continue
        if c["status"] not in ("AUTHORIZED", "ACTIVE"):
            continue
        if start < (c["closure_end"] + buf) and c["closure_start"] < end:
            return True
    return False


# ---------------------------------------------------------------- system tick
def tick():
    """Evaluate every system-event transition against the logical clock.
    Runs before each request and after every clock set; idempotent."""
    ts = now()
    today = ts.date()

    # TrainingRecord: VALID/EXPIRING_SOON -> EXPIRED past expires_at;
    #                 VALID -> EXPIRING_SOON within 30 days of expiry.
    for tr in store.training_records.values():
        if tr["status"] not in ("VALID", "EXPIRING_SOON"):
            continue
        exp = parse_date(tr["expires_at"])
        if today > exp:
            tr["status"] = "EXPIRED"
            touch(tr)
        elif tr["status"] == "VALID" and today >= exp - timedelta(days=EXPIRING_SOON_DAYS):
            tr["status"] = "EXPIRING_SOON"
            touch(tr)

    # TakePermit: ISSUED -> ACTIVE at valid_from; ISSUED/ACTIVE -> EXPIRED past valid_to.
    for p in store.take_permits.values():
        vf = parse_date(p["valid_from"])
        vt = parse_date(p["valid_to"])
        if p["status"] == "ISSUED":
            if today > vt:
                p["status"] = "EXPIRED"
                touch(p)
            elif today >= vf:
                p["status"] = "ACTIVE"
                touch(p)
        elif p["status"] == "ACTIVE":
            if today > vt:
                p["status"] = "EXPIRED"
                touch(p)

    # OperationalAdvisory: ACTIVE -> EXPIRED past effective_to; recompute hazard.
    for a in store.operational_advisories.values():
        if a["status"] == "ACTIVE" and ts > a["effective_to"]:
            a["status"] = "EXPIRED"
            touch(a)
            ap = store.airports.get(a["airport_id"])
            if ap:
                recompute_airport(ap)

    # RunwayClosure: AUTHORIZED -> ACTIVE at closure_start.
    for c in store.runway_closures.values():
        if c["status"] == "AUTHORIZED" and ts >= c["closure_start"]:
            c["status"] = "ACTIVE"
            touch(c)

    # rolling window rollover: refresh airports whose counts changed.
    for ap in store.airports.values():
        cnt, high = window_counts(ap["id"], ts)
        if cnt != ap["strikes_trailing_12m"] or high != ap["strikes_trailing_12m_high_risk"]:
            recompute_airport(ap)


# ---------------------------------------------------------------- trends
def season_of(dt):
    m = dt.month
    if m in (12, 1, 2):
        return "WINTER"
    if m in (3, 4, 5):
        return "SPRING"
    if m in (6, 7, 8):
        return "SUMMER"
    return "AUTUMN"


SEASON_ORDER = {"WINTER": 0, "SPRING": 1, "SUMMER": 2, "AUTUMN": 3}


def species_seasonal_trend(airport_id, lookback_days):
    ts = now()
    window_start = ts - timedelta(days=lookback_days)
    strikes = [s for s in store.strike_reports.values()
               if s["airport_id"] == airport_id and s["status"] == "CONFIRMED"
               and window_start <= s["strike_at"] <= ts]
    dispersals = [d for d in store.dispersal_activities.values()
                  if d["airport_id"] == airport_id and d["status"] == "CLOSED"]
    agg = {}
    for s in strikes:
        key = (s["species_id"], season_of(s["strike_at"]))
        row = agg.setdefault(key, {"strike_count": 0, "dispersal_count": 0, "lethal_take_total": 0})
        row["strike_count"] += 1
    for d in dispersals:
        key = (d["species_id"], season_of(d["performed_at"]))
        row = agg.setdefault(key, {"strike_count": 0, "dispersal_count": 0, "lethal_take_total": 0})
        row["dispersal_count"] += 1
        row["lethal_take_total"] += d["animals_taken_lethal"]
    rows = []
    for (species_id, season), counts in agg.items():
        if counts["strike_count"] == 0 and counts["dispersal_count"] == 0:
            continue
        sp = store.species.get(species_id)
        rows.append({
            "species_id": species_id,
            "common_name": sp["common_name"] if sp else None,
            "season": season,
            "strike_count": counts["strike_count"],
            "dispersal_count": counts["dispersal_count"],
            "lethal_take_total": counts["lethal_take_total"],
        })
    # Ranking: strike_count DESC, ties by species.common_name ASC (created_at NOT used).
    rows.sort(key=lambda r: (-r["strike_count"], r["common_name"] or "", SEASON_ORDER[r["season"]]))
    return rows


def training_compliance(airport_id):
    """training_currency_score: VALID=1.0, EXPIRING_SOON=0.5, EXPIRED/REVOKED=0.0;
    biologist score = sum / max(1, count); airport pct = round_half_up(100*mean, 2)."""
    bios = [b for b in store.biologists.values()
            if b["airport_id"] == airport_id and b.get("active", True)]
    bios.sort(key=lambda b: (b["created_at"], b["_seq"]))
    per = []
    total = 0.0
    for b in bios:
        records = [t for t in store.training_records.values() if t["biologist_id"] == b["id"]]
        contrib = 0.0
        for t in records:
            if t["status"] == "VALID":
                contrib += 1.0
            elif t["status"] == "EXPIRING_SOON":
                contrib += 0.5
        score = contrib / max(1, len(records))
        total += score
        per.append({
            "biologist_id": b["id"],
            "full_name": b["full_name"],
            "training_record_count": len(records),
            "score": score,
        })
    mean = total / max(1, len(bios))
    pct = float(Decimal(str(100.0 * mean)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return {"airport_compliance_pct": pct, "per_biologist": per}
