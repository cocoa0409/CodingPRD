"""Business Brokerage & Main-Street M&A API (task_1047).

Python + Flask, in-memory only. Store starts empty on every boot.
"""
import os
from datetime import datetime, timezone, timedelta

from flask import Flask, request

import store
import serialize
import calc
from store import (brokers, sellers, buyers, listings, cims, ndas, documents,
                   meetings, deals, lois, loans, escrows, new_record, touch)
from envelope import ok, created, ok_list, error_body
from errors import *  # noqa: F401,F403

app = Flask(__name__)

VALID_ROLES = {"PlatformAdmin", "Broker", "Seller", "Buyer", "Lender", "EscrowAgent"}
ALL_ROLES = VALID_ROLES
MEETING_BUFFER = timedelta(minutes=30)


# ----------------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_body(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def _handle_404(_):
    return error_body(ERR_VALIDATION, "Not found", 404)


@app.errorhandler(405)
def _handle_405(_):
    return error_body(ERR_VALIDATION, "Method not allowed", 405)


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return _handle_api_error(err)
    return error_body(ERR_VALIDATION, "Internal error: %s" % err, 500)


# ----------------------------------------------------------------------------
# Auth / request helpers
# ----------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403, "Role %s not permitted" % role)


def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError(ERR_VALIDATION, 400, "Body must be a JSON object")
    return b


def req_int(body, key):
    if key not in body or body[key] is None:
        raise ApiError(ERR_VALIDATION, 400, "Missing field %s" % key)
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, "Field %s must be an integer" % key)
    return v


def opt_int(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, "Field %s must be an integer" % key)
    return v


def req_num(body, key):
    if key not in body or body[key] is None:
        raise ApiError(ERR_VALIDATION, 400, "Missing field %s" % key)
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_VALIDATION, 400, "Field %s must be a number" % key)
    return v


def req_str(body, key):
    if key not in body or body[key] is None:
        raise ApiError(ERR_VALIDATION, 400, "Missing field %s" % key)
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_VALIDATION, 400, "Field %s must be a non-empty string" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, "Field %s must be a string" % key)
    return v


def req_bool(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, "Field %s must be a boolean" % key)
    return v


def parse_dt(value):
    if not isinstance(value, str) or not value:
        raise ApiError(ERR_VALIDATION, 400, "Invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, "Invalid datetime: %s" % value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def get_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit out of range")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "offset out of range")
    return limit, offset


def list_response(records, serializer):
    limit, offset = get_pagination()
    records = sorted(records, key=lambda r: r["_seq"])
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def get_or_404(coll, id_, err):
    rec = coll.get(id_)
    if rec is None:
        raise ApiError(err, 404, "%s not found" % id_)
    return rec


# ----------------------------------------------------------------------------
# Domain helpers
# ----------------------------------------------------------------------------
def buyer_of_loi(loi_rec):
    deal_rec = deals[loi_rec["deal_id"]]
    return buyers.get(deal_rec["buyer_id"])


def release_loi(loi_rec, new_status):
    """Drive an LOI to a terminal status and release its earnest from the buyer."""
    loi_rec["status"] = new_status
    touch(loi_rec)
    b = buyer_of_loi(loi_rec)
    if b is not None:
        b["committed_capital_cents"] -= loi_rec["earnest_deposit_cents"]
        touch(b)


def escrows_of_deal(deal_id):
    return [e for e in escrows.values() if e["deal_id"] == deal_id]


def loans_of_deal(deal_id):
    return [l for l in loans.values() if l["deal_id"] == deal_id]


def lois_of_deal(deal_id):
    return [l for l in lois.values() if l["deal_id"] == deal_id]


def accept_loi_cascade(loi_rec, deal_rec, listing_rec):
    # LOI -> ACCEPTED
    loi_rec["status"] = "ACCEPTED"
    touch(loi_rec)
    # Deal QUALIFIED -> UNDER_LOI with winning-terms snapshot
    deal_rec["status"] = "UNDER_LOI"
    deal_rec["accepted_loi_id"] = loi_rec["id"]
    deal_rec["accepted_price_cents"] = loi_rec["offer_price_cents"]
    deal_rec["earnout_total_cents"] = loi_rec["earnout_amount_cents"]
    deal_rec["earnout_periods"] = loi_rec["earnout_periods"]
    deal_rec["earnout_baseline_sde_cents"] = listing_rec["annual_sde_cents"]
    deal_rec["provisional_commission_cents"] = calc.broker_commission(loi_rec["offer_price_cents"])
    touch(deal_rec)
    # Listing ACTIVE -> UNDER_LOI
    listing_rec["status"] = "UNDER_LOI"
    touch(listing_rec)
    # Sibling cascade: every OTHER deal on this listing in PROSPECT/QUALIFIED -> WITHDRAWN
    for d in list(deals.values()):
        if d["id"] == deal_rec["id"]:
            continue
        if d["listing_id"] != listing_rec["id"]:
            continue
        if d["status"] in ("PROSPECT", "QUALIFIED"):
            for l in lois_of_deal(d["id"]):
                if l["status"] in ("SUBMITTED", "COUNTERED", "ACCEPTED"):
                    release_loi(l, "WITHDRAWN")
            d["status"] = "WITHDRAWN"
            touch(d)


