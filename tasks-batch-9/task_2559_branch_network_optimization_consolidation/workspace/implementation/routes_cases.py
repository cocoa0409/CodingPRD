"""Consolidation cases, the governance decision branches, closure execution and unwind."""
from flask import Blueprint

import calc
import services as svc
from core import (DB, all_of, fail, new_record, public, touch, object_response,
                  list_response, clock_today_iso, day_diff, sort_key_created)
from validation import (authorize, json_body, pagination, filter_value, window,
                        req_int, req_str, req_enum, req_date, req_miles)

bp = Blueprint("cases", __name__)

READ_ALL = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer", "HRPartner",
            "RealEstateManager", "NetworkOpsAdmin", "BranchManager")
READ_GOVERNANCE = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer",
                   "NetworkOpsAdmin")

RATIONALE_CODES = ("LOW_PERFORMANCE", "LEASE_EXPIRY", "MARKET_OVERLAP", "DIGITAL_MIGRATION")
RETENTION_VARIANTS = ("DISTANCE_DECAY", "SEGMENT_MIX")
CASE_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "REJECTED", "SUPERSEDED", "APPROVED",
                 "NOTICE_FILED", "CLOSURE_EXECUTED", "POST_CLOSE_MONITORING", "UNWOUND",
                 "CLOSED_OUT")
MONITORING_POSTURES = ("NOT_STARTED", "ON_TRACK", "REMEDIATION", "RESOLVED")
FORECAST_STATUSES = ("ACTIVE", "SUPERSEDED")
SELECTOR_BRANCH_TYPES = ("FULL_SERVICE", "LIMITED_SERVICE")


def _new_case_fields(user_id, closing_branch_id, receiving_branch_id, rationale_code,
                     planned_closure_date, variant):
    return {
        "closing_branch_id": closing_branch_id,
        "receiving_branch_id": receiving_branch_id,
        "rationale_code": rationale_code,
        "planned_closure_date": planned_closure_date,
        "retention_model_variant": variant,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "decided_by_user_id": None,
        "returned_count": 0,
        "forecast_retention_bps": 0,
        "forecast_retained_deposits_cents": 0,
        "forecast_runoff_cents": 0,
        "severance_pool_cents": 0,
        "gross_annual_savings_cents": 0,
        "transition_incentive_rate_bps": 0,
        "transition_incentive_cents": 0,
        "net_annual_savings_cents": 0,
        "governance_flag": "NONE",
        "impact_tier": "UNASSESSED",
        "notice_required_days": 0,
        "pre_close_deposits_cents": None,
        "executed_on": None,
        "monitoring_posture": "NOT_STARTED",
        "last_observed_month_index": 0,
        "cumulative_variance_bps": 0,
        "severed_fte_count": 0,
        "redeployed_fte_count": 0,
        "pending_disposition_count": 0,
    }


def select_receiving_branch(closing):
    """PRD 3.3 selector policy: absorption floor then a three-key ranking."""
    candidates = []
    for b in all_of("branches"):
        if b["id"] == closing["id"]:
            continue
        if b["market_area_id"] != closing["market_area_id"]:
            continue
        if b["status"] != "ACTIVE":
            continue
        if b["branch_type"] not in SELECTOR_BRANCH_TYPES:
            continue
        if b["deposit_balance_cents"] * 10000 < closing["deposit_balance_cents"] * 5000:
            continue
        candidates.append(b)
    if not candidates:
        return None
    candidates.sort(key=lambda b: (-b["deposit_balance_cents"], -b["monthly_transaction_count"],
                                   b["created_at"], b["_seq"]))
    return candidates[0]


