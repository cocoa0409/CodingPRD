"""StateRulePack endpoints (PRD 3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_DUPLICATE_RULE_PACK
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize_state_rule_pack
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_bool,
    require_enum,
    require_int,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("state_rule_packs", __name__)

PAY_FREQUENCIES = {"WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"}


@bp.route("/household-payroll/state-rule-packs", methods=["POST"])
@require_roles("PayrollAdmin")
def create_state_rule_pack(_user_id: str, _role: str):
    body = get_json_body()
    state_code = require_string(body, "state_code")
    pack = {
        "state_code": state_code,
        "min_pay_frequency": require_enum(body, "min_pay_frequency", PAY_FREQUENCIES),
        "weekly_ot_threshold_minutes": require_int(body, "weekly_ot_threshold_minutes", 0),
        "daily_ot_threshold_minutes": require_int(body, "daily_ot_threshold_minutes", 0),
        "daily_dt_threshold_minutes": require_int(body, "daily_dt_threshold_minutes", 0),
        "live_in_weekly_ot_eligible": require_bool(body, "live_in_weekly_ot_eligible"),
        "live_in_daily_ot_eligible": require_bool(body, "live_in_daily_ot_eligible"),
        "min_wage_cents": require_int(body, "min_wage_cents", 0),
        "sit_rate": require_number(body, "sit_rate"),
        "suta_rate": require_number(body, "suta_rate"),
        "suta_wage_base_cents": require_int(body, "suta_wage_base_cents", 0),
        "workers_comp_required": require_bool(body, "workers_comp_required"),
        "new_hire_report_days": require_int(body, "new_hire_report_days", 0),
        "pay_stub_required": require_bool(body, "pay_stub_required"),
    }
    for existing in db.state_rule_packs.values():
        if existing["state_code"] == state_code:
            raise_err(ERR_DUPLICATE_RULE_PACK, "StateRulePack with this state_code already exists")
    db.stamp_new_immutable(pack)
    db.state_rule_packs[pack["id"]] = pack
    return success_object(serialize_state_rule_pack(pack), 201)


@bp.route("/household-payroll/state-rule-packs", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient", "Worker")
def list_state_rule_packs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.state_rule_packs.values()))
    items = apply_filters(items, ["state_code"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_state_rule_pack(p) for p in page], limit, offset, total)
