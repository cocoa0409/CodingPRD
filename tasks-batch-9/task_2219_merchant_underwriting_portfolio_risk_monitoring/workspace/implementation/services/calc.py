"""The seven normative calculations of the PRD, with the pinned rounding order."""
from services.metrics import (
    activity_between,
    releasable_balance,
    reserve_account_of,
    rule_for_mcc,
    unpaid_exposure,
)
from util import ceil_div, date_minus, rhu_div

# ---- reserve_requirement_determination -----------------------------------
BASE_BY_BAND = {"A": 50, "B": 500, "C": 900, "D": 1500}
THIN_FILE_UPLIFT_BPS = 300
LAG_UPLIFT_PER_WEEK_BPS = 150
CHARGEBACK_UPLIFT_MULTIPLE = 3
DISPUTE_HORIZON_MULTIPLE = 4
RESERVE_BPS_MIN = 100
RESERVE_BPS_MAX = 2500
CAP_MONTHS = 6
EXPOSURE_CAP_MULTIPLE = 2
ROLLING_CEILING_BPS = 1000

# ---- trailing metrics / gating -------------------------------------------
EARLY_WARNING_BPS = 65
EXCESSIVE_BPS = 90

# ---- settlement -----------------------------------------------------------
NORMAL_PAYOUT_LAG_DAYS = 1
DELAYED_PAYOUT_LAG_DAYS = 7
VOLUME_LIMIT_TOLERANCE_BPS = 12500

# ---- reserve release ------------------------------------------------------
ROLLING_RELEASE_LAG_DAYS = 90
CAPPED_RELEASE_LAG_DAYS = 180
RELEASE_COOLING_DAYS = 30

# ---- detectors ------------------------------------------------------------
SPIKE_MULTIPLE = 3
CARD_TESTING_MIN_DECLINES = 50
DECLINE_RATIO_BPS_MIN = 4000
CARD_RATIO_BPS_MIN = 8000
MICRO_TICKET_CENTS_MAX = 500
LAUNDERING_SCORE_MIN = 55
BASELINE_DAYS = 30

# ---- remediation ----------------------------------------------------------
MONTH_DAYS = 30
FAIL_RATIO_BPS = 180
MAX_GRACE_MONTHS = 2
NETWORK_COUNT_MIN = 100

# ---- forecast -------------------------------------------------------------
LGD_BPS = 6000
RESTRICTED_PD_PENALTY_BPS = 500
ADEQUACY_FULL_BPS = 10000
ADEQUACY_PARTIAL_BPS = 7500
PARTIAL_UPLIFT_BPS = 2500


# --------------------------------------------------------------------------
# 1. reserve requirement determination (PRD 3.4)
# --------------------------------------------------------------------------
def reserve_requirement(app, method):
    score = app["credit_score"]
    if score >= 720:
        band = "A"
    elif score >= 660:
        band = "B"
    elif score >= 600:
        band = "C"
    else:
        band = "D"
    base = BASE_BY_BAND[band]

    thin_file = THIN_FILE_UPLIFT_BPS if app["prior_processing_history_months"] < 6 else 0
    rule = rule_for_mcc(app["mcc_code"])
    mcc_uplift = (
        rule["reserve_uplift_bps"]
        if rule is not None and rule["disposition"] == "RESTRICTED_REVIEW"
        else 0
    )

    volume = app["requested_monthly_volume_cents"]
    one_day_volume = rhu_div(volume, 30)
    if method == "LAG_WEIGHTED":
        lag_uplift = ceil_div(app["avg_delivery_lag_days"], 7) * LAG_UPLIFT_PER_WEEK_BPS
        chargeback_uplift = 0
        exposure_raw = rhu_div(volume * min(app["avg_delivery_lag_days"], 30), 30)
    else:
        lag_uplift = 0
        chargeback_uplift = app["declared_chargeback_ratio_bps"] * CHARGEBACK_UPLIFT_MULTIPLE
        exposure_raw = rhu_div(
            volume * app["declared_chargeback_ratio_bps"] * DISPUTE_HORIZON_MULTIPLE, 10000)
    exposure = max(exposure_raw, one_day_volume)

    pct = min(RESERVE_BPS_MAX,
              max(RESERVE_BPS_MIN, base + lag_uplift + chargeback_uplift + thin_file + mcc_uplift))
    monthly_hold = rhu_div(volume * pct, 10000)
    cap = min(monthly_hold * CAP_MONTHS, EXPOSURE_CAP_MULTIPLE * exposure)
    reserve_type = "ROLLING" if pct < ROLLING_CEILING_BPS else "CAPPED"

    return {
        "credit_band": band,
        "base_reserve_bps": base,
        "lag_uplift_bps": lag_uplift,
        "thin_file_uplift_bps": thin_file,
        "mcc_uplift_bps": mcc_uplift,
        "chargeback_uplift_bps": chargeback_uplift,
        "reserve_pct_bps": pct,
        "exposure_estimate_cents": exposure,
        "reserve_cap_cents": cap,
        "reserve_type": reserve_type,
    }