def supersede_prior_drafts(closing_branch_id, exclude_case_id=None):
    for case in all_of("consolidation_cases"):
        if case["closing_branch_id"] != closing_branch_id:
            continue
        if exclude_case_id is not None and case["id"] == exclude_case_id:
            continue
        if case["status"] != "DRAFT":
            continue
        case["status"] = "SUPERSEDED"
        touch(case)
        svc.supersede_active_forecast(case["id"])
        for a in svc.children_of("impact_assessments", "consolidation_case_id", case["id"]):
            if a["status"] in ("DRAFT", "FINALIZED", "REOPENED"):
                a["status"] = "SUPERSEDED"
                touch(a)


# --------------------------------------------------------------------------- #
# Case creation
# --------------------------------------------------------------------------- #
@bp.post("/distribution/consolidation-cases")
def create_case():
    user_id, _role = authorize(("NetworkStrategist",))
    body = json_body()
    closing_branch_id = req_str(body, "closing_branch_id")
    rationale_code = req_enum(body, "rationale_code", RATIONALE_CODES)
    planned_closure_date = req_date(body, "planned_closure_date")
    expected_branch_version = req_int(body, "expected_branch_version", minimum=1)
    variant = req_enum(body, "retention_model_variant", RETENTION_VARIANTS, required=False,
                       default="DISTANCE_DECAY")
    receiving_branch_id = req_str(body, "receiving_branch_id", required=False, default=None)

    closing = svc.ref_lookup("branches", closing_branch_id, "closing branch")
    receiving = None
    if receiving_branch_id is not None:
        receiving = svc.ref_lookup("branches", receiving_branch_id, "receiving branch")

    if closing["version"] != expected_branch_version:
        fail("ERR_STALE_BRANCH_VERSION",
             "Branch version is %d, not the pinned %d."
             % (closing["version"], expected_branch_version))

    for case in all_of("consolidation_cases"):
        if (case["closing_branch_id"] == closing_branch_id
                and case["status"] in svc.OPEN_CASE_STATUSES):
            fail("ERR_BRANCH_HAS_OPEN_CASE",
                 "Branch '%s' already carries an in-flight consolidation case."
                 % closing_branch_id)

    if closing["status"] != "ACTIVE":
        fail("ERR_BRANCH_NOT_ACTIVE",
             "Closing branch is in %s status, not ACTIVE." % closing["status"])

    if receiving is not None:
        if receiving["id"] == closing["id"]:
            fail("ERR_RECEIVING_BRANCH_INVALID",
                 "The receiving branch may not be the closing branch.")
        if receiving["market_area_id"] != closing["market_area_id"]:
            fail("ERR_RECEIVING_BRANCH_INVALID",
                 "The receiving branch must belong to the closing branch's trade area.")
    else:
        receiving = select_receiving_branch(closing)
        if receiving is None:
            fail("ERR_NO_ELIGIBLE_RECEIVING_BRANCH",
                 "No branch of the trade area satisfies the absorption floor.")

    supersede_prior_drafts(closing_branch_id)
    closing["status"] = "UNDER_REVIEW"
    touch(closing)

    rec = new_record("consolidation_cases", _new_case_fields(
        user_id, closing_branch_id, receiving["id"], rationale_code,
        planned_closure_date, variant))
    return object_response(public(rec), 201)


@bp.get("/distribution/consolidation-cases/<case_id>")
def read_case(case_id):
    authorize(READ_ALL)
    rec = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    return object_response(public(rec))


@bp.get("/distribution/consolidation-cases")
def list_cases():
    authorize(READ_ALL)
    limit, offset = pagination()
    closing_branch_id = filter_value("closing_branch_id")
    receiving_branch_id = filter_value("receiving_branch_id")
    status = filter_value("status", CASE_STATUSES)
    posture = filter_value("monitoring_posture", MONITORING_POSTURES)
    rows = all_of("consolidation_cases")
    if closing_branch_id is not None:
        rows = [r for r in rows if r["closing_branch_id"] == closing_branch_id]
    if receiving_branch_id is not None:
        rows = [r for r in rows if r["receiving_branch_id"] == receiving_branch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if r["monitoring_posture"] == posture]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# Submission, decision, revision
