"""Closed-loop attribution and incrementality measurement (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

from core import F, db, fail, insert, new_row, now, ok, rows, touch
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("measurement", __name__)

SALE_WRITE = ("NetworkAdmin", "MeasurementAnalyst")
SALE_READ = ("NetworkAdmin", "MeasurementAnalyst", "BillingOps",
             "AccountManager", "AdvertiserUser")
STUDY_WRITE = ("NetworkAdmin", "MeasurementAnalyst")
STUDY_READ = ("NetworkAdmin", "MeasurementAnalyst", "AccountManager",
              "BillingOps", "AdvertiserUser")

DESIGN_METHODS = ("GEO_HOLDOUT", "USER_HOLDOUT")
INVALIDATED_REASONS = ("DATA_DEFECT", "HOLDOUT_CONTAMINATION", "SUPERSEDED")
REMEASURE_GRACE_DAYS = 30

STUDY_TRANSITIONS = {
    "start": {"DESIGNED": "RUNNING"},
    "measure": {"RUNNING": "MEASURING", "INVALIDATED": "MEASURING"},
    "publish": {"MEASURING": "PUBLISHED"},
    "invalidate": {"MEASURING": "INVALIDATED", "PUBLISHED": "INVALIDATED"},
}

SALE_FILTERS = (
    ("engagement_event_id", "engagement_event_id", "string"),
    ("line_item_id", "line_item_id", "string"),
    ("catalog_product_id", "catalog_product_id", "string"),
    ("restated", "restated", "bool"),
    ("within_window", "within_window", "bool"),
)
STUDY_FILTERS = (
    ("campaign_id", "campaign_id", "string"),
    ("supersedes_study_id", "supersedes_study_id", "string"),
    ("design_method", "design_method", "string"),
    ("study_status", "study_status", "string"),
)


# ---------------------------------------------------------------------------
# Attributed sales
# ---------------------------------------------------------------------------
@bp.post("/rmn/attributed-sales")
def create_sale():
    specs = (
        F("engagement_event_id", "string", required=True),
        F("catalog_product_id", "string", required=True),
        F("retail_order_ref", "string", required=True),
        F("sale_cents", "integer", required=True, minimum=1),
        F("units", "integer", required=True, minimum=1),
        F("occurred_at", "datetime", required=True),
        F("match_type", "enum", required=True,
          enum=("CLICK_THROUGH", "VIEW_THROUGH")),
    )
    ctx = guard(SALE_WRITE, body_specs=specs,
                body_refs=(("catalog_product", "catalog_product_id"),
                           ("engagement_event", "engagement_event_id")))
    data = ctx.data
    engagement = ctx.get("engagement_event")
    line_item_id = engagement["line_item_id"]
    for other in rows("attributed_sale"):
        if other["retail_order_ref"] == data["retail_order_ref"] and \
                other["catalog_product_id"] == data["catalog_product_id"] and \
                other["line_item_id"] == line_item_id:
            fail("ERR_DUPLICATE_ATTRIBUTED_SALE",
                 "This order line is already credited to the line item.")
    match_type = ("CLICK_THROUGH" if engagement["event_type"] == "CLICK"
                  else "VIEW_THROUGH")
    row = new_row()
    row.update({
        "engagement_event_id": engagement["id"],
        "line_item_id": line_item_id,
        "catalog_product_id": data["catalog_product_id"],
        "retail_order_ref": data["retail_order_ref"],
        "sale_cents": data["sale_cents"],
        "units": data["units"],
        "occurred_at": data["occurred_at"],
        "match_type": match_type,
        "attribution_model_applied": None,
        "attribution_weight": 0.0,
        "attributed_credit_cents": 0,
        "within_window": False,
        "restated": False,
    })
    insert("attributed_sale", row)
    D.compute_attribution(row)
    li = db.line_items.get(line_item_id)
    camp = D.campaign_of_line_item(li) if li else None
    if camp is not None:
        touch(camp)
    return ok(D.ser_attributed_sale(row), 201)


@bp.get("/rmn/attributed-sales")
def list_sales():
    ctx = guard(SALE_READ, paginated=True)
    rows_ = rows("attributed_sale")
    if ctx.role == "AdvertiserUser":
        rows_ = [s for s in rows_
                 if _sale_advertiser(s) == ctx.user_id]
    return H.respond_list(ctx, "attributed_sale", rows_, SALE_FILTERS)


def _sale_advertiser(sale):
    li = db.line_items.get(sale["line_item_id"])
    camp = D.campaign_of_line_item(li) if li else None
    return camp["advertiser_id"] if camp else None


@bp.get("/rmn/attributed-sales/<sid>")
def read_sale(sid):
    ctx = guard(SALE_READ)
    sale = db.attributed_sales.get(sid)
    if sale is None:
        fail("ERR_ENGAGEMENT_EVENT_NOT_FOUND", "Attributed sale does not exist.")
    if ctx.role == "AdvertiserUser" and _sale_advertiser(sale) != ctx.user_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "This resource belongs to another advertiser.")
    return ok(D.ser_attributed_sale(sale))


# ---------------------------------------------------------------------------
# Incrementality studies
# ---------------------------------------------------------------------------
@bp.post("/rmn/incrementality-studies")
def create_study():
    specs = (
        F("campaign_id", "string", required=True),
        F("design_method", "enum", required=True, enum=DESIGN_METHODS),
        F("holdout_pct", "number", required=True, minimum=0.05, maximum=0.50),
        F("window_start_at", "datetime", required=True),
        F("window_end_at", "datetime", required=True),
        F("supersedes_study_id", "string", nullable=True),
        F("expected_campaign_version", "integer", required=True),
    )
    ctx = guard(STUDY_WRITE, body_specs=specs,
                body_refs=(("campaign", "campaign_id"),
                           ("study", "supersedes_study_id")),
                occ=("expected_campaign_version", "campaign",
                     "ERR_STALE_CAMPAIGN_VERSION"),
                mutating=True)
    data = ctx.data
    camp = ctx.get("campaign")
    start, end = data["window_start_at"], data["window_end_at"]
    if start >= end or start < camp["flight_start_at"] or \
            end > camp["flight_end_at"]:
        fail("ERR_FLIGHT_WINDOW_OUTSIDE_CAMPAIGN",
             "The study window must lie inside the campaign flight.")
    supersedes = data.get("supersedes_study_id")
    if D.washout_violation(camp["id"], None, start, end, supersedes) is not None:
        fail("ERR_STUDY_WASHOUT_VIOLATION",
             "The study window sits inside the seven day washout gap.")
    if supersedes is not None:
        prior = db.incrementality_studies[supersedes]
        if prior["campaign_id"] != camp["id"] or \
                prior["study_status"] != "PUBLISHED":
            fail("ERR_SUPERSEDED_STUDY_INVALID",
                 "supersedes_study_id must name a PUBLISHED study on the same "
                 "campaign.")
    row = new_row()
    row.update({
        "campaign_id": camp["id"],
        "supersedes_study_id": supersedes,
        "study_status": "DESIGNED",
        "design_method": data["design_method"],
        "holdout_pct": data["holdout_pct"],
        "exposed_group_size": 0,
        "control_group_size": 0,
        "exposed_conversions": 0,
        "control_conversions": 0,
        "exposed_sales_cents": 0,
        "control_sales_cents": 0,
        "lift_pct": None,
        "incremental_sales_cents": None,
        "significance_score": None,
        "significance_flag": None,
        "window_start_at": start,
        "window_end_at": end,
        "published_by_user_id": None,
        "invalidated_reason": "NONE",
    })
    insert("study", row)
    touch(camp)
    return ok(D.ser_study(row), 201)


@bp.get("/rmn/incrementality-studies")
def list_studies():
    ctx = guard(STUDY_READ, paginated=True)
    return H.respond_list(ctx, "study", rows("study"), STUDY_FILTERS,
                          owner_kind="study")


@bp.get("/rmn/incrementality-studies/<sid>")
def read_study(sid):
    ctx = guard(STUDY_READ, path_refs=(("study", sid),))
    return ok(D.ser_study(ctx.get("study")))


@bp.post("/rmn/incrementality-studies/<sid>/start")
def start_study(sid):
    specs = (
        F("exposed_group_size", "integer", required=True, minimum=1),
        F("control_group_size", "integer", required=True, minimum=1),
    )
    ctx = guard(STUDY_WRITE, path_refs=(("study", sid),), body_specs=specs,
                mutating=True)
    study = ctx.get("study")
    camp = db.campaigns[study["campaign_id"]]
    adv = ctx.get("advertiser")
    if adv["onboarding_status"] != "ACTIVE":
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    target = H.require_transition(study["study_status"],
                                  STUDY_TRANSITIONS["start"],
                                  "ERR_STUDY_INVALID_STATE", "study_status")
    if camp["delivery_status"] not in ("SCHEDULED", "DELIVERING"):
        fail("ERR_INVALID_CAMPAIGN_TRANSITION",
             "The campaign is %s." % camp["delivery_status"])
    if D.washout_violation(camp["id"], study["id"], study["window_start_at"],
                           study["window_end_at"],
                           study["supersedes_study_id"]) is not None:
        fail("ERR_STUDY_WASHOUT_VIOLATION",
             "The study window sits inside the seven day washout gap.")
    if now() < study["window_start_at"]:
        fail("ERR_STUDY_WINDOW_NOT_ELAPSED",
             "The study window has not opened yet.")
    study["exposed_group_size"] = ctx.data["exposed_group_size"]
    study["control_group_size"] = ctx.data["control_group_size"]
    study["study_status"] = target
    touch(study)
    return ok(D.ser_study(study))


@bp.post("/rmn/incrementality-studies/<sid>/measure")
def measure_study(sid):
    specs = (
        F("exposed_conversions", "integer", required=True, minimum=0),
        F("control_conversions", "integer", required=True, minimum=0),
        F("exposed_sales_cents", "integer", required=True, minimum=0),
        F("control_sales_cents", "integer", required=True, minimum=0),
    )
    ctx = guard(STUDY_WRITE, path_refs=(("study", sid),), body_specs=specs,
                mutating=True)
    study = ctx.get("study")
    source = study["study_status"]
    if source == "INVALIDATED" and study["invalidated_reason"] != "DATA_DEFECT":
        fail("ERR_STUDY_INVALID_STATE",
             "Only a study invalidated for a data defect is re-measurable.")
    target = H.require_transition(source, STUDY_TRANSITIONS["measure"],
                                  "ERR_STUDY_INVALID_STATE", "study_status")
    if source == "INVALIDATED" and \
            now() >= study["window_end_at"] + timedelta(days=REMEASURE_GRACE_DAYS):
        fail("ERR_STUDY_INVALID_STATE",
             "The re-measurement window has closed.")
    if now() < study["window_end_at"]:
        fail("ERR_STUDY_WINDOW_NOT_ELAPSED",
             "The study window has not elapsed yet.")
    if study["exposed_group_size"] < 1 or study["control_group_size"] < 1:
        fail("ERR_VALIDATION",
             "Both group sizes must be at least 1 before measurement.")
    study["exposed_conversions"] = ctx.data["exposed_conversions"]
    study["control_conversions"] = ctx.data["control_conversions"]
    study["exposed_sales_cents"] = ctx.data["exposed_sales_cents"]
    study["control_sales_cents"] = ctx.data["control_sales_cents"]
    D.compute_study_results(study)
    study["invalidated_reason"] = "NONE"
    study["study_status"] = target
    touch(study)
    return ok(D.ser_study(study))


@bp.post("/rmn/incrementality-studies/<sid>/publish")
def publish_study(sid):
    specs = (F("publication_note", "string"),)
    ctx = guard(STUDY_WRITE, path_refs=(("study", sid),), body_specs=specs,
                mutating=True)
    study = ctx.get("study")
    camp = db.campaigns[study["campaign_id"]]
    target = H.require_transition(study["study_status"],
                                  STUDY_TRANSITIONS["publish"],
                                  "ERR_STUDY_INVALID_STATE", "study_status")
    if not study["significance_flag"]:
        fail("ERR_STUDY_NOT_SIGNIFICANT",
             "significance_flag must be true before publication.")
    for other in D.studies_of_campaign(camp["id"]):
        if other["id"] == study["id"] or other["study_status"] != "PUBLISHED":
            continue
        if study["window_start_at"] < other["window_end_at"] and \
                other["window_start_at"] < study["window_end_at"]:
            fail("ERR_STUDY_WASHOUT_VIOLATION",
                 "Another published study overlaps this window.")
    study["published_by_user_id"] = ctx.user_id
    study["study_status"] = target
    touch(study)
    superseded_id = study["supersedes_study_id"]
    if superseded_id is not None:
        prior = db.incrementality_studies.get(superseded_id)
        if prior is not None and prior["study_status"] == "PUBLISHED":
            prior["study_status"] = "INVALIDATED"
            prior["invalidated_reason"] = "SUPERSEDED"
            touch(prior)
    touch(camp)
    return ok(D.ser_study(study))


@bp.post("/rmn/incrementality-studies/<sid>/invalidate")
def invalidate_study(sid):
    specs = (
        F("invalidated_reason", "enum", required=True, enum=INVALIDATED_REASONS),
        F("invalidation_note", "string"),
    )
    ctx = guard(STUDY_WRITE, path_refs=(("study", sid),), body_specs=specs,
                mutating=True)
    study = ctx.get("study")
    camp = db.campaigns[study["campaign_id"]]
    source = study["study_status"]
    target = H.require_transition(source, STUDY_TRANSITIONS["invalidate"],
                                  "ERR_STUDY_INVALID_STATE", "study_status")
    study["invalidated_reason"] = ctx.data["invalidated_reason"]
    study["study_status"] = target
    touch(study)
    if source == "PUBLISHED":
        # depth-three restatement cascade
        li_ids = set(l["id"] for l in D.line_items_of_campaign(camp["id"]))
        for sale in rows("attributed_sale"):
            if sale["line_item_id"] not in li_ids or sale["restated"]:
                continue
            if study["window_start_at"] <= sale["occurred_at"] < \
                    study["window_end_at"]:
                sale["restated"] = True
                touch(sale)
        touch(camp)
    return ok(D.ser_study(study))
