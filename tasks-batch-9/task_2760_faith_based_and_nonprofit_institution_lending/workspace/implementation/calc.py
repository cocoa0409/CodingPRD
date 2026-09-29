"""Business calculations (PRD sections 2.6, 2.7, 3.1, 3.3-3.9).

Every rounding mode here is pinned by PRD section 2.6:
  * ratios and fractions  -> round half up to 4 decimal places
  * mission_impact_score  -> round half up to 2 decimal places
  * money                 -> truncation toward zero (flooring)
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

import store

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

MIN_GIVING_PERIODS = 4
INTERNAL_HAIRCUT_PCT = Decimal("0.15")
INTERNAL_FACTOR = Decimal("1") - INTERNAL_HAIRCUT_PCT

MIN_DSCR = Decimal("1.2")
TERM_FACTOR_BY_TERM_MONTHS = {
    120: Decimal("5.5"),
    180: Decimal("7.0"),
    240: Decimal("8.5"),
}
PLEDGE_ADVANCE_LTV = Decimal("0.6")

ATTRITION_PCT_BY_TIER = {
    "LEAD": Decimal("0.05"),
    "MAJOR": Decimal("0.12"),
    "GENERAL": Decimal("0.22"),
}
MISSED_PAYMENT_PENALTY_PCT = Decimal("0.15")
ATTRITION_RATE_CEILING = Decimal("0.6")
CAMPAIGN_MATURITY_PCT = Decimal("0.9")
CAMPAIGN_UNDERPERFORM_PCT = Decimal("0.8")
AUTO_LAPSE_MISSED_COUNT = 3

ADVANCE_RATE_BY_ALT_USE_SCORE = {
    1: Decimal("0.40"),
    2: Decimal("0.50"),
    3: Decimal("0.60"),
    4: Decimal("0.70"),
    5: Decimal("0.75"),
}
ADVANCE_RATE_CAP_BY_ASSET_TYPE = {
    "SANCTUARY": Decimal("0.55"),
    "EDUCATION_WING": Decimal("0.65"),
    "PARSONAGE": Decimal("0.70"),
    "LAND": Decimal("0.50"),
    "FELLOWSHIP_HALL": Decimal("0.60"),
    "DONOR_RESTRICTED_ENDOWMENT": Decimal("0.00"),
}
LIEN_FACTOR_BY_POSITION = {
    1: Decimal("1.00"),
    2: Decimal("0.60"),
    3: Decimal("0.00"),
}
APPRAISAL_SEASONING_DAYS = 365
SEASONED_APPRAISAL_FACTOR = Decimal("0.90")
APPRAISAL_STALE_DAYS = 730
LIEN_RELEASE_BUFFER_DAYS = 30

RETAINAGE_TIER_1_PCT = Decimal("0.10")
RETAINAGE_TIER_2_PCT = Decimal("0.05")
RETAINAGE_TIER_3_PCT = Decimal("0.00")
RETAINAGE_TIER_1_CEILING = Decimal("0.5000")
RETAINAGE_TIER_2_CEILING = Decimal("0.9000")
INSPECTION_FEE_CENTS = 45000

WEIGHT_MEMBERSHIP = Decimal("0.35")
WEIGHT_GIVING = Decimal("0.25")
WEIGHT_COMMUNITY = Decimal("0.20")
WEIGHT_DENOMINATIONAL = Decimal("0.20")
COMMUNITY_POINTS_PER_PROGRAM = 20
COMMUNITY_POINTS_CAP = 100
PARTIAL_FORGIVENESS_MIN_SCORE = Decimal("92.00")
FORBEARANCE_MIN_SCORE = Decimal("50.00")

AUDITED_ONLY = "AUDITED_ONLY"
BLENDED = "BLENDED"
GIVING_BASES = (AUDITED_ONLY, BLENDED)

LENDER_CONSERVATIVE = "LENDER_CONSERVATIVE"
SPONSOR_OPTIMISTIC = "SPONSOR_OPTIMISTIC"
VALUATION_BASES = (LENDER_CONSERVATIVE, SPONSOR_OPTIMISTIC)


# ---------------------------------------------------------------------------
# rounding primitives
# ---------------------------------------------------------------------------


def rhu(value, places):
    """Round half up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_money(value):
    """Truncate toward zero to whole cents."""
    return int(Decimal(value).to_integral_value(rounding=ROUND_DOWN))