# --------------------------------------------------------------------------- #
@bp.post("/distribution/consolidation-cases/<case_id>/submit")
def submit_case(case_id):
    user_id, _role = authorize(("NetworkStrategist",))
    case = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    if case["created_by_user_id"] != user_id:
        fail("ERR_CASE_AUTHOR_REQUIRED", "Only the case author may submit this case.")
    if case["status"] != "DRAFT":
        fail("ERR_CASE_STATE_INVALID",
             "A case in %s status cannot be submitted." % case["status"])
    receiving = DB["branches"].get(case["receiving_branch_id"])
    if receiving is None or receiving["status"] != "ACTIVE":
        fail("ERR_RECEIVING_BRANCH_NOT_ACTIVE",
             "The case has no receiving branch in ACTIVE status.")
    if svc.active_forecast(case_id) is None:
        fail("ERR_RETENTION_FORECAST_MISSING",
             "The case has no retention forecast in ACTIVE status.")
    calc.recompute_severance_pool(case)
    calc.recompute_savings_chain(case)
    case["status"] = "SUBMITTED"
    touch(case)
    return object_response(public(case))


@bp.post("/distribution/consolidation-cases/<case_id>/decision")
def decide_case(case_id):
    user_id, _role = authorize(("ConsolidationApprover",))
    case = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    if case["created_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approver who authored this case may not decide it.")
    body = json_body()
    decision = req_enum(body, "decision", ("APPROVE", "RETURN", "REJECT"))
    expected_case_version = req_int(body, "expected_case_version", minimum=1)
    req_str(body, "reason_code", required=False, default=None)
    if case["version"] != expected_case_version:
        fail("ERR_STALE_CASE_VERSION",
             "Case version is %d, not the pinned %d."
             % (case["version"], expected_case_version))
    if case["status"] != "SUBMITTED":
        fail("ERR_CASE_STATE_INVALID",
             "A case in %s status cannot be decided." % case["status"])

    if decision == "APPROVE":
        if case["net_annual_savings_cents"] < calc.GOVERNANCE_FLOOR_CENTS:
            fail("ERR_SAVINGS_BELOW_FLOOR",
                 "Net annual savings of %d cents fall below the governance floor."
                 % case["net_annual_savings_cents"])
        case["status"] = "APPROVED"
    elif decision == "RETURN":
        if case["returned_count"] >= 3:
            fail("ERR_REVISION_LIMIT_EXCEEDED",
                 "The case has already been returned three times.")
        case["status"] = "RETURNED"
        case["returned_count"] = case["returned_count"] + 1
    else:
        case["status"] = "REJECTED"
        closing = DB["branches"].get(case["closing_branch_id"])
        others = [c for c in all_of("consolidation_cases")
                  if c["id"] != case_id
                  and c["closing_branch_id"] == case["closing_branch_id"]
                  and c["status"] in ("SUBMITTED", "APPROVED", "NOTICE_FILED")]
        if closing is not None and not others and closing["status"] == "UNDER_REVIEW":
            closing["status"] = "ACTIVE"
            touch(closing)
        svc.supersede_active_forecast(case_id)
        reset = False
        for a in svc.children_of("impact_assessments", "consolidation_case_id", case_id):
            if a["status"] in ("DRAFT", "FINALIZED", "REOPENED"):
                a["status"] = "SUPERSEDED"
                touch(a)
                reset = True
        if reset:
            case["impact_tier"] = "UNASSESSED"
            case["notice_required_days"] = 0

    case["decided_by_user_id"] = user_id
    touch(case)
    return object_response(public(case))


