"""Property endpoints (PRD 3.1): a PropertyManager registers a property with
its statutory caps and policy constants."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V

bp = Blueprint("properties", __name__)

FIELDS = {
    "name", "state_code", "posting_priority_policy", "late_fee_cap_cents",
    "nsf_fee_cap_cents", "monthly_waiver_cap_cents", "min_partial_payment_percent",
    "collections_threshold_cents", "notice_cure_period_days",
    "plan_cooling_off_days", "plan_setup_fee_cents", "plan_setup_fee_threshold_cents",
}

INT_FIELDS = [
    "late_fee_cap_cents", "nsf_fee_cap_cents", "monthly_waiver_cap_cents",
    "min_partial_payment_percent", "collections_threshold_cents",
    "notice_cure_period_days", "plan_cooling_off_days", "plan_setup_fee_cents",
    "plan_setup_fee_threshold_cents",
]


@bp.post("/properties")
def create_property():
    _uid, role = middleware.current_user()
    middleware.require_role(role, middleware.PM)
    data = V.json_body()
    V.check_unknown(data, FIELDS)
    name = V.req_str(data, "name")
    state_code = V.req_str(data, "state_code")
    policy = V.req_enum(data, "posting_priority_policy", {"FEES_FIRST", "RENT_FIRST"})
    values = {f: V.req_int(data, f) for f in INT_FIELDS}
    if len(state_code) != 2:
        errors.fail(errors.ERR_INVALID_REQUEST, "state_code must be a two-letter code.")
    if not 1 <= values["min_partial_payment_percent"] <= 100:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "min_partial_payment_percent must be an integer from 1 to 100.",
        )
    prop = db.init_common({
        "name": name,
        "state_code": state_code,
        "posting_priority_policy": policy,
        **values,
    })
    db.properties[prop["id"]] = prop
    return response.success_object(serializers.property_view(prop), 201)
