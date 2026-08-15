"""Listing agreements, lifecycle actions, syndication."""
from flask import Blueprint, request
from db import db, clock, parse_iso
from errors import (err_duplicate, err_invalid_deadline, err_invalid_state,
                    err_invalid_request, err_syndication_stale, err_forbidden)
from middleware import (get_caller, require_roles, get_json_body, require_fields,
                        check_enum, check_int, check_str, parse_pagination, paginate)
from response import success_object, success_list
from services.common import (new_entity, touch, get_or_404, serialize_listing,
                             serialize_syndication_event, serialize_offer)
from services.events import emit
from services.sweep import _expire_listing_offers

bp = Blueprint("listings", __name__)

AGREEMENT_TYPES = {"CENTRAL", "OPEN"}
TIER_CODES = {"STANDARD", "PREMIER", "BOUTIQUE"}
CHANNELS = {"YACHTWORLD", "BOATS_COM", "BOATTRADER", "DENISON_MLS"}
OUTCOMES = {"ACKED", "REJECTED"}
NON_TERMINAL_LISTING_STATES = {"DRAFT", "ACTIVE", "SUSPENDED", "UNDER_CONTRACT"}
LIST_PRICE_FLOOR = 100_000_000  # USD 1M


def _other_nonterminal_listing(vessel_id, exclude_id=None):
    for l in db.listings.values():
        if l["vessel_id"] == vessel_id and l["status"] in NON_TERMINAL_LISTING_STATES \
                and l["id"] != exclude_id:
            return l
    return None


@bp.route("/yacht/listings", methods=["POST"])
def create_listing():
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    body = get_json_body()
    require_fields(body, ["brokerage_id", "listing_agent_id", "seller_id", "vessel_id",
                          "agreement_type", "list_price_cents", "start_date", "end_date"])
    # Body FK existence (priority 4)
    brokerage = get_or_404(db.brokerages, body["brokerage_id"], "Brokerage")
    agent = get_or_404(db.agents, body["listing_agent_id"], "BrokerAgent")
    seller = get_or_404(db.clients, body["seller_id"], "Client")
    vessel = get_or_404(db.vessels, body["vessel_id"], "Vessel")
    # Priority 9: uniqueness — one non-terminal listing per vessel
    if _other_nonterminal_listing(vessel["id"]):
        raise err_duplicate("Vessel already has a non-terminal ListingAgreement")
    # Priority 11: end_date strictly after start_date
    check_str(body, "start_date")
    check_str(body, "end_date")
    try:
        start_dt = parse_iso(body["start_date"])
        end_dt = parse_iso(body["end_date"])
    except (ValueError, TypeError):
        raise err_invalid_request("start_date/end_date must be ISO-8601 datetimes")
    if end_dt <= start_dt:
        raise err_invalid_deadline("end_date must be strictly after start_date")
    # Shape
    check_enum(body, "agreement_type", AGREEMENT_TYPES)
    check_int(body, "list_price_cents", min_v=LIST_PRICE_FLOOR)
    check_enum(body, "commission_tier_code", TIER_CODES, required=False)
    check_int(body, "protection_period_days", required=False, min_v=0, max_v=180)
    if agent["brokerage_id"] != brokerage["id"]:
        raise err_invalid_request("listing_agent_id must belong to brokerage_id")
    if agent["status"] != "ACTIVE":
        raise err_invalid_state("listing agent is not ACTIVE")
    if seller["kind"] not in ("SELLER", "BOTH"):
        raise err_invalid_request("seller_id client kind must include SELLER")

    l = new_entity()
    l["brokerage_id"] = body["brokerage_id"]
    l["listing_agent_id"] = body["listing_agent_id"]
    l["seller_id"] = body["seller_id"]
    l["vessel_id"] = body["vessel_id"]
    l["agreement_type"] = body["agreement_type"]
    l["list_price_cents"] = body["list_price_cents"]
    l["commission_tier_code"] = body.get("commission_tier_code")
    l["start_date"] = body["start_date"]
    l["end_date"] = body["end_date"]
    l["protection_period_days"] = body.get("protection_period_days", 90)
    l["status"] = "DRAFT"
    l["syndication_status"] = "NOT_SENT"
    db.listings[l["id"]] = l
    return success_object(serialize_listing(l), 201)


