"""Every computed quantity in the system (PRD 3.1-3.8).

All arithmetic is Decimal based. Every named intermediate rounding step in the
PRD is implemented as its own rounding — never deferred, never hoisted
(PRD 2.6).
"""

from datetime import timedelta
from decimal import Decimal

import constants as C
from db import D, ZERO, db, money, money_floor0, now


# ==========================================================================
# PRD 3.2 — the five-step bond determination
# ==========================================================================
def escalation_years(effective_date, clock_now):
    """Whole days between the estimate's effective date and the clock's current
    date, divided by 365, fractional part discarded, never below zero."""
    whole_days = (clock_now - effective_date).days
    if whole_days < 0:
        return 0
    return whole_days // C.DAYS_PER_ESCALATION_YEAR


def loaded_per_acre_cost(direct_cost_per_acre, years):
    raw = (
        D(direct_cost_per_acre)
        * (Decimal("1") + C.INDIRECT_COST_RATE)
        * ((Decimal("1") + C.ANNUAL_INFLATION_RATE) ** int(years))
    )
    return money(raw)


def basis_acres(permit):
    if permit["bond_basis"] == "INCREMENTAL":
        return money_floor0(permit["disturbed_acres"] - permit["reclaimed_acres_credited"])
    return D(permit["mining_plan_acres"])


def bond_required_amount(permit, estimate):
    """Steps: escalation years -> loaded per-acre cost -> acreage basis ->
    subtotal -> administrative fee -> statutory floor."""
    years = escalation_years(estimate["estimate_effective_date"], now())
    per_acre_loaded = loaded_per_acre_cost(estimate["direct_cost_per_acre"], years)
    acres = basis_acres(permit)
    subtotal = money(per_acre_loaded * acres)
    admin_fee = money(subtotal * C.ADMIN_FEE_RATE)
    if admin_fee < C.ADMIN_FEE_MIN:
        admin_fee = C.ADMIN_FEE_MIN
    if admin_fee > C.ADMIN_FEE_MAX:
        admin_fee = C.ADMIN_FEE_MAX
    required = money(subtotal + admin_fee)
    if required < C.STATUTORY_MINIMUM_BOND:
        required = C.STATUTORY_MINIMUM_BOND
    return money(required)


def accepted_estimate(permit_id):
    for estimate in db.estimates.values():
        if estimate["permit_id"] == permit_id and estimate["status"] == "ACCEPTED":
            return estimate
    return None


# ==========================================================================
# PRD 3.3 — credited value of a bond instrument
# ==========================================================================
def instrument_credited_amount(instrument, operator):
    kind = instrument["instrument_type"]
    face = D(instrument["face_amount"])
    if kind == "CASH":
        return money(face)
    if kind == "SURETY":
        multiplier = C.SURETY_RATING_MULTIPLIER.get(instrument["surety_naic_rating"])
        if multiplier is None:
            return ZERO
        return money(face * multiplier)
    if kind == "COLLATERAL":
        haircut = C.COLLATERAL_HAIRCUT[instrument["collateral_type"]]
        haircut_value = money(D(instrument["collateral_market_value"]) * (Decimal("1") - haircut))
        return money(min(haircut_value, face))
    # SELF_BOND
    if operator is None or operator["self_bond_status"] != "QUALIFIED":
        return ZERO
    headroom = self_bond_headroom(operator)
    return money(min(face, headroom))


def self_bond_exposure_amount(operator_id):
    """Sum of credited_amount over every ACCEPTED SELF_BOND instrument across
    every permit held by the operator (a statewide figure, PRD 3.1)."""
    total = ZERO
    for instrument in db.instruments.values():
        if instrument["instrument_type"] != "SELF_BOND" or instrument["status"] != "ACCEPTED":
            continue
        permit = db.permits.get(instrument["permit_id"])
        if permit is not None and permit["operator_id"] == operator_id:
            total = total + D(instrument["credited_amount"])
    return money(total)


def self_bond_headroom(operator):
    return money_floor0(
        D(operator["self_bond_capacity_amount"]) - self_bond_exposure_amount(operator["id"])
    )


# ==========================================================================
# PRD 3.1 — the self-bonding financial tests
# ==========================================================================
def operator_self_bond_capacity(operator):
    """Returns (passes, capacity)."""
    tnw = D(operator["tangible_net_worth"])
    fixed = D(operator["fixed_assets_in_state"])
    liabilities = D(operator["total_liabilities"])
    income = D(operator["net_income_prior_year"])

    leverage_ok = tnw >= money(liabilities * C.SELF_BOND_MIN_TNW_RATIO)
    profit_ok = income > 0

    if operator["elected_financial_test"] == "NET_WORTH_TEST":
        passes = leverage_ok and profit_ok and tnw >= C.SELF_BOND_MIN_TNW
        capacity = money(tnw * C.NET_WORTH_CAPACITY_RATE) if passes else ZERO
    else:
        passes = leverage_ok and profit_ok and fixed >= C.SELF_BOND_MIN_FIXED_ASSETS
        capacity = money(fixed * C.FIXED_ASSET_CAPACITY_RATE) if passes else ZERO
    return passes, capacity


# ==========================================================================
# PRD 3.5 — the bond release waterfall
# ==========================================================================
def per_acre_bond(permit):
    disturbed = D(permit["disturbed_acres"])
    if disturbed <= 0:
        return ZERO
    return money(D(permit["bond_required_amount"]) / disturbed)


def retention_floor(permit, phase):
    floor = money(D(permit["bond_required_amount"]) * C.PHASE_RETENTION_RATE[phase])
    if floor < C.STATUTORY_MINIMUM_BOND:
        floor = C.STATUTORY_MINIMUM_BOND
    return money(floor)


