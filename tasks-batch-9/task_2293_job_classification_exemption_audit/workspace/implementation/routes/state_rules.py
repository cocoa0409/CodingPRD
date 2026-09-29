"""Jurisdiction rule registry (PRD 2.6)."""
from flask import Blueprint

import db
from constants import ALL_ROLES, DUTIES_TEST_VARIANTS, IC_TESTS
from errors import fail
from middleware import body, endpoint, pagination
from response import success, success_list
from services import serialize
from validation import (
    opt_bool,
    opt_int,
    opt_num,
    req_enum,
    req_int,
    req_state_code,
)

bp = Blueprint("state_rules", __name__)


@bp.post("/state-rules")
@endpoint(["ProgramAdmin"])
def create_state_rule():
    payload = body()
    state_code = req_state_code(payload, "state_code")
    min_weekly = req_int(payload, "min_weekly_salary_cents", minimum=0)
    duties_variant = req_enum(payload, "duties_test_variant", DUTIES_TEST_VARIANTS)
    ic_test = req_enum(payload, "ic_test", IC_TESTS)
    hce_annual = opt_int(payload, "hce_annual_cents", default=0, minimum=0)
    computer_ok = opt_bool(payload, "computer_exemption_recognized", default=True)
    outside_ok = opt_bool(payload, "outside_sales_recognized", default=True)
    hce_ok = opt_bool(payload, "hce_shortcut_recognized", default=True)
    multiplier = opt_num(
        payload, "liquidated_damages_multiplier", default=1.0, minimum=0.0, maximum=3.0
    )
    notice_days = opt_int(payload, "reclass_notice_days", default=14, minimum=0)
    lookback_override = opt_int(
        payload, "back_wage_lookback_weeks_override", default=None, minimum=1
    )

    # rank 13: state_code is globally unique
    for existing in db.state_rules.values():
        if existing["state_code"] == state_code:
            fail("ERR_DUPLICATE_CODE")

    row = db.make_row(
        versioned=False,
        state_code=state_code,
        min_weekly_salary_cents=min_weekly,
        hce_annual_cents=hce_annual,
        duties_test_variant=duties_variant,
        computer_exemption_recognized=computer_ok,
        outside_sales_recognized=outside_ok,
        hce_shortcut_recognized=hce_ok,
        ic_test=ic_test,
        liquidated_damages_multiplier=multiplier,
        reclass_notice_days=notice_days,
        back_wage_lookback_weeks_override=lookback_override,
    )
    db.state_rules[row["id"]] = row
    return success(serialize.state_rule(row), 201)


@bp.get("/state-rules")
@endpoint(ALL_ROLES)
def list_state_rules():
    limit, offset = pagination()
    rows = db.ordered(list(db.state_rules.values()))
    items, total = serialize.paginate(rows, limit, offset, serialize.state_rule)
    return success_list(items, limit, offset, total)
