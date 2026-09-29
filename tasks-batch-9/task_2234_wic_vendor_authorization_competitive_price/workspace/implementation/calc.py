"""Calculation rules (PRD §3.2, §3.4, §3.5, §3.6, §3.7, §3.8, §3.9)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import clock
import config as C
from store import db, sort_key


# ------------------------------------------------------------------ rounding
def rhu(value, places=0):
    """Round half up to `places` decimals, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ------------------------------------------------- peer group assignment (§3.2)
def peer_group_candidates(vendor):
    volume = vendor["reported_monthly_redemption_cents"]
    candidates = []
    for pg in db.peer_groups.values():
        if pg["status"] != "ACTIVE":
            continue
        if pg["store_type"] != vendor["store_type"]:
            continue
        if pg["min_monthly_redemption_cents"] > volume:
            continue
        upper = pg["max_monthly_redemption_cents"]
        if upper is not None and volume > upper:
            continue
        candidates.append(pg)

    def band_width(pg):
        upper = pg["max_monthly_redemption_cents"]
        if upper is None:
            upper = C.UNBOUNDED_BAND_SENTINEL_CENTS
        return upper - pg["min_monthly_redemption_cents"]

    candidates.sort(
        key=lambda pg: (
            band_width(pg),
            pg["min_monthly_redemption_cents"],
            pg["created_at"],
            pg["_seq"],
        )
    )
    return candidates


# ------------------------------------------------- governing cycle selectors
def completeness_governing_cycle():
    """PRD §3.2: greatest submission_open_at at/below the clock, then greater created_at."""
    now = clock.now()
    candidates = [
        c
        for c in db.price_cycles.values()
        if c["status"] in C.CYCLE_STATUSES and c["submission_open_at"] <= now
    ]
    if not candidates:
        return None, []
    governing = max(
        candidates,
        key=lambda c: (c["submission_open_at"], c["created_at"], c["_seq"]),
    )
    return governing, candidates


def published_governing_cycle():
    """PRD §3.4/§3.7: greatest published_at at/below the clock, ties by earlier created_at."""
    now = clock.now()
    published = [
        c
        for c in db.price_cycles.values()
        if c["status"] == "PUBLISHED" and c["published_at"] is not None and c["published_at"] <= now
    ]
    if not published:
        return None
    best = None
    for cycle in published:
        if best is None:
            best = cycle
            continue
        if cycle["published_at"] > best["published_at"]:
            best = cycle
        elif cycle["published_at"] == best["published_at"] and sort_key(cycle) < sort_key(best):
            best = cycle
    return best


# --------------------------------------- price submission completeness (§3.2)
def price_submission_completeness(vendor, extra_required_items=()):
    governing, candidates = completeness_governing_cycle()
    if governing is None:
        return 0, True
    required_items = [
        it
        for it in db.food_items.values()
        if it["status"] == "ACTIVE" and it["required_for_authorization"] is True
    ]
    # PRD §3.1 hop 4: the recompute driven by a delisting turns completeness false
    # "when the delisted item had required_for_authorization set to true", so the
    # item being delisted still counts as required for that recompute.
    for extra in extra_required_items:
        if extra["required_for_authorization"] is True and all(
            it["id"] != extra["id"] for it in required_items
        ):
            required_items.append(extra)
    accepted = [
        s
        for s in db.price_submissions.values()
        if s["vendor_id"] == vendor["id"]
        and s["price_cycle_id"] == governing["id"]
        and s["status"] == "ACCEPTED"
    ]
    accepted_count = len(accepted)
    accepted_items = {s["food_item_id"] for s in accepted}
    complete = all(it["id"] in accepted_items for it in required_items)
    return accepted_count, complete


