"""JurisdictionRule routes (PRD §2.5) — the regulatory backbone config."""

from flask import Blueprint, request

import db as dbmod
import serialize
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, bump, get_rule,
    check_allowed_fields, req_str, req_int, opt_int, opt_bool, req_enum,
    JURISDICTIONS,
)
from services.calc import parse_tier_bounds

bp = Blueprint("jurisdiction", __name__)

_CREATE_FIELDS = {
    "jurisdiction", "oa_response_months", "max_extensions", "extension_months",
    "extension_fee_cents", "annuity_start_year", "term_years",
    "surcharge_window_months", "surcharge_bps_month_1", "surcharge_bps_late",
    "small_entity_multiplier_bps", "fee_tier_bounds",
    "fee_tier_1_cents", "fee_tier_2_cents", "fee_tier_3_cents", "fee_tier_4_cents",
    "paris_window_months", "pct_window_months", "fx_to_usd_cents_bps",
    "requires_recorded_assignment_for_grant",
    "requires_recorded_assignment_for_payment",
    "requires_confirmed_instruction_for_payment",
}

# Fixed at creation (PRD §2.5): jurisdiction, annuity bounds, tier-bound layout,
# priority windows — not patchable.
_PATCH_FIELDS = {
    "oa_response_months", "max_extensions", "extension_months", "extension_fee_cents",
    "surcharge_window_months", "surcharge_bps_month_1", "surcharge_bps_late",
    "small_entity_multiplier_bps",
    "fee_tier_1_cents", "fee_tier_2_cents", "fee_tier_3_cents", "fee_tier_4_cents",
    "fx_to_usd_cents_bps",
    "requires_recorded_assignment_for_grant",
    "requires_recorded_assignment_for_payment",
    "requires_confirmed_instruction_for_payment",
}


def _validate_tier_bounds(value):
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, "fee_tier_bounds must be a non-empty string")
    try:
        tiers = parse_tier_bounds(value)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "fee_tier_bounds must be pipe-separated period-year ranges")
    if len(tiers) != 4:
        raise_err(ERR_INVALID_REQUEST, "fee_tier_bounds must declare four tier ranges")
    return value


@bp.post("/jurisdiction-rules")
def create_rule():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    check_allowed_fields(body, _CREATE_FIELDS)
    jurisdiction = req_enum(body, "jurisdiction", JURISDICTIONS)
    rec = stamp_new({
        "id": new_id(),
        "jurisdiction": jurisdiction,
        "oa_response_months": req_int(body, "oa_response_months"),
        "max_extensions": req_int(body, "max_extensions"),
        "extension_months": req_int(body, "extension_months"),
        "extension_fee_cents": req_int(body, "extension_fee_cents"),
        "annuity_start_year": req_int(body, "annuity_start_year"),
        "term_years": req_int(body, "term_years"),
        "surcharge_window_months": req_int(body, "surcharge_window_months"),
        "surcharge_bps_month_1": req_int(body, "surcharge_bps_month_1"),
        "surcharge_bps_late": req_int(body, "surcharge_bps_late"),
        "small_entity_multiplier_bps": req_int(body, "small_entity_multiplier_bps"),
        "fee_tier_bounds": _validate_tier_bounds(req_str(body, "fee_tier_bounds")),
        "fee_tier_1_cents": req_int(body, "fee_tier_1_cents"),
        "fee_tier_2_cents": req_int(body, "fee_tier_2_cents"),
        "fee_tier_3_cents": req_int(body, "fee_tier_3_cents"),
        "fee_tier_4_cents": req_int(body, "fee_tier_4_cents"),
        "paris_window_months": req_int(body, "paris_window_months"),
        "pct_window_months": req_int(body, "pct_window_months"),
        "fx_to_usd_cents_bps": req_int(body, "fx_to_usd_cents_bps"),
        "requires_recorded_assignment_for_grant": opt_bool(body, "requires_recorded_assignment_for_grant", False),
        "requires_recorded_assignment_for_payment": opt_bool(body, "requires_recorded_assignment_for_payment", False),
        "requires_confirmed_instruction_for_payment": opt_bool(body, "requires_confirmed_instruction_for_payment", False),
    })
    if jurisdiction in dbmod.DB["jurisdiction_index"]:
        raise_err(ERR_INVALID_REQUEST, f"jurisdiction {jurisdiction} already has a JurisdictionRule")
    dbmod.DB["jurisdiction_rules"][rec["id"]] = rec
    dbmod.DB["jurisdiction_index"][jurisdiction] = rec["id"]
    return success_object(serialize.jurisdiction_rule(rec), 201)


@bp.get("/jurisdiction-rules")
def list_rules():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    jurisdiction = request.args.get("jurisdiction")
    items = list(dbmod.DB["jurisdiction_rules"].values())
    if jurisdiction is not None:
        items = [r for r in items if r["jurisdiction"] == jurisdiction]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.jurisdiction_rule(r) for r in page], total, limit, offset)


@bp.get("/jurisdiction-rules/<rule_id>")
def get_rule_route(rule_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.jurisdiction_rule(get_rule(rule_id)))


@bp.patch("/jurisdiction-rules/<rule_id>")
def patch_rule(rule_id):
    require_roles(["PlatformAdmin"])
    rec = get_rule(rule_id)
    body = get_json_body()
    check_allowed_fields(body, _PATCH_FIELDS)
    changed = False
    int_fields = (
        "oa_response_months", "max_extensions", "extension_months", "extension_fee_cents",
        "surcharge_window_months", "surcharge_bps_month_1", "surcharge_bps_late",
        "small_entity_multiplier_bps",
        "fee_tier_1_cents", "fee_tier_2_cents", "fee_tier_3_cents", "fee_tier_4_cents",
        "fx_to_usd_cents_bps",
    )
    for field in int_fields:
        v = opt_int(body, field)
        if v is not None:
            rec[field] = v
            changed = True
    for field in (
        "requires_recorded_assignment_for_grant",
        "requires_recorded_assignment_for_payment",
        "requires_confirmed_instruction_for_payment",
    ):
        v = opt_bool(body, field, None)
        if v is not None:
            rec[field] = v
            changed = True
    if changed:
        bump(rec)
    # Updates never retroactively change already-generated obligations (PRD §2.5).
    return success_object(serialize.jurisdiction_rule(rec))
