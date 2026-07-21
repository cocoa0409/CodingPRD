"""Table holds, bidders, sponsors and program ads."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    ALL_ROLES, ApiError, authenticate, body, db, fetch, get_bool, get_dt,
    get_enum, get_int, get_str, new_row, ok, ok_list, own_check, paged,
    pagination, parse_dt, public, q, q_enum, rows, touch,
)

bp = Blueprint("people", __name__)

HOLD_STATUSES = ("HELD", "CONSUMED", "RELEASED")
SPONSOR_STATUSES = ("PENDING", "CONFIRMED", "WITHDRAWN")
AD_STATUSES = ("SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED",
               "REJECTED", "PLACED")
AD_SIZES = ("FULL_PAGE", "HALF_PAGE", "QUARTER_PAGE")
TIERS = ("GOLD", "SILVER", "BRONZE")
DECISIONS = ("BEGIN_REVIEW", "REQUEST_CHANGES", "APPROVE", "REJECT")


# ---------------------------------------------------------------- holds
@bp.post("/api/table-holds")
def create_hold():
    uid, role = authenticate(("EventOrganizer", "Bidder"))
    payload = body()
    table_id = get_str(payload, "table_id")
    bidder_id = get_str(payload, "bidder_id")
    start_raw, start = get_dt(payload, "hold_start_utc")
    end_raw, end = get_dt(payload, "hold_end_utc")
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST", "hold_end_utc must be after hold_start_utc")
    table = fetch("tables", table_id)
    fetch("bidders", bidder_id)
    if role == "Bidder":
        own_check(bidder_id == uid)
    event = fetch("events", table["event_id"])
    calc.gate(event, restricted=True)

    buffer = timedelta(minutes=15)
    for other in db.holds.values():
        if other["table_id"] != table["id"] or other["status"] != "HELD":
            continue
        o_start = parse_dt(other["hold_start_utc"])
        o_end = parse_dt(other["hold_end_utc"])
        if start < o_end + buffer and o_start < end + buffer:
            raise ApiError("ERR_TABLE_HOLD_CONFLICT", "hold conflicts with an existing hold")

    hold = new_row(table_id=table["id"], bidder_id=bidder_id,
                   hold_start_utc=start_raw, hold_end_utc=end_raw, status="HELD")
    db.holds[hold["id"]] = hold
    return ok(public(hold), 201)


@bp.get("/api/table-holds/<hid>")
def read_hold(hid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("holds", hid)))


@bp.get("/api/table-holds")
def list_holds():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    table_id = q("table_id")
    bidder_id = q("bidder_id")
    status = q_enum("status", HOLD_STATUSES)
    items = [h for h in rows("holds")
             if (table_id is None or h["table_id"] == table_id)
             and (bidder_id is None or h["bidder_id"] == bidder_id)
             and (status is None or h["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/table-holds/<hid>/release")
def release_hold(hid):
    uid, role = authenticate(("EventOrganizer", "Bidder"))
    hold = fetch("holds", hid)
    if role == "Bidder":
        own_check(hold["bidder_id"] == uid)
    table = db.tables.get(hold["table_id"])
    if table is not None:
        calc.gate(fetch("events", table["event_id"]))
    if hold["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", "hold is not HELD")
    hold["status"] = "RELEASED"
    touch(hold)
    if table is not None:
        calc.recompute_table(table)
    return ok(public(hold))


# ---------------------------------------------------------------- bidders
@bp.post("/api/bidders")
def create_bidder():
    authenticate(("EventOrganizer",))
    payload = body()
    event_id = get_str(payload, "event_id")
    display_name = get_str(payload, "display_name")
    email = get_str(payload, "email")
    paddle_number = get_int(payload, "paddle_number", minimum=1)
    pm = get_bool(payload, "payment_method_on_file", required=False, default=False)
    event = fetch("events", event_id)
    calc.gate(event)
    for other in db.bidders.values():
        if other["event_id"] == event_id and other["paddle_number"] == paddle_number:
            raise ApiError("ERR_DUPLICATE_PADDLE_NUMBER", "paddle number already in use")
    bidder = new_row(event_id=event_id, display_name=display_name, email=email,
                     paddle_number=paddle_number, payment_method_on_file=pm,
                     outstanding_balance_cents=0)
    db.bidders[bidder["id"]] = bidder
    return ok(public(bidder), 201)


@bp.get("/api/bidders/<bid>")
def read_bidder(bid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("bidders", bid)))


@bp.get("/api/bidders")
def list_bidders():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    items = [b for b in rows("bidders")
             if event_id is None or b["event_id"] == event_id]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/bidders/<bid>/payment-method")
def set_payment_method(bid):
    uid, role = authenticate(("EventOrganizer", "Bidder"))
    payload = body()
    value = get_bool(payload, "payment_method_on_file")
    bidder = fetch("bidders", bid)
    if role == "Bidder":
        own_check(bidder["id"] == uid)
    calc.gate(fetch("events", bidder["event_id"]))
    bidder["payment_method_on_file"] = value
    touch(bidder)
    return ok(public(bidder))


# ---------------------------------------------------------------- sponsors
@bp.post("/api/sponsors")
def create_sponsor():
    authenticate(("EventOrganizer",))
    payload = body()
    event_id = get_str(payload, "event_id")
    org_name = get_str(payload, "org_name")
    tier = get_enum(payload, "tier", TIERS)
    commitment = get_int(payload, "commitment_cents", minimum=1)
    event = fetch("events", event_id)
    calc.gate(event)
    sponsor = new_row(event_id=event_id, org_name=org_name, tier=tier,
                      commitment_cents=commitment, paid_amount_cents=0,
                      status="PENDING", placed_ad_count=0)
    db.sponsors[sponsor["id"]] = sponsor
    return ok(public(sponsor), 201)


@bp.get("/api/sponsors/<sid>")
def read_sponsor(sid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("sponsors", sid)))


@bp.get("/api/sponsors")
def list_sponsors():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    status = q_enum("status", SPONSOR_STATUSES)
    items = [s for s in rows("sponsors")
             if (event_id is None or s["event_id"] == event_id)
             and (status is None or s["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/sponsors/<sid>/confirm")
def confirm_sponsor(sid):
    authenticate(("FinanceOfficer",))
    payload = body()
    amount = get_int(payload, "paid_amount_cents", minimum=0)
    sponsor = fetch("sponsors", sid)
    calc.gate(fetch("events", sponsor["event_id"]))
    if sponsor["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "sponsor is not PENDING")
    if sponsor["paid_amount_cents"] + amount < sponsor["commitment_cents"]:
        raise ApiError("ERR_SPONSOR_UNDERFUNDED", "payment does not fund the commitment")
    sponsor["paid_amount_cents"] += amount
    sponsor["status"] = "CONFIRMED"
    touch(sponsor)
    return ok(public(sponsor))


@bp.post("/api/sponsors/<sid>/withdraw")
def withdraw_sponsor(sid):
    authenticate(("EventOrganizer",))
    sponsor = fetch("sponsors", sid)
    calc.gate(fetch("events", sponsor["event_id"]))
    if sponsor["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "sponsor is not PENDING")
    for ad in db.ads.values():
        if ad["sponsor_id"] == sponsor["id"] and ad["status"] == "PLACED":
            raise ApiError("ERR_INVALID_STATE", "sponsor has a placed program ad")
    sponsor["status"] = "WITHDRAWN"
    for ad in rows("ads"):
        if ad["sponsor_id"] == sponsor["id"] and ad["status"] in (
                "SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED"):
            ad["status"] = "REJECTED"
            touch(ad)
    touch(sponsor)
    return ok(public(sponsor))


# ---------------------------------------------------------------- program ads
@bp.post("/api/program-ads")
def create_ad():
    uid, role = authenticate(("Sponsor", "EventOrganizer"))
    payload = body()
    sponsor_id = get_str(payload, "sponsor_id")
    event_id = get_str(payload, "event_id")
    ad_size = get_enum(payload, "ad_size", AD_SIZES)
    artwork = get_str(payload, "artwork_ref")
    fetch("sponsors", sponsor_id)
    event = fetch("events", event_id)
    if role == "Sponsor":
        own_check(sponsor_id == uid)
    calc.gate(event)
    ad = new_row(sponsor_id=sponsor_id, event_id=event_id, ad_size=ad_size,
                 artwork_ref=artwork, status="SUBMITTED", revision_count=0,
                 page_number=None, review_notes=None)
    db.ads[ad["id"]] = ad
    return ok(public(ad), 201)


@bp.get("/api/program-ads/<aid>")
def read_ad(aid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("ads", aid)))


@bp.get("/api/program-ads")
def list_ads():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    sponsor_id = q("sponsor_id")
    event_id = q("event_id")
    status = q_enum("status", AD_STATUSES)
    items = [a for a in rows("ads")
             if (sponsor_id is None or a["sponsor_id"] == sponsor_id)
             and (event_id is None or a["event_id"] == event_id)
             and (status is None or a["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/program-ads/<aid>/review")
def review_ad(aid):
    authenticate(("EventOrganizer",))
    payload = body()
    decision = get_enum(payload, "decision", DECISIONS)
    notes = get_str(payload, "notes", required=False, default=None, allow_empty=True)
    if decision == "REQUEST_CHANGES" and (notes is None or notes.strip() == ""):
        raise ApiError("ERR_INVALID_REQUEST", "notes are required to request changes")
    ad = fetch("ads", aid)
    calc.gate(fetch("events", ad["event_id"]))

    if decision == "BEGIN_REVIEW":
        if ad["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "ad is not SUBMITTED")
        ad["status"] = "IN_REVIEW"
    elif decision == "REQUEST_CHANGES":
        if ad["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "ad is not IN_REVIEW")
        ad["status"] = "CHANGES_REQUESTED"
        ad["review_notes"] = notes
    elif decision == "APPROVE":
        if ad["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "ad is not IN_REVIEW")
        sponsor = db.sponsors.get(ad["sponsor_id"])
        if sponsor is None or sponsor["status"] != "CONFIRMED":
            raise ApiError("ERR_SPONSOR_NOT_CONFIRMED", "sponsor is not CONFIRMED")
        ad["status"] = "APPROVED"
    else:
        if ad["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "ad is not IN_REVIEW")
        ad["status"] = "REJECTED"
        if notes is not None:
            ad["review_notes"] = notes
    touch(ad)
    return ok(public(ad))


@bp.post("/api/program-ads/<aid>/resubmit")
def resubmit_ad(aid):
    uid, role = authenticate(("Sponsor",))
    payload = body()
    artwork = get_str(payload, "artwork_ref")
    ad = fetch("ads", aid)
    own_check(ad["sponsor_id"] == uid)
    calc.gate(fetch("events", ad["event_id"]))
    if ad["status"] != "CHANGES_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "ad is not CHANGES_REQUESTED")
    if ad["revision_count"] >= 2:
        raise ApiError("ERR_AD_REVISION_LIMIT", "revision budget exhausted")
    ad["status"] = "SUBMITTED"
    ad["artwork_ref"] = artwork
    ad["revision_count"] += 1
    touch(ad)
    return ok(public(ad))


@bp.post("/api/program-ads/<aid>/place")
def place_ad(aid):
    authenticate(("EventOrganizer",))
    payload = body()
    page_number = get_int(payload, "page_number", minimum=1)
    ad = fetch("ads", aid)
    event = fetch("events", ad["event_id"])
    calc.gate(event)
    if ad["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "ad is not APPROVED")
    if event["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE", "the program has already gone to print")
    ad["status"] = "PLACED"
    ad["page_number"] = page_number
    touch(ad)
    sponsor = db.sponsors.get(ad["sponsor_id"])
    if sponsor is not None:
        calc.recompute_sponsor_ads(sponsor)
    return ok(public(ad))
