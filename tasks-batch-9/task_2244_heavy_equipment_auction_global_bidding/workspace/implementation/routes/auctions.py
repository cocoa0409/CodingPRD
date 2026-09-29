"""Auctions, catalogue assignment and the ring lifecycle (PRD 3.5, 3.6)."""
from datetime import timedelta

from routes.common import (
    ANY_ROLE, ApiError, Blueprint, C, collection_response, db, endpoint,
    field_dt, field_enum, field_int, field_str, fetch, invalid_state, json_body,
    new_entity, object_response, pagination, query_enum, query_str, touch,
)
from services.derive import close_auction, recompute_auction

bp = Blueprint("auctions", __name__)


def _deadline_at(window_end, yard):
    return window_end + timedelta(days=yard["loadout_deadline_days"])


def _window_conflict(yard, kind, start, end, exclude_id=None):
    """Closed-interval comparison of the candidate window extended by the yard's
    teardown buffer against the raw window of every other live on-site sale."""
    if kind != "LIVE_ONSITE":
        return False
    buffer = timedelta(minutes=yard["teardown_buffer_minutes"] or 0)
    candidate_start = start - buffer
    candidate_end = end + buffer
    for other in db.auctions.values():
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["yard_id"] != yard["id"]:
            continue
        if other["kind"] != "LIVE_ONSITE":
            continue
        if other["status"] == "RECONCILED":
            continue
        if candidate_start <= other["window_end"] and candidate_end >= other["window_start"]:
            return True
    return False


@bp.post("/auctions")
@endpoint("AuctionOperator")
def create_auction(actor):
    body = json_body()
    yard_id = field_str(body, "yard_id", required=True)
    kind = field_enum(body, "kind", C.AUCTION_KINDS, required=True)
    reserve_policy = field_enum(body, "reserve_policy", C.RESERVE_POLICIES,
                                required=True)
    premium_code = field_enum(body, "premium_schedule_code",
                              C.PREMIUM_SCHEDULE_CODES, required=True)
    window_start = field_dt(body, "window_start", required=True)
    window_end = field_dt(body, "window_end", required=True)
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_end must be strictly after window_start.")

    yard = fetch(db.yards, yard_id, "ERR_YARD_NOT_FOUND")

    if _window_conflict(yard, kind, window_start, window_end):
        raise ApiError("ERR_AUCTION_WINDOW_CONFLICT")

    auction = new_entity()
    auction.update({
        "yard_id": yard["id"],
        "kind": kind,
        "reserve_policy": reserve_policy,
        "premium_schedule_code": premium_code,
        "window_start": window_start,
        "window_end": window_end,
        "loadout_deadline_at": _deadline_at(window_end, yard),
        "status": "SCHEDULED",
        "assigned_lot_count": 0,
        "sold_lot_count": 0,
        "unsold_lot_count": 0,
        "gross_hammer_cents": 0,
    })
    db.auctions[auction["id"]] = auction
    return object_response(auction, 201)


