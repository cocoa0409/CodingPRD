"""Adstock, saturation, fitting, holdout validation, publication and calibration.

PRD sections 3.4 (adstock, saturation, contribution, economics, holdout, stability)
and 3.7 (calibration application).
"""

from decimal import Decimal

import db as store
from db import base_row, db, touch
from errors import ApiError
from services import ordering
from services.market import sync_market, require_posture_not_frozen
from services.numeric import D, HUNDRED, ONE, ZERO, dsqrt, q0, q2, q4, q6
from services.window import window_periods

STABILITY_FLOOR = Decimal("0.6000")
MAPE_THRESHOLD = Decimal("12.00")


# ------------------------------------------------------------ series maths

def raw_spend_series(window, channel_id, periods):
    """Live (non-superseded) spend per period; a period with no observation is zero."""
    totals = {}
    for row in store.spend_of_window(window["id"]):
        if row["channel_id"] != channel_id:
            continue
        key = row["_period_start_date"]
        totals[key] = totals.get(key, 0) + row["spend_cents"]
    return [totals.get(period, 0) for period in periods]


def adstock_series(spend, decay_rate, max_lag, mode):
    """One rounded integer-cent adstocked value per period."""
    decay = D(decay_rate)
    lag = int(max_lag)
    out = []
    if mode == "SPEND_PERIOD":
        gain = ZERO
        for k in range(lag + 1):
            gain += decay ** k
        for value in spend:
            out.append(q0(D(value) * gain))
    else:
        for index in range(len(spend)):
            acc = D(spend[index])
            for k in range(1, min(lag, index) + 1):
                acc += (decay ** k) * D(spend[index - k])
            out.append(q0(acc))
    return out


def period_units(adstocked, ceiling_units, half_point_cents):
    """Hill saturation: C * a / (a + H); an unadvertised period contributes nothing."""
    value = D(adstocked)
    if value == 0:
        return ZERO
    return D(ceiling_units) * value / (value + D(half_point_cents))


def contribution_period_units(contribution):
    """Re-derive the per-period saturated units a fitted row was built from."""
    return [period_units(a, contribution["_ceiling_units"], contribution["_half_point_cents"])
            for a in contribution["adstocked_spend_series"]]


# ------------------------------------------------------------------ fitting

def _fit_preconditions(run, market, window):
    if run["fit_status"] == "FITTED":
        raise ApiError("ERR_MODEL_RUN_INVALID_STATE",
                       "The model run has already been fitted.")
    if window["status"] != "SEALED":
        raise ApiError("ERR_DATA_WINDOW_NOT_SEALED")
    channels = []
    for channel_id in run["included_channel_ids"]:
        channel = db.media_channels.get(channel_id)
        if channel is None:
            raise ApiError("ERR_MEDIA_CHANNEL_NOT_FOUND")
        channels.append(channel)
    for channel in channels:
        if channel["status"] == "RETIRED":
            raise ApiError("ERR_CHANNEL_RETIRED",
                           "Channel %s is RETIRED." % channel["channel_code"])
    for channel in channels:
        if channel["market_id"] != run["market_id"]:
            raise ApiError("ERR_CHANNEL_NOT_IN_MARKET",
                           "Channel %s does not belong to the run's market." % channel["channel_code"])
    live_spend = store.spend_of_window(window["id"])
    for channel in channels:
        if not any(row["channel_id"] == channel["id"] for row in live_spend):
            raise ApiError("ERR_NO_SPEND_OBSERVATIONS",
                           "Channel %s has no live spend observations in the window."
                           % channel["channel_code"])
    max_lag = max(channel["adstock_max_lag_periods"] for channel in channels)
    if window["expected_period_count"] <= max_lag:
        raise ApiError("ERR_LAG_WINDOW_INCOMPLETE",
                       "The window is not longer than the widest configured adstock lag.")
    return ordering.channels_by_code(channels)


