"""Reduction plans: governance axis, batches and execution."""
from datetime import timedelta

from flask import Blueprint, g

from calc import RESTRICTION_DAYS
from core import (ApiError, apply_changes, base_record, db, iso_ms, ok, touch)
from domain import (latest_analysis, plan_selections, recompute_plan,
                    recompute_plans_touching_site, recompute_site)
from selection_ops import (apply_exempt, apply_select, create_selection,
                           guard_duplicate, guard_scores, guard_warn_window)
from serialize import plan_out
from validation import (READER_ROLES, bad, body, endpoint, must_exist, opt_str,
                        parse_criterion_scores, parse_selection_criteria,
                        req_date, req_enum, req_int, req_str, req_str_list)

bp = Blueprint("plans", __name__)


# ---------------------------------------------------------------------------
# Plan lifecycle
# ---------------------------------------------------------------------------
@bp.route("/reduction-plans", methods=["POST"])
@endpoint(["RestructuringLead"])
def create_plan():
    payload = body()
    name = req_str(payload, "name")
    decisional_unit_name = req_str(payload, "decisional_unit_name")
    criteria = parse_selection_criteria(payload)
    budget = req_int(payload, "severance_budget_cents", 0)

    codes = [c["criterion_code"] for c in criteria]
    if len(set(codes)) != len(codes) or sum(c["weight_pct"] for c in criteria) != 100:
        raise ApiError("ERR_CRITERIA_WEIGHT_INVALID", 422)

    record = base_record()
    record.update({
        "name": name,
        "decisional_unit_name": decisional_unit_name,
        "selection_criteria": criteria,
        "criteria_status": "DRAFT",
        "approval_status": "DRAFT",
        "warn_status": "NOT_ASSESSED",
        "severance_budget_cents": budget,
        "severance_reserve_cents": 0,
        "benefit_liability_cents": 0,
        "selected_count": 0,
        "pool_count": 0,
        "earliest_separation_date": None,
        "owbpa_required": False,
        "owbpa_consideration_days": 21,
        "required_notice_days": 0,
        "notice_deadline_utc": None,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "legal_return_count": 0,
    })
    db.plans[record["id"]] = record
    return ok(plan_out(record), 201)


