"""Monetization offers, probability disclosures and personalized quotes (PRD 3.5/3.6)."""
from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate, require_owner
from response import list_response, object_response, touch
from services import calc, cascades

bp = Blueprint("offers", __name__)

READ_ROLES = (
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_CONTENT_PRODUCER,
    config.ROLE_PLAYER,
)
DISCLOSURE_READ_ROLES = (
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_PLAYER,
)
QUOTE_ROLES = (
    config.ROLE_PLAYER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
def _line_items(payload):
    raw = payload.get("line_items")
    if raw is None:
        v.bad("line_items", "is required")
    if not isinstance(raw, list):
        v.bad("line_items", "must be an array")
    if len(raw) < 1 or len(raw) > 8:
        v.bad("line_items", "must hold between 1 and 8 entries")
    lines = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            v.bad("line_items", "entries must be objects")
        sku = v.req_string(entry, "sku")
        if sku in seen:
            v.bad("line_items", "entries must carry distinct skus")
        seen.add(sku)
        lines.append(
            {
                "sku": sku,
                "base_price_minor": v.req_int(entry, "base_price_minor", minimum=0),
                "declared_value_minor": v.req_int(entry, "declared_value_minor", minimum=0),
                "granted_currency_code": v.req_enum(
                    entry, "granted_currency_code", config.CURRENCY_CODES
                ),
                "granted_amount_minor": v.req_int(entry, "granted_amount_minor", minimum=0),
            }
        )
    return lines


def _disclosure_entries(payload):
    raw = payload.get("entries")
    if raw is None:
        v.bad("entries", "is required")
    if not isinstance(raw, list):
        v.bad("entries", "must be an array")
    if len(raw) < 1 or len(raw) > 20:
        v.bad("entries", "must hold between 1 and 20 entries")
    entries = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            v.bad("entries", "entries must be objects")
        item_sku = v.req_string(entry, "item_sku")
        if item_sku in seen:
            v.bad("entries", "entries must carry distinct item_skus")
        seen.add(item_sku)
        entries.append(
            {
                "item_sku": item_sku,
                "probability_bp": v.req_int(entry, "probability_bp", minimum=1),
                "item_value_minor": v.req_int(entry, "item_value_minor", minimum=0),
                "is_rare": v.opt_bool(entry, "is_rare", default=False),
            }
        )
    return entries


# ---------------------------------------------------------------------------
# Offer authoring
# ---------------------------------------------------------------------------
@bp.post("/offers")
def create_offer():
    user_id, _role = authenticate(config.ROLE_ECONOMY_DESIGNER)
    payload = v.body()
    season = resolve.body_fk(payload, "season_id", db.db.seasons, "ERR_SEASON_NOT_FOUND")
    v.req_string(payload, "season_id")
    offer_type = v.req_enum(payload, "offer_type", config.OFFER_TYPES)
    sku = v.req_string(payload, "sku")
    price_tier = v.req_enum(payload, "price_tier", config.PRICE_TIERS)
    list_price_minor = v.req_int(payload, "list_price_minor", minimum=1)
    lines = _line_items(payload)
    if list_price_minor != sum(line["base_price_minor"] for line in lines):
        v.bad("list_price_minor", "must equal the sum of the line items' base_price_minor")
    personalization_discount_bp = v.opt_int(
        payload, "personalization_discount_bp", default=0, minimum=0, maximum=2000
    )
    minor_purchasable = v.opt_bool(payload, "minor_purchasable", default=False)
    window_start = v.req_datetime(payload, "window_start")
    window_end = v.req_datetime(payload, "window_end")
    if window_end <= window_start:
        v.bad("window_end", "must be strictly after window_start")

    for existing in db.db.offers.values():
        if existing["season_id"] == season["id"] and existing["sku"] == sku:
            fail("ERR_OFFER_SKU_DUPLICATE", "An offer with this sku already exists in the season.")

    offer = db.insert(
        db.db.offers,
        {
            "season_id": season["id"],
            "offer_type": offer_type,
            "sku": sku,
            "price_tier": price_tier,
            "list_price_minor": list_price_minor,
            "line_items": lines,
            "personalization_discount_bp": personalization_discount_bp,
            "minor_purchasable": minor_purchasable,
            "window_start": window_start,
            "window_end": window_end,
            "approval_status": "DRAFT",
            "availability_status": "OFFLINE",
            "fairness_index_bp": 0,
            "disclosure_state": "REQUIRED_MISSING" if offer_type == "LOOT_BOX" else "NOT_REQUIRED",
            "units_sold": 0,
            "pending_purchase_count": 0,
            "created_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "revision_count": 0,
        },
    )
    offer["fairness_index_bp"] = calc.offer_fairness_index_bp(offer)
    return object_response(serialize(offer), 201)


@bp.get("/offers/<offer_id>")
def read_offer(offer_id):
    authenticate(*READ_ROLES)
    offer = resolve.offer(offer_id)
    return object_response(serialize(offer))


@bp.get("/offers")
def list_offers():
    authenticate(*READ_ROLES)
    season_id = request.args.get("season_id")
    offer_type = v.query_enum("offer_type", config.OFFER_TYPES)
    approval_status = v.query_enum("approval_status", config.OFFER_APPROVAL_STATUSES)
    availability_status = v.query_enum("availability_status", config.OFFER_AVAILABILITY_STATUSES)
    limit, offset = v.pagination()
    rows = list(db.db.offers.values())
    if season_id is not None:
        rows = [o for o in rows if o["season_id"] == season_id]
    if offer_type is not None:
        rows = [o for o in rows if o["offer_type"] == offer_type]
    if approval_status is not None:
        rows = [o for o in rows if o["approval_status"] == approval_status]
    if availability_status is not None:
        rows = [o for o in rows if o["availability_status"] == availability_status]
    records = [serialize(o) for o in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Governance dimension
# ---------------------------------------------------------------------------
@bp.post("/offers/<offer_id>/submit")
def submit_offer(offer_id):
    authenticate(config.ROLE_ECONOMY_DESIGNER)
    offer = resolve.offer(offer_id)
    season = db.db.seasons.get(offer["season_id"])

    if offer["approval_status"] != "DRAFT":
        fail("ERR_OFFER_INVALID_APPROVAL_STATE", "Only a DRAFT offer can be submitted for review.")
    if offer["availability_status"] != "OFFLINE":
        fail("ERR_OFFER_INVALID_AVAILABILITY_STATE", "The offer must be OFFLINE to be submitted.")
    if season is None or season["status"] != "LIVE":
        fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE to submit an offer for review.")

    offer["approval_status"] = "IN_REVIEW"
    offer["fairness_index_bp"] = calc.offer_fairness_index_bp(offer)
    touch(offer)
    return object_response(serialize(offer))


@bp.post("/offers/<offer_id>/review")
def review_offer(offer_id):
    user_id, _role = authenticate(config.ROLE_COMPLIANCE_OFFICER)
    offer = resolve.offer(offer_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("APPROVE", "REVISE"))
    v.opt_string(payload, "note")

    if offer["approval_status"] != "IN_REVIEW":
        fail("ERR_OFFER_INVALID_APPROVAL_STATE", "Only an IN_REVIEW offer can be reviewed.")
    if user_id == offer["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The reviewer may not be the offer's author.")

    if decision == "APPROVE":
        offer["approval_status"] = "APPROVED"
    else:
        offer["approval_status"] = "DRAFT"
        offer["revision_count"] += 1
    offer["reviewed_by_user_id"] = user_id
    touch(offer)
    return object_response(serialize(offer))


# ---------------------------------------------------------------------------
# Storefront dimension
# ---------------------------------------------------------------------------
@bp.post("/offers/<offer_id>/publish")
def publish_offer(offer_id):
    authenticate(config.ROLE_ECONOMY_DESIGNER, config.ROLE_LIVEOPS_COMMANDER)
    offer = resolve.offer(offer_id)
    payload = v.body()
    expected_season_version = v.req_int(payload, "expected_season_version", minimum=1)
    season = db.db.seasons.get(offer["season_id"])

    if season is None or season["version"] != expected_season_version:
        fail("ERR_STALE_SEASON_VERSION", "The pinned season version is stale.")
    if offer["availability_status"] != "OFFLINE":
        fail("ERR_OFFER_INVALID_AVAILABILITY_STATE", "Only an OFFLINE offer can be published.")
    if offer["approval_status"] != "APPROVED":
        fail("ERR_OFFER_INVALID_APPROVAL_STATE", "The offer must be APPROVED before publication.")
    if season["status"] != "LIVE":
        fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE to publish an offer.")
    if db.now() > offer["window_end"]:
        fail("ERR_OFFER_WINDOW_CLOSED", "The merchandising window has closed.")
    if offer["disclosure_state"] == "REQUIRED_MISSING":
        fail("ERR_DISCLOSURE_NOT_PUBLISHED", "A randomized offer needs a published probability table.")
    offer["fairness_index_bp"] = calc.offer_fairness_index_bp(offer)
    if offer["fairness_index_bp"] < config.FAIRNESS_FLOOR_BP:
        fail("ERR_FAIRNESS_FLOOR_BREACH", "The fairness index is below the floor.")
    if season["economy_health"] == "INFLATED":
        fail("ERR_ECONOMY_INFLATED_BLOCK", "The season economy is INFLATED.")
    if offer["offer_type"] == "LIMITED_TIME" and season["content_posture"] == "BEHIND":
        fail("ERR_CADENCE_DEBT_BLOCK", "The season is BEHIND on its content roadmap.")
    if calc.offer_sku_window_conflict(offer):
        fail("ERR_OFFER_SKU_WINDOW_CONFLICT", "A live sibling offer shares a sku inside the cooldown.")

    offer["availability_status"] = "LIVE"
    touch(offer)
    season["live_offer_count"] += 1
    touch(season)
    return object_response(serialize(offer))


@bp.post("/offers/<offer_id>/availability")
def change_availability(offer_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER, config.ROLE_COMPLIANCE_OFFICER)
    offer = resolve.offer(offer_id)
    payload = v.body()
    to_status = v.req_enum(payload, "to_status", config.OFFER_AVAILABILITY_STATUSES)
    reason = v.opt_string(payload, "reason")
    season = db.db.seasons.get(offer["season_id"])
    current = offer["availability_status"]

    if to_status == "SUSPENDED":
        if current != "LIVE":
            fail("ERR_OFFER_INVALID_AVAILABILITY_STATE", "Only a LIVE offer can be suspended.")
        cascades.suspend_offer(offer)
    elif to_status == "LIVE":
        if current != "SUSPENDED":
            fail("ERR_OFFER_INVALID_AVAILABILITY_STATE", "Only a SUSPENDED offer can be resumed.")
        if db.now() > offer["window_end"]:
            fail("ERR_OFFER_WINDOW_CLOSED", "The merchandising window has closed.")
        if offer["disclosure_state"] == "REQUIRED_MISSING":
            fail(
                "ERR_DISCLOSURE_NOT_PUBLISHED",
                "A randomized offer needs a published probability table.",
            )
        if season is not None and season["economy_health"] == "INFLATED":
            fail("ERR_ECONOMY_INFLATED_BLOCK", "The season economy is INFLATED.")
        offer["availability_status"] = "LIVE"
        touch(offer)
        if season is not None:
            season["live_offer_count"] += 1
            touch(season)
    elif to_status == "WITHDRAWN":
        if current not in ("OFFLINE", "LIVE", "SUSPENDED"):
            fail("ERR_OFFER_INVALID_AVAILABILITY_STATE", "The offer is already WITHDRAWN.")
        cascades.withdraw_offer(offer, cascades.DENY_OFFER_WITHDRAWN)
    else:
        fail("ERR_OFFER_INVALID_AVAILABILITY_STATE", "No transition to OFFLINE exists.")
    del reason
    return object_response(serialize(offer))


# ---------------------------------------------------------------------------
# Probability disclosures
# ---------------------------------------------------------------------------
@bp.post("/offers/<offer_id>/disclosures")
def create_disclosure(offer_id):
    authenticate(config.ROLE_ECONOMY_DESIGNER)
    offer = resolve.offer(offer_id)
    payload = v.body()
    entries = _disclosure_entries(payload)
    total_probability_bp, expected_value_minor = calc.disclosure_totals(entries)
    if total_probability_bp != 10000:
        fail(
            "ERR_DISCLOSURE_PROBABILITY_SUM",
            "The entries' probability_bp must sum to exactly 10000.",
        )
    table = db.insert(
        db.db.disclosures,
        {
            "offer_id": offer["id"],
            "entries": entries,
            "total_probability_bp": total_probability_bp,
            "expected_value_minor": expected_value_minor,
            "status": "DRAFT",
            "published_at": None,
            "published_by_user_id": None,
        },
    )
    return object_response(serialize(table), 201)


@bp.get("/offers/<offer_id>/disclosures")
def list_disclosures(offer_id):
    authenticate(*DISCLOSURE_READ_ROLES)
    offer = resolve.offer(offer_id)
    status = v.query_enum("status", config.DISCLOSURE_STATUSES)
    limit, offset = v.pagination()
    rows = [d for d in db.db.disclosures.values() if d["offer_id"] == offer["id"]]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    records = [serialize(d) for d in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/offers/<offer_id>/disclosures/<disclosure_id>/publish")
def publish_disclosure(offer_id, disclosure_id):
    user_id, _role = authenticate(config.ROLE_COMPLIANCE_OFFICER)
    offer = resolve.offer(offer_id)
    table = resolve.disclosure(offer, disclosure_id)

    if table["status"] != "DRAFT":
        fail("ERR_DISCLOSURE_INVALID_STATE", "Only a DRAFT table can be published.")
    if offer["availability_status"] == "WITHDRAWN":
        fail("ERR_OFFER_INVALID_AVAILABILITY_STATE", "The owning offer is WITHDRAWN.")
    if table["total_probability_bp"] != 10000:
        fail(
            "ERR_DISCLOSURE_PROBABILITY_SUM",
            "The entries' probability_bp must sum to exactly 10000.",
        )

    table["status"] = "PUBLISHED"
    table["published_at"] = db.now()
    table["published_by_user_id"] = user_id
    touch(table)

    for sibling in ordered(list(db.db.disclosures.values())):
        if (
            sibling["id"] != table["id"]
            and sibling["offer_id"] == offer["id"]
            and sibling["status"] == "PUBLISHED"
        ):
            sibling["status"] = "SUPERSEDED"
            touch(sibling)

    offer["disclosure_state"] = "PUBLISHED"
    touch(offer)
    return object_response(serialize(table))


# ---------------------------------------------------------------------------
# Read-only personalized quote
# ---------------------------------------------------------------------------
@bp.get("/offers/<offer_id>/quote")
def read_quote(offer_id):
    user_id, role = authenticate(*QUOTE_ROLES)
    offer = resolve.offer(offer_id)
    player_id = request.args.get("player_id")
    if player_id is None or player_id == "":
        v.bad("player_id", "is required")
    player = resolve.path_record(db.db.players, player_id, "ERR_PLAYER_NOT_FOUND")
    require_owner(role, user_id, player["id"])

    result = calc.personalized_quote(offer, player)
    data = {"offer_id": offer["id"], "player_id": player["id"]}
    data.update(result)
    return object_response(data)
