"""Every deterministic calculation of the ledger (SCAFFOLD §1.3 / PRD §2.10, §3).

All arithmetic is exact integer arithmetic; every rounding step uses
``round_half_up`` (nearest integer, ties away from zero) and happens at exactly
the point in the sequence the PRD pins it to.
"""

from datetime import datetime, timezone

import store
from errors import fail
from numeric import rhu
from response import format_instant
from validation import parse_date

# --- constants -------------------------------------------------------------
HISTORY_MATURITY_MONTHS = 12
HISTORY_MATURITY_UNITS = 5000

LIFETIME_DEVELOPMENT_FACTOR_BPS = 25000
ANALOG_BLEND_ENG_WEIGHT_BPS = 6000

LABOR_RATE_CENTS_PER_HOUR = 9500

POSTURE_ELEVATED_BPS = 8000
POSTURE_CONSTRAINED_BPS = 10000

TREND_TIER_REDUNDANT_MAX_BPS = 8000
TREND_TIER_SUFFICIENT_MAX_BPS = 12000
TREND_TIER_DEFICIENT_MAX_BPS = 15000

CLAIMS_CURVE_Q1_BPS = 1000
CLAIMS_CURVE_Q2_BPS = 3000
CLAIMS_CURVE_Q3_BPS = 6000
CLAIMS_CURVE_Q4_BPS = 10000

LAG_FACTOR_PER_MONTH_BPS = 1200
LAG_FACTOR_CAP_BPS = 6000
IBNR_CAP_BPS = 15000
IBNR_FLOOR_CENTS_PER_UNIT = 25

COLLECTABILITY_BPS = {"HIGH": 9000, "MEDIUM": 6000, "LOW": 2500, "IMPAIRED": 0}
CREDIT_BASE_RATING = {"AAA": "HIGH", "BBB": "MEDIUM", "CCC": "LOW", "D": "IMPAIRED"}
DOWNGRADE_LADDER = ["HIGH", "MEDIUM", "LOW", "IMPAIRED"]
REALIZATION_HOLD_BPS = 7500
REALIZATION_WATCH_BPS = 4000

SIGNIFICANT_EXPOSURE_THRESHOLD_CENTS = 50_000_000
FIELD_ACTION_QUIET_BUFFER_DAYS = 30


# ---------------------------------------------------------------------------
# Small relational helpers
# ---------------------------------------------------------------------------
def vintages_of_family(family_id):
    return [v for v in store.all_rows("vintages") if v["family_id"] == family_id]


def vintage_ids_of_family(family_id):
    return {v["id"] for v in store.all_rows("vintages") if v["family_id"] == family_id}


def observations_of_family(family_id):
    ids = vintage_ids_of_family(family_id)
    return [o for o in store.all_rows("observations") if o["vintage_id"] in ids]


def observations_of_vintage(vintage_id):
    return [o for o in store.all_rows("observations") if o["vintage_id"] == vintage_id]


def failure_modes_of_family(family_id):
    return [m for m in store.all_rows("failure_modes") if m["family_id"] == family_id]


def accruals_of_family(family_id):
    ids = vintage_ids_of_family(family_id)
    return [a for a in store.all_rows("accruals") if a["vintage_id"] in ids]


def field_actions_of_family(family_id):
    return [f for f in store.all_rows("field_actions") if f["family_id"] == family_id]


def remedy_options_of_action(field_action_id):
    return [
        o for o in store.all_rows("remedy_options") if o["field_action_id"] == field_action_id
    ]


def recoveries_of_supplier(supplier_id):
    return [r for r in store.all_rows("recoveries") if r["supplier_id"] == supplier_id]


def family_of_vintage(vintage):
    return store.get("families", vintage["family_id"])


# ---------------------------------------------------------------------------
# ProductVintage.exposure_status
# ---------------------------------------------------------------------------
def compute_exposure_status(vintage):
    """ACTIVE while the logical clock is strictly earlier than warranty_expiry_date."""
    expiry = parse_date(vintage["warranty_expiry_date"])
    boundary = datetime(expiry.year, expiry.month, expiry.day, tzinfo=timezone.utc)
    return "ACTIVE" if store.logical_now() < boundary else "EXPIRED"