# --------------------------------------------------------------------------
# 2. settlement reserve hold and payout waterfall (PRD 3.9)
# --------------------------------------------------------------------------
def settlement_waterfall(lines, gross_volume_cents, account):
    pct = account["reserve_pct_bps"]
    raw_hold = sum(rhu_div(line["volume_cents"] * pct, 10000) for line in lines)
    if account["reserve_type"] == "CAPPED":
        remaining = max(0, account["reserve_cap_cents"] - account["held_balance_cents"])
        reserve_hold = min(raw_hold, remaining)
    else:
        reserve_hold = raw_hold

    loss_total = sum(line["chargeback_amount_cents"] for line in lines)
    available = max(0, gross_volume_cents - reserve_hold)
    loss_from_settlement = min(loss_total, available)
    deficit = loss_total - loss_from_settlement
    reserve_offset = min(deficit, account["held_balance_cents"] + reserve_hold)
    uncovered = deficit - reserve_offset
    net_payout = available - loss_from_settlement
    return {
        "day_line_count": len(lines),
        "reserve_hold_cents": reserve_hold,
        "loss_offset_from_settlement_cents": loss_from_settlement,
        "reserve_offset_cents": reserve_offset,
        "uncovered_loss_cents": uncovered,
        "net_payout_cents": net_payout,
    }


# --------------------------------------------------------------------------
# 3. reserve release eligibility (PRD 3.10)
# --------------------------------------------------------------------------
def release_lag_days(reserve_type):
    return ROLLING_RELEASE_LAG_DAYS if reserve_type == "ROLLING" else CAPPED_RELEASE_LAG_DAYS


def current_releasable(account, clock_date):
    return releasable_balance(account, clock_date)


# --------------------------------------------------------------------------
# 4. monitoring detector evaluation (PRD 3.7)
# --------------------------------------------------------------------------
def _ratio(numerator, denominator):
    if denominator == 0:
        return 0
    return rhu_div(numerator * 10000, denominator)