@bp.route("/reduction-plans/<plan_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_plan(plan_id):
    return ok(plan_out(must_exist("plans", plan_id)))


@bp.route("/reduction-plans/<plan_id>/lock-criteria", methods=["POST"])
@endpoint(["RestructuringLead"])
def lock_criteria(plan_id):
    plan = must_exist("plans", plan_id)
    if plan["criteria_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)
    plan["criteria_status"] = "LOCKED"
    touch(plan)
    return ok(plan_out(plan))


@bp.route("/reduction-plans/<plan_id>/submit-legal-review", methods=["POST"])
@endpoint(["RestructuringLead"])
def submit_legal_review(plan_id):
    plan = must_exist("plans", plan_id)
    if plan["approval_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)
    if plan["criteria_status"] != "LOCKED":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)
    if plan["selected_count"] < 1:
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)
    plan["approval_status"] = "IN_LEGAL_REVIEW"
    plan["submitted_by_user_id"] = g.user_id
    touch(plan)
    return ok(plan_out(plan))


@bp.route("/reduction-plans/<plan_id>/legal-decision", methods=["POST"])
@endpoint(["EmploymentCounsel"])
def legal_decision(plan_id):
    payload = body()
    decision = req_enum(payload, "decision", ("APPROVE", "RETURN"))
    opt_str(payload, "comment")
    plan = must_exist("plans", plan_id)

    if plan["submitted_by_user_id"] is not None and g.user_id == plan["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
    if plan["approval_status"] != "IN_LEGAL_REVIEW":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    if decision == "APPROVE":
        analysis = latest_analysis(plan["id"])
        if analysis is None or analysis["status"] != "CLEARED":
            raise ApiError("ERR_IMPACT_ANALYSIS_NOT_CLEARED", 422)
        plan["approval_status"] = "APPROVED"
        plan["approved_by_user_id"] = g.user_id
    else:
        plan["approval_status"] = "DRAFT"
        plan["legal_return_count"] += 1
        plan["submitted_by_user_id"] = None
    touch(plan)
    return ok(plan_out(plan))


@bp.route("/reduction-plans/<plan_id>/execute", methods=["POST"])
@endpoint(["RestructuringLead"])
def execute_plan(plan_id):
    plan = must_exist("plans", plan_id)
    if plan["approval_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    selections = [s for s in plan_selections(plan["id"]) if s["status"] == "SELECTED"]
    for selection in selections:
        if selection["notice_status"] != "DELIVERED":
            raise ApiError("ERR_NOTICE_NOT_DELIVERED", 422)

    site_ids = []
    for selection in selections:
        employee = db.employees.get(selection["employee_id"])
        if employee is not None and employee["site_id"] not in site_ids:
            site_ids.append(employee["site_id"])
    for site_id in site_ids:
        site = db.sites.get(site_id)
        if site is None or site["warn_trigger_status"] == "NONE":
            continue
        issued = any(n["plan_id"] == plan["id"] and n["site_id"] == site_id
                     and n["status"] == "ISSUED" for n in db.notices.values())
        if not issued:
            raise ApiError("ERR_WARN_NOTICE_REQUIRED", 422)

    # ---- cascade hop 1: selections SELECTED -> SEPARATED
    for selection in selections:
        selection["status"] = "SEPARATED"
        touch(selection)
        employee = db.employees.get(selection["employee_id"])
        if employee is None:
            continue
        # hop 2: employee PENDING_SEPARATION -> SEPARATED
        if employee["employment_status"] == "PENDING_SEPARATION":
            employee["employment_status"] = "SEPARATED"
            touch(employee)
        # hop 3: freeze the vacated seat
        restriction = base_record()
        restriction.update({
            "employee_id": employee["id"],
            "site_id": employee["site_id"],
            "job_title": employee["job_title"],
            "restriction_status": "RESTRICTED",
            "restricted_until_utc": iso_ms(db.clock + timedelta(days=RESTRICTION_DAYS)),
            "waiver_reason": None,
            "waived_by_user_id": None,
        })
        db.restrictions[restriction["id"]] = restriction

    for site_id in site_ids:
        site = db.sites.get(site_id)
        if site is not None:
            recompute_site(site)
    for site_id in site_ids:
        recompute_plans_touching_site(site_id)

    # ---- settle the release paperwork
    from core import parse_instant
    for offer in db.offers.values():
        if offer["plan_id"] != plan["id"] or offer["status"] != "SIGNED":
            continue
        deadline = parse_instant(offer["revocation_deadline_utc"])
        if deadline is not None and db.clock > deadline:
            offer["status"] = "EFFECTIVE"
            touch(offer)

    recompute_plan(plan, sync_warn=False)
    apply_changes(plan, {
        "approval_status": "EXECUTED",
        "warn_status": "NOTICE_PERIOD_SATISFIED",
    })
    return ok(plan_out(plan))


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------
@bp.route("/reduction-plans/<plan_id>/selection-batch", methods=["POST"])
@endpoint(["RestructuringLead"])
def selection_batch(plan_id):
    payload = body()
    employee_ids = req_str_list(payload, "employee_ids")
    proposed_date = req_date(payload, "proposed_separation_date")
    scores = parse_criterion_scores(payload)

    plan = must_exist("plans", plan_id)

    employees = []
    for employee_id in employee_ids:
        employee = db.employees.get(employee_id)
        if employee is None:
            raise ApiError("ERR_EMPLOYEE_NOT_FOUND", 404)
        employees.append(employee)

    if plan["criteria_status"] != "LOCKED":
        raise ApiError("ERR_CRITERIA_NOT_LOCKED", 422)

    for employee in employees:
        guard_warn_window(employee, proposed_date)

    seen = set()
    for employee in employees:
        if employee["id"] in seen:
            raise ApiError("ERR_DUPLICATE_SELECTION", 409)
        seen.add(employee["id"])
        guard_duplicate(plan["id"], employee["id"])

    guard_scores(plan, scores)

    created = [create_selection(plan, employee, proposed_date, scores)
               for employee in employees]
    recompute_plan(plan)
    return ok({
        "created_count": len(created),
        "selection_ids": [record["id"] for record in created],
    }, 201)


@bp.route("/reduction-plans/<plan_id>/decide-batch", methods=["POST"])
@endpoint(["RestructuringLead"])
def decide_batch(plan_id):
    payload = body()
    selection_ids = req_str_list(payload, "selection_ids")
    decision = req_enum(payload, "decision", ("SELECT", "EXEMPT"))
    exemption_reason = opt_str(payload, "exemption_reason", None, allow_empty=False)
    if decision == "EXEMPT" and (exemption_reason is None or exemption_reason.strip() == ""):
        raise bad("Field 'exemption_reason' is required for an EXEMPT decision.")

    plan = must_exist("plans", plan_id)

    selections = []
    for selection_id in selection_ids:
        selection = db.selections.get(selection_id)
        if selection is None or selection["plan_id"] != plan["id"]:
            raise ApiError("ERR_SELECTION_NOT_FOUND", 404)
        selections.append(selection)

    for selection in selections:
        if selection["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if plan["approval_status"] == "APPROVED":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)
    if plan["approval_status"] == "EXECUTED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if decision == "SELECT" and plan["criteria_status"] != "LOCKED":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    selected_count = 0
    exempted_count = 0
    for selection in selections:
        if decision == "SELECT":
            apply_select(selection)
            selected_count += 1
        else:
            apply_exempt(selection, exemption_reason)
            exempted_count += 1

    return ok({
        "decided_count": len(selections),
        "selected_count": selected_count,
        "exempted_count": exempted_count,
    })