def apply_exposure_status(vintage):
    """Write exposure_status; returns True when the stored value actually moved."""
    new_status = compute_exposure_status(vintage)
    if vintage.get("exposure_status") != new_status:
        vintage["exposure_status"] = new_status
        return True
    return False


# ---------------------------------------------------------------------------
# calculations.history_maturity_classification
# ---------------------------------------------------------------------------
def history_maturity(family):
    observations = observations_of_family(family["id"])
    if observations:
        observed_history_months = max(o["months_in_service_to"] for o in observations)
    else:
        observed_history_months = 0
    observed_exposure_units = sum(
        v["units_shipped"]
        for v in vintages_of_family(family["id"])
        if v["exposure_status"] in ("ACTIVE", "EXPIRED")
    )
    mature = (
        observed_history_months >= HISTORY_MATURITY_MONTHS
        and observed_exposure_units >= HISTORY_MATURITY_UNITS
    )
    return {
        "observed_history_months": observed_history_months,
        "observed_exposure_units": observed_exposure_units,
        "units_sold_lifetime": observed_exposure_units,
        "history_maturity_status": "MATURE" if mature else "LIMITED",
    }


def apply_history_maturity(family):
    figures = history_maturity(family)
    changed = any(family.get(k) != v for k, v in figures.items())
    family.update(figures)
    return changed


# ---------------------------------------------------------------------------
# calculations.family_reserve_balance + family_reserve_posture (PRD §2.10)
# ---------------------------------------------------------------------------
def family_reserve_balance(family, hypothetical_post=None):
    """Full recompute from the four source aggregates, never an incremental delta.

    ``hypothetical_post`` lets the reserve-ceiling guard evaluate the balance that
    *would* result from counting one PROPOSED accrual as POSTED (which also drops
    the accrual it supersedes out of the POSTED filter).
    """
    family_id = family["id"]
    vintage_ids = vintage_ids_of_family(family_id)

    posted_accrual_total = 0
    for accrual in store.all_rows("accruals"):
        if accrual["vintage_id"] not in vintage_ids:
            continue
        status = accrual["status"]
        if hypothetical_post is not None:
            if accrual["id"] == hypothetical_post["id"]:
                status = "POSTED"
            elif (
                status == "POSTED"
                and accrual["period_id"] == hypothetical_post["period_id"]
                and accrual["vintage_id"] == hypothetical_post["vintage_id"]
            ):
                status = "SUPERSEDED"
        if status == "POSTED":
            posted_accrual_total += accrual["accrued_amount_cents"]

    approved_campaign_total = 0
    completed_execution_total = 0
    for action in field_actions_of_family(family_id):
        if action["approval_state"] == "APPROVED":
            approved_campaign_total += action["specific_accrual_cents"]
        if action["execution_state"] == "COMPLETED":
            completed_execution_total += action["executed_cost_cents"]

    applied_true_up_total = 0
    for review in store.all_rows("adequacy_reviews"):
        if review["family_id"] == family_id and review["true_up_applied"]:
            applied_true_up_total += review["recommended_true_up_cents"]

    return (
        posted_accrual_total
        + approved_campaign_total
        + applied_true_up_total
        - completed_execution_total
    )


def family_reserve_posture(balance_cents, reserve_cap_cents):
    ratio_bps = rhu(max(0, balance_cents) * 10000, reserve_cap_cents)
    if ratio_bps >= POSTURE_CONSTRAINED_BPS:
        return "CONSTRAINED"
    if ratio_bps >= POSTURE_ELEVATED_BPS:
        return "ELEVATED"
    return "NORMAL"


def apply_balance_and_posture(family):
    """Recompute the balance, then immediately re-derive the governance posture."""
    balance = family_reserve_balance(family)
    posture = family_reserve_posture(balance, family["reserve_cap_cents"])
    changed = (
        family.get("warranty_reserve_balance_cents") != balance
        or family.get("reserve_posture") != posture
    )
    family["warranty_reserve_balance_cents"] = balance
    family["reserve_posture"] = posture
    return changed


