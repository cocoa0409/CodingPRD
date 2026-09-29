"""The nine calculation rules. Decimal + ROUND_HALF_UP everywhere; never float
arithmetic. PRD 2.6 pins three evaluation orders and they are honoured literally.
"""

from decimal import Decimal, ROUND_HALF_UP

D = Decimal


def dec(value):
    """Any JSON-sourced number into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return D("0")
    return D(str(value))


def rhu(value):
    """Round half up to a whole cent (integer)."""
    return int(dec(value).quantize(D("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places; returned as a float for JSON."""
    return float(dec(value).quantize(D("0.01"), rounding=ROUND_HALF_UP))


def q2(value):
    return dec(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


# =========================================================== 1 + 2. readiness ---
W_ENVIRONMENTAL = D("0.35")
W_UTILITY = D("0.25")
W_ACCESS = D("0.25")
W_ENTITLEMENT = D("0.15")
ENCUMBRANCE_PENALTY_PER_ITEM = D("3.00")
ENCUMBRANCE_PENALTY_CAP = D("12.00")
FEDERAL_PENALTY_PER_PCT = D("0.10")
READINESS_READY_THRESHOLD = D("70.00")
READINESS_CONDITIONAL_THRESHOLD = D("50.00")


def readiness_preliminary(assessment):
    """PRELIMINARY variant: unweighted mean of the four sub-scores, tier null."""
    total = (dec(assessment["environmental_score"]) + dec(assessment["utility_score"])
             + dec(assessment["access_score"]) + dec(assessment["entitlement_score"]))
    return rhu2(total / D("4")), None


def readiness_certified(assessment, federal_interest_pct):
    """CERTIFIED variant: weighted sum less two penalties, rounded exactly once."""
    weighted = (dec(assessment["environmental_score"]) * W_ENVIRONMENTAL
                + dec(assessment["utility_score"]) * W_UTILITY
                + dec(assessment["access_score"]) * W_ACCESS
                + dec(assessment["entitlement_score"]) * W_ENTITLEMENT)
    encumbrance_penalty = min(
        ENCUMBRANCE_PENALTY_CAP,
        ENCUMBRANCE_PENALTY_PER_ITEM * dec(assessment["encumbrance_count"]))
    federal_penalty = FEDERAL_PENALTY_PER_PCT * dec(federal_interest_pct)
    score = q2(weighted - encumbrance_penalty - federal_penalty)
    if score < 0:
        score = D("0.00")
    if score >= READINESS_READY_THRESHOLD:
        tier = "READY"
    elif score >= READINESS_CONDITIONAL_THRESHOLD:
        tier = "CONDITIONAL"
    else:
        tier = "NOT_READY"
    return float(score), tier


# ================================================= 3. permissible transfer floor ---
TSU_TIER_HIGH = D("75")
TSU_TIER_MID = D("50")
TSU_TIER_LOW = D("25")
TSU_RATE_HIGH = D("0.30")
TSU_RATE_MID = D("0.20")
TSU_RATE_LOW = D("0.10")
AFFORDABLE_BONUS_THRESHOLD_PCT = D("20")
AFFORDABLE_BONUS_RATE = D("0.05")
CREDIT_RATE_CAP = D("0.30")


def permissible_floor(appraised_value_cents, transit_supportive_use_pct,
                      affordable_units_pct, transfer_basis, federal_interest_pct):
    """Returns (transit_supportive_credit_cents, federal_interest_floor_cents,
    permissible_floor_cents). Steps 1-3 are identical under both variants."""
    appraised = dec(appraised_value_cents)
    tsu = dec(transit_supportive_use_pct)
    if tsu >= TSU_TIER_HIGH:
        rate = TSU_RATE_HIGH
    elif tsu >= TSU_TIER_MID:
        rate = TSU_RATE_MID
    elif tsu >= TSU_TIER_LOW:
        rate = TSU_RATE_LOW
    else:
        rate = D("0.00")
    if dec(affordable_units_pct) >= AFFORDABLE_BONUS_THRESHOLD_PCT:
        rate = rate + AFFORDABLE_BONUS_RATE
    if rate > CREDIT_RATE_CAP:
        rate = CREDIT_RATE_CAP
    credit_cents = rhu(appraised * rate)
    federal_floor_cents = rhu(appraised * dec(federal_interest_pct) / D("100"))
    if transfer_basis == "FMV_STRICT":
        floor_cents = int(appraised_value_cents)
    else:
        floor_cents = max(int(appraised_value_cents) - credit_cents, federal_floor_cents)
    return credit_cents, federal_floor_cents, floor_cents


# ==================================================== 4. proposal evaluation score ---
LEASE_CAPITALIZATION_YEARS = 20
VALUE_POINTS_CAP = D("40.00")
AFFORDABLE_POINTS_BASE = D("15.00")
AFFORDABLE_POINTS_PER_PCT = D("0.5")
AFFORDABLE_POINTS_CAP = D("25.00")
RIDERSHIP_POINTS_CAP = D("20.00")
RIDERSHIP_BOARDINGS_PER_POINT = D("50")
DESIGN_POINTS_PER_UNIT = D("0.15")
PREQUALIFICATION_PENALTY_POINTS = D("10.00")


def affordable_pct(affordable_units, total_units):
    return rhu2(D("100") * dec(affordable_units) / dec(total_units))


def evaluation_score(proposal, solicitation, developer):
    """Each component is rounded to 2dp BEFORE its cap and before summation."""
    if proposal["proposed_structure"] == "GROUND_LEASE":
        value_basis = dec(proposal["proposed_annual_rent_cents"]) * D(LEASE_CAPITALIZATION_YEARS)
    else:
        value_basis = dec(proposal["proposed_purchase_price_cents"])
    value_points = min(
        VALUE_POINTS_CAP,
        q2(VALUE_POINTS_CAP * value_basis / dec(solicitation["benchmark_value_cents"])))
    headroom = dec(proposal["affordable_pct"]) - dec(solicitation["affordable_housing_min_pct"])
    affordable_points = min(
        AFFORDABLE_POINTS_CAP,
        q2(AFFORDABLE_POINTS_BASE + AFFORDABLE_POINTS_PER_PCT * headroom))
    ridership_points = min(
        RIDERSHIP_POINTS_CAP,
        q2(dec(proposal["transit_ridership_uplift"]) / RIDERSHIP_BOARDINGS_PER_POINT))
    design_points = q2(DESIGN_POINTS_PER_UNIT * dec(proposal["design_compliance_score"]))
    raw = value_points + affordable_points + ridership_points + design_points
    penalty = D("0.00") if developer.get("prequalified") else PREQUALIFICATION_PENALTY_POINTS
    score = q2(raw - penalty)
    if score < 0:
        score = D("0.00")
    return float(score)


# ============================================================= 5. proposal ranking ---
def rank_candidates(candidates):
    """evaluation_score DESC, affordable_pct DESC, created_at ASC. `id` never
    participates; the hidden insertion sequence stands in for created_at so that
    two records minted at the same logical instant keep their true order."""
    ordered = sorted(
        candidates,
        key=lambda p: (-dec(p["evaluation_score"]), -dec(p["affordable_pct"]),
                       p["created_at"], p["_seq"]))
    return ordered


# ================================== 6 + 7. annual revenue and consideration value ---
CREDIT_TIER_T1_CENTS = 1000000
CREDIT_TIER_T2_CENTS = 2500000
CREDIT_TIER_T3_CENTS = 5000000
CREDIT_RATE_T1 = D("0.04")
CREDIT_RATE_T2 = D("0.08")
CREDIT_RATE_T3 = D("0.12")
AFFORDABLE_CREDIT_THRESHOLD = D("0.20")
AFFORDABLE_CREDIT_BONUS = D("0.03")
CREDIT_RATE_CEILING = D("0.15")


def agreement_money(agreement):
    """Returns (capital_credit_cents, annual_revenue_to_agency_cents,
    consideration_value_cents). The credit tier is keyed on the PRE-CREDIT
    subtotal, never on the post-credit total."""
    if agreement["structure"] == "GROUND_LEASE":
        base_component = int(agreement["base_rent_cents"])
    else:
        base_component = rhu(dec(agreement["purchase_price_cents"])
                             / dec(agreement["term_years"]))
    participation = rhu(dec(agreement["projected_gross_revenue_cents"])
                        * dec(agreement["revenue_share_pct"]))
    subtotal = base_component + participation
    if subtotal >= CREDIT_TIER_T3_CENTS:
        rate = CREDIT_RATE_T3
    elif subtotal >= CREDIT_TIER_T2_CENTS:
        rate = CREDIT_RATE_T2
    elif subtotal >= CREDIT_TIER_T1_CENTS:
        rate = CREDIT_RATE_T1
    else:
        rate = D("0.00")
    share = dec(agreement["affordable_units_committed"]) / dec(agreement["total_units"])
    if share >= AFFORDABLE_CREDIT_THRESHOLD:
        rate = rate + AFFORDABLE_CREDIT_BONUS
    if rate > CREDIT_RATE_CEILING:
        rate = CREDIT_RATE_CEILING
    capital_credit = rhu(dec(subtotal) * rate)
    annual_revenue = subtotal - capital_credit
    if agreement["structure"] == "GROUND_LEASE":
        consideration = annual_revenue * LEASE_CAPITALIZATION_YEARS
    else:
        consideration = int(agreement["purchase_price_cents"])
    return capital_credit, annual_revenue, consideration


def apply_agreement_money(agreement):
    credit, annual, consideration = agreement_money(agreement)
    agreement["capital_credit_cents"] = credit
    agreement["annual_revenue_to_agency_cents"] = annual
    agreement["consideration_value_cents"] = consideration


# ================================================= 8. maintenance cost allocation ---
def maintenance_allocation(facility, items):
    """PINNED: round each line to whole cents FIRST, then sum. The agency absorbs
    the residue so the two shares always add back to the total exactly."""
    responsibility = facility["maintenance_responsibility"]
    if responsibility == "DEVELOPER":
        share = D("1.00")
    elif responsibility == "AGENCY":
        share = D("0.00")
    else:
        share = dec(facility["cost_share_pct_developer"])
    developer_share = 0
    for item in items:
        developer_share += rhu(dec(item["cost_cents"]) * share)
    total_cost = sum(int(item["cost_cents"]) for item in items)
    return float(share), total_cost, developer_share, total_cost - developer_share


# ==================================================== 9. federal interest amount ---
def federal_interest_amount(basis_cents, site_area_share_pct):
    return rhu(dec(basis_cents) * dec(site_area_share_pct) / D("100"))


# ============================================== 10. staging capacity availability ---
def peak_occupancy(candidate_start, candidate_bays, conflicting):
    """Half-open intervals. `conflicting` is a list of (start, end, bays) tuples,
    already filtered to APPROVED windows on the same facility that overlap the
    candidate. Boundary set = {candidate.start} U {w.start}; at each boundary sum
    the bays of every conflicting window covering it."""
    boundaries = sorted(set([candidate_start] + [w[0] for w in conflicting]))
    peak = 0
    for boundary in boundaries:
        total = 0
        for start, end, bays in conflicting:
            if start <= boundary < end:
                total += int(bays)
        if total > peak:
            peak = total
    return int(candidate_bays) + peak
