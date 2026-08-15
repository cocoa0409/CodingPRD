"""Business logic: calculations (scaffold §1.3), ledger sync (§2.9),
state-transition cascades (§1.2), and entity serialization."""

import uuid
from datetime import timedelta
from decimal import Decimal

from db import db
from util import rhu, rhu_int

# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------

def now_iso():
    ts = db.clock
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def new_record():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "created_at_sort": db.clock.isoformat(),
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Refresh updated_at and bump version on any mutation of the resource."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Market portfolio ledgers (PRD §2.9) and saturation posture
# ---------------------------------------------------------------------------

COMMITTED_SITE_STATUSES = {
    "APPROVED", "LOI_ACTIVE", "LEASE_EXECUTED", "BUILD_OUT",
    "OPEN", "MEASURING", "UNDERPERFORMING",
}
OPEN_SITE_STATUSES = {"OPEN", "MEASURING", "UNDERPERFORMING"}


def sync_market(market):
    """Recompute open_store_count / committed_capex_cents from their defining
    sets, then re-evaluate saturation posture. Bumps the market's version when
    any derived field or the status changes."""
    mid = market["id"]
    open_count = 0
    for s in db.stores.values():
        if s["market_id"] == mid and s["store_status"] == "OPERATING":
            open_count += 1
    committed = 0
    for s in db.sites.values():
        if s["market_id"] != mid:
            continue
        if s["site_status"] in OPEN_SITE_STATUSES:
            open_count += 1
        if s["site_status"] in COMMITTED_SITE_STATUSES:
            committed += s["build_cost_cents"]
    changed = (
        market["open_store_count"] != open_count
        or market["committed_capex_cents"] != committed
    )
    market["open_store_count"] = open_count
    market["committed_capex_cents"] = committed
    target = market["target_store_count"]
    if target is not None:
        if market["market_status"] == "QUALIFIED" and open_count >= target:
            market["market_status"] = "SATURATED"
            changed = True
        elif market["market_status"] == "SATURATED" and open_count < target:
            market["market_status"] = "QUALIFIED"
            changed = True
    if changed:
        touch(market)


# ---------------------------------------------------------------------------
# market_screening_evaluation (pinned five-step chain)
# ---------------------------------------------------------------------------

def evaluate_market(market):
    pop_score = min(Decimal(market["population"]) / Decimal(250000), Decimal(1)) * 100
    income_score = min(
        Decimal(market["median_household_income_cents"]) / Decimal(7500000),
        Decimal(1)) * 100
    growth_score = min(
        Decimal(max(market["population_growth_bp"], 0)) / Decimal(500),
        Decimal(1)) * 100
    psycho_score = min(
        Decimal(market["psychographic_index"]) / Decimal(120), Decimal(1)) * 100
    raw = rhu(
        Decimal("0.30") * pop_score
        + Decimal("0.30") * income_score
        + Decimal("0.20") * growth_score
        + Decimal("0.20") * psycho_score,
        2,
    )
    if raw >= Decimal("75.00"):
        tier, bonus = "A", 4
    elif raw >= Decimal("50.00"):
        tier, bonus = "B", 2
    else:
        tier, bonus = "C", 0
    target = market["base_target_stores"] + bonus
    open_count = market["open_store_count"]
    if open_count == 0:
        pen_index = Decimal("0.000000")
    else:
        pen_index = rhu(Decimal(open_count) / Decimal(target), 6)
    penalty = min(pen_index, Decimal("1.0")) * 20
    final = rhu(raw - penalty, 2)
    market["raw_score"] = raw
    market["screening_tier"] = tier
    market["target_store_count"] = target
    market["penetration_index"] = pen_index
    market["final_score"] = final
    market["market_status"] = "QUALIFIED" if final >= Decimal("60.00") else "DISQUALIFIED"
    touch(market)


# ---------------------------------------------------------------------------
# cannibalization_impact (per-store rounding BEFORE summation)
# ---------------------------------------------------------------------------

def compute_cannibalization(model):
    D = model["drive_time_minutes"]
    total = 0
    for pair in model["store_drive_times"]:
        store = db.stores.get(pair["store_id"])
        if store is None or store["store_status"] != "OPERATING":
            continue
        dmin = pair["drive_minutes"]
        if dmin > D:
            continue
        if model["cannibalization_variant"] == "FLAT_BAND":
            if dmin <= 5:
                factor = Decimal("0.30")
            elif dmin <= 10:
                factor = Decimal("0.15")
            else:
                factor = Decimal("0.05")
        else:  # DISTANCE_DECAY, exact decimal arithmetic
            factor = (
                Decimal("0.35") * Decimal(D - dmin) ** 2 / Decimal(D) ** 2
            )
        total += rhu_int(Decimal(store["annual_sales_cents"]) * factor)
    return total