def withdraw_deal_cascade(deal_rec):
    st = deal_rec["status"]
    if st in ("CLOSED", "WITHDRAWN"):
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Deal cannot be withdrawn from %s" % st)
    listing_rec = listings.get(deal_rec["listing_id"])

    if st == "PROSPECT":
        pass
    elif st == "QUALIFIED":
        for l in lois_of_deal(deal_rec["id"]):
            if l["status"] in ("SUBMITTED", "COUNTERED"):
                release_loi(l, "WITHDRAWN")
    elif st in ("UNDER_LOI", "DUE_DILIGENCE", "FINANCING"):
        for l in lois_of_deal(deal_rec["id"]):
            if l["status"] in ("SUBMITTED", "COUNTERED", "ACCEPTED"):
                release_loi(l, "WITHDRAWN")
        if listing_rec is not None and listing_rec["status"] == "UNDER_LOI":
            listing_rec["status"] = "ACTIVE"
            touch(listing_rec)
    elif st == "IN_ESCROW":
        deal_escrows = escrows_of_deal(deal_rec["id"])
        for esc in deal_escrows:
            if esc["status"] == "CLOSED":
                raise ApiError(ERR_ESCROW_ALREADY_CLOSED, 409, "Escrow already closed")
        b = buyers.get(deal_rec["buyer_id"])
        for esc in deal_escrows:
            if esc["status"] in ("OPENED", "FUNDED"):
                if b is not None and esc["balance_cents"]:
                    b["escrowed_cents"] -= esc["balance_cents"]
                    touch(b)
                esc["balance_cents"] = 0
                esc["status"] = "CANCELLED"
                touch(esc)
        for l in lois_of_deal(deal_rec["id"]):
            if l["status"] in ("SUBMITTED", "COUNTERED", "ACCEPTED"):
                release_loi(l, "WITHDRAWN")
        if listing_rec is not None and listing_rec["status"] == "IN_ESCROW":
            listing_rec["status"] = "ACTIVE"
            touch(listing_rec)

    deal_rec["status"] = "WITHDRAWN"
    touch(deal_rec)


def close_escrow_cascade(esc):
    esc["status"] = "CLOSED"
    touch(esc)
    deal_rec = deals[esc["deal_id"]]
    final = calc.broker_commission(esc["closing_price_cents"])
    deal_rec["final_commission_cents"] = final
    deal_rec["seller_net_proceeds_cents"] = calc.seller_net_proceeds(
        esc["closing_price_cents"], final, deal_rec["earnout_total_cents"])
    deal_rec["status"] = "CLOSED"
    touch(deal_rec)
    broker_rec = brokers.get(deal_rec["broker_id"])
    if broker_rec is not None:
        broker_rec["accrued_commission_cents"] += final
        touch(broker_rec)
    listing_rec = listings.get(deal_rec["listing_id"])
    if listing_rec is not None:
        listing_rec["status"] = "SOLD"
        touch(listing_rec)


# ============================================================================
# ACTORS
# ============================================================================
@app.route("/brokerage/brokers", methods=["POST"])
def create_broker():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    rec = new_record({
        "firm_name": req_str(body, "firm_name"),
        "license_number": req_str(body, "license_number"),
        "accrued_commission_cents": 0,
    })
    brokers[rec["id"]] = rec
    return created(serialize.broker(rec))


@app.route("/brokerage/sellers", methods=["POST"])
def create_seller():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    rec = new_record({
        "full_name": req_str(body, "full_name"),
        "email": req_str(body, "email"),
    })
    sellers[rec["id"]] = rec
    return created(serialize.seller(rec))


@app.route("/brokerage/buyers", methods=["POST"])
def create_buyer():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    rec = new_record({
        "full_name": req_str(body, "full_name"),
        "email": req_str(body, "email"),
        "proof_of_funds_cents": req_int(body, "proof_of_funds_cents"),
        "net_worth_cents": req_int(body, "net_worth_cents"),
        "committed_capital_cents": 0,
        "escrowed_cents": 0,
    })
    buyers[rec["id"]] = rec
    return created(serialize.buyer(rec))


