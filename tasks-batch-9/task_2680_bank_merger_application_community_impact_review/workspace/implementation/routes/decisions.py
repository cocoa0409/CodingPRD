"""Approval decisions, conditions and consummation (PRD 3.10, 3.11)."""
from flask import Blueprint

import aggregates
import calc
from db import db, add_days, new_record, now_str, parse_dt, serialize, set_fields, touch
from errors import ApiError
from helpers import (
    ensure_application_filer,
    fetch,
    fetch_fk,
    list_and_respond,
    now,
    require_usd,
)
from middleware import (
    ALL_ROLES,
    ROLE_FILER,
    ROLE_MONITOR,
    ROLE_OFFICIAL,
    actor_id,
    get_body,
    present,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response

decisions_bp = Blueprint("decisions", __name__)

DECISIONS = ("APPROVED", "CONDITIONALLY_APPROVED", "DENIED")
CONDITION_TYPES = (
    "DIVESTITURE",
    "COMMUNITY_BENEFITS",
    "CAPITAL_MAINTENANCE",
    "BRANCH_RETENTION",
    "SYSTEMS_CONVERSION",
)
TIMINGS = ("PRE_CONSUMMATION", "POST_CLOSING")


@decisions_bp.post("/approval-decisions")
@require_roles(ROLE_OFFICIAL)
def create_decision():
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    decision_value = req_enum(body, "decision", DECISIONS)

    application = fetch_fk("applications", application_id)
    if application.get("recommended_by_user_id") is not None and actor_id() == application[
        "recommended_by_user_id"
    ]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the deciding official may not be the recorded recommender",
        )
    if aggregates.application_decision(application["id"]) is not None:
        raise ApiError(
            "ERR_DECISION_ALREADY_ISSUED", "an order has already been issued on this application"
        )
    if application["filing_status"] != "RECOMMENDED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "only a RECOMMENDED application can be decided",
        )
    if decision_value in ("APPROVED", "CONDITIONALLY_APPROVED"):
        if application["competitive_posture"] == "BLOCKED":
            raise ApiError(
                "ERR_COMPETITIVE_POSTURE_BLOCKED", "the competitive posture is BLOCKED"
            )

    hearing_granted = aggregates.granted_hearing_count(application["id"]) > 0
    max_delta = aggregates.max_hhi_delta(application["id"])
    expedited = calc.expedited_eligible(
        application["unresolved_protest_count"],
        hearing_granted,
        max_delta,
        application["management_rating"],
    )
    decided_dt = now()

    if decision_value == "DENIED":
        fields = {
            "application_id": application["id"],
            "decision": decision_value,
            "decided_by_user_id": actor_id(),
            "decided_at": now_str(),
            "expedited_processing": expedited,
            "waiting_period_days": 0,
            "consummation_window_open_at": None,
            "consummation_deadline_at": None,
            "status": "CLOSED",
            "consummated_at": None,
        }
    else:
        days = calc.waiting_period_days(
            application["structure"],
            hearing_granted,
            application["unresolved_protest_count"],
            expedited,
        )
        from db import fmt_dt

        fields = {
            "application_id": application["id"],
            "decision": decision_value,
            "decided_by_user_id": actor_id(),
            "decided_at": now_str(),
            "expedited_processing": expedited,
            "waiting_period_days": days,
            "consummation_window_open_at": fmt_dt(add_days(decided_dt, days)),
            "consummation_deadline_at": fmt_dt(
                add_days(decided_dt, calc.CONSUMMATION_DEADLINE_DAYS)
            ),
            "status": "ISSUED",
            "consummated_at": None,
        }

    record = new_record(fields)
    db.decisions[record["id"]] = record

    if decision_value == "DENIED":
        application["filing_status"] = "DENIED"
        touch(application)
        touched_markets = set()
        for branch in db.branches.values():
            if branch.get("designation_application_id") == application["id"] and branch[
                "status"
            ] in ("DESIGNATED_FOR_DIVESTITURE", "DESIGNATED_FOR_CLOSURE"):
                set_fields(
                    branch,
                    status="OPEN",
                    designation_application_id=None,
                    notice_sent_at=None,
                    planned_closure_date=None,
                )
                touched_markets.add(branch["market_id"])
        aggregates.recompute_market_ids(touched_markets)
    else:
        application["filing_status"] = "DECIDED"
        touch(application)
    return object_response(serialize(record), 201)


