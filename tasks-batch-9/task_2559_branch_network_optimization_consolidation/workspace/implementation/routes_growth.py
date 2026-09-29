"""Customer transition waves, de novo growth, runoff surveillance and the logical clock."""
from flask import Blueprint

import calc
import services as svc
from core import (DB, all_of, fail, new_record, public, touch, object_response,
                  list_response, clock_today_iso, day_diff, parse_date)
from validation import (authorize, json_body, pagination, filter_value, filter_bool, window,
                        req_int, req_str, req_enum, req_date, req_instant)

bp = Blueprint("growth", __name__)

READ_CAMPAIGN = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer",
                 "NetworkOpsAdmin", "BranchManager")
CHANNEL_MIXES = ("LETTER_ONLY", "LETTER_EMAIL", "FULL_OMNI")
CAMPAIGN_STATUSES = ("PLANNED", "LAUNCHED", "COMPLETED", "CANCELLED")
PLAN_STATUSES = ("SITE_IDENTIFIED", "REJECTED", "APPROVED", "HELD", "OPENED",
                 "RAMP_TRACKING", "RAMP_MET", "RAMP_REMEDIATION")
RAMP_STATUSES = ("UNTRACKED", "ON_TRACK", "BEHIND", "AT_RISK", "MET")
SUBJECT_TYPES = ("CONSOLIDATION_CASE", "DE_NOVO_PLAN")
BRANCH_TYPES = ("FULL_SERVICE", "LIMITED_SERVICE", "DRIVE_UP")
TENURE_CLASSES = ("LEASED", "OWNED")
TRACKABLE_CASE_STATUSES = ("CLOSURE_EXECUTED", "POST_CLOSE_MONITORING")
TRACKABLE_PLAN_STATUSES = ("OPENED", "RAMP_TRACKING", "RAMP_REMEDIATION")


# --------------------------------------------------------------------------- #
# Customer transition campaigns
# --------------------------------------------------------------------------- #
def _peak_daily_load(receiving_branch_id, start_date, end_date, new_load,
                     exclude_campaign_id=None):
    start = parse_date(start_date)
    end = parse_date(end_date)
    others = []
    for c in all_of("transition_campaigns"):
        if c["receiving_branch_id"] != receiving_branch_id:
            continue
        if exclude_campaign_id is not None and c["id"] == exclude_campaign_id:
            continue
        if c["status"] not in ("PLANNED", "LAUNCHED"):
            continue
        others.append((parse_date(c["wave_start_date"]), parse_date(c["wave_end_date"]),
                       c["daily_onboarding_load"]))
    peak = 0
    day = start
    while day < end:
        load = new_load
        for (cs, ce, dl) in others:
            if cs <= day < ce:
                load += dl
        if load > peak:
            peak = load
        day = day.fromordinal(day.toordinal() + 1)
    return peak


@bp.post("/distribution/transition-campaigns")
def create_campaign():
    authorize(("ComplianceOfficer",))
    body = json_body()
    case_id = req_str(body, "consolidation_case_id")
    wave_start_date = req_date(body, "wave_start_date")
    wave_end_date = req_date(body, "wave_end_date")
    inbound = req_int(body, "inbound_household_count", minimum=1)
    channel_mix = req_enum(body, "channel_mix", CHANNEL_MIXES)

    case = svc.ref_lookup("consolidation_cases", case_id, "consolidation case")

    if day_diff(wave_end_date, wave_start_date) <= 0:
        fail("ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT",
             "The wave end date must fall strictly after the wave start date.")

    wave_days, daily_load = calc.wave_metrics(wave_start_date, wave_end_date, inbound)
    receiving = DB["branches"].get(case["receiving_branch_id"])
    capacity = receiving["onboarding_capacity_households_per_day"] if receiving else 0
    peak = _peak_daily_load(case["receiving_branch_id"], wave_start_date, wave_end_date,
                            daily_load)
    if peak > capacity:
        fail("ERR_ABSORPTION_CAPACITY_EXCEEDED",
             "Peak daily onboarding load of %d exceeds the receiving branch capacity of %d."
             % (peak, capacity))

    rec = new_record("transition_campaigns", {
        "consolidation_case_id": case_id,
        "receiving_branch_id": case["receiving_branch_id"],
        "wave_start_date": wave_start_date,
        "wave_end_date": wave_end_date,
        "inbound_household_count": inbound,
        "channel_mix": channel_mix,
        "wave_days": wave_days,
        "daily_onboarding_load": daily_load,
        "status": "PLANNED",
        "launched_on": None,
    })
    return object_response(public(rec), 201)