# ------------------------------------- maximum allowable reimbursement (§3.4)
def _candidate_prices(cycle, item, allowed_statuses, peer_group_id=None,
                      require_active_peer_group=False):
    rows = []
    for s in db.price_submissions.values():
        if s["price_cycle_id"] != cycle["id"] or s["food_item_id"] != item["id"]:
            continue
        if s["status"] not in allowed_statuses:
            continue
        vendor = db.vendors.get(s["vendor_id"])
        if vendor is None:
            continue
        if vendor["authorization_status"] not in ("IN_REVIEW", "AUTHORIZED", "REAUTH_PENDING"):
            continue
        if peer_group_id is not None and vendor["peer_group_id"] != peer_group_id:
            continue
        if require_active_peer_group:
            pg = db.peer_groups.get(vendor["peer_group_id"]) if vendor["peer_group_id"] else None
            if pg is None or pg["status"] != "ACTIVE":
                continue
        rows.append(s)
    rows.sort(key=lambda s: (s["shelf_price_cents"], s["created_at"], s["_seq"]))
    return [Decimal(s["shelf_price_cents"]) for s in rows]


def _base_price(prices, mar_method):
    n = len(prices)
    if mar_method == "PEER_MEDIAN":
        if n % 2 == 1:
            return prices[n // 2]
        return (prices[n // 2 - 1] + prices[n // 2]) / Decimal(2)
    if mar_method == "PEER_PERCENTILE_75":
        index = ceil_int(Decimal("0.75") * Decimal(n)) - 1
        if index < 0:
            index = 0
        if index > n - 1:
            index = n - 1
        return prices[index]
    # LOWEST_HALF_AVG
    k = ceil_int(Decimal(n) / Decimal(2))
    subset = prices[:k]
    return sum(subset, Decimal(0)) / Decimal(k)


def compute_ceiling_values(peer_group, item, cycle, allowed_statuses):
    """Return the derived ceiling values for one (peer group, item) pair, or None to skip."""
    peer_prices = _candidate_prices(cycle, item, allowed_statuses,
                                    peer_group_id=peer_group["id"])
    peer_n = len(peer_prices)
    if peer_n == 0:
        return None
    if peer_n >= peer_group["min_submissions_for_ceiling"]:
        basis = "PEER_GROUP"
        candidate = peer_prices
    else:
        basis = "STATEWIDE_FALLBACK"
        candidate = _candidate_prices(cycle, item, allowed_statuses,
                                      require_active_peer_group=True)
    base = _base_price(candidate, peer_group["mar_method"])
    allowance = dec(peer_group["competitive_allowance_pct"])
    uncapped = base * (Decimal(1) + allowance)
    cap = C.STATEWIDE_CAP_MULTIPLE * candidate[0]
    cap_binding = cap < uncapped
    mar_cents = rhu_int(cap if cap_binding else uncapped)
    return {
        "basis": basis,
        "base_cents": base,
        "cap_cents": cap,
        "cap_binding": cap_binding,
        "mar_cents": mar_cents,
        "peer_submission_count": peer_n,
        "contributing_submission_count": len(candidate),
    }


# ------------------------------------------ minimum stock verification (§3.6)
def stock_required_categories():
    cats = [c for c in db.food_categories.values() if c["stock_required"] is True]
    cats.sort(key=lambda c: (c["code"], c["_seq"]))
    return cats


def verify_minimum_stock(visit, vendor):
    """Stamp required_units/verdict onto stock_findings; return (pct, any_missing, passing, total)."""
    required = stock_required_categories()
    multiplier = Decimal(1)
    pg = db.peer_groups.get(vendor["peer_group_id"]) if vendor["peer_group_id"] else None
    if pg is not None:
        multiplier = dec(pg["min_stock_multiplier"])

    findings = visit["stock_findings"]
    by_category = {}
    for entry in findings:
        by_category.setdefault(entry["food_category_id"], entry)

    passing = 0
    any_missing = False
    for cat in required:
        required_units = ceil_int(Decimal(cat["min_stock_units"]) * multiplier)
        entry = by_category.get(cat["id"])
        if entry is None:
            entry = {
                "food_category_id": cat["id"],
                "observed_units": 0,
                "observed_variety_count": 0,
                "required_units": required_units,
                "verdict": "MISSING",
            }
            findings.append(entry)
            by_category[cat["id"]] = entry
            any_missing = True
            continue
        entry["required_units"] = required_units
        if entry["observed_units"] < required_units:
            entry["verdict"] = "BELOW_UNITS"
        elif entry["observed_variety_count"] < cat["min_variety_count"]:
            entry["verdict"] = "BELOW_VARIETY"
        else:
            entry["verdict"] = "PASS"
            passing += 1

    total = len(required)
    if total == 0:
        pct = Decimal("100.0")
    else:
        pct = rhu(Decimal(100) * Decimal(passing) / Decimal(total), 1)
    return pct, any_missing, passing, total


def compliance_buy_overcharge(visit, vendor, buy_items):
    """PRD §3.6: sum of per-entry excess over the governing ACTIVE ceiling."""
    if not buy_items:
        return 0
    governing = published_governing_cycle()
    if governing is None:
        return 0
    total = 0
    for entry in buy_items:
        item = find_active_or_any_item_by_upc(entry.get("upc"))
        if item is None:
            continue
        ceiling = find_active_ceiling(vendor["peer_group_id"], item["id"], governing["id"])
        if ceiling is None:
            continue
        excess = entry.get("charged_unit_price_cents", 0) - ceiling["mar_cents"]
        if excess < 0:
            excess = 0
        total += excess * entry.get("quantity", 0)
    return total


def find_active_ceiling(peer_group_id, food_item_id, price_cycle_id):
    for ceiling in db.price_ceilings.values():
        if (
            ceiling["status"] == "ACTIVE"
            and ceiling["peer_group_id"] == peer_group_id
            and ceiling["food_item_id"] == food_item_id
            and ceiling["price_cycle_id"] == price_cycle_id
        ):
            return ceiling
    return None


def find_active_or_any_item_by_upc(upc):
    """UPC resolution: unique among ACTIVE items, falling back to a delisted match."""
    if not isinstance(upc, str):
        return None
    fallback = None
    for item in sorted(db.food_items.values(), key=sort_key):
        if item["upc"] != upc:
            continue
        if item["status"] == "ACTIVE":
            return item
        if fallback is None:
            fallback = item
    return fallback


# ------------------------------------------------ adjustment proration (§3.8)
def prorate_adjustment(claim, rate):
    lines = [
        line
        for line in db.claim_lines.values()
        if line["redemption_claim_id"] == claim["id"]
        and line["edit_result"] in ("ACCEPTED", "ACCEPTED_REDUCED")
    ]
    lines.sort(key=lambda line: line["line_number"])
    rate_dec = dec(rate)
    recoupments = []
    for line in lines:
        share = rhu_int(Decimal(line["allowed_cents"]) * rate_dec)
        recoupments.append(
            {
                "claim_line_id": line["id"],
                "allowed_cents": line["allowed_cents"],
                "recoupment_cents": share,
            }
        )
    total = sum(entry["recoupment_cents"] for entry in recoupments)
    return total, recoupments


# --------------------------------------------- redemption average (§3.5)
def vendor_avg_monthly_redemption(vendor):
    claims = [
        c
        for c in db.redemption_claims.values()
        if c["vendor_id"] == vendor["id"]
        and c["status"] in ("ADJUDICATED", "ADJUSTED", "PAID")
    ]
    if not claims:
        return vendor["reported_monthly_redemption_cents"]
    months = sorted({c["claim_month"] for c in claims}, reverse=True)[: C.AVG_REDEMPTION_MONTHS]
    month_set = set(months)
    selected = [c for c in claims if c["claim_month"] in month_set]
    if not selected:
        return vendor["reported_monthly_redemption_cents"]
    total = sum((c["adjudicated_total_cents"] or 0) for c in selected)
    return rhu_int(Decimal(total) / Decimal(len(months)))


# ------------------------------------------------------- risk score (§3.9)
def risk_components(vendor, window_end):
    window_start = clock.add_days(window_end, -C.RISK_WINDOW_DAYS)
    lines = []
    for claim in db.redemption_claims.values():
        if claim["vendor_id"] != vendor["id"]:
            continue
        if claim["status"] not in ("ADJUDICATED", "ADJUSTED", "PAID"):
            continue
        adjudicated_at = claim["adjudicated_at"]
        if adjudicated_at is None:
            continue
        if not (window_start < adjudicated_at <= window_end):
            continue
        lines.extend(
            line
            for line in db.claim_lines.values()
            if line["redemption_claim_id"] == claim["id"]
        )
    total_lines = len(lines)
    if total_lines == 0:
        edit_rejection_rate_pct = Decimal(0)
        price_excess_pct = Decimal(0)
    else:
        rejected = sum(1 for line in lines if line["edit_result"] == "REJECTED")
        excess = sum(1 for line in lines if line["edit_code"] == "E05")
        edit_rejection_rate_pct = Decimal(100) * Decimal(rejected) / Decimal(total_lines)
        price_excess_pct = Decimal(100) * Decimal(excess) / Decimal(total_lines)

    visits = [
        v
        for v in db.monitoring_visits.values()
        if v["vendor_id"] == vendor["id"]
        and v["status"] in ("PASSED", "FAILED", "CURED", "ESCALATED")
        and v["conducted_at"] is not None
        and window_start < v["conducted_at"] <= window_end
    ]
    if not visits:
        failed_visit_pct = Decimal(0)
    else:
        failed = sum(1 for v in visits if v["status"] in ("FAILED", "ESCALATED"))
        failed_visit_pct = Decimal(100) * Decimal(failed) / Decimal(len(visits))

    points = vendor["sanction_points"]
    raw = (
        C.W_EDIT * edit_rejection_rate_pct
        + C.W_PRICE * price_excess_pct
        + C.W_VISIT * failed_visit_pct
        + C.POINT_WEIGHT * Decimal(min(C.POINT_CAP, points))
    )
    score = rhu(raw, 1)
    if score > Decimal("100.0"):
        score = Decimal("100.0")
    if score >= C.HIGH_TIER_MIN:
        tier = "HIGH"
    elif score >= C.ELEVATED_TIER_MIN:
        tier = "ELEVATED"
    else:
        tier = "LOW"
    return {
        "window_start": window_start,
        "window_end": window_end,
        "evaluated_line_count": total_lines,
        "evaluated_visit_count": len(visits),
        "edit_rejection_rate_pct": rhu(edit_rejection_rate_pct, 1),
        "price_excess_pct": rhu(price_excess_pct, 1),
        "failed_visit_pct": rhu(failed_visit_pct, 1),
        "sanction_points": points,
        "risk_score": score,
        "risk_tier": tier,
    }


# --------------------------------------------- sanction schedule (§3.9)
def sanction_schedule(vendor, violation_code, exclude_case_id=None):
    base_tier = C.BASE_TIER_BY_VIOLATION[violation_code]
    case_points = C.POINTS_BY_BASE_TIER[base_tier]
    cumulative = 0
    for case in db.sanction_cases.values():
        if case["vendor_id"] != vendor["id"]:
            continue
        if exclude_case_id is not None and case["id"] == exclude_case_id:
            continue
        if case["status"] not in C.RESOLVED_SANCTION_STATUSES:
            continue
        cumulative += C.POINTS_BY_BASE_TIER[case["base_tier"]]
    combined = cumulative + case_points
    escalation_step = sum(1 for t in C.ESCALATION_THRESHOLDS if combined >= t)
    effective_tier = min(4, base_tier + escalation_step)
    disqualification_months = C.DISQ_MONTHS_BY_TIER[effective_tier]
    cmp_permitted = violation_code != "CLASS_A"
    raw_cmp = (
        Decimal(vendor["avg_monthly_redemption_cents"])
        * C.CMP_MULTIPLIER_BY_TIER[effective_tier]
        * Decimal(C.CMP_MONTHS_BY_TIER[effective_tier])
    )
    cmp_amount_cents = min(C.CMP_CAP_CENTS, rhu_int(raw_cmp))
    return {
        "base_tier": base_tier,
        "case_points": case_points,
        "cumulative_points_at_open": cumulative,
        "effective_tier": effective_tier,
        "disqualification_months": disqualification_months,
        "cmp_amount_cents": cmp_amount_cents,
        "cmp_permitted": cmp_permitted,
    }