# ---------------------------------------------------------------------------
# sales_forecast_gross (GRAVITY / ANALOG variants)
# ---------------------------------------------------------------------------

_FORMAT_FACTORS = {
    "EXPRESS": Decimal("0.85"),
    "STANDARD": Decimal("1.00"),
    "FLAGSHIP": Decimal("1.20"),
}


def compute_gross(site, model, variant):
    if variant == "GRAVITY":
        a_site = Decimal(site["square_footage"]) / Decimal(25)  # 5^2
        comp_sum = Decimal(0)
        for listing in db.listings.values():
            if (listing["trade_area_model_id"] == model["id"]
                    and listing["listing_type"] == "COMPETITOR"):
                d = max(listing["distance_minutes"], 1)
                comp_sum += Decimal(listing["estimated_sqft"]) / Decimal(d * d)
        capture = rhu(a_site / (a_site + comp_sum), 6)
        return rhu_int(
            Decimal(model["trade_area_population"])
            * Decimal(model["per_capita_spend_cents"])
            * capture
        )
    # ANALOG
    market = db.markets[site["market_id"]]
    analogs = [
        s for s in db.stores.values()
        if s["market_id"] == site["market_id"]
        and s["store_status"] == "OPERATING"
        and s["format_type"] == site["format_type"]
    ]
    if analogs:
        base = rhu_int(
            Decimal(sum(s["annual_sales_cents"] for s in analogs))
            / Decimal(len(analogs))
        )
    else:
        base = market["prototype_sales_cents"]
    return rhu_int(Decimal(base) * _FORMAT_FACTORS[site["format_type"]])


# ---------------------------------------------------------------------------
# occupancy_cost_ratio (PROVISIONAL / FINAL share the same formula)
# ---------------------------------------------------------------------------

def occupancy_ratio_bp(rent_psf, cam_psf, tax_psf, sqft, net_sales):
    annual = (rent_psf + cam_psf + tax_psf) * sqft
    if net_sales == 0:
        return 0 if annual == 0 else 9999999
    return rhu_int(Decimal(annual) * 10000 / Decimal(net_sales))


def occupancy_band(ratio_bp):
    if ratio_bp <= 1500:
        return "GREEN"
    if ratio_bp <= 2200:
        return "YELLOW"
    return "RED"


# ---------------------------------------------------------------------------
# site_visit_total_score
# ---------------------------------------------------------------------------

def visit_total_score(visibility, access, parking, cotenancy):
    return rhu(
        Decimal("0.30") * visibility
        + Decimal("0.25") * access
        + Decimal("0.15") * parking
        + Decimal("0.30") * cotenancy,
        2,
    )


# ---------------------------------------------------------------------------
# committee_vote_tally
# ---------------------------------------------------------------------------

def quorum_count(eligible):
    return (2 * eligible + 2) // 3  # ceil(E * 2/3), exact integer arithmetic


def decided_outcome(approve, reject, abstain, quorum):
    non_abstain = approve + reject
    if non_abstain == 0:
        return "REJECT"
    if approve * 100 > 60 * non_abstain and non_abstain >= quorum:
        return "APPROVE"
    return "REJECT"


# ---------------------------------------------------------------------------
# loi_effective_rent (pinned rounding order)
# ---------------------------------------------------------------------------

def effective_annual_rent(rent_psf, escalation_bp, term_years,
                          ti_allowance, free_rent_months, sqft):
    esc = Decimal(escalation_bp) / Decimal(10000)
    psf = [Decimal(rent_psf)]
    for _ in range(2, term_years + 1):
        psf.append(rhu(psf[-1] * (1 + esc), 0))
    year_rents = [rhu_int(p * sqft) for p in psf]
    monthly_year1 = rhu(Decimal(year_rents[0]) / Decimal(12), 0)
    free_rent_value = int(monthly_year1) * free_rent_months
    total = sum(year_rents) - ti_allowance - free_rent_value
    return rhu_int(Decimal(total) / Decimal(term_years))


# ---------------------------------------------------------------------------
# LOI exclusivity windows (half-open [start, end))
# ---------------------------------------------------------------------------

def loi_windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Crew build windows: closed interval + 6-day buffer (gap of >= 7 days OK)
# ---------------------------------------------------------------------------