def cents_to_dollars(cents):
    """Round-half-up division by 100 (PRD section 2.6)."""
    return int(rhu(Decimal(cents) / Decimal(100), 0))


def num(value):
    """Render a Decimal ratio as a JSON number."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# the four-period window (PRD section 3.1)
# ---------------------------------------------------------------------------


def institution_periods(institution_id):
    return [p for p in store.giving_periods.values()
            if p.get("institution_id") == institution_id]


def candidate_periods(institution_id, as_of):
    """Periods whose period_end is at or before as_of, newest first."""
    rows = [p for p in institution_periods(institution_id)
            if p["_period_end_dt"] <= as_of]
    rows.sort(key=lambda p: p["_seq"])
    rows.sort(key=lambda p: p["_period_end_dt"], reverse=True)
    return rows


def window_periods(institution_id, as_of, basis):
    rows = candidate_periods(institution_id, as_of)
    if basis == AUDITED_ONLY:
        rows = [p for p in rows if p.get("source") == "AUDITED"]
    return rows[:MIN_GIVING_PERIODS]


def per_period_unrestricted(period):
    value = (period["total_contributions_cents"]
             - period["restricted_contributions_cents"]
             - period["donor_restricted_endowment_draw_cents"])
    return value if value > 0 else 0


def basis_contribution(period, basis):
    """The period's unrestricted contribution under the basis in force."""
    raw = per_period_unrestricted(period)
    if basis == BLENDED and period.get("source") == "INTERNAL":
        return floor_money(Decimal(raw) * INTERNAL_FACTOR)
    return raw


# ---------------------------------------------------------------------------
# C1 institution_unrestricted_giving_base
# ---------------------------------------------------------------------------


def giving_base_cents(institution_id, as_of, basis):
    window = window_periods(institution_id, as_of, basis)
    if len(window) < MIN_GIVING_PERIODS:
        return 0
    return sum(basis_contribution(p, basis) for p in window)


# ---------------------------------------------------------------------------
# C2 net_available_for_debt_service_dollars — PINNED rounding order:
# round each period to whole dollars first, then sum.
# ---------------------------------------------------------------------------


def net_available_dollars(institution_id, as_of, basis):
    window = window_periods(institution_id, as_of, basis)
    if len(window) < MIN_GIVING_PERIODS:
        return 0
    total = 0
    for period in window:
        net = basis_contribution(period, basis) - period["operating_expense_cents"]
        if net < 0:
            net = 0
        total += cents_to_dollars(net)
    return total


# ---------------------------------------------------------------------------
# membership_trend_pct (PRD section 3.1)
# ---------------------------------------------------------------------------


def membership_trend_pct(institution_id, as_of, basis):
    window = window_periods(institution_id, as_of, basis)
    if len(window) < MIN_GIVING_PERIODS:
        return None
    newest = window[0]
    oldest = window[-1]
    old = oldest["member_household_count"]
    if old == 0:
        return None
    delta = newest["member_household_count"] - old
    return rhu(Decimal(delta) / Decimal(old), 4)


# ---------------------------------------------------------------------------
# institution-level reporting basis
# ---------------------------------------------------------------------------


def period_counts(institution_id):
    rows = institution_periods(institution_id)
    audited = len([p for p in rows if p.get("source") == "AUDITED"])
    return len(rows), audited


def mandated_basis(institution_id):
    """AUDITED_ONLY when audited_period_count >= 4, BLENDED otherwise."""
    _total, audited = period_counts(institution_id)
    return AUDITED_ONLY if audited >= MIN_GIVING_PERIODS else BLENDED


def institution_computed(institution):
    """The five figures an institution read reports, computed on the clock."""
    institution_id = institution["id"]
    total, audited = period_counts(institution_id)
    basis = AUDITED_ONLY if audited >= MIN_GIVING_PERIODS else BLENDED
    as_of = store.clock_now()
    if total < MIN_GIVING_PERIODS:
        base = 0
        net = 0
    else:
        base = giving_base_cents(institution_id, as_of, basis)
        net = net_available_dollars(institution_id, as_of, basis)
    return {
        "period_count": total,
        "audited_period_count": audited,
        "unrestricted_giving_base_cents": base,
        "net_available_for_debt_service_dollars": net,
        "membership_trend_pct": membership_trend_pct(institution_id, as_of, basis),
    }


