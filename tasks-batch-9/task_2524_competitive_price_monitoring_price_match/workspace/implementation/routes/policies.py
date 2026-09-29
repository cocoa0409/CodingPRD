"""Price match policy endpoints (PRD 3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import (ALL_ROLES, COMPLIANCE_OFFICER, PRICING_MANAGER, body,
                        endpoint)
from response import object_response
from routes.common import FK_MARKET, filtered, list_page, path_lookup, resolve_fks
from services import serialize
from util import (as_bool, as_enum, as_enum_list, as_int, as_ratio, as_str,
                  as_str_list, get_required)

bp = Blueprint("policies", __name__)

TIERS = ("PRIMARY", "SECONDARY")
POLICY_STATUSES = ("ACTIVE", "SUSPENDED")
DEFAULT_MAX_MATCH_DISCOUNT_PCT = 0.25
DEFAULT_CLAIM_WINDOW_HOURS = 168


@bp.post("/match-policies")
@endpoint([PRICING_MANAGER, COMPLIANCE_OFFICER])
def create_policy(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_MARKET])

    market = fks["market_id"]
    if market is None:
        get_required(payload, "market_id")
    tiers = as_str_list(get_required(payload, "eligible_competitor_tiers"),
                        "eligible_competitor_tiers", min_len=1)
    budget_cents = as_int(get_required(payload, "daily_override_budget_cents"),
                          "daily_override_budget_cents", minimum=0)
    excluded_category_codes = []
    if payload.get("excluded_category_codes") is not None:
        excluded_category_codes = as_str_list(payload["excluded_category_codes"],
                                             "excluded_category_codes")
    verification_required = True
    if payload.get("verification_required") is not None:
        verification_required = as_bool(payload["verification_required"],
                                        "verification_required")
    max_match_discount_pct = DEFAULT_MAX_MATCH_DISCOUNT_PCT
    if payload.get("max_match_discount_pct") is not None:
        max_match_discount_pct = as_ratio(payload["max_match_discount_pct"],
                                          "max_match_discount_pct",
                                          min_exclusive=0, max_inclusive=1)
    claim_window_hours = DEFAULT_CLAIM_WINDOW_HOURS
    if payload.get("claim_window_hours") is not None:
        claim_window_hours = as_int(payload["claim_window_hours"],
                                    "claim_window_hours", gt=0)
    status_raw = None
    if payload.get("status") is not None:
        status_raw = as_str(payload["status"], "status", min_len=1)

    as_enum_list(tiers, "eligible_competitor_tiers", TIERS)
    status = "ACTIVE"
    if status_raw is not None:
        status = as_enum(status_raw, "status", POLICY_STATUSES)

    if status == "ACTIVE":
        for existing in db.policies.values():
            if (existing["market_id"] == market["id"]
                    and existing["status"] == "ACTIVE"):
                raise err("ERR_DUPLICATE_RESOURCE",
                          "The market already holds an ACTIVE price match policy.")

    record = db.new_record()
    record.update({
        "market_id": market["id"],
        "eligible_competitor_tiers": tiers,
        "excluded_category_codes": excluded_category_codes,
        "verification_required": verification_required,
        "max_match_discount_pct": max_match_discount_pct,
        "daily_override_budget_cents": budget_cents,
        "claim_window_hours": claim_window_hours,
        "status": status,
    })
    db.policies[record["id"]] = record
    return object_response(serialize.policy(record), 201)


@bp.get("/match-policies/<policy_id>")
@endpoint(ALL_ROLES)
def read_policy(user_id, role, policy_id):
    policy = path_lookup("policies", policy_id, "ERR_POLICY_NOT_FOUND")
    return object_response(serialize.policy(policy))


@bp.get("/match-policies")
@endpoint(ALL_ROLES)
def list_policies(user_id, role):
    rows = filtered(db.ordered(db.policies), request.args,
                    [("market_id", "market_id"), ("status", "status")])
    return list_page(rows, serialize.policy)