def crew_windows_conflict(a_start, a_end, b_start, b_end):
    buffer = timedelta(days=6)
    return a_start <= b_end + buffer and b_start <= a_end + buffer


# ---------------------------------------------------------------------------
# Milestone ordering
# ---------------------------------------------------------------------------

MILESTONE_ORDER = [
    "PERMIT_SUBMITTED",
    "PERMIT_APPROVED",
    "BUILD_START",
    "BUILD_COMPLETE",
]


def lower_milestones_completed(site_id, milestone_type):
    idx = MILESTONE_ORDER.index(milestone_type)
    for lower in MILESTONE_ORDER[:idx]:
        m = next(
            (x for x in db.milestones.values()
             if x["site_id"] == site_id and x["milestone_type"] == lower),
            None,
        )
        if m is None or m["milestone_status"] != "COMPLETED":
            return False
    return True


# ---------------------------------------------------------------------------
# Site withdraw compensation cascade (PRD §3.2)
# ---------------------------------------------------------------------------

def withdraw_site(site):
    prior = site["site_status"]
    site["site_status"] = "WITHDRAWN"
    touch(site)
    for loi in db.lois.values():
        if loi["site_id"] == site["id"] and loi["loi_status"] in (
                "DRAFT", "SENT", "COUNTERED"):
            loi["loi_status"] = "WITHDRAWN"
            touch(loi)
    for review in db.reviews.values():
        if review["site_id"] == site["id"] and review["review_status"] in (
                "OPEN", "DECIDED"):
            review["review_status"] = "VOID"
            touch(review)
    # Capital release is implicit in the ledger recompute: WITHDRAWN is not in
    # COMMITTED_SITE_STATUSES, so approval-time commitments release exactly.
    if prior in ("APPROVED", "LOI_ACTIVE", "LEASE_EXECUTED", "BUILD_OUT"):
        sync_market(db.markets[site["market_id"]])


# ---------------------------------------------------------------------------
# Serializers (exact scaffold field sets)
# ---------------------------------------------------------------------------

