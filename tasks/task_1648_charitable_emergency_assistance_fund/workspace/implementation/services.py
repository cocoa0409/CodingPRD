"""Business logic: calculations, state transitions, side effects (PRD §3)."""

from datetime import timedelta

import db
from errors import (
    raise_err,
    ERR_NO_ACTIVE_POLICY,
    ERR_ANNUAL_CAP_EXCEEDED,
    ERR_CATEGORY_CAP_EXCEEDED,
    ERR_INCOME_LIMIT_EXCEEDED,
    ERR_FUNDS_EXHAUSTED,
    ERR_INVALID_REQUEST,
)


# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------

def stamp_new(record, with_version=True):
    """Populate system fields on a freshly built record."""
    record["id"] = db.new_id()
    record["created_at"] = db.now_iso()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version (resources that carry them)."""
    record["updated_at"] = db.now_iso()
    record["version"] += 1


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------

def active_policy():
    for p in db.policies.values():
        if p["status"] == "ACTIVE":
            return p
    return None


def require_active_policy():
    p = active_policy()
    if p is None:
        raise_err(ERR_NO_ACTIVE_POLICY, "No EligibilityPolicy is ACTIVE")
    return p


# ---------------------------------------------------------------------------
# Household benefit usage (calculation: household_benefit_usage)
# ---------------------------------------------------------------------------

def household_award_set(household_id, year):
    """Non-VOIDED awards of the household whose benefit_year == year."""
    result = []
    for a in db.awards.values():
        if a["status"] in ("ACTIVE", "PARTIALLY_DISBURSED", "DISBURSED") \
                and a["benefit_year"] == year:
            app = db.applications[a["application_id"]]
            if app["household_id"] == household_id:
                result.append((a, app))
    return result


def household_usage(household_id, year, policy):
    """Exposure-basis usage figures against the given policy."""
    award_set = household_award_set(household_id, year)
    ytd = sum(a["awarded_amount_cents"] for a, _ in award_set)
    rent_ytd = sum(a["awarded_amount_cents"] for a, app in award_set
                   if app["category"] == "RENT")
    utility_ytd = sum(a["awarded_amount_cents"] for a, app in award_set
                      if app["category"] == "UTILITY")
    committed = 0
    for a, _ in award_set:
        for alloc in db.allocations.values():
            if alloc["award_id"] == a["id"]:
                committed += alloc["consumed_cents"]
    return {
        "benefit_year": year,
        "ytd_exposure_cents": ytd,
        "ytd_committed_cents": committed,
        "rent_ytd_cents": rent_ytd,
        "utility_ytd_cents": utility_ytd,
        "remaining_annual_cap_cents": policy["max_annual_benefit_cents"] - ytd,
        "remaining_rent_cap_cents": policy["rent_cap_cents"] - rent_ytd,
        "remaining_utility_cap_cents": policy["utility_cap_cents"] - utility_ytd,
    }


# ---------------------------------------------------------------------------
# Fiscal eligibility screen (income + caps) used by approve/waitlist/promotion
# ---------------------------------------------------------------------------

def check_fiscal_eligibility(application, policy):
    """Income + caps gating. Returns (rem_annual, rem_cat).

    Raises ERR_INCOME_LIMIT_EXCEEDED / ERR_ANNUAL_CAP_EXCEEDED /
    ERR_CATEGORY_CAP_EXCEEDED. Per PRD §2.9 order 11: income, annual cap,
    category cap, funds — in that order.
    """
    household = db.households[application["household_id"]]
    if household["annual_income_cents"] > policy["income_limit_cents"]:
        raise_err(ERR_INCOME_LIMIT_EXCEEDED,
                  "household annual_income_cents exceeds the policy income limit")
    year = db.clock.now().year
    usage = household_usage(application["household_id"], year, policy)
    rem_annual = usage["remaining_annual_cap_cents"]
    if application["category"] == "RENT":
        rem_cat = usage["remaining_rent_cap_cents"]
    else:
        rem_cat = usage["remaining_utility_cap_cents"]
    if rem_annual == 0:
        raise_err(ERR_ANNUAL_CAP_EXCEEDED,
                  "Household remaining annual benefit-year cap is exactly 0")
    if rem_cat == 0:
        raise_err(ERR_CATEGORY_CAP_EXCEEDED,
                  "Household remaining category cap is exactly 0")
    return rem_annual, rem_cat


def latest_passed_verification(application_id):
    """Latest PASSED VendorVerification for the application (by created_at)."""
    passed = [v for v in db.verifications.values()
              if v["application_id"] == application_id and v["status"] == "PASSED"]
    if not passed:
        return None
    passed.sort(key=lambda v: (v["created_at"], v["id"]))
    return passed[-1]


def determine_award_amount(application, policy, rem_annual, rem_cat):
    """award_amount_determination: min(requested, confirmed, rem_annual, rem_cat)."""
    verification = latest_passed_verification(application["id"])
    confirmed = verification["confirmed_amount_cents"] if verification else 0
    award = min(application["requested_amount_cents"], confirmed,
                rem_annual, rem_cat)
    if award == 0:
        # Caps are known non-zero (checked earlier), so this arises from a
        # zero confirmed amount.
        raise_err(ERR_INVALID_REQUEST,
                  "Computed award amount is zero (confirmed amount was 0)")
    return award


# ---------------------------------------------------------------------------
# Funding source balances (calculation: source_balance_reconciliation)
# ---------------------------------------------------------------------------

def recompute_source(source):
    reserved = 0
    committed = 0
    for a in db.allocations.values():
        if a["funding_source_id"] != source["id"]:
            continue
        if a["status"] == "RESERVED":
            reserved += a["allocated_cents"] - a["consumed_cents"]
            committed += a["consumed_cents"]
        elif a["status"] == "CONSUMED":
            committed += a["consumed_cents"]
        elif a["status"] == "RELEASED":
            committed += a["consumed_cents"]
    source["reserved_cents"] = reserved
    source["committed_cents"] = committed
    source["available_cents"] = (
        source["total_budget_cents"] - committed - reserved)


def refresh_source_status(source):
    """Automatic ACTIVE <-> EXHAUSTED transitions based on availability."""
    if source["status"] == "ACTIVE" and source["available_cents"] == 0:
        source["status"] = "EXHAUSTED"
        touch(source)
    elif source["status"] == "EXHAUSTED" and source["available_cents"] > 0:
        source["status"] = "ACTIVE"
        touch(source)


def source_household_room(source, household_id, year):
    """max_per_household_cents minus allocations to this household's
    non-VOIDED current-year awards from this source."""
    used = 0
    for a in db.allocations.values():
        if a["funding_source_id"] != source["id"]:
            continue
        award = db.awards[a["award_id"]]
        if award["status"] == "VOIDED" or award["benefit_year"] != year:
            continue
        app = db.applications[award["application_id"]]
        if app["household_id"] == household_id:
            used += a["allocated_cents"]
    return source["max_per_household_cents"] - used


# ---------------------------------------------------------------------------
# Allocation waterfall (calculation: allocation_waterfall)
# ---------------------------------------------------------------------------

def compatible_sources(application, household_id):
    """ACTIVE sources matching category, period, availability and room."""
    now = db.clock.now()
    year = now.year
    result = []
    for s in db.funding_sources.values():
        if s["status"] != "ACTIVE":
            continue
        if application["category"] not in s["allowed_categories"]:
            continue
        if not (db.parse_iso(s["period_start"]) <= now
                < db.parse_iso(s["period_end"])):
            continue
        if s["available_cents"] <= 0:
            continue
        room = source_household_room(s, household_id, year)
        if room <= 0:
            continue
        result.append((s, room))
    # Rank: (1) len(allowed_categories) ASC, (2) period_end ASC,
    #       (3) created_at ASC
    result.sort(key=lambda t: (len(t[0]["allowed_categories"]),
                               db.parse_iso(t[0]["period_end"]),
                               t[0]["created_at"],
                               t[0]["id"]))
    return result


def run_allocation_waterfall(award, application, award_amount):
    """Create RESERVED FundingAllocations across ranked compatible sources.

    Atomic: if the sweep cannot cover the full award, raises
    ERR_FUNDS_EXHAUSTED and nothing persists (callers must not have committed
    anything yet — this function builds allocations only on success).
    """
    household_id = application["household_id"]
    ranked = compatible_sources(application, household_id)
    remaining = award_amount
    plan = []
    for rank, (source, room) in enumerate(ranked):
        if remaining <= 0:
            break
        take = min(remaining, source["available_cents"], room)
        if take <= 0:
            continue
        plan.append((source, rank, take))
        # Simulate the running accumulator: the take commits before the next
        # source is evaluated.
        remaining -= take
    if remaining > 0:
        raise_err(ERR_FUNDS_EXHAUSTED,
                  "Allocation waterfall cannot cover the full computed award")
    # Commit
    created = []
    for source, rank, take in plan:
        alloc = stamp_new({
            "award_id": award["id"],
            "funding_source_id": source["id"],
            "allocated_cents": take,
            "consumed_cents": 0,
            "rank_order": rank,
            "status": "RESERVED",
        })
        db.allocations[alloc["id"]] = alloc
        recompute_source(source)
        refresh_source_status(source)
        created.append(alloc)
    return created


# ---------------------------------------------------------------------------
# Approve / promote shared workflow
# ---------------------------------------------------------------------------

def execute_approval(application, policy):
    """Compute the award and run the waterfall; create the award entity.

    Caller has already run check_fiscal_eligibility and obtained
    (rem_annual, rem_cat). Returns the created AssistanceAward.
    """
    rem_annual, rem_cat = check_fiscal_eligibility(application, policy)
    award_amount = determine_award_amount(application, policy,
                                          rem_annual, rem_cat)
    award = stamp_new({
        "application_id": application["id"],
        "policy_id": policy["id"],
        "awarded_amount_cents": award_amount,
        "benefit_year": db.clock.now().year,
        "status": "ACTIVE",
    })
    # Waterfall runs first and is atomic; only persist the award on success.
    run_allocation_waterfall(award, application, award_amount)
    db.awards[award["id"]] = award
    application["active_award_id"] = award["id"]
    return award


# ---------------------------------------------------------------------------
# Appeal window (calculation: appeal_window_check)
# ---------------------------------------------------------------------------

def appeal_deadline(application):
    policy = db.policies.get(application["policy_id"])
    days = policy["appeal_window_days"] if policy else 30
    return db.parse_iso(application["denied_at"]) + timedelta(days=days)