@bp.get("/distribution/transition-campaigns/<campaign_id>")
def read_campaign(campaign_id):
    authorize(READ_CAMPAIGN)
    rec = svc.path_lookup("transition_campaigns", campaign_id, "Transition campaign")
    return object_response(public(rec))


@bp.get("/distribution/transition-campaigns")
def list_campaigns():
    authorize(READ_CAMPAIGN)
    limit, offset = pagination()
    case_id = filter_value("consolidation_case_id")
    receiving_branch_id = filter_value("receiving_branch_id")
    status = filter_value("status", CAMPAIGN_STATUSES)
    rows = all_of("transition_campaigns")
    if case_id is not None:
        rows = [r for r in rows if r["consolidation_case_id"] == case_id]
    if receiving_branch_id is not None:
        rows = [r for r in rows if r["receiving_branch_id"] == receiving_branch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.post("/distribution/transition-campaigns/<campaign_id>/launch")
def launch_campaign(campaign_id):
    authorize(("ComplianceOfficer",))
    campaign = svc.path_lookup("transition_campaigns", campaign_id, "Transition campaign")
    case = DB["consolidation_cases"].get(campaign["consolidation_case_id"])
    if case is None or case["status"] != "NOTICE_FILED":
        fail("ERR_CASE_STATE_INVALID",
             "A transition wave may only be launched while the case stands at NOTICE_FILED.")
    if campaign["status"] != "PLANNED":
        fail("ERR_CAMPAIGN_STATE_INVALID",
             "A campaign in %s status cannot be launched." % campaign["status"])
    today = clock_today_iso()
    if day_diff(campaign["wave_start_date"], today) <= 0:
        fail("ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT",
             "The wave start date has already been reached.")
    notice = svc.regulator_notice_open(case["id"])
    if notice is None:
        fail("ERR_CASE_STATE_INVALID", "The case has no open regulatory closure notice.")
    if day_diff(campaign["wave_start_date"], notice["filed_on"]) < calc.CAMPAIGN_NOTICE_LEAD_DAYS:
        fail("ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT",
             "The wave must start at least %d days after the notice filing."
             % calc.CAMPAIGN_NOTICE_LEAD_DAYS)
    campaign["status"] = "LAUNCHED"
    campaign["launched_on"] = today
    touch(campaign)
    return object_response(public(campaign))


# --------------------------------------------------------------------------- #
# De novo site plans
# --------------------------------------------------------------------------- #
@bp.post("/distribution/de-novo-plans")
def create_de_novo_plan():
    authorize(("NetworkStrategist",))
    body = json_body()
    market_area_id = req_str(body, "market_area_id")
    site_label = req_str(body, "site_label", min_len=1, max_len=80)
    proposed_branch_code = req_str(body, "proposed_branch_code", pattern=r"[A-Z]{2}-[0-9]{3}")
    target_year1 = req_int(body, "target_year1_deposits_cents", minimum=1)
    capex = req_int(body, "capex_budget_cents", minimum=0)

    market = svc.ref_lookup("market_areas", market_area_id, "market area")

    rec = new_record("de_novo_plans", {
        "market_area_id": market_area_id,
        "opened_branch_id": None,
        "site_label": site_label,
        "proposed_branch_code": proposed_branch_code,
        "target_year1_deposits_cents": target_year1,
        "capex_budget_cents": capex,
        "site_score": calc.site_score(market),
        "status": "SITE_IDENTIFIED",
        "opened_on": None,
        "ramp_month_index": 0,
        "ramp_attainment_bps": 0,
        "ramp_status": "UNTRACKED",
    })
    return object_response(public(rec), 201)


@bp.get("/distribution/de-novo-plans/<plan_id>")
def read_de_novo_plan(plan_id):
    authorize(READ_CAMPAIGN)
    rec = svc.path_lookup("de_novo_plans", plan_id, "De novo site plan")
    return object_response(public(rec))


@bp.get("/distribution/de-novo-plans")
def list_de_novo_plans():
    authorize(READ_CAMPAIGN)
    limit, offset = pagination()
    market_area_id = filter_value("market_area_id")
    opened_branch_id = filter_value("opened_branch_id")
    status = filter_value("status", PLAN_STATUSES)
    ramp_status = filter_value("ramp_status", RAMP_STATUSES)
    rows = all_of("de_novo_plans")
    if market_area_id is not None:
        rows = [r for r in rows if r["market_area_id"] == market_area_id]
    if opened_branch_id is not None:
        rows = [r for r in rows if r["opened_branch_id"] == opened_branch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if ramp_status is not None:
        rows = [r for r in rows if r["ramp_status"] == ramp_status]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.post("/distribution/de-novo-plans/<plan_id>/decision")
def decide_de_novo_plan(plan_id):
    authorize(("ConsolidationApprover",))
    body = json_body()
    decision = req_enum(body, "decision", ("APPROVE", "REJECT"))
    req_str(body, "reason_code", required=False, default=None)
    plan = svc.path_lookup("de_novo_plans", plan_id, "De novo site plan")
    if plan["status"] != "SITE_IDENTIFIED":
        fail("ERR_PLAN_STATE_INVALID",
             "A plan in %s status cannot be decided." % plan["status"])
    if decision == "APPROVE":
        market = DB["market_areas"].get(plan["market_area_id"])
        if plan["site_score"] < calc.SITE_SCORE_MINIMUM:
            fail("ERR_SITE_SCORE_BELOW_MINIMUM",
                 "Site score %d falls below the siting minimum of %d."
                 % (plan["site_score"], calc.SITE_SCORE_MINIMUM))
        if market is not None and market["saturation_tier"] == "OVER_BRANCHED":
            fail("ERR_MARKET_OVER_BRANCHED", "The trade area is OVER_BRANCHED.")
        if market is not None and market["de_novo_hold"]:
            fail("ERR_MARKET_DE_NOVO_HOLD", "The trade area is under a de novo hold.")
        plan["status"] = "APPROVED"
    else:
        plan["status"] = "REJECTED"
    touch(plan)
    return object_response(public(plan))


@bp.post("/distribution/de-novo-plans/<plan_id>/open")
def open_de_novo_plan(plan_id):
    authorize(("NetworkStrategist",))
    body = json_body()
    branch_type = req_enum(body, "branch_type", BRANCH_TYPES)
    tenure_class = req_enum(body, "tenure_class", TENURE_CLASSES)
    capacity = req_int(body, "onboarding_capacity_households_per_day", minimum=1,
                       required=False, default=40)
    plan = svc.path_lookup("de_novo_plans", plan_id, "De novo site plan")
    if plan["status"] != "APPROVED":
        fail("ERR_PLAN_STATE_INVALID",
             "A plan in %s status cannot be opened." % plan["status"])
    for b in all_of("branches"):
        if b["branch_code"] == plan["proposed_branch_code"]:
            fail("ERR_DUPLICATE_KEY",
                 "Branch code '%s' is already in use." % plan["proposed_branch_code"])
    market = DB["market_areas"].get(plan["market_area_id"])
    if market is not None and market["de_novo_hold"]:
        fail("ERR_MARKET_DE_NOVO_HOLD", "The trade area is under a de novo hold.")

    today = clock_today_iso()
    branch = new_record("branches", {
        "market_area_id": plan["market_area_id"],
        "branch_code": plan["proposed_branch_code"],
        "branch_type": branch_type,
        "tenure_class": tenure_class,
        "status": "DE_NOVO_RAMPING",
        "deposit_balance_cents": 0,
        "monthly_transaction_count": 0,
        "digital_adoption_bps": 0,
        "annual_noninterest_expense_cents": 0,
        "annual_revenue_cents": 0,
        "fte_count": 0,
        "atm_count": 1,
        "opened_on": today,
        "scoring_variant": "TRAILING_BLEND",
        "onboarding_capacity_households_per_day": capacity,
        "absorbing_branch_id": None,
        "performance_score_bps": None,
        "performance_band": "UNSCORED",
        "snapshot_count": 0,
        "pre_close_deposits_cents": None,
        "pre_close_fte_count": None,
        "transferred_in_deposits_cents": 0,
    })
    if market is not None:
        svc.refresh_market_footprint(market)

    plan["opened_branch_id"] = branch["id"]
    plan["opened_on"] = today
    plan["status"] = "RAMP_TRACKING"
    plan["ramp_month_index"] = 0
    plan["ramp_status"] = "ON_TRACK"
    touch(plan)
    return object_response(public(plan))


# --------------------------------------------------------------------------- #
# Deposit observations (PRD 3.9)
# --------------------------------------------------------------------------- #
def _apply_case_observation(case, month_index, observed):
    forecast = calc.case_forecast_deposits_cents(
        case["pre_close_deposits_cents"] or 0, case["forecast_runoff_cents"], month_index)
    variance = calc.variance_against_forecast_bps(observed, forecast)
    breach = variance <= calc.BREACH_THRESHOLD_BPS

    case["last_observed_month_index"] = month_index
    case["cumulative_variance_bps"] = variance
    if case["status"] == "CLOSURE_EXECUTED":
        case["status"] = "POST_CLOSE_MONITORING"

    previous = case["monitoring_posture"]
    if breach:
        posture = "REMEDIATION"
    elif previous == "REMEDIATION" and variance >= calc.RECOVERY_THRESHOLD_BPS:
        posture = "RESOLVED"
    else:
        posture = "ON_TRACK"
    case["monitoring_posture"] = posture
    touch(case)

    market = DB["market_areas"].get(svc.market_of_case(case))
    if market is not None:
        if posture == "REMEDIATION" and previous != "REMEDIATION":
            market["remediation_case_count"] += 1
            touch(market)
        elif previous == "REMEDIATION" and posture == "RESOLVED":
            market["remediation_case_count"] -= 1
            touch(market)
        svc.apply_de_novo_hold(market)
    return forecast, variance, breach


def _apply_plan_observation(plan, month_index, observed):
    target = calc.ramp_target_cents(plan["target_year1_deposits_cents"], month_index)
    attainment = calc.ramp_attainment_bps(observed, target)
    variance = attainment - 10000
    breach = attainment < calc.RAMP_AT_RISK_BPS

    plan["ramp_month_index"] = month_index
    plan["ramp_attainment_bps"] = attainment
    plan["ramp_status"] = calc.ramp_status_for(month_index, attainment)

    # PRD 3.9: the four status rules are applied in the order the PRD states them,
    # so a recovery out of RAMP_REMEDIATION can feed the month-12 RAMP_MET rule in
    # the same request.
    status = plan["status"]
    if status == "OPENED":
        status = "RAMP_TRACKING"
    if status == "RAMP_TRACKING" and attainment < calc.RAMP_AT_RISK_BPS:
        status = "RAMP_REMEDIATION"
        plan["ramp_status"] = "AT_RISK"
    if status == "RAMP_REMEDIATION" and attainment >= calc.RAMP_AT_RISK_BPS:
        status = "RAMP_TRACKING"
    if (status == "RAMP_TRACKING" and month_index == calc.MONITORING_HORIZON_MONTHS
            and attainment >= calc.RAMP_MET_BPS):
        status = "RAMP_MET"
        plan["ramp_status"] = "MET"
        branch = DB["branches"].get(plan["opened_branch_id"])
        if branch is not None and branch["status"] == "DE_NOVO_RAMPING":
            branch["status"] = "ACTIVE"
            touch(branch)
    plan["status"] = status
    touch(plan)
    return target, variance, breach


@bp.post("/distribution/deposit-observations")
def create_deposit_observation():
    authorize(("NetworkOpsAdmin", "NetworkStrategist"))
    body = json_body()
    subject_type = req_enum(body, "subject_type", SUBJECT_TYPES)
    month_index = req_int(body, "month_index", minimum=1, maximum=12)
    observed = req_int(body, "observed_deposits_cents", minimum=0)
    case_id = req_str(body, "consolidation_case_id", required=False, default=None)
    plan_id = req_str(body, "de_novo_plan_id", required=False, default=None)

    case = svc.ref_lookup("consolidation_cases", case_id, "consolidation case") \
        if case_id is not None else None
    plan = svc.ref_lookup("de_novo_plans", plan_id, "de novo site plan") \
        if plan_id is not None else None

    coherent_case = (subject_type == "CONSOLIDATION_CASE" and case is not None
                     and plan is None)
    coherent_plan = (subject_type == "DE_NOVO_PLAN" and plan is not None and case is None)

    if coherent_case and month_index <= case["last_observed_month_index"]:
        fail("ERR_OBSERVATION_OUT_OF_SEQUENCE",
             "Month %d does not follow the last recorded month %d."
             % (month_index, case["last_observed_month_index"]))
    if coherent_plan and month_index <= plan["ramp_month_index"]:
        fail("ERR_OBSERVATION_OUT_OF_SEQUENCE",
             "Month %d does not follow the last recorded month %d."
             % (month_index, plan["ramp_month_index"]))

    if coherent_case:
        if case["status"] not in TRACKABLE_CASE_STATUSES:
            fail("ERR_OBSERVATION_SUBJECT_MISMATCH",
                 "A case in %s status is not trackable." % case["status"])
    elif coherent_plan:
        if plan["status"] not in TRACKABLE_PLAN_STATUSES:
            fail("ERR_OBSERVATION_SUBJECT_MISMATCH",
                 "A plan in %s status is not trackable." % plan["status"])
    else:
        fail("ERR_OBSERVATION_SUBJECT_MISMATCH",
             "Exactly one foreign key matching the subject type must be supplied.")

    if coherent_case:
        forecast, variance, breach = _apply_case_observation(case, month_index, observed)
    else:
        forecast, variance, breach = _apply_plan_observation(plan, month_index, observed)

    rec = new_record("deposit_observations", {
        "subject_type": subject_type,
        "consolidation_case_id": case_id,
        "de_novo_plan_id": plan_id,
        "month_index": month_index,
        "observed_deposits_cents": observed,
        "forecast_deposits_cents": forecast,
        "variance_bps": variance,
        "breach": breach,
        "observed_on": clock_today_iso(),
    }, versioned=False)
    return object_response(public(rec), 201)


@bp.get("/distribution/deposit-observations/<observation_id>")
def read_deposit_observation(observation_id):
    authorize(READ_CAMPAIGN)
    rec = svc.path_lookup("deposit_observations", observation_id, "Deposit observation")
    return object_response(public(rec))


@bp.get("/distribution/deposit-observations")
def list_deposit_observations():
    authorize(READ_CAMPAIGN)
    limit, offset = pagination()
    subject_type = filter_value("subject_type", SUBJECT_TYPES)
    case_id = filter_value("consolidation_case_id")
    plan_id = filter_value("de_novo_plan_id")
    breach = filter_bool("breach")
    rows = all_of("deposit_observations")
    if subject_type is not None:
        rows = [r for r in rows if r["subject_type"] == subject_type]
    if case_id is not None:
        rows = [r for r in rows if r["consolidation_case_id"] == case_id]
    if plan_id is not None:
        rows = [r for r in rows if r["de_novo_plan_id"] == plan_id]
    if breach is not None:
        rows = [r for r in rows if r["breach"] == breach]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# The logical clock (PRD 2.8)
# --------------------------------------------------------------------------- #
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(("NetworkOpsAdmin",))
    body = json_body()
    instant = req_instant(body, "to_iso8601")
    return object_response(svc.advance_clock(instant))
