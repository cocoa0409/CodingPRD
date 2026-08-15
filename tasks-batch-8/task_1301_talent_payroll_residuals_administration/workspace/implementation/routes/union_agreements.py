"""UnionAgreement endpoints."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_AGREEMENT_INVALID_STATE, ERR_AGREEMENT_WINDOW_OVERLAP
from helpers import (
    new_id, now_timestamp, parse_date, require_enum, require_field,
    require_int, require_number, require_string, err_validation,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("union_agreements", __name__)

UNION_CODES = {"SAG_AFTRA", "WGA", "DGA", "AFM", "IATSE"}
TIER_CATEGORIES = {"PRINCIPAL", "BACKGROUND", "STUNT"}
RESIDUAL_MARKETS = {
    "NETWORK_REBROADCAST", "SYNDICATION", "STREAMING", "FOREIGN", "HOME_VIDEO"
}


def _validate_rate_tiers(value):
    if not isinstance(value, list) or len(value) == 0:
        raise err_validation("Field 'rate_tiers' must be a non-empty array")
    seen = set()
    for element in value:
        if not isinstance(element, dict):
            raise err_validation("Each rate tier must be an object")
        tier_code = element.get("tier_code")
        if not isinstance(tier_code, str) or tier_code == "":
            raise err_validation("Each rate tier requires a non-empty 'tier_code'")
        if tier_code in seen:
            raise err_validation(f"Duplicate tier_code '{tier_code}' in rate_tiers")
        seen.add(tier_code)
        category = element.get("category")
        if category not in TIER_CATEGORIES:
            raise err_validation(
                f"Rate tier category must be one of {sorted(TIER_CATEGORIES)}"
            )
        day_rate = element.get("day_rate_cents")
        if isinstance(day_rate, bool) or not isinstance(day_rate, int) or day_rate <= 0:
            raise err_validation("Rate tier 'day_rate_cents' must be an integer > 0")
        threshold = element.get("ot_daily_threshold_minutes")
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
            raise err_validation(
                "Rate tier 'ot_daily_threshold_minutes' must be an integer > 0"
            )
        multiplier = element.get("ot_multiplier")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or multiplier < 1.0:
            raise err_validation("Rate tier 'ot_multiplier' must be a number >= 1.0")
    return value


def _validate_residual_base_pct(value):
    if not isinstance(value, dict) or len(value) == 0:
        raise err_validation(
            "Field 'residual_base_pct_by_market' must be an object with at least one key"
        )
    for key, pct in value.items():
        if key not in RESIDUAL_MARKETS:
            raise err_validation(
                f"Residual market key must be one of {sorted(RESIDUAL_MARKETS)}"
            )
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            raise err_validation("Residual base percentages must be numbers")
    return value


@bp.post("/payroll/union-agreements")
def create_union_agreement():
    require_roles({"PayrollAdmin"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    union_code = require_enum(body, "union_code", UNION_CODES)
    name = require_string(body, "name")
    effective_from_raw = require_string(body, "effective_from")
    effective_to_raw = require_string(body, "effective_to")
    effective_from = parse_date(effective_from_raw, "effective_from")
    effective_to = parse_date(effective_to_raw, "effective_to")
    rate_tiers = _validate_rate_tiers(require_field(body, "rate_tiers"))
    meal_penalty_cents = require_int(body, "meal_penalty_cents", minimum=0)
    rest_penalty_cents = require_int(body, "rest_penalty_cents", minimum=0)
    turnaround_min_hours = require_number(body, "turnaround_min_hours", minimum=0)
    phw_pension_pct = require_number(body, "phw_pension_pct", minimum=0)
    phw_health_pct = require_number(body, "phw_health_pct", minimum=0)
    phw_welfare_pct = require_number(body, "phw_welfare_pct", minimum=0)
    residual_base_pct_by_market = _validate_residual_base_pct(
        require_field(body, "residual_base_pct_by_market")
    )

    # Temporal: effective_to strictly after effective_from (ERR_INVALID_TEMPORAL, 422)
    if effective_to <= effective_from:
        from helpers import temporal_error
        raise temporal_error("effective_to must be strictly after effective_from")

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "union_code": union_code,
        "name": name,
        "effective_from": effective_from_raw,
        "effective_to": effective_to_raw,
        "rate_tiers": rate_tiers,
        "meal_penalty_cents": meal_penalty_cents,
        "rest_penalty_cents": rest_penalty_cents,
        "turnaround_min_hours": turnaround_min_hours,
        "phw_pension_pct": phw_pension_pct,
        "phw_health_pct": phw_health_pct,
        "phw_welfare_pct": phw_welfare_pct,
        "residual_base_pct_by_market": residual_base_pct_by_market,
        "status": "DRAFT",
    }
    db.union_agreements[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/union-agreements")
def list_union_agreements():
    require_roles(ALL_ROLES)
    items = list(db.union_agreements.values())
    union_code = request.args.get("union_code")
    if union_code is not None:
        items = [a for a in items if a["union_code"] == union_code]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response([serialize(a) for a in items], request.args)


@bp.post("/payroll/union-agreements/<agreement_id>/ratify")
def ratify_union_agreement(agreement_id):
    require_roles({"PayrollAdmin"})
    agreement = get_or_404(db.union_agreements, agreement_id, "UnionAgreement")

    # State gate: ratify requires DRAFT
    if agreement["status"] != "DRAFT":
        raise ApiError(
            ERR_AGREEMENT_INVALID_STATE,
            "Ratify target is not DRAFT",
            409,
        )

    # Half-open window overlap vs other RATIFIED agreements of the same union_code.
    this_from = parse_date(agreement["effective_from"], "effective_from")
    this_to = parse_date(agreement["effective_to"], "effective_to")
    for other in db.union_agreements.values():
        if other["id"] == agreement_id:
            continue
        if other["status"] != "RATIFIED":
            continue
        if other["union_code"] != agreement["union_code"]:
            continue
        other_from = parse_date(other["effective_from"], "effective_from")
        other_to = parse_date(other["effective_to"], "effective_to")
        # Half-open overlap: other.from < this.to AND this.from < other.to;
        # adjacency (equality) is allowed.
        if other_from < this_to and this_from < other_to:
            raise ApiError(
                ERR_AGREEMENT_WINDOW_OVERLAP,
                "Ratify would create overlapping RATIFIED windows for the same union_code",
                409,
            )

    agreement["status"] = "RATIFIED"
    bump_version(agreement)
    return success_object(serialize(agreement), 200)