def available_headroom(permit, phase):
    return money_floor0(D(permit["bond_held_amount"]) - retention_floor(permit, phase))


def release_requested_amount(permit, phase, acres_requested):
    eligible = money(per_acre_bond(permit) * D(acres_requested) * C.PHASE_RELEASE_PCT[phase])
    available = available_headroom(permit, phase)
    return money(min(eligible, available))


# ==========================================================================
# PRD 3.6 — violation points and civil penalties
# ==========================================================================
def violation_history_points(operator_id, exclude_notice_id=None):
    cutoff = now() - timedelta(days=C.HISTORY_LOOKBACK_DAYS)
    prior_count = 0
    for notice in db.notices.values():
        if exclude_notice_id is not None and notice["id"] == exclude_notice_id:
            continue
        if notice["notice_status"] == "VACATED":
            continue
        permit = db.permits.get(notice["permit_id"])
        if permit is None or permit["operator_id"] != operator_id:
            continue
        if notice["created_at"] < cutoff:
            continue
        prior_count += 1
    return min(prior_count * C.HISTORY_POINTS_PER_PRIOR, C.HISTORY_POINTS_CAP)


def total_points(severity, negligence, duration, history):
    return min(severity + negligence + duration + history, C.TOTAL_POINTS_CAP)


def penalty_assessment_amount(notice, good_faith_level):
    base = money(D(notice["total_points"]) * C.DOLLARS_PER_POINT)

    if base > C.CREDIT_CAP_HIGH_BASE_THRESHOLD:
        credit_cap = C.CREDIT_CAP_HIGH
    elif base > C.CREDIT_CAP_LOW_BASE_THRESHOLD:
        credit_cap = C.CREDIT_CAP_LOW
    else:
        credit_cap = ZERO

    credit = money(base * C.GOOD_FAITH_RATE[good_faith_level])
    if credit > credit_cap:
        credit = credit_cap
    subtotal = money(base - credit)

    if notice["violation_class"] != "IMMINENT_HARM":
        surcharge_rate = ZERO
    elif subtotal > C.IMMINENT_HARM_SURCHARGE_HIGH_THRESHOLD:
        surcharge_rate = C.IMMINENT_HARM_SURCHARGE_HIGH
    elif subtotal > C.IMMINENT_HARM_SURCHARGE_LOW_THRESHOLD:
        surcharge_rate = C.IMMINENT_HARM_SURCHARGE_LOW
    else:
        surcharge_rate = ZERO

    surcharge = money(subtotal * surcharge_rate)
    penalty = money(subtotal + surcharge)
    if penalty < C.MINIMUM_PENALTY:
        penalty = C.MINIMUM_PENALTY
    return money(penalty)


def operator_violation_points_total(operator_id):
    total = 0
    for notice in db.notices.values():
        if notice["notice_status"] not in ("ISSUED", "CESSATION_ORDERED"):
            continue
        permit = db.permits.get(notice["permit_id"])
        if permit is not None and permit["operator_id"] == operator_id:
            total += int(notice["total_points"])
    return total


def operator_outstanding_penalty_balance(operator_id):
    total = ZERO
    for notice in db.notices.values():
        if notice["penalty_status"] != "ASSESSED":
            continue
        permit = db.permits.get(notice["permit_id"])
        if permit is not None and permit["operator_id"] == operator_id:
            total = total + D(notice["penalty_amount"])
    return money(total)


# ==========================================================================
# PRD 3.8 — legacy priority score and funding queue
# ==========================================================================
def legacy_priority_score(site):
    acre_points = money(D(site["acres_affected"]) * C.ACRE_POINT_RATE)
    if acre_points > C.ACRE_POINTS_CAP:
        acre_points = C.ACRE_POINTS_CAP
    raw = (
        C.HAZARD_WEIGHT[site["hazard_class"]]
        + D(site["public_safety_score"]) * C.PUBLIC_SAFETY_WEIGHT
        + D(site["water_quality_score"]) * C.WATER_QUALITY_WEIGHT
        + acre_points
    )
    score = money(raw)
    if score > C.SCORE_CAP:
        score = C.SCORE_CAP
    return money(score)


def funding_queue():
    candidates = [
        site
        for site in db.mine_sites.values()
        if site["site_class"] == "ABANDONED_LEGACY" and site["funding_status"] == "NOMINATED"
    ]
    return sorted(
        candidates,
        key=lambda s: (
            -D(s["legacy_priority_score"]),
            -D(s["unfunded_reclamation_need"]),
            s["created_at"],
            s["_seq"],
        ),
    )


def total_awarded_funding():
    total = ZERO
    for site in db.mine_sites.values():
        total = total + D(site["awarded_funding_amount"])
    return money(total)


# ==========================================================================
# PRD 3.7 — forfeiture settlement
# ==========================================================================
def forfeiture_finalization_settlement(state_estimate, forfeited_bond_amount):
    deficiency = money_floor0(D(state_estimate) - D(forfeited_bond_amount))
    return deficiency, ZERO


def forfeiture_completion_settlement(actual_cost, forfeited_bond_amount):
    deficiency = money_floor0(D(actual_cost) - D(forfeited_bond_amount))
    surplus = money_floor0(D(forfeited_bond_amount) - D(actual_cost))
    return deficiency, surplus


# ==========================================================================
# InspectorProfile derived counter (PRD 3.1)
# ==========================================================================
def scheduled_inspection_count(inspector_id):
    count = 0
    for inspection in db.inspections.values():
        if inspection["inspector_id"] == inspector_id and inspection["status"] == "SCHEDULED":
            count += 1
    return count
