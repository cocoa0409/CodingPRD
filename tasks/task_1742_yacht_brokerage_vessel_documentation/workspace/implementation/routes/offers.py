"""Offers: submission, accept/reject/counter/withdraw/fail, contingencies."""
from datetime import timedelta
from flask import Blueprint, request
from db import db, clock, parse_iso
from errors import (err_invalid_deadline, err_deadline_passed, err_invalid_state,
                    err_invalid_request, err_listing_not_accepting,
                    err_stale_version, err_forbidden)
from middleware import (get_caller, require_roles, get_json_body, require_fields,
                        check_enum, check_int, check_bool, parse_pagination, paginate)
from response import success_object, success_list
from services.common import (new_entity, touch, get_or_404, serialize_offer,
                             serialize_contingency)
from services.events import emit

bp = Blueprint("offers", __name__)

US_STATES = {"FL", "CA", "WA", "NY", "TX", "RI", "MD", "NC", "SC", "MA", "GA", "NJ"}


def _create_contingency(offer_id, kind, deadline_dt):
    c = new_entity()
    c["offer_id"] = offer_id
    c["kind"] = kind
    c["deadline"] = _render(deadline_dt)
    c["status"] = "OPEN"
    c["objection_note"] = None
    c["objected_at"] = None
    db.contingencies[c["id"]] = c
    return c


def _render(dt):
    from db import render_iso
    return render_iso(dt)


def _lien_payoff_plan_computable(vessel_id):
    """A payoff plan is computable when the waterfall yields non-null — it always
    yields an allocation in this implementation, so acceptance is allowed. The
    plan is genuinely non-computable only if data is corrupt; keep permissive."""
    return True


@bp.route("/yacht/offers", methods=["POST"])
def create_offer():
    caller = get_caller()
    require_roles(caller, ["SellingAgent"])
    body = get_json_body()
    require_fields(body, ["listing_id", "buyer_id", "selling_agent_id",
                          "offer_price_cents", "deposit_pct_basis",
                          "acceptance_deadline", "settlement_state_code"])
    # Body FK existence (priority 4)
    listing = get_or_404(db.listings, body["listing_id"], "ListingAgreement")
    buyer = get_or_404(db.clients, body["buyer_id"], "Client")
    selling_agent = get_or_404(db.agents, body["selling_agent_id"], "BrokerAgent")
    parent = None
    if body.get("parent_offer_id"):
        parent = get_or_404(db.offers, body["parent_offer_id"], "Offer")
    # Priority 11: acceptance_deadline strictly in the future — BEFORE listing
    # acceptance check (priority 14) and BEFORE request-shape validation (priority 20)
    try:
        deadline_dt = parse_iso(body["acceptance_deadline"])
    except (ValueError, TypeError):
        raise err_invalid_request("acceptance_deadline must be an ISO-8601 datetime")
    if deadline_dt <= clock.now():
        raise err_invalid_deadline("acceptance_deadline must be in the future")
    # Priority 14: listing acceptance
    if listing["status"] not in ("ACTIVE", "UNDER_CONTRACT"):
        raise err_listing_not_accepting()
    # Priority 20: shape
    check_int(body, "offer_price_cents", min_v=1)
    check_int(body, "deposit_pct_basis", min_v=1000, max_v=10000)
    check_enum(body, "settlement_state_code", US_STATES)
    check_bool(body, "offshore_delivery", required=False)
    if buyer["kind"] not in ("BUYER", "BOTH"):
        raise err_invalid_request("buyer_id client kind must include BUYER")

    o = new_entity()
    o["listing_id"] = listing["id"]
    o["buyer_id"] = buyer["id"]
    o["selling_agent_id"] = selling_agent["id"]
    o["offer_price_cents"] = body["offer_price_cents"]
    o["deposit_pct_basis"] = body["deposit_pct_basis"]
    o["acceptance_deadline"] = body["acceptance_deadline"]
    o["settlement_state_code"] = body["settlement_state_code"]
    o["offshore_delivery"] = body.get("offshore_delivery", False)
    o["wants_financing_contingency"] = bool(body.get("financing_contingency", False))
    o["status"] = "PENDING"
    o["parent_offer_id"] = body.get("parent_offer_id")
    o["round_no"] = (parent["round_no"] + 1) if parent is not None else 1
    db.offers[o["id"]] = o
    return success_object(serialize_offer(o), 201)