def perform_fit(run, user_id):
    market = db.markets[run["market_id"]]
    window = db.data_windows[run["data_window_id"]]
    channels = _fit_preconditions(run, market, window)

    sales = sorted(store.sales_of_window(window["id"]), key=lambda s: s["_period_start_date"])
    observation_period_count = len(sales)
    modeled_sales_units = sum(s["units_sold"] for s in sales)
    total_revenue_cents = sum(s["revenue_cents"] for s in sales)
    if observation_period_count == 0 or modeled_sales_units == 0:
        raise ApiError("ERR_DATA_WINDOW_INCOMPLETE",
                       "The window carries no sales observations to fit against.")
    unit_price_cents = q0(D(total_revenue_cents) / D(modeled_sales_units))

    periods = window_periods(window)
    mode = run["carryover_attribution_mode"]
    half_width = q2(D("40.0") / dsqrt(observation_period_count))

    drafts = []
    contribution_total = ZERO
    for channel in channels:
        spend = raw_spend_series(window, channel["id"], periods)
        adstocked = adstock_series(spend, channel["adstock_decay_rate"],
                                   channel["adstock_max_lag_periods"], mode)
        mean_adstocked = q0(D(sum(adstocked)) / D(len(adstocked)))
        exact_units = ZERO
        for value in adstocked:
            exact_units += period_units(value, channel["response_ceiling_units"],
                                        channel["saturation_half_point_cents"])
        contribution_units = q4(exact_units)
        attributed_spend_cents = sum(spend)
        contribution_revenue_cents = q0(contribution_units * D(unit_price_cents))
        if attributed_spend_cents == 0:
            average_roi = Decimal("0.0000")
        else:
            average_roi = q4(D(contribution_revenue_cents) / D(attributed_spend_cents))
        ceiling = D(channel["response_ceiling_units"])
        half_point = D(channel["saturation_half_point_cents"])
        denominator = (D(mean_adstocked) + half_point) ** 2
        marginal_roi = q6(D(unit_price_cents) * ceiling * half_point / denominator)
        drafts.append({
            "channel": channel,
            "adstocked": adstocked,
            "mean_adstocked": mean_adstocked,
            "contribution_units": contribution_units,
            "attributed_spend_cents": attributed_spend_cents,
            "contribution_revenue_cents": contribution_revenue_cents,
            "average_roi": average_roi,
            "marginal_roi": marginal_roi,
        })
        contribution_total += contribution_units

    baseline_sales_units = q4(D(modeled_sales_units) - contribution_total)
    if baseline_sales_units < 0:
        raise ApiError("ERR_MODEL_BASELINE_NEGATIVE",
                       "The channel contributions exceed modelled sales.")

    for existing in store.contributions_of_run(run["id"]):
        db.channel_contributions.pop(existing["id"], None)

    for draft in drafts:
        channel = draft["channel"]
        units = draft["contribution_units"]
        row = base_row("channel_contributions")
        row.update({
            "model_run_id": run["id"],
            "channel_id": channel["id"],
            "attribution_mode_used": mode,
            "adstocked_spend_series": list(draft["adstocked"]),
            "mean_adstocked_spend_cents": draft["mean_adstocked"],
            "contribution_units": units,
            "calibrated_contribution_units": units,
            "contribution_revenue_cents": draft["contribution_revenue_cents"],
            "calibrated_contribution_revenue_cents": draft["contribution_revenue_cents"],
            "attributed_spend_cents": draft["attributed_spend_cents"],
            "average_roi": draft["average_roi"],
            "marginal_roi": draft["marginal_roi"],
            "ci_half_width_pct": half_width,
            "ci_low_units": q4(units * (ONE - half_width / HUNDRED)),
            "ci_high_units": q4(units * (ONE + half_width / HUNDRED)),
            "is_current": True,
            "_ceiling_units": channel["response_ceiling_units"],
            "_half_point_cents": channel["saturation_half_point_cents"],
        })
        db.add("channel_contributions", row)

    run["observation_period_count"] = observation_period_count
    run["modeled_sales_units"] = modeled_sales_units
    run["unit_price_cents"] = unit_price_cents
    run["baseline_sales_units"] = baseline_sales_units
    run["fit_status"] = "FITTED"
    run["validation_status"] = "UNVALIDATED"
    run["holdout_mape_pct"] = None
    run["fitted_by_user_id"] = user_id
    touch(run)
    sync_market(market)
    return run


