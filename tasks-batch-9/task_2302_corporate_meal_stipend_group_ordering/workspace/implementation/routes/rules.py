"""Employee group reads and budget-rule authorship / activation."""

from flask import Blueprint

from envelope import list_response, object_response
from errors import ApiError
from helpers import (auth, f_datetime, f_enum, f_int, f_int_array, get_body,
                     pagination, q_enum)
from routes.common import paginate, require
from store import base_row, db, fmt_dt, public, touch

bp = Blueprint("rules", __name__)

OVERAGE_POLICIES = ("PERSONAL_CARD", "BLOCK")
TIP_POLICIES = ("EMPLOYER_COVERS_TIP", "EMPLOYEE_PAYS_TIP")
RULE_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")


@bp.get("/employee-groups/<group_id>")
def read_group(group_id):
    auth("PlatformAdmin", "ProgramAdmin", "BenefitsController")
    group = require(db.employee_groups, group_id, "ERR_EMPLOYEE_GROUP_NOT_FOUND")
    return object_response(public(group))


@bp.post("/employee-groups/<group_id>/budget-rules")
def draft_rule(group_id):
    user_id, _role = auth("BenefitsController")
    body = get_body()
    # PRD §2.11 — the parent must exist before any child-level validation runs
    group = require(db.employee_groups, group_id, "ERR_EMPLOYEE_GROUP_NOT_FOUND")

    effective_from = f_datetime(body, "effective_from")
    per_meal_cap = f_int(body, "per_meal_cap_cents", minimum=1)
    daily_limit = f_int(body, "daily_meal_limit", minimum=1, maximum=5)
    monthly_allocation = f_int(body, "monthly_allocation_cents", minimum=0)
    weekdays = f_int_array(body, "eligible_weekdays", minimum=1, maximum=7)
    window_start = f_int(body, "eligible_window_start_minute", minimum=0, maximum=1440)
    window_end = f_int(body, "eligible_window_end_minute", minimum=0, maximum=1440)
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'eligible_window_end_minute' must be greater than "
                       "'eligible_window_start_minute'.")
    overage_policy = f_enum(body, "overage_policy", OVERAGE_POLICIES,
                            required=False, default="PERSONAL_CARD")
    tip_policy = f_enum(body, "tip_coverage_policy", TIP_POLICIES,
                        required=False, default="EMPLOYEE_PAYS_TIP")

    row = base_row()
    row.update({
        "group_id": group["id"],
        "effective_from": fmt_dt(effective_from),
        "per_meal_cap_cents": per_meal_cap,
        "daily_meal_limit": daily_limit,
        "monthly_allocation_cents": monthly_allocation,
        "eligible_weekdays": weekdays,
        "eligible_window_start_minute": window_start,
        "eligible_window_end_minute": window_end,
        "overage_policy": overage_policy,
        "tip_coverage_policy": tip_policy,
        "rule_sequence": None,
        "drafted_by_user_id": user_id,
        "status": "DRAFT",
        "_effective_from": effective_from,
    })
    db.budget_rules[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/employee-groups/<group_id>/budget-rules")
def list_rules(group_id):
    auth("PlatformAdmin", "ProgramAdmin", "BenefitsController")
    limit, offset = pagination()
    status = q_enum("status", RULE_STATUSES)
    group = require(db.employee_groups, group_id, "ERR_EMPLOYEE_GROUP_NOT_FOUND")
    rows = [r for r in db.budget_rules.values() if r["group_id"] == group["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/budget-rules/<rule_id>/activate")
def activate_rule(rule_id):
    user_id, _role = auth("BenefitsController")

    rule = db.budget_rules.get(rule_id)
    # rank 4 — segregation of duties, before request-shape validation
    if rule is not None and rule.get("drafted_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The activating user must differ from the drafting user.")

    body = get_body()
    expected_version = f_int(body, "expected_employee_group_version")

    if rule is None:
        raise ApiError("ERR_BUDGET_RULE_NOT_FOUND")

    if rule["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "A rule in status %s cannot be activated." % rule["status"])

    if rule["_effective_from"] > db.now:
        raise ApiError("ERR_RULE_NOT_EFFECTIVE",
                       "The rule is not yet effective.")

    group = db.employee_groups.get(rule["group_id"])
    if group is None:
        raise ApiError("ERR_EMPLOYEE_GROUP_NOT_FOUND")
    if expected_version != group["version"]:
        raise ApiError("ERR_STALE_EMPLOYEE_GROUP_VERSION",
                       "The employee group has been modified since it was read.")

    # supersede the previously ACTIVE rule of the group
    for other in db.budget_rules.values():
        if other["group_id"] == group["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)

    group["_activation_count"] = group.get("_activation_count", 0) + 1
    rule["rule_sequence"] = group["_activation_count"]
    rule["status"] = "ACTIVE"
    touch(rule)

    group["active_rule_count"] = len([r for r in db.budget_rules.values()
                                      if r["group_id"] == group["id"] and r["status"] == "ACTIVE"])
    touch(group)

    return object_response(public(rule))