@decisions_bp.get("/approval-decisions/<record_id>")
@require_roles(*ALL_ROLES)
def get_decision(record_id):
    return object_response(serialize(fetch("decisions", record_id)))


@decisions_bp.get("/approval-decisions")
@require_roles(*ALL_ROLES)
def list_decisions():
    return list_and_respond("decisions", ("application_id", "status"))


@decisions_bp.post("/approval-conditions")
@require_roles(ROLE_OFFICIAL)
def create_condition():
    body = get_body(required=True)
    decision_id = req_str(body, "decision_id")
    condition_type = req_enum(body, "condition_type", CONDITION_TYPES)
    timing = req_enum(body, "timing", TIMINGS)
    description = req_str(body, "description", min_len=1, max_len=2000)
    threshold_usd = (
        require_usd(body, "threshold_usd") if present(body, "threshold_usd") else None
    )

    decision = fetch_fk("decisions", decision_id)
    record = new_record(
        {
            "decision_id": decision["id"],
            "condition_type": condition_type,
            "timing": timing,
            "description": description,
            "threshold_usd": threshold_usd,
            "status": "OPEN",
            "satisfied_at": None,
            "satisfied_by_user_id": None,
        }
    )
    db.conditions[record["id"]] = record
    return object_response(serialize(record), 201)


@decisions_bp.get("/approval-conditions/<record_id>")
@require_roles(*ALL_ROLES)
def get_condition(record_id):
    return object_response(serialize(fetch("conditions", record_id)))


@decisions_bp.get("/approval-conditions")
@require_roles(*ALL_ROLES)
def list_conditions():
    return list_and_respond("conditions", ("decision_id", "timing", "status", "condition_type"))


@decisions_bp.post("/approval-conditions/<record_id>/satisfy")
@require_roles(ROLE_MONITOR)
def satisfy_condition(record_id):
    condition = fetch("conditions", record_id)
    get_body(required=False)
    decision = db.decisions.get(condition["decision_id"])
    if decision is None:
        raise ApiError("ERR_DECISION_NOT_FOUND", "the condition's decision is unknown")
    application = db.applications.get(decision["application_id"])

    if condition["status"] == "SATISFIED":
        raise ApiError(
            "ERR_INVALID_CONDITION_STATE", "the condition is already SATISFIED"
        )
    if decision["status"] not in ("ISSUED", "CONSUMMATED"):
        raise ApiError(
            "ERR_INVALID_DECISION_STATE", "the order must be ISSUED or CONSUMMATED"
        )

    if condition["status"] == "BREACHED":
        plan = aggregates.executed_plan(decision["application_id"])
        if plan is None:
            raise ApiError(
                "ERR_BENEFITS_PLAN_NOT_EXECUTED",
                "no EXECUTED community benefits plan exists for the application",
            )
        if int(plan["consecutive_deficient_periods"]) != 0 or plan[
            "compliance_status"
        ] == "DEFICIENT":
            raise ApiError(
                "ERR_INVALID_CONDITION_STATE",
                "the plan has not recovered from its deficiency run",
            )
    else:
        if condition["condition_type"] == "DIVESTITURE":
            if application is None or application["competitive_posture"] not in (
                "CLEARED",
                "CLEARED_WITH_DIVESTITURE",
            ):
                raise ApiError(
                    "ERR_COMPETITIVE_POSTURE_BLOCKED",
                    "the competitive posture does not clear the divestiture condition",
                )
        elif condition["condition_type"] == "COMMUNITY_BENEFITS":
            if aggregates.executed_plan(decision["application_id"]) is None:
                raise ApiError(
                    "ERR_BENEFITS_PLAN_NOT_EXECUTED",
                    "no EXECUTED community benefits plan exists for the application",
                )

    condition["_satisfied_by_cascade"] = False
    set_fields(
        condition,
        status="SATISFIED",
        satisfied_at=now_str(),
        satisfied_by_user_id=actor_id(),
    )
    if application is not None:
        still_breached = any(
            c["status"] == "BREACHED" for c in aggregates.decision_conditions(decision["id"])
        )
        if not still_breached and application["post_closing_monitoring_status"] == "ESCALATED":
            set_fields(application, post_closing_monitoring_status="MONITORING")
    return object_response(serialize(condition))