# ---------------------------------------------------------------------------
# C4 pledge attrition and the two campaign valuations (PRD section 3.3)
# ---------------------------------------------------------------------------


def effective_attrition_pct(pledge):
    rate = ATTRITION_PCT_BY_TIER[pledge["donor_tier"]]
    if pledge.get("missed_payments_count", 0) >= 2:
        rate = rate + MISSED_PAYMENT_PENALTY_PCT
    if rate > ATTRITION_RATE_CEILING:
        rate = ATTRITION_RATE_CEILING
    return rhu(rate, 4)


def campaign_pledges(campaign_id):
    return store.by_seq(store.children(store.pledges, "pledge_campaign_id",
                                       campaign_id))


def campaign_projected_value(campaign, basis):
    rows = campaign_pledges(campaign["id"])
    collected = sum(p["collected_cents"] for p in rows)
    active = [p for p in rows if p["status"] == "ACTIVE"]
    if basis == SPONSOR_OPTIMISTIC:
        remaining_total = sum(p["pledged_amount_cents"] - p["collected_cents"]
                              for p in active)
        rate = (Decimal(campaign["sponsor_collection_rate_bps"])
                / Decimal(10000))
        return collected + floor_money(Decimal(remaining_total) * rate)
    total = collected
    for pledge in active:
        remaining = pledge["pledged_amount_cents"] - pledge["collected_cents"]
        rate = effective_attrition_pct(pledge)
        total += floor_money(Decimal(remaining) * (Decimal(1) - rate))
    return total


def underperform_threshold_cents(campaign):
    return floor_money(Decimal(campaign["goal_cents"]) * CAMPAIGN_UNDERPERFORM_PCT)


def maturity_threshold_cents(campaign):
    return floor_money(Decimal(campaign["goal_cents"]) * CAMPAIGN_MATURITY_PCT)


def campaign_buckets(campaign):
    rows = campaign_pledges(campaign["id"])
    return {
        "total_pledged_cents": sum(p["pledged_amount_cents"] for p in rows),
        "active_pledged_cents": sum(p["pledged_amount_cents"] for p in rows
                                    if p["status"] == "ACTIVE"),
        "lapsed_pledged_cents": sum(p["pledged_amount_cents"] for p in rows
                                    if p["status"] == "LAPSED"),
        "fulfilled_pledged_cents": sum(p["pledged_amount_cents"] for p in rows
                                       if p["status"] == "FULFILLED"),
        "collected_to_date_cents": sum(p["collected_cents"] for p in rows),
    }


def cascade_underperforming(campaign):
    """Push PLEDGE_ADVANCE applications in UNDERWRITING to REVISION_REQUESTED."""
    for app in store.by_seq(store.loan_applications.values()):
        if app.get("pledge_campaign_id") != campaign["id"]:
            continue
        if app.get("purpose") != "PLEDGE_ADVANCE":
            continue
        if app.get("status") != "UNDERWRITING":
            continue
        app["status"] = "REVISION_REQUESTED"
        app["revision_reason"] = "PLEDGE_CAMPAIGN_UNDERPERFORMING"
        app["revision_count"] = app.get("revision_count", 0) + 1
        store.touch(app)


def recompute_campaign(campaign):
    """Rewrite the buckets, both valuations and the underperformance gate."""
    campaign.update(campaign_buckets(campaign))
    campaign["attrition_adjusted_value_cents"] = campaign_projected_value(
        campaign, LENDER_CONSERVATIVE)
    campaign["sponsor_projected_value_cents"] = campaign_projected_value(
        campaign, SPONSOR_OPTIMISTIC)
    conservative = campaign["attrition_adjusted_value_cents"]
    floor80 = underperform_threshold_cents(campaign)
    floor90 = maturity_threshold_cents(campaign)
    if campaign["status"] == "OPEN":
        if campaign["total_pledged_cents"] >= floor90 and conservative < floor80:
            campaign["status"] = "UNDERPERFORMING"
            store.touch(campaign)
            cascade_underperforming(campaign)
    elif campaign["status"] == "UNDERPERFORMING":
        if conservative >= floor80:
            campaign["status"] = "OPEN"
    store.touch(campaign)


