from decimal import Decimal, ROUND_HALF_UP
from db import db, now_iso


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

COMMON_SYS = ("id", "created_at", "updated_at", "version")


def touch(entity):
    """Bump version + updated_at for a standard mutable entity."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def season_of(season_id):
    return db.seasons.get(season_id)


def team_of(team_id):
    return db.teams.get(team_id)


def contract_of(cid):
    return db.contracts.get(cid)


# ---------------------------------------------------------------------------
# Roster / payroll helpers
# ---------------------------------------------------------------------------

def cap_counts(c):
    return (c["contract_type"] == "STANDARD") or (
        c["contract_type"] == "TWO_WAY" and c["two_way_promoted"] is True
    )


def team_active_contracts(team_id):
    return [c for c in db.contracts.values()
            if c["team_id"] == team_id and c["status"] == "ACTIVE"]


def compute_payroll_active(team_id):
    return sum(c["base_salary_cents"] for c in team_active_contracts(team_id)
               if cap_counts(c))


def compute_full_commitment(team_id):
    return sum(c["base_salary_cents"] for c in team_active_contracts(team_id))


def recompute_team_payroll(team):
    team["payroll_active_cents"] = compute_payroll_active(team["id"])


def active_standard_count(team_id):
    # STANDARD count for roster_max purposes: STANDARD contracts + promoted two-way
    return sum(1 for c in team_active_contracts(team_id) if cap_counts(c))


def active_two_way_unpromoted_count(team_id):
    return sum(1 for c in team_active_contracts(team_id)
               if c["contract_type"] == "TWO_WAY" and c["two_way_promoted"] is False)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

TIER_WIDTH = 5000000
RATE_TIER_1 = Decimal("1.5")
RATE_TIER_2 = Decimal("2.0")
RATE_TIER_3 = Decimal("2.5")


def luxury_tax_cents(payroll_active, salary_cap):
    overage = max(0, payroll_active - salary_cap)
    tier1 = min(overage, TIER_WIDTH)
    tier2 = min(max(overage - TIER_WIDTH, 0), TIER_WIDTH)
    tier3 = max(overage - 2 * TIER_WIDTH, 0)
    raw = (Decimal(tier1) * RATE_TIER_1
           + Decimal(tier2) * RATE_TIER_2
           + Decimal(tier3) * RATE_TIER_3)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def revenue_waterfall(pool_cents, league_share_pct, teams):
    """teams: list of team dicts in the season. Returns list of (team, amount, weight)."""
    league_cut = int((Decimal(pool_cents) * Decimal(str(league_share_pct))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    distributable = pool_cents - league_cut
    total_weight = sum(t["market_size_weight"] for t in teams)

    shares = {}
    for t in teams:
        # exact integer floor of distributable * weight / total_weight
        shares[t["id"]] = (distributable * t["market_size_weight"]) // total_weight

    remainder = distributable - sum(shares.values())
    order = sorted(teams, key=lambda t: (-t["market_size_weight"], t["_seq"]))
    i = 0
    while remainder > 0 and order:
        tid = order[i % len(order)]["id"]
        shares[tid] += 1
        remainder -= 1
        i += 1

    return [(t, shares[t["id"]], t["market_size_weight"]) for t in teams]
