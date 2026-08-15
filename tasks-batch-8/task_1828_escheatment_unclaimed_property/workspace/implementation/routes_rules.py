"""Dormancy rule endpoints (PRD 3.2)."""

from flask import Blueprint

import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, check_rule_window_overlap, PROPERTY_TYPES,
)

bp = Blueprint("dormancy_rules", __name__)


def rule_view(rule):
    return {
        "id": rule["id"],
        "state_code": rule["state_code"],
        "property_type": rule["property_type"],
        "dormancy_years": rule["dormancy_years"],
        "effective_from": rule["effective_from"].isoformat(),
        "effective_to": rule["effective_to"].isoformat() if rule["effective_to"] else None,
        "dd_threshold_cents": rule["dd_threshold_cents"],
        "dd_window_min_days": rule["dd_window_min_days"],
        "dd_window_max_days": rule["dd_window_max_days"],
        "annual_interest_rate_bp": rule["annual_interest_rate_bp"],
        "daily_penalty_cents": rule["daily_penalty_cents"],
        "gross_daily_penalty_cents": rule["gross_daily_penalty_cents"],
        "gross_negligence_day_threshold": rule["gross_negligence_day_threshold"],
        "penalty_cap_pct": rule["penalty_cap_pct"],
        "report_cutoff_month_day": rule["report_cutoff_month_day"],
        "report_due_month_day": rule["report_due_month_day"],
        "created_at": rule["created_at"],
        "updated_at": rule["updated_at"],
        "version": rule["version"],
    }


def _parse_rule_fields(data, existing=None):
    """Parse create/update fields. `existing` supplies values for PUT merges."""
    def get(name, default=None):
        if existing is not None and name not in data:
            return existing[name]
        return data.get(name, default)

    out = {}
    if existing is None or "state_code" in data:
        out["state_code"] = mw.req_string(data, "state_code") if existing is None else existing["state_code"]
    if existing is None or "property_type" in data:
        if existing is None:
            out["property_type"] = mw.req_enum(data, "property_type", PROPERTY_TYPES)
        else:
            out["property_type"] = existing["property_type"]
    out["dormancy_years"] = mw.opt_int(data, "dormancy_years", get("dormancy_years"), min_value=1, max_value=15)
    if "effective_from" in data or existing is None:
        out["effective_from"] = mw.req_date(data, "effective_from")
    else:
        out["effective_from"] = existing["effective_from"]
    out["effective_to"] = mw.opt_date(data, "effective_to", None if existing is None else existing["effective_to"])
    out["dd_threshold_cents"] = mw.opt_int(data, "dd_threshold_cents", get("dd_threshold_cents", 5000), min_value=0)
    out["dd_window_min_days"] = mw.opt_int(data, "dd_window_min_days", get("dd_window_min_days", 60), min_value=0)
    out["dd_window_max_days"] = mw.opt_int(data, "dd_window_max_days", get("dd_window_max_days", 180), min_value=0)
    out["annual_interest_rate_bp"] = mw.opt_int(data, "annual_interest_rate_bp", get("annual_interest_rate_bp", 1200), min_value=0)
    out["daily_penalty_cents"] = mw.opt_int(data, "daily_penalty_cents", get("daily_penalty_cents", 10000), min_value=0)
    out["gross_daily_penalty_cents"] = mw.opt_int(data, "gross_daily_penalty_cents", get("gross_daily_penalty_cents", 25000), min_value=0)
    out["gross_negligence_day_threshold"] = mw.opt_int(data, "gross_negligence_day_threshold", get("gross_negligence_day_threshold", 30), min_value=0)
    out["penalty_cap_pct"] = mw.opt_int(data, "penalty_cap_pct", get("penalty_cap_pct", 25), min_value=0)
    out["report_cutoff_month_day"] = mw.opt_month_day(data, "report_cutoff_month_day", get("report_cutoff_month_day", "06-30"))
    out["report_due_month_day"] = mw.opt_month_day(data, "report_due_month_day", get("report_due_month_day", "11-01"))
    return out


@bp.post("/escheatment/dormancy-rules")
def create_rule():
    ctx = mw.get_user()
    mw.require_role(ctx, ("HolderAdmin",))
    data = mw.body_json()
    fields = _parse_rule_fields(data)
    check_rule_window_overlap(
        fields["state_code"], fields["property_type"],
        fields["effective_from"], fields["effective_to"],
    )
    rule = new_entity(fields)
    db.dormancy_rules[rule["id"]] = rule
    return resp.success(rule_view(rule), "object", 201)


@bp.get("/escheatment/dormancy-rules")
def list_rules():
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    limit, offset = mw.pagination_params()
    items = list(db.dormancy_rules.values())
    state_code = mw.request.args.get("state_code")
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    property_type = mw.request.args.get("property_type")
    if property_type is not None:
        items = [r for r in items if r["property_type"] == property_type]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([rule_view(r) for r in page], "array", 200, pagination=meta)


@bp.get("/escheatment/dormancy-rules/<ruleId>")
def get_rule(ruleId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    rule = db.dormancy_rules.get(ruleId)
    if rule is None:
        raise_error(errors.ERR_DORMANCY_RULE_NOT_FOUND, "Dormancy rule does not exist")
    return resp.success(rule_view(rule), "object", 200)


@bp.put("/escheatment/dormancy-rules/<ruleId>")
def update_rule(ruleId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("HolderAdmin",))
    data = mw.body_json()
    rule = db.dormancy_rules.get(ruleId)
    if rule is None:
        raise_error(errors.ERR_DORMANCY_RULE_NOT_FOUND, "Dormancy rule does not exist")
    fields = _parse_rule_fields(data, existing=rule)
    check_rule_window_overlap(
        rule["state_code"], rule["property_type"],
        fields["effective_from"], fields["effective_to"],
        exclude_id=rule["id"],
    )
    for key, value in fields.items():
        rule[key] = value
    touch(rule)
    return resp.success(rule_view(rule), "object", 200)
