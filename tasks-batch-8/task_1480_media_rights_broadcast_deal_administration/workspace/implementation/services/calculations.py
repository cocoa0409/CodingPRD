"""Calculation rules from the scaffold (§calculations), with PRD §2.6/§3 fidelity.

All monetary math uses Decimal with ROUND_HALF_UP to integer cents.
"""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from services.clock import now, format_iso

# Constants from the scaffold.
LATE_FEE_DAILY_RATE = Decimal("0.0005")
REMEDY_RATE = Decimal("0.25")
AGGRAVATION_MULTIPLIER = Decimal("1.5")
AGGRAVATION_THRESHOLD = Decimal("0.2")
BREACH_THRESHOLD = 3
SHORTFALL_GRACE_DAYS = 30
WARNING_RATING_RATIO = Decimal("0.7")

# Time-window constants referenced by the PRD (§3.9, §3.5, §3.6).
RENEWAL_WINDOW_DAYS = 90
MATCHING_WINDOW_DAYS = 30
RENEWAL_TERM_YEARS = 3
DEFAULT_GRACE_DAYS = 30
NO_SHOW_GRACE_HOURS = 24
FROZEN_GRACE_DAYS = 30
LATE_GRACE_DAYS = 14


def _cents(value):
    """Round a Decimal to whole cents HALF_UP and return int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def escalated_season_fee(deal, season_index):
    """escalated_rights_fee for season n (1-based), per scaffold formula.

    comp = base * (1 + r)^(n-1)
    floor_val = comp if n == 1 else prior_fee * (1 + g)
    fee_n = min(max(comp, floor_val), cap), rounded HALF_UP to integer cents.
    """
    base = Decimal(deal["base_fee_cents"])
    r = Decimal(str(deal.get("escalator_rate_pct") or 0))
    g = Decimal(str(deal.get("minimum_growth_pct") or 0))
    cap = Decimal(deal["fee_cap_cents"]) if deal.get("fee_cap_cents") is not None else None
    n = season_index

    comp = base * (Decimal(1) + r) ** (n - 1)
    if n == 1:
        floor_val = comp
    else:
        prior = Decimal(escalated_season_fee(deal, n - 1))
        floor_val = prior * (Decimal(1) + g)
    pre_cap = comp if comp >= floor_val else floor_val
    fee = pre_cap
    if cap is not None and fee > cap:
        fee = cap
    return _cents(fee)


def deal_season_count(deal):
    """Number of seasons in the deal term. Derived from the term length in years
    (the term covers at least one full season; each year ≈ one season)."""
    ts = deal.get("term_start")
    te = deal.get("term_end")
    if ts is not None and te is not None:
        days = (te - ts).days
        return max(1, round(days / 365))
    # Pre-execution fallback: use milestone/obligations season coverage.
    seen = {m["season_index"] for m in db.payment_milestones.values() if m["deal_id"] == deal["id"]}
    seen |= {o["season_index"] for o in db.production_obligations.values() if o["deal_id"] == deal["id"]}
    return max(seen) if seen else 1


def total_contracted_fee(deal):
    """Sum over seasons of escalated_rights_fee."""
    seasons = deal_season_count(deal)
    return sum(escalated_season_fee(deal, n) for n in range(1, seasons + 1))


def recompute_season_allocation(deal, season_index):
    """payment_schedule_allocation: assign base_amount_cents across a season's
    milestones (status != DEFAULTED), ordered by sequence_in_season ASC,
    tie-break created_at ASC. Remainder distributed one cent at a time."""
    fee_n = escalated_season_fee(deal, season_index)
    milestones = [
        m for m in db.payment_milestones.values()
        if m["deal_id"] == deal["id"] and m["season_index"] == season_index
        and m["status"] != "DEFAULTED"
    ]
    if not milestones:
        return
    milestones.sort(key=lambda m: (m["sequence_in_season"], m["created_at"]))
    fee_dec = Decimal(fee_n)
    bases = []
    total_weight = Decimal("0")
    for m in milestones:
        w = Decimal(str(m["milestone_weight"]))
        total_weight += w
        pre = fee_dec * w
        bases.append(_cents(pre))
    # Remainder reconciliation only applies when the season's weights sum to
    # exactly 1.0 — the scaffold's invariant {-k+1..k-1} holds only there.
    if total_weight == Decimal("1.0"):
        remainder = fee_n - sum(bases)
        i = 0
        step = 1 if remainder > 0 else -1
        remaining = abs(remainder)
        while remaining > 0 and milestones:
            bases[i % len(milestones)] += step
            remaining -= 1
            i += 1
    for m, b in zip(milestones, bases):
        m["base_amount_cents"] = b
        m["escalated_amount_cents"] = b + m.get("late_fee_cents", 0)
        m["updated_at"] = format_iso(now())
        m["version"] += 1


def recompute_all_allocations(deal):
    seasons = {m["season_index"] for m in db.payment_milestones.values() if m["deal_id"] == deal["id"]}
    for s in sorted(seasons):
        recompute_season_allocation(deal, s)


def make_good_credit(deal, obligation):
    """make_good_credit calculation."""
    sg = obligation["shortfall_games"]
    gr = obligation["games_required"]
    fee_n = escalated_season_fee(deal, obligation["season_index"])
    if gr == 0:
        per_game = 0
    else:
        per_game = _cents(Decimal(fee_n) / Decimal(gr))
    base_credit = sg * per_game
    if gr == 0:
        multiplier = Decimal("1.0")
    else:
        ratio = Decimal(sg) / Decimal(gr)
        multiplier = AGGRAVATION_MULTIPLIER if ratio > AGGRAVATION_THRESHOLD else Decimal("1.0")
    credit = _cents(Decimal(base_credit) * multiplier)
    if credit > fee_n:
        credit = fee_n
    return credit


def rating_shortfall_remedy(deal):
    """rating_shortfall_remedy (final variant): CONFIRMED measurements only."""
    commit = deal.get("audience_commitment_basis_points") or 0
    delivered = deal.get("cumulative_rating_basis_points") or 0
    if commit <= 0 or delivered >= commit:
        return 0
    shortfall_bp = commit - delivered
    ratio = Decimal(shortfall_bp) / Decimal(commit)
    total = Decimal(deal.get("total_contracted_fee_cents") or 0)
    return _cents(total * ratio * REMEDY_RATE)


def _season_close_reached(deal):
    """PRD §2.10: the rating-based WARNING clause applies only "evaluated at
    season close" — i.e. once the logical clock has passed the end of the
    deal's final season (the asset's season_end_date, extended by one season
    length per additional season of the term)."""
    asset = db.rights_assets.get(deal.get("asset_id"))
    if asset is None:
        return False
    season_length = asset["season_end_date"] - asset["season_start_date"]
    seasons = deal_season_count(deal)
    final_season_end = asset["season_end_date"] + season_length * (seasons - 1)
    return now() > final_season_end


def evaluate_posture(deal):
    """deal_posture_rule — top-down ladder."""
    milestones = [m for m in db.payment_milestones.values() if m["deal_id"] == deal["id"]]
    obligations = [o for o in db.production_obligations.values() if o["deal_id"] == deal["id"]]

    if any(m["status"] == "DEFAULTED" for m in milestones):
        return "FROZEN"
    if deal.get("payment_delinquency_count", 0) >= BREACH_THRESHOLD:
        return "FROZEN"
    now_dt = now()
    for o in obligations:
        if o["status"] == "SHORTFALL_DECLARED" and o.get("shortfall_declared_at"):
            if (now_dt - o["shortfall_declared_at"]).days > SHORTFALL_GRACE_DAYS:
                return "FROZEN"

    if deal.get("payment_delinquency_count", 0) in (1, 2):
        return "WARNING"
    if any(o["status"] == "SHORTFALL_DECLARED" for o in obligations):
        return "WARNING"
    commit = deal.get("audience_commitment_basis_points") or 0
    if commit > 0 and _season_close_reached(deal):
        delivered = Decimal(deal.get("cumulative_rating_basis_points") or 0)
        if delivered < WARNING_RATING_RATIO * Decimal(commit):
            return "WARNING"
    return "CLEAN"


def refresh_posture(deal):
    new_posture = evaluate_posture(deal)
    if deal.get("posture") != new_posture:
        deal["posture"] = new_posture
        if new_posture == "FROZEN":
            if deal.get("posture_frozen_since") is None:
                deal["posture_frozen_since"] = now()
        else:
            deal["posture_frozen_since"] = None
        deal["updated_at"] = format_iso(now())
        deal["version"] += 1
    return deal["posture"]


# --- Conflict scans (§2.9) -------------------------------------------------

def half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def sublicense_intersects_blackout(s_start, s_end, b_start, b_end):
    # Half-open [s_start, s_end) ∩ closed [b_start, b_end]
    return s_start <= b_end and s_end > b_start


def write_conflict(asset_id, conflict_type, left_kind, left_id, right_kind, right_id, detail):
    row = {
        "id": str(uuid.uuid4()),
        "asset_id": asset_id,
        "conflict_type": conflict_type,
        "left_entity_kind": left_kind,
        "left_entity_id": left_id,
        "right_entity_kind": right_kind,
        "right_entity_id": right_id,
        "detected_at": format_iso(now()),
        "created_at": format_iso(now()),
        "detail": detail,
    }
    db.rights_conflicts[row["id"]] = row
    return row


def run_exclusivity_scan(asset_id):
    """Scan all packages on the asset in {OPEN_FOR_BIDS, UNDER_NEGOTIATION, AWARDED}
    and write EXCLUSIVITY_OVERLAP rows for conflicting pairs."""
    packages = [
        p for p in db.packages.values()
        if p["asset_id"] == asset_id and p["status"] in ("OPEN_FOR_BIDS", "UNDER_NEGOTIATION", "AWARDED")
    ]
    for i in range(len(packages)):
        for j in range(i + 1, len(packages)):
            p1, p2 = packages[i], packages[j]
            if p1["territory_code"] != p2["territory_code"]:
                continue
            if p1["platform_class"] != p2["platform_class"]:
                continue
            if not half_open_overlap(p1["window_start"], p1["window_end"], p2["window_start"], p2["window_end"]):
                continue
            if p1["exclusivity_class"] != "EXCLUSIVE" and p2["exclusivity_class"] != "EXCLUSIVE":
                continue
            detail = (
                f"Packages {p1['package_code']} and {p2['package_code']} overlap on "
                f"territory {p1['territory_code']} platform {p1['platform_class']} "
                f"with at least one EXCLUSIVE."
            )
            write_conflict(asset_id, "EXCLUSIVITY_OVERLAP", "PACKAGE", p1["id"], "PACKAGE", p2["id"], detail)