@app.route("/brokerage/brokers/<id_>", methods=["GET"])
def get_broker(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(brokers, id_, ERR_BROKER_NOT_FOUND)
    return ok(serialize.broker(rec))


@app.route("/brokerage/buyers/<id_>", methods=["GET"])
def get_buyer(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(buyers, id_, ERR_BUYER_NOT_FOUND)
    return ok(serialize.buyer(rec))


# ============================================================================
# LISTING
# ============================================================================
@app.route("/brokerage/listings", methods=["POST"])
def create_listing():
    uid, role = authenticate()
    authorize(role, {"Broker"})
    body = get_body()
    seller_id = req_str(body, "seller_id")
    business_name = req_str(body, "business_name")
    industry_code = req_str(body, "industry_code")
    annual_sde_cents = req_int(body, "annual_sde_cents")
    annual_revenue_cents = req_int(body, "annual_revenue_cents")
    ffe_value_cents = req_int(body, "ffe_value_cents")
    inventory_value_cents = req_int(body, "inventory_value_cents")
    industry_multiple = req_num(body, "industry_multiple")
    asking_price_cents = req_int(body, "asking_price_cents")
    start_raw = req_str(body, "exclusive_start_date")
    end_raw = req_str(body, "exclusive_end_date")
    # existence of referenced seller (404)
    get_or_404(sellers, seller_id, ERR_SELLER_NOT_FOUND)
    # interval validity (constraint)
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if not (end_dt > start_dt):
        raise ApiError(ERR_INVALID_INTERVAL, 409, "exclusive_end_date must be after start")
    # exclusivity overlap per seller (temporal), half-open [start, end)
    for other in listings.values():
        if other["seller_id"] != seller_id or other["status"] == "WITHDRAWN":
            continue
        o_start = parse_dt(other["exclusive_start_date"])
        o_end = parse_dt(other["exclusive_end_date"])
        if start_dt < o_end and o_start < end_dt:
            raise ApiError(ERR_LISTING_PERIOD_OVERLAP, 409, "Exclusive window overlaps")
    rec = new_record({
        "broker_id": uid,
        "seller_id": seller_id,
        "business_name": business_name,
        "industry_code": industry_code,
        "annual_sde_cents": annual_sde_cents,
        "annual_revenue_cents": annual_revenue_cents,
        "ffe_value_cents": ffe_value_cents,
        "inventory_value_cents": inventory_value_cents,
        "industry_multiple": industry_multiple,
        "asking_price_cents": asking_price_cents,
        "exclusive_start_date": start_raw,
        "exclusive_end_date": end_raw,
        "status": "DRAFT",
    })
    listings[rec["id"]] = rec
    return created(serialize.listing(rec))


@app.route("/brokerage/listings", methods=["GET"])
def list_listings():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    broker_id = request.args.get("broker_id")
    seller_id = request.args.get("seller_id")
    status = request.args.get("status")
    recs = []
    for r in listings.values():
        if broker_id is not None and r["broker_id"] != broker_id:
            continue
        if seller_id is not None and r["seller_id"] != seller_id:
            continue
        if status is not None and r["status"] != status:
            continue
        recs.append(r)
    return list_response(recs, serialize.listing)


@app.route("/brokerage/listings/<id_>", methods=["GET"])
def get_listing(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    return ok(serialize.listing(rec))


@app.route("/brokerage/listings/<id_>/activate", methods=["POST"])
def activate_listing(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    if rec["broker_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Broker does not own listing")
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Listing not in DRAFT")
    has_published = any(c["listing_id"] == id_ and c["status"] == "PUBLISHED"
                        for c in cims.values())
    if not has_published:
        raise ApiError(ERR_CIM_NOT_PUBLISHED, 409, "Listing requires a PUBLISHED CIM")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(serialize.listing(rec))


@app.route("/brokerage/listings/<id_>/withdraw", methods=["POST"])
def withdraw_listing(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    if rec["broker_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Broker does not own listing")
    if rec["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Listing cannot be withdrawn from %s" % rec["status"])
    if rec["status"] == "ACTIVE":
        if any(d["listing_id"] == id_ and d["status"] == "IN_ESCROW" for d in deals.values()):
            raise ApiError(ERR_LISTING_HAS_ACTIVE_ESCROW, 409, "Listing has a deal in escrow")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok(serialize.listing(rec))


# ============================================================================
# CIM
# ============================================================================
@app.route("/brokerage/listings/<id_>/cims", methods=["POST"])
def create_cim(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    listing_rec = get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    if listing_rec["broker_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Broker does not own listing")
    body = get_body()
    method = req_str(body, "valuation_method")
    if method not in ("SDE_MULTIPLE", "ASSET_BASED"):
        raise ApiError(ERR_VALIDATION, 400, "Invalid valuation_method")
    rec = new_record({
        "listing_id": id_,
        "valuation_method": method,
        "recommended_price_cents": None,
        "status": "DRAFT",
    })
    cims[rec["id"]] = rec
    return created(serialize.cim(rec))


@app.route("/brokerage/listings/<id_>/cims", methods=["GET"])
def list_cims(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    recs = [c for c in cims.values() if c["listing_id"] == id_]
    return list_response(recs, serialize.cim)


@app.route("/brokerage/cims/<id_>/publish", methods=["POST"])
def publish_cim(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(cims, id_, ERR_CIM_NOT_FOUND)
    listing_rec = listings.get(rec["listing_id"])
    if listing_rec is not None and listing_rec["broker_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Broker does not own listing")
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_CIM_INVALID_STATE, 409, "CIM not in DRAFT")
    rec["recommended_price_cents"] = calc.cim_recommended_price(listing_rec, rec["valuation_method"])
    rec["status"] = "PUBLISHED"
    touch(rec)
    return ok(serialize.cim(rec))


# ============================================================================
# NDA
# ============================================================================
@app.route("/brokerage/listings/<id_>/ndas", methods=["POST"])
def sign_nda(id_):
    uid, role = authenticate()
    authorize(role, {"Buyer"})
    listing_rec = get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    if listing_rec["status"] != "ACTIVE":
        raise ApiError(ERR_LISTING_NOT_ACTIVE, 409, "Listing not ACTIVE")
    rec = new_record({
        "listing_id": id_,
        "buyer_id": uid,
        "status": "SIGNED",
    })
    ndas[rec["id"]] = rec
    return created(serialize.nda(rec))


@app.route("/brokerage/listings/<id_>/ndas", methods=["GET"])
def list_listing_ndas(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    buyer_id = request.args.get("buyer_id")
    recs = [n for n in ndas.values() if n["listing_id"] == id_
            and (buyer_id is None or n["buyer_id"] == buyer_id)]
    return list_response(recs, serialize.nda)


@app.route("/brokerage/buyers/<id_>/ndas", methods=["GET"])
def list_buyer_ndas(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(buyers, id_, ERR_BUYER_NOT_FOUND)
    recs = [n for n in ndas.values() if n["buyer_id"] == id_]
    return list_response(recs, serialize.nda)


def buyer_has_signed_nda(listing_id, buyer_id):
    return any(n["listing_id"] == listing_id and n["buyer_id"] == buyer_id
               and n["status"] == "SIGNED" for n in ndas.values())


# ============================================================================
# DATA ROOM DOCUMENTS
# ============================================================================
@app.route("/brokerage/listings/<id_>/documents", methods=["POST"])
def upload_document(id_):
    uid, role = authenticate()
    authorize(role, {"Broker", "Seller"})
    listing_rec = get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    if role == "Broker" and listing_rec["broker_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Broker does not own listing")
    if role == "Seller" and listing_rec["seller_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Seller does not own listing")
    body = get_body()
    title = req_str(body, "title")
    doc_type = req_str(body, "doc_type")
    if doc_type not in ("FINANCIALS", "LEASE", "TAX_RETURN", "LICENSES", "OTHER"):
        raise ApiError(ERR_VALIDATION, 400, "Invalid doc_type")
    rec = new_record({
        "listing_id": id_,
        "title": title,
        "doc_type": doc_type,
    })
    documents[rec["id"]] = rec
    return created(serialize.document(rec))


@app.route("/brokerage/listings/<id_>/documents", methods=["GET"])
def list_documents(id_):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    if role == "Buyer" and not buyer_has_signed_nda(id_, uid):
        raise ApiError(ERR_NDA_REQUIRED, 409, "Buyer needs a SIGNED NDA")
    recs = [d for d in documents.values() if d["listing_id"] == id_]
    return list_response(recs, serialize.document)


# ============================================================================
# MANAGEMENT MEETINGS
# ============================================================================
@app.route("/brokerage/listings/<id_>/meetings", methods=["POST"])
def schedule_meeting(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    listing_rec = get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    body = get_body()
    buyer_id = req_str(body, "buyer_id")
    start_raw = req_str(body, "start_at")
    end_raw = req_str(body, "end_at")
    get_or_404(buyers, buyer_id, ERR_BUYER_NOT_FOUND)
    if listing_rec["broker_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Broker does not own listing")
    # referential: buyer must hold a SIGNED NDA
    if not buyer_has_signed_nda(id_, buyer_id):
        raise ApiError(ERR_NDA_REQUIRED, 409, "Buyer needs a SIGNED NDA")
    # constraint: interval order
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if not (end_dt > start_dt):
        raise ApiError(ERR_INVALID_INTERVAL, 409, "end_at must be after start_at")
    # temporal: buffer separation from other SCHEDULED meetings on same listing
    for other in meetings.values():
        if other["listing_id"] != id_ or other["status"] != "SCHEDULED":
            continue
        o_start = parse_dt(other["start_at"])
        o_end = parse_dt(other["end_at"])
        if start_dt > o_end:
            gap = start_dt - o_end
        elif o_start > end_dt:
            gap = o_start - end_dt
        else:
            gap = timedelta(0)  # overlapping intervals
        if gap < MEETING_BUFFER:
            raise ApiError(ERR_MEETING_SLOT_CONFLICT, 409, "Meeting within buffer of another")
    rec = new_record({
        "listing_id": id_,
        "buyer_id": buyer_id,
        "start_at": start_raw,
        "end_at": end_raw,
        "status": "SCHEDULED",
    })
    meetings[rec["id"]] = rec
    return created(serialize.meeting(rec))


@app.route("/brokerage/listings/<id_>/meetings", methods=["GET"])
def list_listing_meetings(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(listings, id_, ERR_LISTING_NOT_FOUND)
    buyer_id = request.args.get("buyer_id")
    recs = [m for m in meetings.values() if m["listing_id"] == id_
            and (buyer_id is None or m["buyer_id"] == buyer_id)]
    return list_response(recs, serialize.meeting)


@app.route("/brokerage/buyers/<id_>/meetings", methods=["GET"])
def list_buyer_meetings(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(buyers, id_, ERR_BUYER_NOT_FOUND)
    recs = [m for m in meetings.values() if m["buyer_id"] == id_]
    return list_response(recs, serialize.meeting)


# ============================================================================
# DEAL
# ============================================================================
@app.route("/brokerage/deals", methods=["POST"])
def create_deal():
    uid, role = authenticate()
    authorize(role, {"Broker"})
    body = get_body()
    listing_id = req_str(body, "listing_id")
    buyer_id = req_str(body, "buyer_id")
    get_or_404(listings, listing_id, ERR_LISTING_NOT_FOUND)
    get_or_404(buyers, buyer_id, ERR_BUYER_NOT_FOUND)
    rec = new_record({
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "broker_id": uid,
        "status": "PROSPECT",
        "accepted_loi_id": None,
        "accepted_price_cents": None,
        "earnout_total_cents": 0,
        "earnout_periods": 0,
        "earnout_baseline_sde_cents": 0,
        "earnout_paid_cents": 0,
        "provisional_commission_cents": None,
        "final_commission_cents": None,
        "seller_net_proceeds_cents": None,
    })
    deals[rec["id"]] = rec
    return created(serialize.deal(rec))


@app.route("/brokerage/deals", methods=["GET"])
def list_deals():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    listing_id = request.args.get("listing_id")
    buyer_id = request.args.get("buyer_id")
    broker_id = request.args.get("broker_id")
    status = request.args.get("status")
    recs = []
    for r in deals.values():
        if listing_id is not None and r["listing_id"] != listing_id:
            continue
        if buyer_id is not None and r["buyer_id"] != buyer_id:
            continue
        if broker_id is not None and r["broker_id"] != broker_id:
            continue
        if status is not None and r["status"] != status:
            continue
        recs.append(r)
    return list_response(recs, serialize.deal)


@app.route("/brokerage/deals/<id_>", methods=["GET"])
def get_deal(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    return ok(serialize.deal(rec))


def _own_deal(rec, uid):
    if rec["broker_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Broker does not own deal")


@app.route("/brokerage/deals/<id_>/qualify", methods=["POST"])
def qualify_deal(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    _own_deal(rec, uid)
    if rec["status"] != "PROSPECT":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Deal not in PROSPECT")
    listing_rec = listings[rec["listing_id"]]
    buyer_rec = buyers[rec["buyer_id"]]
    # referential: SIGNED NDA
    if not buyer_has_signed_nda(rec["listing_id"], rec["buyer_id"]):
        raise ApiError(ERR_NDA_REQUIRED, 409, "Buyer needs a SIGNED NDA")
    # fiscal: proof-of-funds vs required down payment
    required_down = calc.required_down_payment(listing_rec["asking_price_cents"])
    if buyer_rec["proof_of_funds_cents"] < required_down:
        raise ApiError(ERR_INSUFFICIENT_FUNDS, 402, "Proof of funds below required down payment")
    # fiscal: capacity vs asking price
    capacity = calc.qualification_capacity(buyer_rec["proof_of_funds_cents"], buyer_rec["net_worth_cents"])
    if capacity < listing_rec["asking_price_cents"]:
        raise ApiError(ERR_INSUFFICIENT_FUNDS, 402, "Qualification capacity below asking price")
    rec["status"] = "QUALIFIED"
    touch(rec)
    return ok(serialize.deal(rec))


@app.route("/brokerage/deals/<id_>/open-diligence", methods=["POST"])
def open_diligence(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    _own_deal(rec, uid)
    if rec["status"] != "UNDER_LOI":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Deal not in UNDER_LOI")
    has_doc = any(d["listing_id"] == rec["listing_id"] for d in documents.values())
    if not has_doc:
        raise ApiError(ERR_DATA_ROOM_EMPTY, 409, "Data room is empty")
    rec["status"] = "DUE_DILIGENCE"
    touch(rec)
    return ok(serialize.deal(rec))


@app.route("/brokerage/deals/<id_>/enter-financing", methods=["POST"])
def enter_financing(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    _own_deal(rec, uid)
    if rec["status"] != "DUE_DILIGENCE":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Deal not in DUE_DILIGENCE")
    rec["status"] = "FINANCING"
    touch(rec)
    return ok(serialize.deal(rec))


@app.route("/brokerage/deals/<id_>/withdraw", methods=["POST"])
def withdraw_deal(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    _own_deal(rec, uid)
    get_body()  # optional reason, tolerated
    withdraw_deal_cascade(rec)
    return ok(serialize.deal(rec))


@app.route("/brokerage/deals/<id_>/record-earnout-period", methods=["POST"])
def record_earnout_period(id_):
    uid, role = authenticate()
    authorize(role, {"Broker"})
    rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    _own_deal(rec, uid)
    body = get_body()
    actual_sde_cents = req_int(body, "actual_sde_cents")
    if rec["status"] != "CLOSED":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Deal not CLOSED")
    payment = calc.earnout_period_payment(
        actual_sde_cents, rec["earnout_baseline_sde_cents"],
        rec["earnout_total_cents"], rec["earnout_periods"])
    rec["earnout_paid_cents"] += payment
    touch(rec)
    return ok(serialize.deal(rec))


# ============================================================================
# LOI
# ============================================================================
@app.route("/brokerage/deals/<id_>/lois", methods=["POST"])
def submit_loi(id_):
    uid, role = authenticate()
    authorize(role, {"Buyer"})
    deal_rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    if deal_rec["buyer_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Buyer does not own deal")
    body = get_body()
    offer_price_cents = req_int(body, "offer_price_cents")
    earnest_deposit_cents = req_int(body, "earnest_deposit_cents")
    earnout_amount_cents = req_int(body, "earnout_amount_cents")
    earnout_periods = req_int(body, "earnout_periods")
    if earnout_periods < 1:
        raise ApiError(ERR_VALIDATION, 400, "earnout_periods must be >= 1")
    financing_contingency = req_bool(body, "financing_contingency", True)
    expected_deal_version = req_int(body, "expected_deal_version")
    # state
    if deal_rec["status"] != "QUALIFIED":
        raise ApiError(ERR_DEAL_NOT_QUALIFIED, 409, "Deal not QUALIFIED")
    # OCC
    if expected_deal_version != deal_rec["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale deal version")
    # fiscal
    buyer_rec = buyers[deal_rec["buyer_id"]]
    available = (buyer_rec["proof_of_funds_cents"] - buyer_rec["committed_capital_cents"]
                 - buyer_rec["escrowed_cents"])
    if available < earnest_deposit_cents:
        raise ApiError(ERR_INSUFFICIENT_FUNDS, 402, "Available capital below earnest deposit")
    # supersede any existing non-terminal LOI on this deal
    for l in lois_of_deal(id_):
        if l["status"] in ("SUBMITTED", "COUNTERED", "ACCEPTED"):
            release_loi(l, "WITHDRAWN")
    rec = new_record({
        "deal_id": id_,
        "offer_price_cents": offer_price_cents,
        "earnest_deposit_cents": earnest_deposit_cents,
        "earnout_amount_cents": earnout_amount_cents,
        "earnout_periods": earnout_periods,
        "financing_contingency": financing_contingency,
        "counter_price_cents": None,
        "round_number": 1,
        "status": "SUBMITTED",
    })
    lois[rec["id"]] = rec
    buyer_rec["committed_capital_cents"] += earnest_deposit_cents
    touch(buyer_rec)
    deal_rec["version"] += 1
    deal_rec["updated_at"] = store.now_iso()
    return created(serialize.loi(rec))


@app.route("/brokerage/deals/<id_>/lois", methods=["GET"])
def list_lois(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    status = request.args.get("status")
    recs = [l for l in lois.values() if l["deal_id"] == id_
            and (status is None or l["status"] == status)]
    return list_response(recs, serialize.loi)


def _seller_owns_loi(loi_rec, uid):
    deal_rec = deals[loi_rec["deal_id"]]
    listing_rec = listings.get(deal_rec["listing_id"])
    if listing_rec is None or listing_rec["seller_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Seller does not own listing behind offer")


def _buyer_owns_loi(loi_rec, uid):
    deal_rec = deals[loi_rec["deal_id"]]
    if deal_rec["buyer_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Buyer does not own offer")


@app.route("/brokerage/lois/<id_>/counter", methods=["POST"])
def counter_loi(id_):
    uid, role = authenticate()
    authorize(role, {"Seller"})
    rec = get_or_404(lois, id_, ERR_LOI_NOT_FOUND)
    _seller_owns_loi(rec, uid)
    body = get_body()
    counter_price_cents = req_int(body, "counter_price_cents")
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_LOI_INVALID_STATE, 409, "LOI not SUBMITTED")
    rec["counter_price_cents"] = counter_price_cents
    rec["round_number"] += 1
    rec["status"] = "COUNTERED"
    touch(rec)
    return ok(serialize.loi(rec))


@app.route("/brokerage/lois/<id_>/revise", methods=["POST"])
def revise_loi(id_):
    uid, role = authenticate()
    authorize(role, {"Buyer"})
    rec = get_or_404(lois, id_, ERR_LOI_NOT_FOUND)
    _buyer_owns_loi(rec, uid)
    body = get_body()
    offer_price_cents = req_int(body, "offer_price_cents")
    earnest_deposit_cents = req_int(body, "earnest_deposit_cents")
    if rec["status"] != "COUNTERED":
        raise ApiError(ERR_LOI_INVALID_STATE, 409, "LOI not COUNTERED")
    buyer_rec = buyer_of_loi(rec)
    delta = earnest_deposit_cents - rec["earnest_deposit_cents"]
    available = (buyer_rec["proof_of_funds_cents"] - buyer_rec["committed_capital_cents"]
                 - buyer_rec["escrowed_cents"])
    if available < delta:
        raise ApiError(ERR_INSUFFICIENT_FUNDS, 402, "Available capital below earnest increase")
    rec["offer_price_cents"] = offer_price_cents
    rec["earnest_deposit_cents"] = earnest_deposit_cents
    rec["counter_price_cents"] = None
    rec["round_number"] += 1
    rec["status"] = "SUBMITTED"
    touch(rec)
    buyer_rec["committed_capital_cents"] += delta
    touch(buyer_rec)
    return ok(serialize.loi(rec))


@app.route("/brokerage/lois/<id_>/accept", methods=["POST"])
def accept_loi(id_):
    uid, role = authenticate()
    authorize(role, {"Seller"})
    rec = get_or_404(lois, id_, ERR_LOI_NOT_FOUND)
    _seller_owns_loi(rec, uid)
    deal_rec = deals[rec["deal_id"]]
    listing_rec = listings[deal_rec["listing_id"]]
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_LOI_INVALID_STATE, 409, "LOI not SUBMITTED")
    if deal_rec["status"] != "QUALIFIED" or listing_rec["status"] != "ACTIVE":
        raise ApiError(ERR_LISTING_NOT_ACTIVE, 409, "Deal/listing not in acceptable state")
    accept_loi_cascade(rec, deal_rec, listing_rec)
    return ok(serialize.loi(rec))


@app.route("/brokerage/lois/<id_>/reject", methods=["POST"])
def reject_loi(id_):
    uid, role = authenticate()
    authorize(role, {"Seller"})
    rec = get_or_404(lois, id_, ERR_LOI_NOT_FOUND)
    _seller_owns_loi(rec, uid)
    if rec["status"] not in ("SUBMITTED", "COUNTERED"):
        raise ApiError(ERR_LOI_INVALID_STATE, 409, "LOI not SUBMITTED/COUNTERED")
    release_loi(rec, "REJECTED")
    return ok(serialize.loi(rec))


@app.route("/brokerage/lois/<id_>/withdraw", methods=["POST"])
def withdraw_loi(id_):
    uid, role = authenticate()
    authorize(role, {"Buyer"})
    rec = get_or_404(lois, id_, ERR_LOI_NOT_FOUND)
    _buyer_owns_loi(rec, uid)
    if rec["status"] not in ("SUBMITTED", "COUNTERED"):
        raise ApiError(ERR_LOI_INVALID_STATE, 409, "LOI not SUBMITTED/COUNTERED")
    release_loi(rec, "WITHDRAWN")
    return ok(serialize.loi(rec))


# ============================================================================
# SBA FINANCING
# ============================================================================
@app.route("/brokerage/deals/<id_>/loan-applications", methods=["POST"])
def submit_loan(id_):
    uid, role = authenticate()
    authorize(role, {"Buyer"})
    deal_rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    if deal_rec["buyer_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Buyer does not own deal")
    body = get_body()
    requested_amount_cents = req_int(body, "requested_amount_cents")
    rec = new_record({
        "deal_id": id_,
        "requested_amount_cents": requested_amount_cents,
        "approved_amount_cents": None,
        "decision_reason": None,
        "status": "SUBMITTED",
    })
    loans[rec["id"]] = rec
    return created(serialize.loan(rec))


@app.route("/brokerage/deals/<id_>/loan-applications", methods=["GET"])
def list_loans(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    status = request.args.get("status")
    recs = [l for l in loans.values() if l["deal_id"] == id_
            and (status is None or l["status"] == status)]
    return list_response(recs, serialize.loan)


@app.route("/brokerage/loan-applications/<id_>/decision", methods=["POST"])
def decide_loan(id_):
    _, role = authenticate()
    authorize(role, {"Lender"})
    rec = get_or_404(loans, id_, ERR_LOAN_NOT_FOUND)
    body = get_body()
    outcome = req_str(body, "outcome")
    if outcome not in ("APPROVED", "CONDITIONALLY_APPROVED", "DECLINED"):
        raise ApiError(ERR_VALIDATION, 400, "Invalid outcome")
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_LOAN_INVALID_STATE, 409, "Loan not SUBMITTED")
    reason = opt_str(body, "decision_reason")
    if outcome == "APPROVED":
        rec["approved_amount_cents"] = rec["requested_amount_cents"]
        rec["status"] = "APPROVED"
    elif outcome == "CONDITIONALLY_APPROVED":
        approved = opt_int(body, "approved_amount_cents")
        if approved is None:
            raise ApiError(ERR_INVALID_REQUEST, 422, "CONDITIONALLY_APPROVED requires approved_amount_cents")
        rec["approved_amount_cents"] = approved
        rec["status"] = "CONDITIONALLY_APPROVED"
    else:  # DECLINED
        rec["status"] = "DECLINED"
    if reason is not None:
        rec["decision_reason"] = reason
    touch(rec)
    return ok(serialize.loan(rec))


@app.route("/brokerage/loan-applications/<id_>/finalize-conditions", methods=["POST"])
def finalize_loan(id_):
    _, role = authenticate()
    authorize(role, {"Lender"})
    rec = get_or_404(loans, id_, ERR_LOAN_NOT_FOUND)
    body = get_body()
    outcome = req_str(body, "outcome")
    if outcome not in ("APPROVED", "DECLINED"):
        raise ApiError(ERR_VALIDATION, 400, "Invalid outcome")
    if rec["status"] != "CONDITIONALLY_APPROVED":
        raise ApiError(ERR_LOAN_INVALID_STATE, 409, "Loan not CONDITIONALLY_APPROVED")
    reason = opt_str(body, "decision_reason")
    rec["status"] = "APPROVED" if outcome == "APPROVED" else "DECLINED"
    if reason is not None:
        rec["decision_reason"] = reason
    touch(rec)
    return ok(serialize.loan(rec))


# ============================================================================
# ESCROW / CLOSING
# ============================================================================
@app.route("/brokerage/deals/<id_>/escrow", methods=["POST"])
def open_escrow(id_):
    _, role = authenticate()
    authorize(role, {"EscrowAgent"})
    deal_rec = get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    body = get_body()
    closing_price_cents = req_int(body, "closing_price_cents")
    required_deposit_cents = req_int(body, "required_deposit_cents")
    if deal_rec["status"] != "FINANCING":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "Deal not in FINANCING")
    approved = any(l["status"] == "APPROVED" for l in loans_of_deal(id_))
    if not approved:
        raise ApiError(ERR_FINANCING_NOT_APPROVED, 409, "No APPROVED loan on deal")
    rec = new_record({
        "deal_id": id_,
        "closing_price_cents": closing_price_cents,
        "required_deposit_cents": required_deposit_cents,
        "balance_cents": 0,
        "status": "OPENED",
    })
    escrows[rec["id"]] = rec
    deal_rec["status"] = "IN_ESCROW"
    touch(deal_rec)
    listing_rec = listings.get(deal_rec["listing_id"])
    if listing_rec is not None and listing_rec["status"] == "UNDER_LOI":
        listing_rec["status"] = "IN_ESCROW"
        touch(listing_rec)
    return created(serialize.escrow(rec))


@app.route("/brokerage/deals/<id_>/escrow", methods=["GET"])
def list_escrow(id_):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(deals, id_, ERR_DEAL_NOT_FOUND)
    recs = escrows_of_deal(id_)
    return list_response(recs, serialize.escrow)


@app.route("/brokerage/escrow-accounts/<id_>/deposit", methods=["POST"])
def deposit_escrow(id_):
    uid, role = authenticate()
    authorize(role, {"Buyer"})
    rec = get_or_404(escrows, id_, ERR_ESCROW_NOT_FOUND)
    deal_rec = deals[rec["deal_id"]]
    if deal_rec["buyer_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Buyer does not own deal")
    body = get_body()
    amount_cents = req_int(body, "amount_cents")
    if rec["status"] != "OPENED":
        raise ApiError(ERR_ESCROW_INVALID_STATE, 409, "Escrow not OPENED")
    if amount_cents < rec["required_deposit_cents"]:
        raise ApiError(ERR_DEPOSIT_TOO_LOW, 402, "Deposit below required")
    rec["balance_cents"] += amount_cents
    rec["status"] = "FUNDED"
    touch(rec)
    buyer_rec = buyers.get(deal_rec["buyer_id"])
    if buyer_rec is not None:
        buyer_rec["escrowed_cents"] += amount_cents
        touch(buyer_rec)
    return ok(serialize.escrow(rec))


@app.route("/brokerage/escrow-accounts/<id_>/close", methods=["POST"])
def close_escrow(id_):
    _, role = authenticate()
    authorize(role, {"EscrowAgent"})
    rec = get_or_404(escrows, id_, ERR_ESCROW_NOT_FOUND)
    if rec["status"] != "FUNDED":
        raise ApiError(ERR_ESCROW_NOT_FUNDED, 409, "Escrow not FUNDED")
    close_escrow_cascade(rec)
    return ok(serialize.escrow(rec))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
