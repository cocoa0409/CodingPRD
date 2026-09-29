"""One-time (non-recurring) items and their estimate cascade."""

from flask import Blueprint

from db import db, make_record, now_iso, ordered, touch
from errors import fail
from middleware import authorize, body, req_enum, req_int, req_str, validation
from response import object_response
from routes.helpers import cycle_or_404, item_or_404, listing, source_or_404
from services import cascade

bp = Blueprint("items", __name__)

ITEM_TYPES = ("SETTLEMENT", "ASSET_SALE", "FEDERAL_AID", "TAX_AMNESTY")
ROLES = ("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist")
READ_ROLES = ROLES + ("RatingAnalyst",)


@bp.get("/one-time-items")
@authorize(*READ_ROLES)
def list_items():
    return listing(
        ordered(db.items),
        {
            "cycle_id": ("cycle_id", str),
            "source_id": ("source_id", str),
            "status": ("status", str),
            "item_type": ("item_type", str),
        },
    )


@bp.get("/one-time-items/<item_id>")
@authorize(*READ_ROLES)
def get_item(item_id):
    return object_response(item_or_404(item_id))


@bp.post("/one-time-items")
@authorize(*ROLES)
def create_item():
    data = body()

    cycle = None
    source = None
    if data.get("cycle_id") is not None:
        if not isinstance(data["cycle_id"], str):
            validation("cycle_id must be a string")
        cycle = cycle_or_404(data["cycle_id"])
    if data.get("source_id") is not None:
        if not isinstance(data["source_id"], str):
            validation("source_id must be a string")
        source = source_or_404(data["source_id"])

    if cycle is None:
        validation("cycle_id is required")
    if source is None:
        validation("source_id is required")
    item_type = req_enum(data, "item_type", ITEM_TYPES)
    amount = req_int(data, "amount_cents", minimum=1)
    description = req_str(data, "description")

    if source["status"] != "ACTIVE":
        fail("ERR_SOURCE_RETIRED", "a RETIRED source may not receive one-time items")
    if cycle["status"] in ("CERTIFIED", "SUPERSEDED"):
        fail("ERR_CYCLE_ALREADY_CERTIFIED",
             "a certified cycle's one-time items are frozen")

    rec = make_record(
        {
            "cycle_id": cycle["id"],
            "source_id": source["id"],
            "item_type": item_type,
            "amount_cents": amount,
            "description": description,
            "status": "ACTIVE",
            "voided_at": None,
        }
    )
    db.items[rec["id"]] = rec
    cascade.one_time_item_cascade(rec)
    return object_response(rec, 201)


@bp.post("/one-time-items/<item_id>/void")
@authorize(*ROLES)
def void_item(item_id):
    item = item_or_404(item_id)
    if item["status"] != "ACTIVE":
        fail("ERR_ONE_TIME_ITEM_NOT_ACTIVE", "only an ACTIVE item may be voided")
    cycle = db.cycles.get(item["cycle_id"])
    if cycle is not None and cycle["status"] in ("CERTIFIED", "SUPERSEDED"):
        fail("ERR_CYCLE_ALREADY_CERTIFIED",
             "a certified cycle's one-time items are frozen")
    item["status"] = "VOIDED"
    item["voided_at"] = now_iso()
    touch(item)
    cascade.one_time_item_cascade(item)
    return object_response(item)
