import re
from flask import Blueprint
from db import db, new_common_fields
from errors import err
from middleware import get_caller, require_role
from response import object_response
from validate import body, require_str, require_bool, require_number, require_int

state_rules_bp = Blueprint("state_rules", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


@state_rules_bp.post("/state-compliance-rules")
def create_state_rule():
    caller = get_caller()
    require_role(caller, {"ComplianceOfficer"})
    b = body()

    state_code = require_str(b, "state_code")
    if not STATE_CODE_RE.match(state_code):
        raise err("ERR_VALIDATION", "state_code must be a 2-letter uppercase code.")

    enrollment_allowed = require_bool(b, "enrollment_allowed", required=False, default=True)
    max_monthly_fee_pct_of_rent = require_number(b, "max_monthly_fee_pct_of_rent", min_v=0, max_v=1, exclusive_min=True)
    cooling_off_buffer_days = require_int(b, "cooling_off_buffer_days", required=False, default=30, non_negative=True)
    mandatory_alternative_offering = require_bool(b, "mandatory_alternative_offering", required=False, default=True)

    if state_code in db.state_compliance_rules:
        raise err("ERR_VALIDATION", "state_code must be unique.")

    rule = {
        **new_common_fields(has_version=False),
        "state_code": state_code,
        "enrollment_allowed": enrollment_allowed,
        "max_monthly_fee_pct_of_rent": max_monthly_fee_pct_of_rent,
        "cooling_off_buffer_days": cooling_off_buffer_days,
        "mandatory_alternative_offering": mandatory_alternative_offering,
    }
    db.state_compliance_rules[state_code] = rule
    return object_response(rule, 201)