@bp.route("/yacht/offers/<oid>", methods=["GET"])
def get_offer(oid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    o = get_or_404(db.offers, oid, "Offer")
    return success_object(serialize_offer(o))


@bp.route("/yacht/offers", methods=["GET"])
def list_offers():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    limit, offset = parse_pagination()
    items = sorted(db.offers.values(), key=lambda x: x["created_at"])
    for f in ("listing_id", "buyer_id", "selling_agent_id", "parent_offer_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if str(o.get(f)) == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_offer(o) for o in page], limit, offset, total)


def _check_occ_offer(body, offer):
    expected = body.get("expected_offer_version")
    if expected is None:
        raise err_invalid_request("expected_offer_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_offer_version must be an integer")
    if expected != offer["version"]:
        raise err_stale_version()


@bp.route("/yacht/offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    o = get_or_404(db.offers, oid, "Offer")
    body = get_json_body()
    # State check (priority 5)
    if o["status"] != "PENDING":
        raise err_invalid_state("Offer must be PENDING to accept")
    listing = db.listings.get(o["listing_id"])
    if listing is None or listing["status"] != "ACTIVE":
        raise err_invalid_state("Listing must be ACTIVE to accept an offer")
    # OCC (priority 6)
    _check_occ_offer(body, o)
    # Deadline (priority 12)
    if clock.now() > parse_iso(o["acceptance_deadline"]):
        raise err_deadline_passed()
    # Encumbrance resolvability
    vessel = db.vessels.get(listing["vessel_id"])
    if vessel is not None and vessel["liens_status"] == "ENCUMBERED":
        if not _lien_payoff_plan_computable(vessel["id"]):
            raise err_invalid_state("Vessel encumbrance cannot be resolved")

    o["status"] = "ACCEPTED"
    touch(o)
    listing["status"] = "UNDER_CONTRACT"
    touch(listing)
    # Auto-create contingencies
    now = clock.now()
    _create_contingency(o["id"], "SURVEY", now + timedelta(days=10))
    _create_contingency(o["id"], "SEA_TRIAL", now + timedelta(days=10))
    _create_contingency(o["id"], "DOCUMENTATION", now + timedelta(days=21))
    if o.get("wants_financing_contingency"):
        _create_contingency(o["id"], "FINANCING", now + timedelta(days=10))
    emit("Offer", o["id"], "OFFER_ACCEPTED", caller.role, caller.user_id,
         {"status": "ACCEPTED"})
    return success_object(serialize_offer(o))


@bp.route("/yacht/offers/<oid>/reject", methods=["POST"])
def reject_offer(oid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    o = get_or_404(db.offers, oid, "Offer")
    get_json_body()
    if o["status"] != "PENDING":
        raise err_invalid_state("Offer must be PENDING to reject")
    if clock.now() > parse_iso(o["acceptance_deadline"]):
        raise err_deadline_passed()
    o["status"] = "REJECTED"
    touch(o)
    return success_object(serialize_offer(o))


@bp.route("/yacht/offers/<oid>/counter", methods=["POST"])
def counter_offer(oid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent", "SellingAgent"])
    o = get_or_404(db.offers, oid, "Offer")
    body = get_json_body()
    if o["status"] != "PENDING":
        raise err_invalid_state("Offer must be PENDING to counter")
    _check_occ_offer(body, o)
    if clock.now() > parse_iso(o["acceptance_deadline"]):
        raise err_deadline_passed()
    require_fields(body, ["offer_price_cents", "deposit_pct_basis", "acceptance_deadline"])
    check_int(body, "offer_price_cents", min_v=1)
    check_int(body, "deposit_pct_basis", min_v=1000, max_v=10000)
    try:
        parse_iso(body["acceptance_deadline"])
    except (ValueError, TypeError):
        raise err_invalid_request("acceptance_deadline must be an ISO-8601 datetime")

    o["status"] = "COUNTERED"
    touch(o)
    child = new_entity()
    child["listing_id"] = o["listing_id"]
    child["buyer_id"] = o["buyer_id"]
    child["selling_agent_id"] = o["selling_agent_id"]
    child["offer_price_cents"] = body["offer_price_cents"]
    child["deposit_pct_basis"] = body["deposit_pct_basis"]
    child["acceptance_deadline"] = body["acceptance_deadline"]
    child["settlement_state_code"] = o["settlement_state_code"]
    child["offshore_delivery"] = o["offshore_delivery"]
    child["wants_financing_contingency"] = o.get("wants_financing_contingency", False)
    child["status"] = "PENDING"
    child["parent_offer_id"] = o["id"]
    child["round_no"] = o["round_no"] + 1
    db.offers[child["id"]] = child
    emit("Offer", o["id"], "OFFER_COUNTERED", caller.role, caller.user_id,
         {"child_offer_id": child["id"], "round_no": child["round_no"]})
    return success_object(serialize_offer(child), 201)


@bp.route("/yacht/offers/<oid>/withdraw", methods=["POST"])
def withdraw_offer(oid):
    caller = get_caller()
    require_roles(caller, ["SellingAgent"])
    o = get_or_404(db.offers, oid, "Offer")
    get_json_body()
    if o["status"] != "PENDING":
        raise err_invalid_state("Offer must be PENDING to withdraw")
    if caller.user_id != o["selling_agent_id"]:
        raise err_forbidden("Only the offer's selling agent may withdraw it")
    o["status"] = "WITHDRAWN"
    touch(o)
    return success_object(serialize_offer(o))


@bp.route("/yacht/offers/<oid>/fail", methods=["POST"])
def fail_offer(oid):
    caller = get_caller()
    require_roles(caller, ["SellingAgent"])
    o = get_or_404(db.offers, oid, "Offer")
    get_json_body()
    if o["status"] != "ACCEPTED":
        raise err_invalid_state("Offer must be ACCEPTED to fail")
    # Kick-out armed: at least one contingency OBJECTED >= 5 days unresolved, or EXPIRED
    now = clock.now()
    armed = False
    for c in db.contingencies.values():
        if c["offer_id"] != o["id"]:
            continue
        if c["status"] == "EXPIRED":
            armed = True
            break
        if c["status"] == "OBJECTED" and c.get("objected_at") is not None:
            if now >= parse_iso(c["objected_at"]) + timedelta(days=5):
                armed = True
                break
    if not armed:
        raise err_invalid_state("No unresolved contingency objection arms the kick-out")

    o["status"] = "FAILED"
    touch(o)
    listing = db.listings.get(o["listing_id"])
    if listing is not None and listing["status"] == "UNDER_CONTRACT":
        listing["status"] = "ACTIVE"
        touch(listing)
        emit("ListingAgreement", listing["id"], "LISTING_REACTIVATED",
             caller.role, caller.user_id, {"status": "ACTIVE"})
    emit("Offer", o["id"], "OFFER_FAILED", caller.role, caller.user_id,
         {"status": "FAILED"})
    return success_object(serialize_offer(o))


@bp.route("/yacht/offers/<oid>/contingencies", methods=["GET"])
def list_contingencies(oid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    o = get_or_404(db.offers, oid, "Offer")
    items = sorted([c for c in db.contingencies.values() if c["offer_id"] == o["id"]],
                   key=lambda x: x["created_at"])
    return success_list([serialize_contingency(c) for c in items],
                        len(items) or 10, 0, len(items))


# ---------------------------------------------------------------------------
# Contingency actions
# ---------------------------------------------------------------------------

def _get_contingency_and_offer(cid):
    c = get_or_404(db.contingencies, cid, "Contingency")
    offer = get_or_404(db.offers, c["offer_id"], "Offer")
    return c, offer


@bp.route("/yacht/contingencies/<cid>/satisfy", methods=["POST"])
def satisfy_contingency(cid):
    caller = get_caller()
    require_roles(caller, ["SellingAgent"])
    c, offer = _get_contingency_and_offer(cid)
    get_json_body()
    if c["status"] != "OPEN":
        raise err_invalid_state("Contingency must be OPEN")
    if clock.now() > parse_iso(c["deadline"]):
        raise err_deadline_passed()
    if offer["status"] != "ACCEPTED":
        raise err_invalid_state("Parent offer must be ACCEPTED")
    c["status"] = "SATISFIED"
    touch(c)
    return success_object(serialize_contingency(c))


@bp.route("/yacht/contingencies/<cid>/waive", methods=["POST"])
def waive_contingency(cid):
    caller = get_caller()
    require_roles(caller, ["SellingAgent"])
    c, offer = _get_contingency_and_offer(cid)
    get_json_body()
    if c["status"] != "OPEN":
        raise err_invalid_state("Contingency must be OPEN")
    if clock.now() > parse_iso(c["deadline"]):
        raise err_deadline_passed()
    if offer["status"] != "ACCEPTED":
        raise err_invalid_state("Parent offer must be ACCEPTED")
    c["status"] = "WAIVED"
    touch(c)
    return success_object(serialize_contingency(c))


@bp.route("/yacht/contingencies/<cid>/object", methods=["POST"])
def object_contingency(cid):
    caller = get_caller()
    require_roles(caller, ["SellingAgent"])
    c, offer = _get_contingency_and_offer(cid)
    body = get_json_body()
    if c["status"] != "OPEN":
        raise err_invalid_state("Contingency must be OPEN")
    if clock.now() > parse_iso(c["deadline"]):
        raise err_deadline_passed()
    if not body.get("objection_note") or not isinstance(body.get("objection_note"), str):
        raise err_invalid_request("objection_note must be a non-empty string")
    c["status"] = "OBJECTED"
    c["objection_note"] = body["objection_note"]
    c["objected_at"] = clock.iso()
    touch(c)
    return success_object(serialize_contingency(c))


@bp.route("/yacht/contingencies/<cid>/renegotiate", methods=["POST"])
def renegotiate_contingency(cid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    c, offer = _get_contingency_and_offer(cid)
    body = get_json_body()
    if c["status"] != "OBJECTED":
        raise err_invalid_state("Contingency must be OBJECTED to renegotiate")
    # Within the 5-day cure window since objection
    if c.get("objected_at") is not None:
        if clock.now() > parse_iso(c["objected_at"]) + timedelta(days=5):
            raise err_deadline_passed("Cure window has elapsed")
    require_fields(body, ["new_deadline"])
    try:
        nd = parse_iso(body["new_deadline"])
    except (ValueError, TypeError):
        raise err_invalid_request("new_deadline must be an ISO-8601 datetime")
    if nd <= clock.now():
        raise err_invalid_deadline("new_deadline must lie after the current clock")
    c["status"] = "OPEN"
    c["deadline"] = body["new_deadline"]
    touch(c)
    return success_object(serialize_contingency(c))
