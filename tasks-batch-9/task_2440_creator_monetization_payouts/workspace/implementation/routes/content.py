"""Content items and ad-suitability re-rating (PRD 3.4)."""
from flask import Blueprint, request

import rescore
import serialize
from apierrors import fail
from envelope import created, ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, sort_rows

bp = Blueprint("content", __name__)

RATINGS = ("GREEN", "YELLOW", "RED")
READ_ROLES = ("Creator", "PolicyReviewer", "FinanceOperator", "PlatformAdmin", "Auditor")

CREATE = (
    F("creator_id", "str", required=True),
    F("title", "str", required=True, text=(1, 200)),
    F("published_at", "datetime", required=True),
)
RATE = (
    F("suitability_rating", "enum", required=True, enum=RATINGS),
    F("rating_source", "enum", required=True,
      enum=("DEFAULT", "AUTOMATED", "MANUAL", "APPEAL")),
    F("note", "str"),
)

PATH = (("content_item_id", "content_items"),)
OWN = lambda ctx: ctx.path["content_item_id"]["creator_id"]


@bp.route("/monetization/content-items", methods=["POST"])
@endpoint(roles=("Creator", "PlatformAdmin"), fields=CREATE,
          refs=(("creator_id", "creators"),),
          owner=lambda ctx: ctx.data.get("creator_id"))
def create_content(ctx):
    if ctx.data["published_at"] > db.now:                                # 72
        fail("ERR_PUBLISHED_IN_FUTURE",
             "published_at may not be later than the current logical time.")
    row = db.insert("content_items", {
        "creator_id": ctx.refs["creator_id"]["id"],
        "title": ctx.data["title"],
        "published_at": ctx.data["published_at"],
        "suitability_rating": "GREEN",
        "rating_source": "DEFAULT",
        "last_rated_by_user_id": None,
        "last_rated_at": None,
    })
    return created(serialize.content_item(row))


@bp.route("/monetization/content-items", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_content(ctx):
    rows = db.rows("content_items")
    if ctx.is_creator:
        rows = [r for r in rows if r["creator_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "creator_id": "creator_id",
        "suitability_rating": "suitability_rating",
        "rating_source": "rating_source",
    })
    if "monetization_state" in request.args:
        wanted = request.args.get("monetization_state")
        rows = [r for r in rows
                if serialize.calc.MONETIZATION_STATE[r["suitability_rating"]] == wanted]
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.content_item)


@bp.route("/monetization/content-items/<content_item_id>", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN)
def read_content(ctx, content_item_id):
    return ok(serialize.content_item(ctx.path["content_item_id"]))


@bp.route("/monetization/content-items/<content_item_id>/rate", methods=["POST"])
@endpoint(roles=("PolicyReviewer",), path=PATH, fields=RATE)
def rate_content(ctx, content_item_id):
    row = ctx.path["content_item_id"]
    if ctx.data["suitability_rating"] == row["suitability_rating"]:       # 18
        fail("ERR_RATING_UNCHANGED",
             "The supplied suitability_rating equals the stored rating.")
    if ctx.data["rating_source"] not in ("AUTOMATED", "MANUAL"):          # 46
        fail("ERR_RATING_SOURCE_RESERVED",
             "rating_source DEFAULT and APPEAL are reserved for the system.")
    row["suitability_rating"] = ctx.data["suitability_rating"]            # hop 1
    row["rating_source"] = ctx.data["rating_source"]
    row["last_rated_by_user_id"] = ctx.user_id
    row["last_rated_at"] = db.now
    db.touch(row)
    rescore.rescore_content(row)                                    # hops 2, 3
    return ok(serialize.content_item(row))