@bp.post("/distribution/consolidation-cases/<case_id>/revise")
def revise_case(case_id):
    user_id, _role = authorize(("NetworkStrategist",))
    case = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    if case["created_by_user_id"] != user_id:
        fail("ERR_CASE_AUTHOR_REQUIRED", "Only the case author may revise this case.")
    body = json_body()
    planned_closure_date = req_date(body, "planned_closure_date", required=False, default=None)
    receiving_branch_id = req_str(body, "receiving_branch_id", required=False, default=None)
    receiving = None
    if receiving_branch_id is not None:
        receiving = svc.ref_lookup("branches", receiving_branch_id, "receiving branch")
    if case["status"] != "RETURNED":
        fail("ERR_CASE_STATE_INVALID",
             "A case in %s status cannot be revised." % case["status"])
    if receiving is not None:
        if receiving["id"] == case["closing_branch_id"]:
            fail("ERR_RECEIVING_BRANCH_INVALID",
                 "The receiving branch may not be the closing branch.")
        if receiving["status"] != "ACTIVE":
            fail("ERR_RECEIVING_BRANCH_INVALID",
                 "The receiving branch must be in ACTIVE status.")
        case["receiving_branch_id"] = receiving["id"]
    if planned_closure_date is not None:
        case["planned_closure_date"] = planned_closure_date
    case["status"] = "DRAFT"
    touch(case)
    return object_response(public(case))


# --------------------------------------------------------------------------- #
# Closure execution, unwind and close-out
# --------------------------------------------------------------------------- #
@bp.post("/distribution/consolidation-cases/<case_id>/execute-closure")
def execute_closure(case_id):
    authorize(("ComplianceOfficer",))
    case = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    if case["status"] != "NOTICE_FILED":
        fail("ERR_CASE_STATE_INVALID",
             "A case in %s status cannot execute a closure." % case["status"])
    notice = svc.regulator_notice_open(case_id)
    if notice is None:
        fail("ERR_NOTICE_NOT_OPEN", "The case has no open regulatory closure notice.")
    receiving = DB["branches"].get(case["receiving_branch_id"])
    if receiving is None or receiving["status"] != "ACTIVE":
        fail("ERR_RECEIVING_BRANCH_NOT_ACTIVE", "The receiving branch is not ACTIVE.")
    today = clock_today_iso()
    if day_diff(today, notice["effective_closure_date"]) < 0:
        fail("ERR_NOTICE_PERIOD_NOT_ELAPSED",
             "The notice does not take effect until %s." % notice["effective_closure_date"])
    campaigns = svc.children_of("transition_campaigns", "consolidation_case_id", case_id)
    if not any(c["status"] == "LAUNCHED" for c in campaigns):
        fail("ERR_TRANSITION_CAMPAIGN_NOT_LAUNCHED",
             "No transition campaign of the case has been launched.")
    premises = [p for p in all_of("property_dispositions")
                if p["branch_id"] == case["closing_branch_id"]]
    if not premises:
        fail("ERR_PROPERTY_DISPOSITION_MISSING",
             "No premises disposition exists for the closing branch.")
    if case["pending_disposition_count"] != 0:
        fail("ERR_STAFF_DISPOSITIONS_PENDING",
             "%d staff disposition(s) are still pending." % case["pending_disposition_count"])

    closing = DB["branches"].get(case["closing_branch_id"])
    retained = case["forecast_retained_deposits_cents"]
    runoff = case["forecast_runoff_cents"]

    case["status"] = "CLOSURE_EXECUTED"
    case["executed_on"] = today
    case["pre_close_deposits_cents"] = closing["deposit_balance_cents"]

    closing["pre_close_deposits_cents"] = closing["deposit_balance_cents"]
    closing["deposit_balance_cents"] = 0
    closing["pre_close_fte_count"] = closing["fte_count"]
    closing["fte_count"] = 0
    closing["absorbing_branch_id"] = case["receiving_branch_id"]
    closing["status"] = "CLOSED"
    touch(closing)

    receiving["deposit_balance_cents"] += retained
    receiving["transferred_in_deposits_cents"] += retained
    touch(receiving)

    market = DB["market_areas"].get(closing["market_area_id"])
    if market is not None:
        market["absorbed_deposits_cents"] += retained
        market["cumulative_runoff_deposits_cents"] += runoff
        svc.refresh_market_footprint(market)

    for d in svc.children_of("staff_dispositions", "consolidation_case_id", case_id):
        if d["disposition_state"] == "OFFER_ACCEPTED":
            d["disposition_state"] = "COMPLETED"
            touch(d)
    for c in campaigns:
        if c["status"] == "LAUNCHED":
            c["status"] = "COMPLETED"
            touch(c)
    for p in svc.oldest_first(premises):
        if p["status"] == "PENDING":
            p["status"] = "MARKETED"
            p["marketing_started_on"] = today
            calc.refresh_carry(p)
            touch(p)

    calc.recompute_savings_chain(case)
    if case["net_annual_savings_cents"] < calc.GOVERNANCE_FLOOR_CENTS:
        svc.set_governance_flag(case, "SAVINGS_WATCH")
    touch(case)
    return object_response(public(case))