# --------------------------------------------------------------- validation

def perform_validate(run):
    if run["fit_status"] != "FITTED":
        raise ApiError("ERR_MODEL_RUN_INVALID_STATE",
                       "Only a FITTED model run can be validated.")
    window = db.data_windows[run["data_window_id"]]
    periods = window_periods(window)
    sales_by_period = {}
    for row in store.sales_of_window(window["id"]):
        sales_by_period[row["_period_start_date"]] = row

    observation_period_count = run["observation_period_count"]
    baseline_per_period = q4(D(run["baseline_sales_units"]) / D(observation_period_count))
    holdout_periods = run["holdout_periods"]
    contributions = ordering.by_channel_code(
        store.contributions_of_run(run["id"], current_only=True))
    series = [(c, contribution_period_units(c)) for c in contributions]

    holdout = periods[len(periods) - holdout_periods:]
    accumulated = ZERO
    for period in holdout:
        index = periods.index(period)
        predicted = baseline_per_period
        for _contribution, values in series:
            predicted += q4(values[index])
        predicted = q4(predicted)
        observation = sales_by_period.get(period)
        if observation is None:
            raise ApiError("ERR_DATA_WINDOW_INCOMPLETE",
                           "A holdout period has no sales observation.")
        actual = D(observation["units_sold"])
        accumulated += abs(predicted - actual) / actual

    mape = q2(HUNDRED * accumulated / D(holdout_periods))
    run["holdout_mape_pct"] = mape
    run["validation_status"] = "HOLDOUT_PASSED" if mape <= MAPE_THRESHOLD else "HOLDOUT_FAILED"
    touch(run)
    return run


# -------------------------------------------------------------- publication

def _roi_by_code(run_id):
    out = {}
    for contribution in store.contributions_of_run(run_id, current_only=True):
        channel = db.media_channels.get(contribution["channel_id"])
        code = channel["channel_code"] if channel else contribution["channel_id"]
        out[code] = D(contribution["average_roi"])
    return out


def refresh_stability(candidate, incumbent):
    """Returns (stability_score, refresh_generation)."""
    if incumbent is None:
        # PRD 3.5: a market's first publication records a stability score of exactly 1.0000.
        return Decimal("1.0000"), 1
    new_rois = _roi_by_code(candidate["id"])
    prev_rois = _roi_by_code(incumbent["id"])
    codes = sorted(set(list(new_rois.keys()) + list(prev_rois.keys())))
    drift = ZERO
    for code in codes:
        drift += abs(new_rois.get(code, ZERO) - prev_rois.get(code, ZERO))
    base = ZERO
    for code in prev_rois:
        base += prev_rois[code]
    if base == 0:
        score = Decimal("1.0000") if drift == 0 else Decimal("0.0000")
    else:
        raw = ONE - (drift / base)
        score = q4(raw if raw > 0 else ZERO)
    return score, incumbent["refresh_generation"] + 1


def perform_publish(run, user_id, override_stability):
    market = db.markets[run["market_id"]]
    if run["fit_status"] != "FITTED":
        raise ApiError("ERR_MODEL_RUN_INVALID_STATE",
                       "Only a FITTED model run can be published.")
    if run["publication_status"] in ("PUBLISHED", "SUPERSEDED"):
        raise ApiError("ERR_MODEL_RUN_INVALID_STATE",
                       "The model run is already %s." % run["publication_status"])
    if run["validation_status"] != "HOLDOUT_PASSED":
        raise ApiError("ERR_HOLDOUT_NOT_PASSED")
    require_posture_not_frozen(market)

    incumbent = store.published_run_of_market(market["id"])
    score, generation = refresh_stability(run, incumbent)
    if incumbent is not None and score < STABILITY_FLOOR and override_stability is not True:
        raise ApiError("ERR_MODEL_UNSTABLE",
                       "Refresh stability score %s is below the 0.6000 publication floor." % score)

    run["stability_score"] = score
    run["refresh_generation"] = generation
    run["previous_published_run_id"] = incumbent["id"] if incumbent else None
    run["publication_status"] = "PUBLISHED"
    run["published_by_user_id"] = user_id
    touch(run)

    if incumbent is not None:
        incumbent["publication_status"] = "SUPERSEDED"
        touch(incumbent)
        for contribution in store.contributions_of_run(incumbent["id"]):
            if contribution["is_current"]:
                contribution["is_current"] = False
                touch(contribution)
        for report in store.reports_of_run(incumbent["id"]):
            if report["status"] == "CURRENT":
                report["status"] = "STALE"
                touch(report)
        for scenario in store.scenarios_of_run(incumbent["id"]):
            if scenario["status"] in ("OPTIMIZED", "APPROVED"):
                scenario["status"] = "INVALIDATED"
                touch(scenario)

    sync_market(market)
    return run


