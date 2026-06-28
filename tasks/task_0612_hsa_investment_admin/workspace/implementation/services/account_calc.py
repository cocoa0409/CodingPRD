"""Account-level derived field recomputation and the contribution-limit
calculation (PRD §3.3, §3.4, §2.6).

All money is integer cents. The only rounding direction in the system is floor,
applied once at the end of a division (PRD §2.5). Ledger math is exact integer
add/subtract.
"""
from db import db, touch

# Constants (SCAFFOLD §1.3 contribution_limit / PRD §3.3), integer cents.
SELF_ANNUAL = 432000      # $4,320.00
FAMILY_ANNUAL = 862500    # $8,625.00
CATCHUP_ANNUAL = 100000   # $1,000.00


def _attested_periods(account_id):
    return [
        cp for cp in db.coverage_periods.values()
        if cp["account_id"] == account_id and cp["status"] == "ATTESTED"
    ]


def _month_covered(period, m):
    # closed-closed interval [effective_month, end_month]
    return period["effective_month"] <= m <= period["end_month"]


def _monthly_tier_limit(periods, m):
    """Greatest-tier-per-month rule. SELF_MONTHLY = SELF_ANNUAL/12 etc., kept as
    exact cents*12 numerators (we return the annual numerator; callers divide by
    12 once at the end)."""
    has_family = any(p["coverage_tier"] == "FAMILY" and _month_covered(p, m) for p in periods)
    if has_family:
        return FAMILY_ANNUAL
    has_any = any(_month_covered(p, m) for p in periods)
    if has_any:
        return SELF_ANNUAL
    return 0


def catch_up_eligible(account):
    """turns_55_or_older_in_plan_year for the owning accountholder against the
    account's plan_year (PRD §3.1; evaluated lazily, read off the logical clock
    only for the age math which is fully determined by date_of_birth + plan_year).
    True when the accountholder reaches age 55+ at any point during plan_year."""
    holder = db.accountholders.get(account["accountholder_id"])
    if holder is None:
        return False
    dob = _parse_year(holder.get("date_of_birth"))
    if dob is None:
        return False
    # Turns 55 at any point during plan_year => born on/before Dec 31 of
    # (plan_year - 55). i.e. age at end of plan_year >= 55.
    return (account["plan_year"] - dob) >= 55


def _parse_year(iso):
    if not iso or not isinstance(iso, str):
        return None
    try:
        return int(iso[:4])
    except (ValueError, TypeError):
        return None


def compute_applicable_limit(account):
    """Compute applicable_limit_cents under the account's active variant
    (default LAST_MONTH_RULE). PRD §3.3."""
    periods = _attested_periods(account["id"])
    eligible = catch_up_eligible(account)
    variant = account.get("limit_variant", "LAST_MONTH_RULE")

    if variant == "PRORATED":
        # base = floor( sum over m=1..12 of monthly_tier_limit[m] / 12 ),
        # but monthly_tier_limit[m] = annual/12, so:
        # sum over m of (annual_numerator/12) / 12. Keep numerators (annual figures)
        # and apply the single floor at the very end.
        monthly_numerators = [_monthly_tier_limit(periods, m) for m in range(1, 13)]
        base_numerator_sum = sum(monthly_numerators)  # sum of annual figures / 12 implied
        # monthly amount m = monthly_numerators[m]/12; base = sum(monthly)/12 floored once.
        # => base = floor( (sum of annual_numerators / 12) / 12 )
        #         = floor( sum_of_annual_numerators / 144 )
        base = base_numerator_sum // 144
        if eligible:
            covered_months = sum(1 for n in monthly_numerators if n > 0)
            catch_up = (CATCHUP_ANNUAL * covered_months) // 12
        else:
            catch_up = 0
        return base + catch_up

    # LAST_MONTH_RULE (default): full undivided annual for December coverage.
    dec_family = any(p["coverage_tier"] == "FAMILY" and _month_covered(p, 12) for p in periods)
    dec_any = any(_month_covered(p, 12) for p in periods)
    if dec_family:
        base = FAMILY_ANNUAL
    elif dec_any:
        base = SELF_ANNUAL
    else:
        base = 0
    catch_up = CATCHUP_ANNUAL if eligible else 0
    return base + catch_up


def catch_up_component(account):
    """The catch-up sub-limit (catch-up component) under the active variant,
    used by the catch-up guard at post time (PRD §3.4)."""
    variant = account.get("limit_variant", "LAST_MONTH_RULE")
    if variant == "PRORATED":
        periods = _attested_periods(account["id"])
        monthly_numerators = [_monthly_tier_limit(periods, m) for m in range(1, 13)]
        covered_months = sum(1 for n in monthly_numerators if n > 0)
        return (CATCHUP_ANNUAL * covered_months) // 12
    return CATCHUP_ANNUAL


def posted_contributions(account_id, plan_year):
    return [
        c for c in db.contributions.values()
        if c["account_id"] == account_id and c["status"] == "POSTED"
    ]


def recompute_derived(account, bump=True):
    """Bubble-up recomputation of contributions_ytd_cents, applicable_limit_cents,
    excess_contribution_cents and contribution_posture, in dependency order
    (PRD §2.6, §3.4). When bump=True, mark the account mutated (updated_at /
    version), per PRD §2.4 'derived recomputation counts as a mutation'."""
    # STEP 1: contributions_ytd_cents = sum POSTED amounts in plan_year.
    posted = posted_contributions(account["id"], account["plan_year"])
    account["contributions_ytd_cents"] = sum(c["amount_cents"] for c in posted)

    # STEP 2: applicable_limit_cents (depends on coverage, not contributions).
    account["applicable_limit_cents"] = compute_applicable_limit(account)

    # STEP 3: excess = max(0, ytd - limit).
    account["excess_contribution_cents"] = max(
        0, account["contributions_ytd_cents"] - account["applicable_limit_cents"]
    )

    # Posture (PRD §2.6): OPEN iff lifecycle ACTIVE and excess == 0; else LOCKED.
    derive_posture(account)

    if bump:
        touch(account)


def derive_posture(account):
    if account["lifecycle_status"] == "ACTIVE" and account["excess_contribution_cents"] == 0:
        account["contribution_posture"] = "OPEN"
    else:
        account["contribution_posture"] = "LOCKED"