@decisions_bp.post("/approval-decisions/<record_id>/consummate")
@require_roles(ROLE_FILER)
def consummate(record_id):
    decision = fetch("decisions", record_id)
    get_body(required=False)
    application = db.applications.get(decision["application_id"])
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "the order's application is unknown")
    ensure_application_filer(application)

    if decision["status"] != "ISSUED" or decision["decision"] not in (
        "APPROVED",
        "CONDITIONALLY_APPROVED",
    ):
        raise ApiError("ERR_INVALID_DECISION_STATE", "the order is not an issued approval")

    for period in aggregates.application_periods(application["id"]):
        if period["status"] != "CLOSED":
            raise ApiError(
                "ERR_COMMENT_PERIOD_NOT_OPEN",
                "every public comment period must be CLOSED before consummation",
            )

    conditions = aggregates.decision_conditions(decision["id"])
    for condition in conditions:
        if condition["timing"] == "PRE_CONSUMMATION" and condition["status"] != "SATISFIED":
            raise ApiError(
                "ERR_CONDITION_NOT_SATISFIED",
                "a pre-consummation condition is not SATISFIED",
            )

    instant = now()
    window_open = parse_dt(decision["consummation_window_open_at"])
    deadline = parse_dt(decision["consummation_deadline_at"])
    if window_open is not None and instant < window_open:
        raise ApiError(
            "ERR_WAITING_PERIOD_NOT_ELAPSED", "the statutory waiting period has not elapsed"
        )
    if deadline is not None and instant > deadline:
        # the lapse is recorded before the error is returned (PRD 3.11)
        set_fields(decision, status="LAPSED")
        raise ApiError(
            "ERR_CONSUMMATION_WINDOW_LAPSED", "the consummation window has lapsed"
        )

    if any(c["condition_type"] == "COMMUNITY_BENEFITS" for c in conditions):
        if aggregates.executed_plan(application["id"]) is None:
            raise ApiError(
                "ERR_BENEFITS_PLAN_NOT_EXECUTED",
                "an EXECUTED community benefits plan is required",
            )

    set_fields(decision, status="CONSUMMATED", consummated_at=now_str())
    application["filing_status"] = "CONSUMMATED"
    touch(application)

    acquirer = db.institutions.get(application["acquirer_id"])
    target = db.institutions.get(application["target_id"])
    touched_markets = set()
    if target is not None:
        set_fields(target, status="MERGED_OUT")
        for branch in db.branches.values():
            if branch["institution_id"] == target["id"] and branch["status"] == "OPEN":
                set_fields(branch, institution_id=application["acquirer_id"])
                touched_markets.add(branch["market_id"])
    for branch in db.branches.values():
        if (
            branch.get("designation_application_id") == application["id"]
            and branch["status"] == "DESIGNATED_FOR_DIVESTITURE"
        ):
            set_fields(branch, status="DIVESTED")
            touched_markets.add(branch["market_id"])

    aggregates.recompute_market_ids(touched_markets)
    aggregates.recompute_institution_ids(
        [application["acquirer_id"], application["target_id"]]
    )

    monitoring = (
        "MONITORING" if aggregates.executed_plan(application["id"]) is not None
        else "NOT_APPLICABLE"
    )
    set_fields(application, post_closing_monitoring_status=monitoring)
    del acquirer
    return object_response(serialize(decision))