# -------------------------------------------------------------- calibration

def perform_recalibrate(run):
    market = db.markets[run["market_id"]]
    if run["fit_status"] != "FITTED":
        raise ApiError("ERR_MODEL_RUN_INVALID_STATE",
                       "Only a FITTED model run can be recalibrated.")
    if run["calibration_status"] != "PENDING_CALIBRATION":
        raise ApiError("ERR_CALIBRATION_NOT_PENDING")

    records = {}
    for record in store.calibration_records_of_run(run["id"], live_only=True):
        records[record["channel_id"]] = record

    contributions = ordering.by_channel_code(
        store.contributions_of_run(run["id"], current_only=True))
    staged = []
    calibrated_total = ZERO
    for contribution in contributions:
        record = records.get(contribution["channel_id"])
        if record is not None:
            units = q4(D(contribution["contribution_units"]) * D(record["calibration_multiplier"]))
            revenue = q0(units * D(run["unit_price_cents"]))
        else:
            units = D(contribution["contribution_units"])
            revenue = contribution["contribution_revenue_cents"]
        staged.append((contribution, units, revenue))
        calibrated_total += units

    baseline = q4(D(run["modeled_sales_units"]) - calibrated_total)
    if baseline < 0:
        raise ApiError("ERR_MODEL_BASELINE_NEGATIVE",
                       "The calibrated contributions exceed modelled sales.")

    for contribution, units, revenue in staged:
        changed = (D(contribution["calibrated_contribution_units"]) != units
                   or contribution["calibrated_contribution_revenue_cents"] != revenue)
        contribution["calibrated_contribution_units"] = units
        contribution["calibrated_contribution_revenue_cents"] = revenue
        if changed:
            touch(contribution)

    run["baseline_sales_units"] = baseline
    run["calibration_status"] = "CALIBRATED"
    touch(run)
    sync_market(market)
    return run


# ----------------------------------------------------------------- cascades

def cascade_window_reopened(window):
    """PRD 3.3: the four-hop invalidation chain a reopen fires."""
    market = db.markets[window["market_id"]]
    affected_runs = []
    for run in store.runs_of_window(window["id"]):
        if run["fit_status"] == "FITTED":
            run["fit_status"] = "STALE_FIT"
            run["validation_status"] = "UNVALIDATED"
            touch(run)
            affected_runs.append(run)
    for run in affected_runs:
        for contribution in store.contributions_of_run(run["id"]):
            if contribution["is_current"]:
                contribution["is_current"] = False
                touch(contribution)
    for run in affected_runs:
        for scenario in store.scenarios_of_run(run["id"]):
            if scenario["status"] in ("OPTIMIZED", "APPROVED"):
                scenario["status"] = "INVALIDATED"
                touch(scenario)
    # Posture falls to FROZEN, which freezes every remaining OPTIMIZED scenario
    # of the whole market. DRAFT scenarios are untouched.
    sync_market(market)


def cascade_experiment_accepted(market):
    """PRD 3.6: staleness propagation when an incrementality read-out is accepted."""
    published = store.published_run_of_market(market["id"])
    if published is not None and published["calibration_status"] == "CALIBRATED":
        published["calibration_status"] = "STALE"
        touch(published)
        for report in store.reports_of_run(published["id"]):
            if report["status"] == "CURRENT":
                report["status"] = "STALE"
                touch(report)
    sync_market(market)