@bp.post("/distribution/consolidation-cases/<case_id>/unwind-closure")
def unwind_closure(case_id):
    authorize(("ComplianceOfficer",))
    case = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    body = json_body()
    req_str(body, "rescission_reason_code")
    if case["status"] != "CLOSURE_EXECUTED":
        fail("ERR_CASE_STATE_INVALID",
             "A case in %s status cannot be unwound." % case["status"])
    today = clock_today_iso()
    if case["last_observed_month_index"] != 0:
        fail("ERR_UNWIND_WINDOW_CLOSED",
             "A runoff observation has already landed against this closure.")
    if day_diff(today, case["executed_on"]) > calc.UNWIND_WINDOW_DAYS:
        fail("ERR_UNWIND_WINDOW_CLOSED", "The 30-day unwind window has closed.")

    closing = DB["branches"].get(case["closing_branch_id"])
    receiving = DB["branches"].get(case["receiving_branch_id"])
    retained = case["forecast_retained_deposits_cents"]
    runoff = case["forecast_runoff_cents"]

    case["status"] = "UNWOUND"

    if closing is not None:
        closing["deposit_balance_cents"] = closing["pre_close_deposits_cents"] or 0
        closing["pre_close_deposits_cents"] = None
        closing["fte_count"] = closing["pre_close_fte_count"] or 0
        closing["pre_close_fte_count"] = None
        closing["absorbing_branch_id"] = None
        closing["status"] = "ACTIVE"
        touch(closing)
    if receiving is not None:
        receiving["deposit_balance_cents"] -= retained
        receiving["transferred_in_deposits_cents"] -= retained
        touch(receiving)
    market = DB["market_areas"].get(closing["market_area_id"]) if closing else None
    if market is not None:
        market["absorbed_deposits_cents"] -= retained
        market["cumulative_runoff_deposits_cents"] -= runoff
        svc.refresh_market_footprint(market)

    notice = svc.regulator_notice_open(case_id)
    if notice is not None:
        notice["status"] = "WITHDRAWN"
        touch(notice)

    for p in svc.oldest_first(all_of("property_dispositions")):
        if p["branch_id"] != case["closing_branch_id"] or p["status"] != "MARKETED":
            continue
        p["status"] = "PENDING"
        p["marketing_started_on"] = None
        calc.refresh_carry(p)
        touch(p)

    calc.recompute_savings_chain(case)
    if case["governance_flag"] == "SAVINGS_WATCH":
        svc.set_governance_flag(case, "NONE")
    touch(case)
    return object_response(public(case))


@bp.post("/distribution/consolidation-cases/<case_id>/close-out")
def close_out_case(case_id):
    authorize(("NetworkOpsAdmin",))
    case = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    if case["status"] != "POST_CLOSE_MONITORING":
        fail("ERR_CASE_STATE_INVALID",
             "A case in %s status cannot be closed out." % case["status"])
    if (case["last_observed_month_index"] < calc.MONITORING_HORIZON_MONTHS
            or case["monitoring_posture"] not in ("ON_TRACK", "RESOLVED")):
        fail("ERR_MONITORING_INCOMPLETE",
             "The twelve-month monitoring horizon is not complete.")
    case["status"] = "CLOSED_OUT"
    touch(case)
    return object_response(public(case))