# ---------------------------------------------------------------------------
# C5 collateral_special_purpose_lending_value (PRD section 3.4)
# ---------------------------------------------------------------------------


def appraisal_age_days(asset, as_of=None):
    as_of = as_of if as_of is not None else store.clock_now()
    return store.days_between(asset["_appraisal_date_dt"], as_of)


def lending_value_cents(asset):
    score_rate = ADVANCE_RATE_BY_ALT_USE_SCORE[asset["alternative_use_score"]]
    type_cap = ADVANCE_RATE_CAP_BY_ASSET_TYPE[asset["asset_type"]]
    effective = score_rate if score_rate < type_cap else type_cap
    position = asset.get("lien_position")
    if position is None:
        position = 1
    if position > 3:
        position = 3
    if position < 1:
        position = 1
    lien_factor = LIEN_FACTOR_BY_POSITION[position]
    age = appraisal_age_days(asset)
    seasoning = (SEASONED_APPRAISAL_FACTOR if age > APPRAISAL_SEASONING_DAYS
                 else Decimal("1.00"))
    v1 = floor_money(Decimal(asset["appraised_value_cents"]) * effective)
    v2 = floor_money(Decimal(v1) * lien_factor)
    return floor_money(Decimal(v2) * seasoning)


def revalue_asset(asset):
    asset["lending_value_cents"] = lending_value_cents(asset)


# ---------------------------------------------------------------------------
# C6 maximum_supportable_principal (PRD section 3.5)
# ---------------------------------------------------------------------------


def assigned_assets(application_id):
    return store.by_seq(store.children(store.collateral_assets,
                                       "assigned_loan_application_id",
                                       application_id))


def first_lien_value_cents(application_id):
    return sum(a["lending_value_cents"] for a in assigned_assets(application_id)
               if a.get("lien_position") == 1)


def max_supportable(application, net_dollars):
    """Returns (max_supportable_principal_cents, binding_cap)."""
    institution = store.institutions.get(application.get("institution_id"))
    packet = store.governance_authorizations.get(
        application.get("governance_authorization_id"))
    campaign = store.pledge_campaigns.get(application.get("pledge_campaign_id"))

    capacity_ads_dollars = floor_money(Decimal(net_dollars or 0) / MIN_DSCR)
    term_factor = TERM_FACTOR_BY_TERM_MONTHS.get(application.get("term_months"))
    if term_factor is None:
        ds_capacity_cents = 0
    else:
        ds_capacity_cents = floor_money(
            Decimal(capacity_ads_dollars) * term_factor) * 100

    caps = [("DEBT_SERVICE", ds_capacity_cents),
            ("COLLATERAL", first_lien_value_cents(application["id"]))]
    if institution is not None:
        caps.append(("BYLAWS_CAP", institution["bylaws_borrowing_cap_cents"]))
    if packet is not None:
        caps.append(("AUTHORIZED_AMOUNT", packet["authorized_amount_cents"]))
    if application.get("purpose") == "PLEDGE_ADVANCE" and campaign is not None:
        caps.append(("PLEDGE_ADVANCE_LTV", floor_money(
            Decimal(campaign["attrition_adjusted_value_cents"])
            * PLEDGE_ADVANCE_LTV)))

    best_name, best_value = caps[0]
    for name, value in caps[1:]:
        if value < best_value:
            best_name, best_value = name, value
    return best_value, best_name


# ---------------------------------------------------------------------------
# C7 draw_net_disbursement (PRD section 3.7)
# ---------------------------------------------------------------------------


