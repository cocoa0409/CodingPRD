"""HedgePolicy endpoints (PRD 3.1, 2.9)."""

from flask import Blueprint

import calc
import fetch
import serializers as ser
import validators as v
from db import db, rows_in_order
from errors import fail
from middleware import ALL_ROLES, RISK_POLICY_ADMIN, endpoint, new_row, touch
from response import created, ok

bp = Blueprint("policies", __name__)


@bp.post("/fuel/hedge-policies")
@endpoint(RISK_POLICY_ADMIN)
def create_policy():
    data = v.body()
    policy_code = v.get_string(data, "policy_code", min_len=1, max_len=32)
    fiscal_year = v.get_int(data, "fiscal_year", minimum=2020, maximum=2100)
    max_coverage = v.get_number(data, "max_coverage_pct", exclusive_minimum=0,
                                maximum=100, places=2)
    min_coverage = v.get_number(data, "min_coverage_pct", minimum=0, places=2)
    max_single = v.get_number(data, "max_single_counterparty_pct", exclusive_minimum=0,
                              maximum=100, places=2)
    permitted = v.get_enum_array(data, "permitted_instrument_types", calc.INSTRUMENT_TYPES)
    max_volatility = v.get_number(data, "max_earnings_volatility_usd",
                                  exclusive_minimum=0, places=2)
    max_uplift = v.get_number(data, "max_tankering_uplift_gallons", exclusive_minimum=0)
    min_days = v.get_number(data, "min_days_cover", exclusive_minimum=0, places=2)
    fleets = v.get_enum_array(data, "eligible_fleet_types", calc.FLEET_TYPES)

    if min_coverage >= max_coverage:
        fail("ERR_INVALID_REQUEST",
             "Field 'min_coverage_pct' must be strictly below 'max_coverage_pct'.")

    for row in db.policies.values():
        if row["policy_code"] == policy_code:
            fail("ERR_DUPLICATE_POLICY_CODE",
                 "policy_code %r is already in use." % policy_code)

    policy = new_row()
    policy.update({
        "policy_code": policy_code,
        "fiscal_year": fiscal_year,
        "max_coverage_pct": max_coverage,
        "min_coverage_pct": min_coverage,
        "max_single_counterparty_pct": max_single,
        "permitted_instrument_types": permitted,
        "max_earnings_volatility_usd": max_volatility,
        "max_tankering_uplift_gallons": max_uplift,
        "min_days_cover": min_days,
        "eligible_fleet_types": fleets,
        "status": "ACTIVE",
    })

    for row in rows_in_order(db.policies):
        if row["fiscal_year"] == fiscal_year and row["status"] == "ACTIVE":
            row["status"] = "SUPERSEDED"
            touch(row)

    db.policies[policy["id"]] = policy
    return created(ser.policy(policy))


@bp.get("/fuel/hedge-policies/<policy_id>")
@endpoint(*ALL_ROLES)
def read_policy(policy_id):
    return ok(ser.policy(fetch.policy(policy_id)))