# --------------------------------------------------------------------------- #
# Retention forecasts (PRD 3.3)
# --------------------------------------------------------------------------- #
@bp.post("/distribution/retention-forecasts")
def create_retention_forecast():
    authorize(("NetworkStrategist",))
    body = json_body()
    case_id = req_str(body, "consolidation_case_id")
    model_variant = req_enum(body, "model_variant", RETENTION_VARIANTS)
    distance_miles = req_miles(body, "distance_miles")
    retail = req_int(body, "retail_share_bps", minimum=0, maximum=10000)
    small_business = req_int(body, "small_business_share_bps", minimum=0, maximum=10000)
    wealth = req_int(body, "wealth_share_bps", minimum=0, maximum=10000)
    expected_case_version = req_int(body, "expected_case_version", minimum=1)

    case = svc.ref_lookup("consolidation_cases", case_id, "consolidation case")
    if case["version"] != expected_case_version:
        fail("ERR_STALE_CASE_VERSION",
             "Case version is %d, not the pinned %d."
             % (case["version"], expected_case_version))
    if retail + small_business + wealth != 10000:
        fail("ERR_SEGMENT_MIX_INVALID",
             "The three segment shares must sum to exactly 10000 basis points.")

    closing = DB["branches"].get(case["closing_branch_id"])
    baseline = closing["deposit_balance_cents"] if closing else 0
    digital = closing["digital_adoption_bps"] if closing else 0

    bps = calc.retention_bps(model_variant, distance_miles, digital,
                             retail, small_business, wealth)
    retained, runoff = calc.retention_split(baseline, bps)

    svc.supersede_active_forecast(case_id)
    rec = new_record("retention_forecasts", {
        "consolidation_case_id": case_id,
        "model_variant": model_variant,
        "distance_miles": distance_miles,
        "retail_share_bps": retail,
        "small_business_share_bps": small_business,
        "wealth_share_bps": wealth,
        "baseline_deposits_cents": baseline,
        "digital_adoption_bps": digital,
        "retention_bps": bps,
        "retained_deposits_cents": retained,
        "runoff_cents": runoff,
        "status": "ACTIVE",
    })

    case["forecast_retention_bps"] = bps
    case["forecast_retained_deposits_cents"] = retained
    case["forecast_runoff_cents"] = runoff
    svc.refresh_case_savings(case)
    return object_response(public(rec), 201)


@bp.get("/distribution/consolidation-cases/<case_id>/retention-forecasts")
def list_case_forecasts(case_id):
    authorize(READ_GOVERNANCE)
    limit, offset = pagination()
    status = filter_value("status", FORECAST_STATUSES)
    svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    rows = svc.children_of("retention_forecasts", "consolidation_case_id", case_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = svc.newest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.get("/distribution/retention-forecasts/<forecast_id>")
def read_retention_forecast(forecast_id):
    authorize(READ_GOVERNANCE)
    rec = svc.path_lookup("retention_forecasts", forecast_id, "Retention forecast")
    return object_response(public(rec))


@bp.get("/distribution/retention-forecasts")
def list_retention_forecasts():
    authorize(READ_GOVERNANCE)
    limit, offset = pagination()
    case_id = filter_value("consolidation_case_id")
    model_variant = filter_value("model_variant", RETENTION_VARIANTS)
    status = filter_value("status", FORECAST_STATUSES)
    rows = all_of("retention_forecasts")
    if case_id is not None:
        rows = [r for r in rows if r["consolidation_case_id"] == case_id]
    if model_variant is not None:
        rows = [r for r in rows if r["model_variant"] == model_variant]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)