def _num(v):
    """Decimal -> JSON number (int when integral, else float)."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        f = float(v)
        return f
    return v


def ser_market(m):
    return {
        "id": m["id"],
        "name": m["name"],
        "state_code": m["state_code"],
        "population": m["population"],
        "median_household_income_cents": m["median_household_income_cents"],
        "population_growth_bp": m["population_growth_bp"],
        "psychographic_index": m["psychographic_index"],
        "base_target_stores": m["base_target_stores"],
        "annual_capex_budget_cents": m["annual_capex_budget_cents"],
        "max_rent_psf_cents": m["max_rent_psf_cents"],
        "prototype_sales_cents": m["prototype_sales_cents"],
        "market_status": m["market_status"],
        "raw_score": _num(m["raw_score"]),
        "screening_tier": m["screening_tier"],
        "target_store_count": m["target_store_count"],
        "penetration_index": _num(m["penetration_index"]),
        "final_score": _num(m["final_score"]),
        "open_store_count": m["open_store_count"],
        "committed_capex_cents": m["committed_capex_cents"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_store(s):
    return {
        "id": s["id"],
        "market_id": s["market_id"],
        "store_code": s["store_code"],
        "format_type": s["format_type"],
        "annual_sales_cents": s["annual_sales_cents"],
        "store_status": s["store_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_site(s):
    return {
        "id": s["id"],
        "market_id": s["market_id"],
        "address": s["address"],
        "format_type": s["format_type"],
        "square_footage": s["square_footage"],
        "asking_rent_psf_cents": s["asking_rent_psf_cents"],
        "cam_psf_cents": s["cam_psf_cents"],
        "tax_psf_cents": s["tax_psf_cents"],
        "build_cost_cents": s["build_cost_cents"],
        "site_status": s["site_status"],
        "consecutive_miss_count": s["consecutive_miss_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_model(m):
    return {
        "id": m["id"],
        "site_id": m["site_id"],
        "drive_time_minutes": m["drive_time_minutes"],
        "trade_area_population": m["trade_area_population"],
        "per_capita_spend_cents": m["per_capita_spend_cents"],
        "cannibalization_variant": m["cannibalization_variant"],
        "store_drive_times": [
            {"store_id": p["store_id"], "drive_minutes": p["drive_minutes"]}
            for p in m["store_drive_times"]
        ],
        "model_status": m["model_status"],
        "cannibalized_sales_cents": m["cannibalized_sales_cents"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_listing(l):
    return {
        "id": l["id"],
        "trade_area_model_id": l["trade_area_model_id"],
        "listing_type": l["listing_type"],
        "brand_name": l["brand_name"],
        "estimated_sqft": l["estimated_sqft"],
        "distance_minutes": l["distance_minutes"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_visit(v):
    return {
        "id": v["id"],
        "site_id": v["site_id"],
        "visited_on": v["visited_on"],
        "visibility_score": v["visibility_score"],
        "access_score": v["access_score"],
        "parking_score": v["parking_score"],
        "cotenancy_score": v["cotenancy_score"],
        "total_score": _num(v["total_score"]),
        "visit_status": v["visit_status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_forecast(f):
    return {
        "id": f["id"],
        "site_id": f["site_id"],
        "trade_area_model_id": f["trade_area_model_id"],
        "model_variant": f["model_variant"],
        "forecast_status": f["forecast_status"],
        "gross_annual_sales_cents": f["gross_annual_sales_cents"],
        "cannibalized_sales_cents": f["cannibalized_sales_cents"],
        "net_annual_sales_cents": f["net_annual_sales_cents"],
        "occupancy_ratio_bp": f["occupancy_ratio_bp"],
        "occupancy_band": f["occupancy_band"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_member(m):
    return {
        "id": m["id"],
        "display_name": m["display_name"],
        "is_chair": m["is_chair"],
        "member_status": m["member_status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_review(r):
    return {
        "id": r["id"],
        "site_id": r["site_id"],
        "sales_forecast_id": r["sales_forecast_id"],
        "sponsor_member_id": r["sponsor_member_id"],
        "chair_override": r["chair_override"],
        "expires_at": r["expires_at"],
        "review_status": r["review_status"],
        "decided_outcome": r["decided_outcome"],
        "eligible_member_count": r["eligible_member_count"],
        "quorum_count": r["quorum_count"],
        "approve_votes": r["approve_votes"],
        "reject_votes": r["reject_votes"],
        "abstain_votes": r["abstain_votes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_vote(v):
    # A vote carries only id + created_at; no updated_at, no version.
    return {
        "id": v["id"],
        "review_id": v["review_id"],
        "member_id": v["member_id"],
        "ballot": v["ballot"],
        "created_at": v["created_at"],
    }


def ser_loi(l):
    return {
        "id": l["id"],
        "site_id": l["site_id"],
        "rent_psf_cents": l["rent_psf_cents"],
        "escalation_pct_bp": l["escalation_pct_bp"],
        "term_years": l["term_years"],
        "ti_allowance_cents": l["ti_allowance_cents"],
        "free_rent_months": l["free_rent_months"],
        "exclusivity_start_date": l["exclusivity_start_date"],
        "exclusivity_end_date": l["exclusivity_end_date"],
        "countered_rent_psf_cents": l["countered_rent_psf_cents"],
        "agreed_rent_psf_cents": l["agreed_rent_psf_cents"],
        "round_number": l["round_number"],
        "effective_annual_rent_cents": l["effective_annual_rent_cents"],
        "loi_status": l["loi_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_lease(l):
    return {
        "id": l["id"],
        "loi_id": l["loi_id"],
        "final_rent_psf_cents": l["final_rent_psf_cents"],
        "escalation_pct_bp": l["escalation_pct_bp"],
        "term_years": l["term_years"],
        "ti_allowance_cents": l["ti_allowance_cents"],
        "free_rent_months": l["free_rent_months"],
        "crew_id": l["crew_id"],
        "build_start_date": l["build_start_date"],
        "build_end_date": l["build_end_date"],
        "effective_annual_rent_cents": l["effective_annual_rent_cents"],
        "final_occupancy_ratio_bp": l["final_occupancy_ratio_bp"],
        "lease_status": l["lease_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_crew(c):
    return {
        "id": c["id"],
        "crew_code": c["crew_code"],
        "crew_status": c["crew_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_milestone(m):
    return {
        "id": m["id"],
        "site_id": m["site_id"],
        "milestone_type": m["milestone_type"],
        "planned_date": m["planned_date"],
        "actual_date": m["actual_date"],
        "milestone_status": m["milestone_status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_snapshot(s):
    return {
        "id": s["id"],
        "site_id": s["site_id"],
        "period_index": s["period_index"],
        "actual_sales_cents": s["actual_sales_cents"],
        "expected_sales_cents": s["expected_sales_cents"],
        "variance_bp": s["variance_bp"],
        "snapshot_status": s["snapshot_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