def apply_posture_only(family):
    posture = family_reserve_posture(
        family["warranty_reserve_balance_cents"], family["reserve_cap_cents"]
    )
    changed = family.get("reserve_posture") != posture
    family["reserve_posture"] = posture
    return changed


# ---------------------------------------------------------------------------
# calculations.warranty_accrual_amount
# ---------------------------------------------------------------------------
def warranty_accrual_amount(accrual):
    vintage = store.get("vintages", accrual["vintage_id"])
    family = family_of_vintage(vintage)
    units = vintage["units_shipped"]

    paid_to_date_cents = sum(o["paid_cost_cents"] for o in observations_of_vintage(vintage["id"]))

    if accrual["method"] == "HISTORICAL_RATE":
        own_observations = observations_of_vintage(vintage["id"])
        modes = []
        for mode in failure_modes_of_family(family["id"]):
            if any(o["failure_mode_id"] == mode["id"] for o in own_observations):
                modes.append(mode)
        modes.sort(key=lambda m: m["mode_code"])

        gross_ultimate_cents = 0
        expected_claim_rate_ppm = 0
        total_ult_claims = 0
        for mode in modes:
            claim_count_m = sum(
                o["claim_count"]
                for o in own_observations
                if o["failure_mode_id"] == mode["id"]
            )
            rate_ppm_m = rhu(claim_count_m * 1000000, units)
            ult_claims_m = rhu(
                rate_ppm_m * units * LIFETIME_DEVELOPMENT_FACTOR_BPS, 1000000 * 10000
            )
            gross_ultimate_cents += ult_claims_m * mode["cost_per_claim_cents"]
            expected_claim_rate_ppm += rate_ppm_m
            total_ult_claims += ult_claims_m

        if total_ult_claims == 0:
            cost_per_claim_basis_cents = 0
        else:
            cost_per_claim_basis_cents = rhu(gross_ultimate_cents, total_ult_claims)
    else:
        analog = store.get("families", family["analog_family_id"])
        analog_claims = sum(o["claim_count"] for o in observations_of_family(analog["id"]))
        analog_units = sum(
            v["units_shipped"]
            for v in vintages_of_family(analog["id"])
            if v["exposure_status"] in ("ACTIVE", "EXPIRED")
        )
        if analog_units == 0:
            analog_rate_ppm = 0
        else:
            analog_rate_ppm = rhu(analog_claims * 1000000, analog_units)
        analog_ultimate_ppm = rhu(analog_rate_ppm * LIFETIME_DEVELOPMENT_FACTOR_BPS, 10000)
        # PINNED: the two weighted terms are summed as exact whole numbers and the
        # sum is rounded exactly once.
        blended_rate_ppm = rhu(
            family["engineering_estimate_rate_ppm"] * ANALOG_BLEND_ENG_WEIGHT_BPS
            + analog_ultimate_ppm * (10000 - ANALOG_BLEND_ENG_WEIGHT_BPS),
            10000,
        )
        expected_claim_rate_ppm = blended_rate_ppm
        ult_claims = rhu(blended_rate_ppm * units, 1000000)
        cost_per_claim_basis_cents = family["standard_cost_per_claim_cents"]
        gross_ultimate_cents = ult_claims * family["standard_cost_per_claim_cents"]

    return {
        "expected_claim_rate_ppm": expected_claim_rate_ppm,
        "cost_per_claim_basis_cents": cost_per_claim_basis_cents,
        "paid_to_date_cents": paid_to_date_cents,
        "accrued_amount_cents": max(0, gross_ultimate_cents - paid_to_date_cents),
    }


# ---------------------------------------------------------------------------
# calculations.field_action_specific_accrual
# ---------------------------------------------------------------------------
def option_per_unit_expected_cents(option):
    per_unit_labor_cents = rhu(option["labor_hours_centi"] * LABOR_RATE_CENTS_PER_HOUR, 100)
    per_unit_gross_cents = (
        option["parts_cost_cents"] + per_unit_labor_cents + option["admin_cost_cents"]
    )
    # PINNED: the take-rate weighting is rounded to whole cents PER UNIT first.
    return rhu(per_unit_gross_cents * option["expected_take_rate_bps"], 10000)


