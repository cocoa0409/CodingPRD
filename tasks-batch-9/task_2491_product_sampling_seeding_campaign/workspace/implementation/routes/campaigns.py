"""Campaign definition, lifecycle and the cost-summary read."""

from decimal import Decimal

from flask import Blueprint

import clock
import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import acting_user_id, endpoint
from response import collection, single
from services import calculations as calc
from services.gates import must_exist, require_posture_not_frozen
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("campaigns", __name__)

OBJECTIVE_TYPES = ("TRIAL_GENERATION", "REVIEW_ACQUISITION", "AWARENESS")
CAMPAIGN_STATUSES = ("DRAFT", "SCREENING_OPEN", "SAMPLING_ACTIVE", "SUSPENDED",
                     "REVIEW_WINDOW", "CLOSED")

CREATE_FIELDS = [
    field("name", "string", required=True, max_length=160),
    field("objective_type", "enum", required=True, values=OBJECTIVE_TYPES),
    field("target_segment_codes", "string_array", required=True,
          min_items=1, max_items=8, unique_items=True),
    field("sampling_window_start", "datetime", required=True),
    field("sampling_window_end", "datetime", required=True),
    field("budget_total_cents", "integer", required=True, minimum=0),
    field("syndication_retailer_ids", "string_array", min_items=0, max_items=8),
    field("review_due_days", "integer", default=21, minimum=1, maximum=90),
    field("min_review_word_count", "integer", default=50, minimum=10, maximum=500),
    field("holdout_pct", "number", default=Decimal("0.2"),
          minimum=0, maximum="0.5", max_decimals=4),
]

LIST_FILTERS = [
    field("status", "enum", values=CAMPAIGN_STATUSES),
    field("objective_type", "enum", values=OBJECTIVE_TYPES),
]


@bp.post("/campaigns")
@endpoint(["CampaignManager"])
def create_campaign():
    body, _ = parse_body(CREATE_FIELDS)

    # rung 5 — the sampling window must be strictly increasing
    start = clock.sec(clock.parse(body["sampling_window_start"]))
    end = clock.sec(clock.parse(body["sampling_window_end"]))
    if not end > start:
        raise ApiError("ERR_CAMPAIGN_WINDOW_INVALID",
                       "sampling_window_end must be strictly later than sampling_window_start")

    # rung 8 — retailer clearance list resolved left to right
    retailer_ids = body["syndication_retailer_ids"] or []
    for retailer_id in retailer_ids:
        must_exist("retailers", retailer_id, "Retailer")

    row = new_row()
    row.update({
        "name": body["name"],
        "objective_type": body["objective_type"],
        "target_segment_codes": list(body["target_segment_codes"]),
        "syndication_retailer_ids": list(retailer_ids),
        "sampling_window_start": body["sampling_window_start"],
        "sampling_window_end": body["sampling_window_end"],
        "review_due_days": body["review_due_days"],
        "min_review_word_count": body["min_review_word_count"],
        "holdout_pct": body["holdout_pct"],
        "budget_total_cents": body["budget_total_cents"],
        "status": "DRAFT",
        "compliance_posture": "OPEN",
        "kit_assembly_unit_cost_cents": 0,
        "budget_committed_cents": 0,
        "budget_available_cents": body["budget_total_cents"],
        "enrollment_count": 0,
        "holdout_enrollment_count": 0,
        "allocated_sample_count": 0,
        "delivered_sample_count": 0,
        "approved_review_count": 0,
        "syndicated_review_count": 0,
        "disclosure_rejected_review_count": 0,
        "substantiated_diversion_count": 0,
        "write_off_cost_cents": 0,
        "cost_per_sample_provisional_cents": 0,
        "cost_per_sample_final_cents": 0,
        "launched_by_user_id": None,
        "closed_at": None,
    })
    db.campaigns[row["id"]] = row
    return single(serializers.campaign(row), 201)


@bp.get("/campaigns/<campaign_id>")
@endpoint(["CampaignManager", "ComplianceModerator", "FulfillmentOps", "PlatformAdmin"])
def get_campaign(campaign_id):
    parse_body([])
    row = must_exist("campaigns", campaign_id, "Campaign")
    return single(serializers.campaign(row))


