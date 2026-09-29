"""Revenue ingestion and accrual (PRD 3.3)."""
from flask import Blueprint, request

import calc
import ledger
import serialize
from apierrors import fail
from envelope import created
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, sort_rows

bp = Blueprint("revenue", __name__)

READ_ROLES = ("FinanceOperator", "PlatformAdmin", "PolicyReviewer", "Auditor", "Creator")

CREATE = (
    F("creator_id", "str", required=True),
    F("product_id", "str", required=True),
    F("content_item_id", "str", default=None),
    F("gross_amount_cents", "int", required=True, exclusive_min=0),
    F("occurred_at", "datetime", required=True),
)
REFS = (("creator_id", "creators"), ("product_id", "products"),
        ("content_item_id", "content_items"))


@bp.route("/monetization/revenue-events", methods=["POST"])
@endpoint(roles=("PlatformAdmin", "FinanceOperator"), fields=CREATE, refs=REFS)
def create_revenue_event(ctx):
    creator = ctx.refs["creator_id"]
    product = ctx.refs["product_id"]
    item = ctx.refs.get("content_item_id")
    occurred_at = ctx.data["occurred_at"]

    if creator["eligibility_status"] != "ELIGIBLE":                       # 38
        fail("ERR_CREATOR_NOT_ELIGIBLE", "The creator is not ELIGIBLE.")
    if product["status"] != "ACTIVE":                                     # 39
        fail("ERR_PRODUCT_RETIRED", "The product is retired.")
    for inv in db.rows("investigations"):                                 # 48
        if inv["creator_id"] != creator["id"] or inv["state"] != "OPEN":
            continue
        if inv["violation_window_start"] <= occurred_at <= inv["violation_window_end"]:
            fail("ERR_ACCRUAL_UNDER_INVESTIGATION",
                 "occurred_at falls inside an open investigation window.")
    if item is not None and item["creator_id"] != creator["id"]:          # 49
        fail("ERR_CONTENT_CREATOR_MISMATCH",
             "The content item belongs to another creator.")
    if product["product_type"] == "ADVERTISING" and item is None:         # 50
        fail("ERR_CONTENT_LINK_REQUIRED",
             "content_item_id is required for ADVERTISING revenue.")
    if product["product_type"] != "ADVERTISING" and item is not None:     # 51
        fail("ERR_CONTENT_LINK_FORBIDDEN",
             "content_item_id is forbidden for non-ADVERTISING revenue.")
    periods = [p for p in db.rows("periods")
               if p["status"] == "OPEN"
               and p["period_start"] <= occurred_at < p["period_end"]]
    if len(periods) != 1:                                                 # 71
        fail("ERR_NO_OPEN_PERIOD_FOR_EVENT",
             "No OPEN earnings period contains occurred_at.")
    period = periods[0]

    rating = item["suitability_rating"] if item is not None else "GREEN"
    effective, share, status = calc.revenue_share_split(
        ctx.data["gross_amount_cents"], product, creator, rating, "INITIAL_ACCRUAL")
    row = db.insert("revenue_events", {
        "creator_id": creator["id"],
        "product_id": product["id"],
        "content_item_id": item["id"] if item is not None else None,
        "period_id": period["id"],
        "gross_amount_cents": ctx.data["gross_amount_cents"],
        "occurred_at": occurred_at,
        "terms_version_at_accrual": product["terms_version"],
        "suitability_rating_at_accrual": rating,
        "effective_share_bps": effective,
        "creator_share_cents": share,
        "status": status,
        "last_status_change_at": db.now,
    })
    if share > 0:
        ledger.append(creator["id"], "ACCRUAL", share, "REVENUE_EVENT", row["id"])
    return created(serialize.revenue_event(row))


@bp.route("/monetization/revenue-events", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_revenue_events(ctx):
    rows = db.rows("revenue_events")
    if ctx.is_creator:
        rows = [r for r in rows if r["creator_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "creator_id": "creator_id",
        "product_id": "product_id",
        "content_item_id": "content_item_id",
        "period_id": "period_id",
        "status": "status",
    })
    rows = sort_rows(rows, lambda r: (r["occurred_at"], r["created_at"]))
    return respond(ctx, rows, serialize.revenue_event)