def evaluate_detectors(merchant, as_of_date):
    """Return the detector hits in the pinned detector order."""
    rows = activity_between(merchant["id"], as_of_date, as_of_date)
    today = rows[0] if rows else None
    baseline = activity_between(
        merchant["id"], date_minus(as_of_date, BASELINE_DAYS), date_minus(as_of_date, 1))
    baseline_volume = sum(r["volume_cents"] for r in baseline)
    baseline_txn = sum(r["txn_count"] for r in baseline)
    baseline_avg_daily_volume = rhu_div(baseline_volume, BASELINE_DAYS)
    baseline_avg_ticket = 0 if baseline_txn == 0 else rhu_div(baseline_volume, baseline_txn)

    hits = []

    # 1. CHARGEBACK_THRESHOLD - no day row needed
    ratio = merchant["rolling_chargeback_ratio_bps"]
    if ratio >= EARLY_WARNING_BPS:
        hits.append({
            "alert_type": "CHARGEBACK_THRESHOLD",
            "severity_score": 90 if ratio >= EXCESSIVE_BPS else 60,
            "observed_metric_bps": ratio,
        })

    if today is not None:
        # 2. VELOCITY_SPIKE
        if (baseline_avg_daily_volume > 0
                and today["volume_cents"] >= SPIKE_MULTIPLE * baseline_avg_daily_volume):
            observed = rhu_div(today["volume_cents"] * 10000, baseline_avg_daily_volume)
            hits.append({
                "alert_type": "VELOCITY_SPIKE",
                "severity_score": min(100, 20 + observed // 1000),
                "observed_metric_bps": observed,
            })

        # 3. CARD_TESTING - all five conditions
        if today["txn_count"] > 0 and today["decline_count"] >= CARD_TESTING_MIN_DECLINES:
            decline_ratio = _ratio(today["decline_count"],
                                   today["txn_count"] + today["decline_count"])
            card_ratio = _ratio(today["distinct_card_count"], today["txn_count"])
            if (decline_ratio >= DECLINE_RATIO_BPS_MIN
                    and card_ratio >= CARD_RATIO_BPS_MIN
                    and today["avg_ticket_cents"] <= MICRO_TICKET_CENTS_MAX):
                hits.append({
                    "alert_type": "CARD_TESTING",
                    "severity_score": 85,
                    "observed_metric_bps": decline_ratio,
                })

        # 4. LAUNDERING_PATTERN - additive weighted score
        score = 0
        if today["txn_count"] > 0 and _ratio(today["cross_border_count"], today["txn_count"]) >= 5000:
            score += 30
        if today["volume_cents"] > 0 and _ratio(today["refund_cents"], today["volume_cents"]) >= 3000:
            score += 25
        if today["txn_count"] >= 100 and today["unique_bin_count"] <= 3:
            score += 25
        if baseline_avg_ticket > 0 and today["avg_ticket_cents"] >= 5 * baseline_avg_ticket:
            score += 20
        if score >= LAUNDERING_SCORE_MIN:
            hits.append({
                "alert_type": "LAUNDERING_PATTERN",
                "severity_score": score,
                "observed_metric_bps": score * 100,
            })

    return hits


def gating_band(rolling_ratio_bps):
    if rolling_ratio_bps < EARLY_WARNING_BPS:
        return "NORMAL"
    if rolling_ratio_bps < EXCESSIVE_BPS:
        return "EARLY_WARNING"
    return "EXCESSIVE"


# --------------------------------------------------------------------------
# 5. remediation month evaluation (PRD 3.11)
# --------------------------------------------------------------------------
def remediation_month_window(window_start_date, month_index):
    from util import date_plus
    start = date_plus(window_start_date, (month_index - 1) * MONTH_DAYS)
    end = date_plus(window_start_date, month_index * MONTH_DAYS - 1)
    return start, end


def evaluate_month(program, month_index):
    start, end = remediation_month_window(program["window_start_date"], month_index)
    rows = activity_between(program["merchant_id"], start, end)
    month_txn = sum(r["txn_count"] for r in rows)
    month_cb = sum(r["chargeback_count"] for r in rows)
    observed = _ratio(month_cb, month_txn)
    return {
        "observed_ratio_bps": observed,
        "month_txn_count": month_txn,
        "month_chargeback_count": month_cb,
        "compliant": observed < program["target_ratio_bps"],
    }


# --------------------------------------------------------------------------
# 6. portfolio loss forecast (PRD 3.13)
# --------------------------------------------------------------------------
def portfolio_forecast(merchants, method, stress_multiplier_bps):
    unpaid_total = 0
    gross_total = 0
    net_total = 0
    held_total = 0
    for merchant in merchants:
        amount_ratio = merchant["amount_based_chargeback_ratio_bps"]
        if amount_ratio < 65:
            pd_bps = 100
        elif amount_ratio < 90:
            pd_bps = 300
        elif amount_ratio < 180:
            pd_bps = 900
        else:
            pd_bps = 2000
        if merchant["account_state"] == "RESTRICTED":
            pd_bps += RESTRICTED_PD_PENALTY_BPS
        if method == "STRESSED":
            pd_bps = min(10000, rhu_div(pd_bps * stress_multiplier_bps, 10000))

        m_unpaid = unpaid_exposure(merchant["id"])
        m_gross = rhu_div(m_unpaid * pd_bps * LGD_BPS, 10000 * 10000)
        account = reserve_account_of(merchant["id"])
        m_held = account["held_balance_cents"] if account else 0
        m_net = max(0, m_gross - m_held)

        unpaid_total += m_unpaid
        gross_total += m_gross
        net_total += m_net
        held_total += m_held

    coverage_gap = max(0, gross_total - held_total)
    adequacy = 0 if gross_total == 0 else rhu_div(held_total * 10000, gross_total)
    if adequacy >= ADEQUACY_FULL_BPS:
        required = 0
    elif adequacy >= ADEQUACY_PARTIAL_BPS:
        required = rhu_div(coverage_gap * PARTIAL_UPLIFT_BPS, 10000)
    else:
        required = coverage_gap
    projected = (
        0 if gross_total == 0
        else rhu_div((held_total + required) * 10000, gross_total)
    )
    return {
        "merchant_count": len(merchants),
        "unpaid_exposure_cents": unpaid_total,
        "gross_expected_loss_cents": gross_total,
        "net_expected_loss_cents": net_total,
        "total_reserve_held_cents": held_total,
        "reserve_adequacy_ratio_bps": adequacy,
        "coverage_gap_cents": coverage_gap,
        "required_additional_reserve_cents": required,
        "projected_adequacy_ratio_bps": projected,
    }
