"""StateRule administration (PRD §3.1). Immutable configuration records."""

from flask import Blueprint

from db import logical_now, next_seq, store
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, fail
from middleware import (
    ALL_ROLES,
    ROLE_ADMIN,
    authorize,
    get_body,
    public,
    req_bool,
    req_int,
    req_number,
    req_object,
    req_str,
)
from response import object_response
from util import new_uuid, render_instant

bp = Blueprint("state_rules", __name__)

ORDER_TYPES = ("CHILD_SUPPORT", "FEDERAL_TAX_LEVY", "STUDENT_LOAN", "CREDITOR")


@bp.post("/state-rules")
def create_state_rule():
    authorize(ROLE_ADMIN)
    body = get_body()
    state_code = req_str(body, "state_code")
    caps = req_object(body, "caps")
    for order_type in ORDER_TYPES:
        if order_type not in caps or isinstance(caps[order_type], bool) \
                or not isinstance(caps[order_type], (int, float)):
            fail(ERR_INVALID_REQUEST, 400,
                 "caps must map each order type (%s) to a numeric fraction."
                 % ", ".join(ORDER_TYPES))
        if caps[order_type] < 0:
            fail(ERR_INVALID_REQUEST, 400, "caps fractions must be non-negative.")
    multiplier = req_number(body, "min_wage_multiplier")
    if multiplier < 0:
        fail(ERR_INVALID_REQUEST, 400, "min_wage_multiplier must be >= 0.")
    hourly_floor_cents = req_int(body, "hourly_floor_cents")
    if hourly_floor_cents < 0:
        fail(ERR_INVALID_REQUEST, 400, "hourly_floor_cents must be >= 0.")
    fee_deductible = req_bool(body, "fee_deductible_from_wages")

    if state_code in store.state_rules:
        fail(ERR_INVALID_REQUEST, 400,
             "A StateRule already exists for state_code '%s'." % state_code)

    rule = {
        "id": new_uuid(),
        "created_at": render_instant(logical_now()),
        "state_code": state_code,
        "caps": {t: caps[t] for t in ORDER_TYPES},
        "min_wage_multiplier": multiplier,
        "hourly_floor_cents": hourly_floor_cents,
        "fee_deductible_from_wages": fee_deductible,
        "_seq": next_seq(),
    }
    store.state_rules[state_code] = rule
    return object_response(public(rule), 201)


@bp.get("/state-rules/<stateCode>")
def get_state_rule(stateCode):
    authorize(*ALL_ROLES)
    rule = store.state_rules.get(stateCode)
    if rule is None:
        fail(ERR_NOT_FOUND, 404, "StateRule '%s' does not exist." % stateCode)
    return object_response(public(rule))