def waterfall(loan, approved_amount_cents):
    gross = approved_amount_cents
    principal = loan["principal_cents"]
    post_draw_gross = loan["disbursed_principal_cents"] + gross
    if principal > 0:
        bps = (post_draw_gross * 10000) // principal
    else:
        bps = 0
    completion_pct = (Decimal(bps) / Decimal(10000)).quantize(Decimal("0.0001"))

    if completion_pct < RETAINAGE_TIER_1_CEILING:
        rate = RETAINAGE_TIER_1_PCT
    elif completion_pct < RETAINAGE_TIER_2_CEILING:
        rate = RETAINAGE_TIER_2_PCT
    else:
        rate = RETAINAGE_TIER_3_PCT
    retainage_cents = floor_money(Decimal(gross) * rate)

    pool = gross - retainage_cents
    shortfall = loan["interest_reserve_shortfall_cents"]
    bucket1 = pool if pool < shortfall else shortfall
    if bucket1 < 0:
        bucket1 = 0
    pool -= bucket1
    bucket2 = pool if pool < INSPECTION_FEE_CENTS else INSPECTION_FEE_CENTS
    if bucket2 < 0:
        bucket2 = 0
    pool -= bucket2
    bucket3 = pool
    return {
        "completion_pct_at_disbursement": completion_pct,
        "retainage_cents": retainage_cents,
        "interest_reserve_applied_cents": bucket1,
        "inspection_fee_cents": bucket2,
        "net_disbursed_cents": bucket3,
    }


# ---------------------------------------------------------------------------
# C8 mission_impact_score (PRD section 3.9)
# ---------------------------------------------------------------------------


def _trend_points(delta, old):
    """100 / 70 / 40 / 10 on the four-step decline scale, exact arithmetic."""
    if old == 0:
        return 100
    if delta >= 0:
        return 100
    if delta * 100 >= -5 * old:
        return 70
    if delta * 100 >= -15 * old:
        return 40
    return 10


def mission_score(institution, denominational_support_letter):
    as_of = store.clock_now()
    window = candidate_periods(institution["id"], as_of)[:MIN_GIVING_PERIODS]
    if window:
        newest = window[0]
        oldest = window[-1]
        membership_points = _trend_points(
            newest["member_household_count"] - oldest["member_household_count"],
            oldest["member_household_count"])
        giving_points = _trend_points(
            per_period_unrestricted(newest) - per_period_unrestricted(oldest),
            per_period_unrestricted(oldest))
    else:
        membership_points = 100
        giving_points = 100
    community_points = institution.get("community_program_count", 0) * \
        COMMUNITY_POINTS_PER_PROGRAM
    if community_points > COMMUNITY_POINTS_CAP:
        community_points = COMMUNITY_POINTS_CAP
    denominational_points = 100 if denominational_support_letter else 0
    score = rhu(
        WEIGHT_MEMBERSHIP * Decimal(membership_points)
        + WEIGHT_GIVING * Decimal(giving_points)
        + WEIGHT_COMMUNITY * Decimal(community_points)
        + WEIGHT_DENOMINATIONAL * Decimal(denominational_points), 2)
    return {
        "membership_trend_points": membership_points,
        "giving_trend_points": giving_points,
        "community_points": community_points,
        "denominational_points": denominational_points,
        "mission_impact_score": score,
    }


# ---------------------------------------------------------------------------
# C9 loan_risk_posture (PRD section 3.8) and the RESTRICTED cascade
# ---------------------------------------------------------------------------


def derive_posture(loan):
    loan_id = loan["id"]
    plans = store.children(store.workout_plans, "loan_id", loan_id)
    if any(p["status"] == "APPROVED" for p in plans):
        return "WORKOUT_GATED"
    covenants = store.children(store.covenants, "loan_id", loan_id)
    if any(c["status"] == "BREACHED" for c in covenants):
        return "RESTRICTED"
    if any(c["status"] == "BREACH_PENDING_CURE" for c in covenants):
        return "WATCH"
    return "OPEN"


def suspend_approved_draws(loan):
    for draw in store.by_seq(store.children(store.draw_requests, "loan_id",
                                            loan["id"])):
        if draw["status"] != "APPROVED":
            continue
        draw["status"] = "SUSPENDED"
        loan["reserved_draw_cents"] -= draw["approved_amount_cents"]
        store.touch(draw)


def recompute_posture(loan):
    """Re-derive risk_posture; PAID_OFF freezes the risk dimension."""
    if loan["servicing_status"] == "PAID_OFF":
        return
    previous = loan["risk_posture"]
    posture = derive_posture(loan)
    if posture == previous:
        return
    loan["risk_posture"] = posture
    store.touch(loan)
    if posture == "RESTRICTED":
        suspend_approved_draws(loan)


def free_commitment(loan):
    return loan["undrawn_commitment_cents"] - loan["reserved_draw_cents"]