@bp.route("/yacht/listings/<lid>", methods=["GET"])
def get_listing(lid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    return success_object(serialize_listing(l))


@bp.route("/yacht/listings", methods=["GET"])
def list_listings():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    limit, offset = parse_pagination()
    items = sorted(db.listings.values(), key=lambda x: x["created_at"])
    for f in ("status", "vessel_id", "seller_id", "brokerage_id", "listing_agent_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l[f] == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_listing(l) for l in page], limit, offset, total)


def _agent_for_caller(caller):
    return db.agents.get(caller.user_id)


@bp.route("/yacht/listings/<lid>/activate", methods=["POST"])
def activate_listing(lid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    # State check (priority 5)
    if l["status"] not in ("DRAFT", "SUSPENDED"):
        raise err_invalid_state("Listing must be DRAFT or SUSPENDED to activate")
    # Business preconditions per state machine
    agent = _agent_for_caller(caller)
    if agent is None or agent["brokerage_id"] != l["brokerage_id"]:
        raise err_forbidden("Acting agent's brokerage does not match listing brokerage")
    if agent["status"] != "ACTIVE":
        raise err_invalid_state("Agent is not ACTIVE")
    seller = db.clients.get(l["seller_id"])
    if seller is None or seller["kind"] not in ("SELLER", "BOTH"):
        raise err_invalid_state("Seller missing or kind does not include SELLER")
    if _other_nonterminal_listing(l["vessel_id"], exclude_id=l["id"]):
        raise err_duplicate("Another non-terminal listing exists for this vessel")
    if clock.now() >= parse_iso(l["end_date"]):
        raise err_invalid_deadline("Listing end_date has passed")
    l["status"] = "ACTIVE"
    touch(l)
    emit("ListingAgreement", l["id"], "LISTING_ACTIVATED", caller.role, caller.user_id,
         {"status": "ACTIVE"})
    return success_object(serialize_listing(l))


@bp.route("/yacht/listings/<lid>/suspend", methods=["POST"])
def suspend_listing(lid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    if l["status"] != "ACTIVE":
        raise err_invalid_state("Listing must be ACTIVE to suspend")
    l["status"] = "SUSPENDED"
    touch(l)
    emit("ListingAgreement", l["id"], "LISTING_SUSPENDED", caller.role, caller.user_id,
         {"status": "SUSPENDED"})
    return success_object(serialize_listing(l))


@bp.route("/yacht/listings/<lid>/cancel", methods=["POST"])
def cancel_listing(lid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    if l["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Listing must be ACTIVE or SUSPENDED to cancel")
    has_accepted = any(o["listing_id"] == l["id"] and o["status"] == "ACCEPTED"
                       for o in db.offers.values())
    if has_accepted:
        raise err_invalid_state("Listing has an ACCEPTED offer")
    l["status"] = "CANCELLED"
    l["syndication_status"] = "WITHDRAWN"
    touch(l)
    _expire_listing_offers(l["id"])
    emit("ListingAgreement", l["id"], "LISTING_CANCELLED", caller.role, caller.user_id,
         {"status": "CANCELLED"})
    return success_object(serialize_listing(l))


@bp.route("/yacht/listings/<lid>/price", methods=["PUT"])
def change_price(lid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    body = get_json_body()
    require_fields(body, ["list_price_cents"])
    check_int(body, "list_price_cents", min_v=LIST_PRICE_FLOOR)
    l["list_price_cents"] = body["list_price_cents"]
    l["syndication_status"] = "STALE"
    touch(l)
    return success_object(serialize_listing(l))


@bp.route("/yacht/listings/<lid>/syndication-events", methods=["POST"])
def push_syndication(lid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    body = get_json_body()
    require_fields(body, ["channel", "payload_price_cents", "outcome"])
    # Priority 19: listing must be ACTIVE and payload price must equal list price
    if l["status"] != "ACTIVE" or body.get("payload_price_cents") != l["list_price_cents"]:
        raise err_syndication_stale()
    check_enum(body, "channel", CHANNELS)
    check_enum(body, "outcome", OUTCOMES)
    check_int(body, "payload_price_cents", min_v=0)

    from db import clock as _clock
    ev = new_entity(common=False)
    ev["listing_id"] = l["id"]
    ev["channel"] = body["channel"]
    ev["payload_price_cents"] = body["payload_price_cents"]
    ev["outcome"] = body["outcome"]
    ev["sent_at"] = _clock.iso()
    db.syndication_events[ev["id"]] = ev
    if body["outcome"] == "ACKED":
        l["syndication_status"] = "SYNDICATED"
    return success_object(serialize_syndication_event(ev), 201)


@bp.route("/yacht/listings/<lid>/syndication-events", methods=["GET"])
def list_syndication(lid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    items = sorted([s for s in db.syndication_events.values() if s["listing_id"] == l["id"]],
                   key=lambda x: x["created_at"])
    return success_list([serialize_syndication_event(s) for s in items],
                        len(items) or 10, 0, len(items))


@bp.route("/yacht/listings/<lid>/offers", methods=["GET"])
def listing_offers(lid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    l = get_or_404(db.listings, lid, "ListingAgreement")
    items = sorted([o for o in db.offers.values() if o["listing_id"] == l["id"]],
                   key=lambda x: x["created_at"])
    return success_list([serialize_offer(o) for o in items], len(items) or 10, 0, len(items))
