"""Guild agreement rate cards (PRD 2.6, 3.1)."""
from flask import Blueprint

from db import base_row, db
from errors import ApiError
from middleware import (ALL_ROLES, GUILD_ADMINISTRATOR, fetch, require)
from response import created, ok
from routes.common import list_out, match, out
from services import calc
from validation import (body_json, filter_int, v_int, v_map_int, v_map_num, v_num)

bp = Blueprint("agreements", __name__)

LEVELS = calc.LEVELS
THRESHOLD_KEYS = calc.LEVELS_ABOVE_STAFF


@bp.post("/guild-agreements")
def create_agreement():
    require(GUILD_ADMINISTRATOR)
    body = body_json()
    row = base_row()
    row["mba_year"] = v_int(body, "mba_year", 2020, 2035)
    row["min_weekly_cents_by_level"] = v_map_int(body, "min_weekly_cents_by_level", LEVELS, lo=1)
    row["script_fee_cents_by_length"] = v_map_int(
        body, "script_fee_cents_by_length", calc.LENGTH_FORMATS, lo=1)
    row["type_share_pct_by_assignment_type"] = v_map_num(
        body, "type_share_pct_by_assignment_type", calc.ASSIGNMENT_TYPES,
        lo=0, hi=1, lo_exclusive=True)
    row["guarantee_offset_pct_by_level"] = v_map_num(
        body, "guarantee_offset_pct_by_level", LEVELS, lo=0, hi=1)
    thresholds = v_map_int(body, "level_credit_thresholds", THRESHOLD_KEYS, lo=1)
    previous = None
    for key in THRESHOLD_KEYS:
        if previous is not None and not thresholds[key] > previous:
            raise ApiError("ERR_INVALID_REQUEST")
        previous = thresholds[key]
    row["level_credit_thresholds"] = thresholds
    row["diversity_subsidy_pct"] = v_num(
        body, "diversity_subsidy_pct", lo=0, hi=1, lo_exclusive=True,
        required=False, default=0.5)
    row["diversity_subsidy_cap_weekly_cents"] = v_int(
        body, "diversity_subsidy_cap_weekly_cents", lo=1)
    row["mini_room_floor_multiplier"] = v_num(
        body, "mini_room_floor_multiplier", lo=1, required=False, default=1.2)
    row["short_commitment_weeks_threshold"] = v_int(
        body, "short_commitment_weeks_threshold", lo=1, required=False, default=20)
    row["short_commitment_uplift_pct"] = v_num(
        body, "short_commitment_uplift_pct", lo=0, hi=1, required=False, default=0.1)
    row["facility_fee_tiers"] = v_map_int(
        body, "facility_fee_tiers", calc.FACILITY_TIERS, lo=0)
    bounds = v_map_int(body, "facility_tier_subtotal_bounds", calc.TIER_BOUND_KEYS, lo=1)
    if not bounds["TIER_1_MAX"] < bounds["TIER_2_MAX"]:
        raise ApiError("ERR_INVALID_REQUEST")
    row["facility_tier_subtotal_bounds"] = bounds
    row["format_surcharge_pct"] = v_map_num(
        body, "format_surcharge_pct", calc.ROOM_FORMATS, lo=0, hi=1)
    row["max_free_revision_rounds"] = v_int(
        body, "max_free_revision_rounds", lo=0, required=False, default=2)
    row["credit_share_threshold_pct"] = v_int(
        body, "credit_share_threshold_pct", lo=1, hi=100, required=False, default=33)
    row["arbitration_concurrence_pct"] = v_num(
        body, "arbitration_concurrence_pct", lo=0, hi=1, lo_exclusive=True,
        required=False, default=0.667)
    row["arbitration_concurrence_band_pct"] = v_int(
        body, "arbitration_concurrence_band_pct", lo=1, hi=100, required=False, default=10)
    outline = v_int(body, "outline_lead_days", lo=1)
    first = v_int(body, "first_draft_lead_days", lo=1)
    second = v_int(body, "second_draft_lead_days", lo=1)
    polish = v_int(body, "polish_lead_days", lo=1)
    if not (first < outline and second < first and polish < second):
        raise ApiError("ERR_INVALID_REQUEST")
    row["outline_lead_days"] = outline
    row["first_draft_lead_days"] = first
    row["second_draft_lead_days"] = second
    row["polish_lead_days"] = polish
    row["turnaround_buffer_days"] = v_int(
        body, "turnaround_buffer_days", lo=0, required=False, default=2)
    row["clearance_item_weights"] = v_map_int(
        body, "clearance_item_weights", calc.CLEARANCE_ITEM_TYPES, lo=1)
    row["clearance_escalation_score"] = v_int(
        body, "clearance_escalation_score", lo=0, required=False, default=30)
    # mba_year is unique across all rate cards (PRD 2.6)
    for existing in db.agreements.values():
        if existing["mba_year"] == row["mba_year"]:
            raise ApiError("ERR_INVALID_REQUEST")
    db.agreements[row["id"]] = row
    return created(out(row))


@bp.get("/guild-agreements/<agreement_id>")
def get_agreement(agreement_id):
    require(*ALL_ROLES)
    row = fetch(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    return ok(out(row))


@bp.get("/guild-agreements")
def list_agreements():
    require(*ALL_ROLES)
    rows = list(db.agreements.values())
    rows = match(rows, "mba_year", filter_int("mba_year"))
    return list_out(rows, order="created_desc")
