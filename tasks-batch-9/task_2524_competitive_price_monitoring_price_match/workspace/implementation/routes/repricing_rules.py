"""Automated repricing rule endpoints (PRD 3.6)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import ALL_ROLES, PRICING_MANAGER, body, endpoint
from response import object_response
from routes.common import FK_MARKET, filtered, list_page, path_lookup, resolve_fks
from services import serialize
from util import (as_enum, as_int, as_ratio, as_str, as_str_list, get_required)

bp = Blueprint("repricing_rules", __name__)

RULE_STATUSES = ("ACTIVE", "PAUSED")


@bp.post("/repricing-rules")
@endpoint([PRICING_MANAGER])
def create_repricing_rule(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_MARKET])

    market = fks["market_id"]
    if market is None:
        get_required(payload, "market_id")
    category_code = as_str(get_required(payload, "category_code"),
                           "category_code", min_len=1)
    target_position_bp = as_int(get_required(payload, "target_position_bp"),
                                "target_position_bp", minimum=5000, maximum=15000)
    max_change_pct = as_ratio(get_required(payload, "max_change_pct"),
                              "max_change_pct", min_exclusive=0, max_inclusive=1)
    frequency_limit_days = as_int(
        get_required(payload, "change_frequency_limit_days"),
        "change_frequency_limit_days", minimum=0)
    priority = as_int(get_required(payload, "priority"), "priority", minimum=0)
    brand_exclusions = []
    if payload.get("brand_exclusions") is not None:
        brand_exclusions = as_str_list(payload["brand_exclusions"],
                                       "brand_exclusions")
    status = "ACTIVE"
    if payload.get("status") is not None:
        status = as_enum(as_str(payload["status"], "status", min_len=1), "status",
                         RULE_STATUSES)

    record = db.new_record()
    record.update({
        "market_id": market["id"],
        "category_code": category_code,
        "target_position_bp": target_position_bp,
        "max_change_pct": max_change_pct,
        "change_frequency_limit_days": frequency_limit_days,
        "priority": priority,
        "brand_exclusions": brand_exclusions,
        "status": status,
    })
    db.rules[record["id"]] = record
    return object_response(serialize.rule(record), 201)


@bp.patch("/repricing-rules/<rule_id>/status")
@endpoint([PRICING_MANAGER])
def patch_rule_status(user_id, role, rule_id):
    rule = path_lookup("rules", rule_id, "ERR_RULE_NOT_FOUND")
    payload = body()
    to_status_raw = as_str(get_required(payload, "to_status"), "to_status",
                          min_len=1)
    to_status = as_enum(to_status_raw, "to_status", RULE_STATUSES)

    if rule["status"] == to_status:
        raise err("ERR_INVALID_STATE",
                  "The rule is already %s." % to_status)
    rule["status"] = to_status
    db.touch(rule)
    return object_response(serialize.rule(rule))


@bp.get("/repricing-rules/<rule_id>")
@endpoint(ALL_ROLES)
def read_repricing_rule(user_id, role, rule_id):
    rule = path_lookup("rules", rule_id, "ERR_RULE_NOT_FOUND")
    return object_response(serialize.rule(rule))


@bp.get("/repricing-rules")
@endpoint(ALL_ROLES)
def list_repricing_rules(user_id, role):
    rows = filtered(db.ordered(db.rules), request.args,
                    [("market_id", "market_id"),
                     ("category_code", "category_code"), ("status", "status")])
    return list_page(rows, serialize.rule)
