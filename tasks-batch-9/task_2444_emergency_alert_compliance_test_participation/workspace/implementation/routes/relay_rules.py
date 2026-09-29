"""RelayRule endpoints (PRD 3.1)."""

from flask import Blueprint, request

import serializers
from auth import ANY_ROLE, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from store import base_row, db, mark_created, relay_rules_of_plan, touch
from validators import (
    EVENT_CODE_RE,
    FIPS_RE,
    RELAY_CLASSES,
    get_relay_rule,
    get_state_plan,
    json_body,
    opt_int,
    req_array,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("relay_rules", __name__)


@bp.post("/relay-rules")
@guard("ComplianceAdmin")
def create_relay_rule():
    body = json_body(request)
    state_plan_id = req_string(body, "state_plan_id")
    event_code = req_string(body, "event_code", pattern=EVENT_CODE_RE)
    fips_codes = req_array(body, "fips_codes", non_empty=False, member_pattern=FIPS_RE)
    relay_class = req_enum(body, "relay_class", RELAY_CLASSES)
    priority = req_int(body, "priority", minimum=1, maximum=100)
    forward_delay_seconds = opt_int(
        body, "forward_delay_seconds", minimum=0, maximum=600, default=0
    )

    get_state_plan(state_plan_id)

    # rung 11 — no two ACTIVE rules of one plan share event_code + priority
    for rule in relay_rules_of_plan(state_plan_id):
        if (rule["status"] == "ACTIVE" and rule["event_code"] == event_code
                and rule["priority"] == priority):
            raise ApiError("ERR_DUPLICATE_RELAY_PRIORITY")

    rule = base_row()
    rule.update({
        "state_plan_id": state_plan_id,
        "event_code": event_code,
        "fips_codes": list(fips_codes),
        "relay_class": relay_class,
        "priority": priority,
        "forward_delay_seconds": forward_delay_seconds,
        "specificity": 2 if len(fips_codes) > 0 else 1,
        "status": "ACTIVE",
    })
    db.relay_rules[rule["id"]] = rule
    mark_created(rule)
    return object_response(serializers.relay_rule(rule), 201)


@bp.get("/relay-rules/<rule_id>")
@guard(*ANY_ROLE)
def read_relay_rule(rule_id):
    rule = get_relay_rule(rule_id)
    return object_response(serializers.relay_rule(rule))


@bp.get("/relay-rules")
@guard(*ANY_ROLE)
def list_relay_rules():
    rows = list(db.relay_rules.values())
    rows = filter_equals(rows, request, (
        ("state_plan_id", "state_plan_id"),
        ("event_code", "event_code"),
        ("relay_class", "relay_class"),
        ("status", "status"),
    ))
    return collection_response(rows, request, serializers.relay_rule)


@bp.post("/relay-rules/<rule_id>/retire")
@guard("ComplianceAdmin")
def retire_relay_rule(rule_id):
    rule = get_relay_rule(rule_id)
    if rule["status"] != "ACTIVE":
        raise ApiError("ERR_RELAY_RULE_NOT_ACTIVE")
    rule["status"] = "RETIRED"
    touch(rule)
    return object_response(serializers.relay_rule(rule))