@bp.get("/auctions/<auction_id>")
@endpoint(*ANY_ROLE)
def get_auction(actor, auction_id):
    return object_response(fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND"))


@bp.get("/auctions")
@endpoint(*ANY_ROLE)
def list_auctions(actor):
    limit, offset = pagination()
    yard_id = query_str("yard_id")
    kind = query_enum("kind", C.AUCTION_KINDS)
    status = query_enum("status", C.AUCTION_STATUSES)
    rows = list(db.auctions.values())
    if yard_id is not None:
        rows = [a for a in rows if a["yard_id"] == yard_id]
    if kind is not None:
        rows = [a for a in rows if a["kind"] == kind]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return collection_response(rows, limit, offset)


@bp.post("/auctions/<auction_id>/reschedule")
@endpoint("AuctionOperator")
def reschedule_auction(actor, auction_id):
    body = json_body()
    window_start = field_dt(body, "window_start", required=True)
    window_end = field_dt(body, "window_end", required=True)
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_end must be strictly after window_start.")
    auction = fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if auction["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED auction may be rescheduled.")
    yard = db.yards[auction["yard_id"]]
    if _window_conflict(yard, auction["kind"], window_start, window_end,
                        exclude_id=auction["id"]):
        raise ApiError("ERR_AUCTION_WINDOW_CONFLICT")
    auction["window_start"] = window_start
    auction["window_end"] = window_end
    auction["loadout_deadline_at"] = _deadline_at(window_end, yard)
    touch(auction)
    return object_response(auction)


@bp.post("/auctions/<auction_id>/lot-assignments")
@endpoint("AuctionOperator")
def assign_lot(actor, auction_id):
    body = json_body()
    lot_id = field_str(body, "lot_id", required=True)
    reserve_present = "reserve_price_cents" in body
    reserve_price = field_int(body, "reserve_price_cents", nullable=True,
                              min_value=1, max_value=1000000000, default=None)

    auction = fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    consignment = db.consignments[lot["consignment_id"]]

    report = None
    for candidate in db.condition_reports.values():
        if candidate["lot_id"] == lot["id"]:
            report = candidate
            break

    # rung 23 (PRD 3.4) — "The lot must not already be assigned to another
    # auction ... failing which the refusal is ERR_LOT_AUCTION_MISMATCH."  An
    # already-assigned lot has necessarily left CATALOG_READY, so this guard is
    # evaluated before the generic lot-state guard or it could never fire.
    if lot["auction_id"] is not None and lot["auction_id"] != auction["id"]:
        raise ApiError("ERR_LOT_AUCTION_MISMATCH")

    # rung 8 — generic state guards
    if lot["lifecycle_status"] != "CATALOG_READY":
        raise invalid_state("Only a CATALOG_READY lot may be catalogued into a ring.")
    if auction["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED auction may take assignments.")
    if report is None or report["status"] != "PUBLISHED":
        raise invalid_state("The lot's condition report must be PUBLISHED.")

    # rung 11 — consignment must be catalogued
    if consignment["status"] != "CATALOGED":
        raise ApiError("ERR_CONSIGNMENT_NOT_CATALOGED")

    # rung 13 — title
    if lot["title_status"] not in C.TITLE_CLEAR_STATUSES:
        raise ApiError("ERR_TITLE_NOT_CLEAR")

    # rung 21 — unverified hours must be disclosed
    if not report["hour_meter_verified"] and not lot["sold_as_hours_unverified"]:
        raise ApiError("ERR_HOUR_METER_UNVERIFIED")

    # rung 23 — the lot must not already belong to a different ring
    if consignment["status"] not in ("INTAKE_ACCEPTED", "CATALOGED"):
        raise ApiError("ERR_LOT_AUCTION_MISMATCH")
    if lot["auction_id"] is not None and lot["auction_id"] != auction["id"]:
        raise ApiError("ERR_LOT_AUCTION_MISMATCH")

    # rung 26 — reserve only where both the ring and the agreement allow it
    effective_reserve = reserve_price if reserve_present else lot["reserve_price_cents"]
    if effective_reserve is not None:
        if (auction["reserve_policy"] != "RESERVE_ALLOWED"
                or consignment["agreement_type"] != "RESERVE"):
            raise ApiError("ERR_RESERVE_NOT_ALLOWED")

    if reserve_present:
        lot["reserve_price_cents"] = reserve_price
    lot["auction_id"] = auction["id"]
    lot["lifecycle_status"] = "ASSIGNED"
    touch(lot)
    recompute_auction(auction)
    touch(auction)
    return object_response(lot, 201)


@bp.post("/auctions/<auction_id>/open")
@endpoint("AuctionOperator")
def open_auction(actor, auction_id):
    json_body()
    auction = fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if auction["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED auction may be opened.")
    if db.now() > auction["window_end"]:
        raise invalid_state("The bidding window has already elapsed.")
    if (auction["assigned_lot_count"] or 0) < 1:
        raise invalid_state("An auction needs at least one assigned lot to open.")
    auction["status"] = "OPEN"
    touch(auction)
    return object_response(auction)


@bp.post("/auctions/<auction_id>/close")
@endpoint("AuctionOperator")
def close_auction_route(actor, auction_id):
    json_body()
    auction = fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if auction["status"] != "OPEN":
        raise invalid_state("Only an OPEN auction may be closed.")
    close_auction(auction)
    return object_response(auction)


@bp.post("/auctions/<auction_id>/reconcile")
@endpoint("SettlementOfficer")
def reconcile_auction(actor, auction_id):
    json_body()
    auction = fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if auction["status"] != "CLOSED":
        raise invalid_state("Only a CLOSED auction may be reconciled.")

    sales = [s for s in db.sales.values() if s["auction_id"] == auction["id"]]
    for sale in sales:
        if sale["status"] in ("PROVISIONAL", "CONSIGNOR_COUNTERED"):
            raise ApiError("ERR_SETTLEMENT_INCOMPLETE")
    for sale in sales:
        if sale["status"] != "CONFIRMED":
            continue
        posted = [s for s in db.consignor_settlements.values()
                  if s["sale_id"] == sale["id"] and s["status"] == "POSTED"]
        if not posted:
            raise ApiError("ERR_SETTLEMENT_INCOMPLETE")

    auction["status"] = "RECONCILED"
    recompute_auction(auction)
    touch(auction)
    return object_response(auction)