def apply_specific_accrual(action, option):
    """Recompute the option's per-unit figure, then the action's specific accrual."""
    per_unit = option_per_unit_expected_cents(option)
    option_changed = option.get("per_unit_expected_cents") != per_unit
    option["per_unit_expected_cents"] = per_unit
    action["specific_accrual_cents"] = per_unit * action["affected_unit_count"]
    return option_changed


# ---------------------------------------------------------------------------
# calculations.remedy_option_selection — implicit (server-side) form
# ---------------------------------------------------------------------------
def select_cheapest_eligible_option(action):
    candidates = []
    for option in remedy_options_of_action(action["id"]):
        if not option["is_engineering_approved"]:
            continue
        if option["expected_take_rate_bps"] < 1:
            continue
        if action["is_safety_recall"] and option["remedy_class"] != "PERMANENT_REPAIR":
            continue
        candidates.append(option)
    if not candidates:
        return None
    candidates.sort(
        key=lambda o: (
            option_per_unit_expected_cents(o),
            o["expected_take_rate_bps"],
            o["created_at"],
            o["_seq"],
        )
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# calculations.booking_period_selection
# ---------------------------------------------------------------------------
def booking_period():
    candidates = [
        p for p in store.all_rows("periods") if p["status"] in ("OPEN", "ANALYSIS_LOCKED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]))
    candidates.sort(key=lambda p: p["period_code"], reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# calculations.adequacy_trend_adjustment
# ---------------------------------------------------------------------------
def adequacy_analysis(period, family):
    working_set = [a for a in accruals_of_family(family["id"]) if a["status"] == "POSTED"]

    # STEP 1 — earned portion, rounded per accrual before summing.
    earned = []
    expected_to_date_cents = 0
    for accrual in working_set:
        earned_a = rhu(accrual["accrued_amount_cents"] * accrual["elapsed_exposure_bps"], 10000)
        earned.append((accrual, earned_a))
        expected_to_date_cents += earned_a

    # STEP 2 — cash actually paid through the review period, inclusive upper bound.
    actual_paid_cents = 0
    for observation in observations_of_family(family["id"]):
        if observation["observation_period_code"] <= period["period_code"]:
            actual_paid_cents += observation["paid_cost_cents"]

    # STEP 3 — the ratio.
    if expected_to_date_cents == 0:
        fail("ERR_NO_EXPECTED_BASE")
    ave_ratio_bps = rhu(actual_paid_cents * 10000, expected_to_date_cents)

    # STEP 4 — trend tier and adequacy status, selected together.
    if ave_ratio_bps <= TREND_TIER_REDUNDANT_MAX_BPS:
        trend_adjustment_bps, adequacy_status = -1000, "REDUNDANT"
    elif ave_ratio_bps <= TREND_TIER_SUFFICIENT_MAX_BPS:
        trend_adjustment_bps, adequacy_status = 0, "SUFFICIENT"
    elif ave_ratio_bps <= TREND_TIER_DEFICIENT_MAX_BPS:
        trend_adjustment_bps, adequacy_status = 1500, "DEFICIENT"
    else:
        trend_adjustment_bps, adequacy_status = 3000, "DEFICIENT"

    # STEP 5 — unearned base, reusing STEP 1's rounded earned figures.
    remaining_base_cents = sum(a["accrued_amount_cents"] - e for a, e in earned)

    # STEP 6 — apply the tier.
    adjusted_remaining_cents = rhu(
        remaining_base_cents * (10000 + trend_adjustment_bps), 10000
    )

    # STEP 7 — the signed recommendation.
    recommended_true_up_cents = (adjusted_remaining_cents - remaining_base_cents) + (
        actual_paid_cents - expected_to_date_cents
    )

    return {
        "expected_to_date_cents": expected_to_date_cents,
        "actual_paid_cents": actual_paid_cents,
        "ave_ratio_bps": ave_ratio_bps,
        "trend_adjustment_bps": trend_adjustment_bps,
        "remaining_base_cents": remaining_base_cents,
        "adjusted_remaining_cents": adjusted_remaining_cents,
        "recommended_true_up_cents": recommended_true_up_cents,
        "adequacy_status": adequacy_status,
    }


# ---------------------------------------------------------------------------
# calculations.service_contract_recognition
# ---------------------------------------------------------------------------
def whole_months_between(d0, d1):
    months = 12 * (d1.year - d0.year) + (d1.month - d0.month)
    if d1.day < d0.day:
        months -= 1
    return months


def service_contract_figures(contract):
    sold = parse_date(contract["sold_date"])
    clock_date = store.logical_date()
    raw = whole_months_between(sold, clock_date)
    months_elapsed = min(contract["term_months"], max(0, raw))

    if contract["recognition_method"] == "STRAIGHT_LINE":
        recognized = rhu(
            contract["total_contract_price_cents"] * months_elapsed, contract["term_months"]
        )
    else:
        elapsed_bps = rhu(months_elapsed * 10000, contract["term_months"])
        if elapsed_bps <= 2500:
            cum_bps = CLAIMS_CURVE_Q1_BPS
        elif elapsed_bps <= 5000:
            cum_bps = CLAIMS_CURVE_Q2_BPS
        elif elapsed_bps <= 7500:
            cum_bps = CLAIMS_CURVE_Q3_BPS
        else:
            cum_bps = CLAIMS_CURVE_Q4_BPS
        recognized = rhu(contract["total_contract_price_cents"] * cum_bps, 10000)

    deferred = (
        contract["total_contract_price_cents"] - recognized - contract["refunded_revenue_cents"]
    )
    return months_elapsed, recognized, deferred


def apply_contract_recognition(contract):
    months_elapsed, recognized, deferred = service_contract_figures(contract)
    changed = (
        contract.get("months_elapsed") != months_elapsed
        or contract.get("recognized_revenue_cents") != recognized
        or contract.get("deferred_revenue_cents") != deferred
    )
    contract["months_elapsed"] = months_elapsed
    contract["recognized_revenue_cents"] = recognized
    contract["deferred_revenue_cents"] = deferred
    return changed


# ---------------------------------------------------------------------------
# calculations.ibnr_liability_reserve
# ---------------------------------------------------------------------------
def ibnr_liability_reserve(reserve, family):
    reported = reserve["reported_claim_count"]
    case_reserve = reserve["asserted_case_reserve_cents"]

    if reported == 0:
        avg_case_severity_cents = 0
    else:
        avg_case_severity_cents = rhu(case_reserve, reported)

    lag_factor_bps = min(
        LAG_FACTOR_CAP_BPS, LAG_FACTOR_PER_MONTH_BPS * reserve["reporting_lag_months"]
    )
    ibnr_claim_count = rhu(reported * lag_factor_bps, 10000)
    trended_severity_cents = rhu(
        avg_case_severity_cents * (10000 + reserve["severity_trend_bps"]), 10000
    )
    raw_ibnr_cents = ibnr_claim_count * trended_severity_cents

    cap_cents = rhu(case_reserve * IBNR_CAP_BPS, 10000)
    floor_cents = family["units_sold_lifetime"] * IBNR_FLOOR_CENTS_PER_UNIT
    # CLAMP ORDER IS PINNED: cap first (inner min), then floor (outer max).
    ibnr_reserve_cents = max(floor_cents, min(raw_ibnr_cents, cap_cents))

    return {
        "avg_case_severity_cents": avg_case_severity_cents,
        "lag_factor_bps": lag_factor_bps,
        "ibnr_claim_count": ibnr_claim_count,
        "ibnr_reserve_cents": ibnr_reserve_cents,
        "total_liability_reserve_cents": case_reserve + ibnr_reserve_cents,
    }


# ---------------------------------------------------------------------------
# calculations.supplier_recovery_recognized
# ---------------------------------------------------------------------------
def supplier_cap_cents(supplier):
    return rhu(
        supplier["annual_purchase_volume_cents"] * supplier["contractual_recovery_cap_bps"], 10000
    )


def value_recovery_expected_value(recovery, supplier):
    """EXPECTED_VALUE variant — probability-weight, round, then apply the ceiling."""
    cap_cents = supplier_cap_cents(supplier)
    rating = supplier["collectability_rating"]
    weighted = rhu(recovery["asserted_amount_cents"] * COLLECTABILITY_BPS[rating], 10000)
    recovery["valuation_variant"] = "EXPECTED_VALUE"
    recovery["collectability_rating_at_valuation"] = rating
    recovery["recognized_recovery_cents"] = min(cap_cents, weighted)


def value_recovery_contractual_floor(recovery, supplier):
    """CONTRACTUAL_FLOOR variant — the agreed figure, no probability weighting."""
    cap_cents = supplier_cap_cents(supplier)
    recovery["valuation_variant"] = "CONTRACTUAL_FLOOR"
    recovery["collectability_rating_at_valuation"] = supplier["collectability_rating"]
    recovery["recognized_recovery_cents"] = min(cap_cents, recovery["settled_amount_cents"])


# ---------------------------------------------------------------------------
# Supplier aggregates and calculations.supplier_collectability_rating
# ---------------------------------------------------------------------------
def recompute_supplier_aggregates(supplier):
    gross = open_asset = realized = written_off = 0
    closed_count = 0
    for recovery in recoveries_of_supplier(supplier["id"]):
        status = recovery["status"]
        if status in ("ASSERTED", "NEGOTIATION", "SETTLED", "WRITTEN_OFF"):
            gross += recovery["asserted_amount_cents"]
        if status in ("ASSERTED", "NEGOTIATION"):
            open_asset += recovery["recognized_recovery_cents"]
        if status == "SETTLED":
            realized += recovery["recognized_recovery_cents"]
        if status == "WRITTEN_OFF":
            written_off += recovery["asserted_amount_cents"]
        if status in ("SETTLED", "WRITTEN_OFF"):
            closed_count += 1
    figures = {
        "gross_asserted_recovery_cents": gross,
        "open_recovery_asset_cents": open_asset,
        "realized_recovery_cents": realized,
        "written_off_recovery_cents": written_off,
        "closed_recovery_count": closed_count,
    }
    changed = any(supplier.get(k) != v for k, v in figures.items())
    supplier.update(figures)
    return changed


def recompute_supplier_open_asset(supplier):
    open_asset = sum(
        r["recognized_recovery_cents"]
        for r in recoveries_of_supplier(supplier["id"])
        if r["status"] in ("ASSERTED", "NEGOTIATION")
    )
    changed = supplier.get("open_recovery_asset_cents") != open_asset
    supplier["open_recovery_asset_cents"] = open_asset
    return changed


def recompute_supplier_gross_asserted(supplier):
    gross = sum(
        r["asserted_amount_cents"]
        for r in recoveries_of_supplier(supplier["id"])
        if r["status"] in ("ASSERTED", "NEGOTIATION", "SETTLED", "WRITTEN_OFF")
    )
    changed = supplier.get("gross_asserted_recovery_cents") != gross
    supplier["gross_asserted_recovery_cents"] = gross
    return changed


def _downgrade(rating, notches):
    index = DOWNGRADE_LADDER.index(rating) + notches
    return DOWNGRADE_LADDER[min(index, len(DOWNGRADE_LADDER) - 1)]


def recompute_supplier_rating(supplier):
    base_rating = CREDIT_BASE_RATING[supplier["credit_rating"]]
    denom = supplier["realized_recovery_cents"] + supplier["written_off_recovery_cents"]
    if denom == 0:
        realization_bps = 10000
    else:
        realization_bps = rhu(supplier["realized_recovery_cents"] * 10000, denom)

    if supplier["closed_recovery_count"] == 0:
        rating = base_rating
    elif realization_bps >= REALIZATION_HOLD_BPS:
        rating = base_rating
    elif realization_bps >= REALIZATION_WATCH_BPS:
        rating = _downgrade(base_rating, 1)
    else:
        rating = _downgrade(base_rating, 2)

    changed = (
        supplier.get("realization_bps") != realization_bps
        or supplier.get("collectability_rating") != rating
    )
    supplier["realization_bps"] = realization_bps
    supplier["collectability_rating"] = rating
    return changed


# ---------------------------------------------------------------------------
# calculations.reserve_rollforward_disclosure
# ---------------------------------------------------------------------------
def rollforward_figures(period):
    period_id = period["id"]
    period_code = period["period_code"]

    prior_snapshot = None
    prior_code = None
    for candidate in store.all_rows("periods"):
        if candidate["status"] != "CLOSED":
            continue
        if candidate["period_code"] >= period_code:
            continue
        snapshots = [r for r in store.all_rows("rollforwards") if r["period_id"] == candidate["id"]]
        if not snapshots:
            continue
        if prior_code is None or candidate["period_code"] > prior_code:
            prior_code = candidate["period_code"]
            snapshots.sort(key=lambda r: (r["created_at"], r["_seq"]))
            prior_snapshot = snapshots[-1]

    beginning_balance_cents = 0 if prior_snapshot is None else prior_snapshot["ending_balance_cents"]

    accruals_cents = sum(
        a["accrued_amount_cents"]
        for a in store.all_rows("accruals")
        if a["period_id"] == period_id and a["status"] == "POSTED"
    )
    campaign_accruals_cents = 0
    significant_exposure_count = 0
    for action in store.all_rows("field_actions"):
        if action["approved_period_id"] == period_id and action["approval_state"] == "APPROVED":
            campaign_accruals_cents += action["specific_accrual_cents"]
            if action["specific_accrual_cents"] >= SIGNIFICANT_EXPOSURE_THRESHOLD_CENTS:
                significant_exposure_count += 1
    changes_in_estimate_cents = sum(
        r["recommended_true_up_cents"]
        for r in store.all_rows("adequacy_reviews")
        if r["period_id"] == period_id and r["true_up_applied"]
    )
    claims_paid_cents = sum(
        o["paid_cost_cents"]
        for o in store.all_rows("observations")
        if o["observation_period_code"] == period_code
    )
    supplier_recoveries_cents = sum(
        r["recognized_recovery_cents"]
        for r in store.all_rows("recoveries")
        if r["settled_period_id"] == period_id and r["status"] == "SETTLED"
    )

    ending_balance_cents = (
        beginning_balance_cents
        + accruals_cents
        + campaign_accruals_cents
        + changes_in_estimate_cents
        - claims_paid_cents
        + supplier_recoveries_cents
    )

    return {
        "beginning_balance_cents": beginning_balance_cents,
        "accruals_cents": accruals_cents,
        "campaign_accruals_cents": campaign_accruals_cents,
        "changes_in_estimate_cents": changes_in_estimate_cents,
        "claims_paid_cents": claims_paid_cents,
        "supplier_recoveries_cents": supplier_recoveries_cents,
        "ending_balance_cents": ending_balance_cents,
        "significant_exposure_count": significant_exposure_count,
    }


# ---------------------------------------------------------------------------
# Clock-driven recomputation (PRD §2.5)
# ---------------------------------------------------------------------------
def apply_clock_move():
    """Every time-dependent recomputation, evaluated in the pinned order."""
    for vintage in store.all_rows("vintages"):
        if apply_exposure_status(vintage):
            store.touch(vintage)

    for family in store.all_rows("families"):
        if apply_history_maturity(family):
            store.touch(family)

    for contract in store.all_rows("service_contracts"):
        if contract["status"] != "ACTIVE":
            continue
        changed = apply_contract_recognition(contract)
        if contract["months_elapsed"] >= contract["term_months"]:
            contract["status"] = "EXPIRED"
            contract["recognized_revenue_cents"] = contract["total_contract_price_cents"]
            contract["deferred_revenue_cents"] = 0
            changed = True
        if changed:
            store.touch(contract)


def logical_instant_iso():
    return format_instant(store.logical_now())
