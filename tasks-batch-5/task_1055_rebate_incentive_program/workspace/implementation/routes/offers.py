"""Offer endpoints (6)."""
from flask import Blueprint, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err
from services import budget

bp = Blueprint("offers", __name__)

READ_ROLES = (
    "ProgramAdmin", "ClaimsProcessor", "FinanceOfficer", "FraudAnalyst", "Dealer", "Consumer",
)

LIVE_OFFER_STATES = {"DRAFT", "PUBLISHED", "SUSPENDED"}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open intersection; windows that merely touch do not intersect."""
    return a_start < b_end and b_start < a_end


def check_overlap(offer):
    for other in db.offers.values():
        if other["id"] == offer["id"]:
            continue
        if other["program_id"] != offer["program_id"]:
            continue
        if other["sku_scope"] != offer["sku_scope"]:
            continue
        if other["channel"] != offer["channel"]:
            continue
        if other["status"] not in LIVE_OFFER_STATES:
            continue
        if _overlaps(
            offer["effective_start_date"], offer["effective_end_date"],
            other["effective_start_date"], other["effective_end_date"],
        ):
            raise err("ERR_OFFER_WINDOW_OVERLAP")


@bp.post("/api/offers")
@mw.require("ProgramAdmin")
def create_offer():
    data = mw.body()
    program_id = data.get("program_id")
    if not isinstance(program_id, str) or not program_id:
        raise err("ERR_VALIDATION", "Field 'program_id' is required.")
    program = db.get_program(program_id)

    name = mw.as_string(data, "name")
    channel = mw.as_enum(data, "channel", {"DEALER", "CONSUMER", "BOTH"})
    sku_scope = mw.as_string(data, "sku_scope")
    start = mw.as_datetime(data, "effective_start_date")
    end = mw.as_datetime(data, "effective_end_date")
    max_rebate = mw.as_int(data, "max_rebate_cents_per_claim", positive=True)
    tier_enabled = mw.as_bool(data, "dealer_tier_enabled", default=True)

    if end <= start:
        raise err("ERR_VALIDATION", "effective_end_date must be strictly after effective_start_date.")

    rec = db.base_record()
    rec.update({
        "program_id": program["id"],
        "name": name,
        "channel": channel,
        "sku_scope": sku_scope,
        "effective_start_date": start,
        "effective_end_date": end,
        "max_rebate_cents_per_claim": max_rebate,
        "dealer_tier_enabled": tier_enabled,
        "status": "DRAFT",
        "closed_at": None,
        "active_claim_count": 0,
    })
    check_overlap(rec)
    db.offers[rec["id"]] = rec
    return resp.created(ser.offer(rec))


@bp.get("/api/offers/<oid>")
@mw.require(*READ_ROLES)
def read_offer(oid):
    return resp.ok(ser.offer(db.get_offer(oid)))


@bp.get("/api/offers")
@mw.require(*READ_ROLES)
def list_offers():
    items = db.by_created(list(db.offers.values()))
    for field in ("program_id", "status", "channel", "sku_scope"):
        value = request.args.get(field)
        if value:
            items = [o for o in items if o[field] == value]
    return resp.paginated(items, ser.offer)


@bp.post("/api/offers/<oid>/publish")
@mw.require("ProgramAdmin")
def publish_offer(oid):
    offer = db.get_offer(oid)
    if offer["status"] not in ("DRAFT", "SUSPENDED"):
        raise err("ERR_OFFER_NOT_PUBLISHED", "Offer cannot be published from its current state.")
    program = db.programs.get(offer["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE")
    check_overlap(offer)
    offer["status"] = "PUBLISHED"
    db.touch(offer)
    return resp.ok(ser.offer(offer))


@bp.post("/api/offers/<oid>/suspend")
@mw.require("ProgramAdmin")
def suspend_offer(oid):
    offer = db.get_offer(oid)
    if offer["status"] != "PUBLISHED":
        raise err("ERR_OFFER_NOT_PUBLISHED", "Only a published offer may be suspended.")
    budget.suspend_offer(offer)
    return resp.ok(ser.offer(offer))


@bp.post("/api/offers/<oid>/close")
@mw.require("ProgramAdmin")
def close_offer(oid):
    offer = db.get_offer(oid)
    if offer["status"] not in LIVE_OFFER_STATES:
        raise err("ERR_OFFER_NOT_PUBLISHED", "Offer cannot be closed from its current state.")
    offer["status"] = "CLOSED"
    offer["closed_at"] = db.now()
    db.touch(offer)
    return resp.ok(ser.offer(offer))