@bp.get("/campaigns")
@endpoint(["CampaignManager", "ComplianceModerator", "FulfillmentOps", "PlatformAdmin"])
def list_campaigns():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.campaigns.values())
    if query["status"] is not None:
        rows = [r for r in rows if r["status"] == query["status"]]
    if query["objective_type"] is not None:
        rows = [r for r in rows if r["objective_type"] == query["objective_type"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.campaign(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.get("/campaigns/<campaign_id>/cost-summary")
@endpoint(["CampaignManager", "PlatformAdmin"])
def campaign_cost_summary(campaign_id):
    parse_body([])
    row = must_exist("campaigns", campaign_id, "Campaign")
    return single(serializers.cost_summary(row))


def _require_status(campaign, expected):
    if campaign["status"] != expected:
        raise ApiError("ERR_INVALID_CAMPAIGN_TRANSITION",
                       "Campaign status is '%s', not '%s'" % (campaign["status"], expected))


@bp.post("/campaigns/<campaign_id>/open-screening")
@endpoint(["CampaignManager"])
def open_screening(campaign_id):
    parse_body([])
    campaign = must_exist("campaigns", campaign_id, "Campaign")
    _require_status(campaign, "DRAFT")
    # rung 27 — a campaign with an empty kit cannot assemble anything
    if not calc.active_kit_lines(campaign["id"]):
        raise ApiError("ERR_CAMPAIGN_KIT_EMPTY",
                       "The campaign has no ACTIVE kit line")
    campaign["status"] = "SCREENING_OPEN"
    calc.refresh_kit_assembly_unit_cost(campaign)
    campaign["budget_available_cents"] = (campaign["budget_total_cents"]
                                         - campaign["budget_committed_cents"])
    touch(campaign)
    return single(serializers.campaign(campaign))


@bp.post("/campaigns/<campaign_id>/activate-sampling")
@endpoint(["CampaignManager"])
def activate_sampling(campaign_id):
    parse_body([])
    campaign = must_exist("campaigns", campaign_id, "Campaign")
    _require_status(campaign, "SCREENING_OPEN")
    passed = [e for e in store.campaign_enrollments(campaign["id"])
              if e["screening_status"] == "SCREEN_PASSED"]
    if not passed:
        raise ApiError("ERR_INVALID_CAMPAIGN_TRANSITION",
                       "The campaign has no SCREEN_PASSED enrollment")
    campaign["status"] = "SAMPLING_ACTIVE"
    campaign["launched_by_user_id"] = acting_user_id()
    touch(campaign)
    return single(serializers.campaign(campaign))


@bp.post("/campaigns/<campaign_id>/suspend")
@endpoint(["ComplianceModerator"])
def suspend_campaign(campaign_id):
    parse_body([])
    campaign = must_exist("campaigns", campaign_id, "Campaign")
    _require_status(campaign, "SAMPLING_ACTIVE")
    campaign["status"] = "SUSPENDED"
    touch(campaign)
    return single(serializers.campaign(campaign))


@bp.post("/campaigns/<campaign_id>/resume")
@endpoint(["ComplianceModerator"])
def resume_campaign(campaign_id):
    parse_body([])
    campaign = must_exist("campaigns", campaign_id, "Campaign")
    _require_status(campaign, "SUSPENDED")
    require_posture_not_frozen(campaign)
    campaign["status"] = "SAMPLING_ACTIVE"
    touch(campaign)
    return single(serializers.campaign(campaign))


@bp.post("/campaigns/<campaign_id>/open-review-window")
@endpoint(["CampaignManager"])
def open_review_window(campaign_id):
    parse_body([])
    campaign = must_exist("campaigns", campaign_id, "Campaign")
    _require_status(campaign, "SAMPLING_ACTIVE")
    outstanding = [s for s in store.campaign_shipments(campaign["id"])
                   if s["status"] == "ALLOCATED"]
    if outstanding:
        raise ApiError("ERR_INVALID_CAMPAIGN_TRANSITION",
                       "The campaign still has ALLOCATED shipments")
    campaign["status"] = "REVIEW_WINDOW"
    calc.refresh_final_cost(campaign)
    touch(campaign)
    return single(serializers.campaign(campaign))


@bp.post("/campaigns/<campaign_id>/close")
@endpoint(["CampaignManager"])
def close_campaign(campaign_id):
    parse_body([])
    campaign = must_exist("campaigns", campaign_id, "Campaign")
    _require_status(campaign, "REVIEW_WINDOW")
    undecided = [r for r in store.campaign_reviews(campaign["id"])
                 if r["status"] == "SUBMITTED"]
    if undecided:
        raise ApiError("ERR_INVALID_CAMPAIGN_TRANSITION",
                       "The campaign still has SUBMITTED reviews awaiting moderation")
    campaign["status"] = "CLOSED"
    for enrollment in store.campaign_enrollments(campaign["id"]):
        if enrollment["obligation_status"] == "REVIEW_DUE":
            enrollment["obligation_status"] = "FORFEITED"
            touch(enrollment)
    calc.refresh_final_cost(campaign)
    campaign["closed_at"] = clock.now_iso()
    touch(campaign)
    return single(serializers.campaign(campaign))
