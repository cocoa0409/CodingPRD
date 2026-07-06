"""PayoutCycle endpoints — create, list, read, release, return."""
from flask import Blueprint, request

import db
from clock import clock, parse_iso
from datetime import timedelta
from errors import raise_error
from middleware import require_auth
from response import ok, created, paginate_and_serialize
from services.calc import floor_fee
from services.serialize import serialize

bp = Blueprint("payouts", __name__)


def _get_cycle_or_404(pid):
    row = db.payout_cycles.get(pid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"payout_cycle {pid} not found")
    return row


def _get_creator_or_404(cid):
    row = db.creators.get(cid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"creator {cid} not found")
    return row


@bp.post("/pod/creators/<cid>/payout-cycles")
@require_auth(["PlatformAdmin"])
def create_cycle(cid):
    _get_creator_or_404(cid)
    body = request.get_json(silent=True) or {}
    for f in ("cycle_start", "cycle_end"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    try:
        start = parse_iso(body["cycle_start"])
        end = parse_iso(body["cycle_end"])
    except Exception:
        raise_error("ERR_INVALID_REQUEST", "invalid cycle_start or cycle_end")

    # Priority 14 — window length > 0 and no overlap with any DRAFT cycle for this creator.
    if (end - start).total_seconds() <= 0:
        raise_error("ERR_PAYOUT_WINDOW_OVERLAP", "cycle_end must be after cycle_start")

    for existing in db.payout_cycles.all():
        if existing["creator_id"] != cid:
            continue
        if existing["status"] != "DRAFT":
            continue
        ex_start = parse_iso(existing["cycle_start"])
        ex_end = parse_iso(existing["cycle_end"])
        # Half-open [start, end). Overlap iff start < ex_end AND ex_start < end.
        if start < ex_end and ex_start < end:
            raise_error("ERR_PAYOUT_WINDOW_OVERLAP", "overlaps with existing draft cycle")

    row = db.new_common_fields()
    row.update(
        {
            "creator_id": cid,
            "cycle_start": body["cycle_start"],
            "cycle_end": body["cycle_end"],
            "gross_earnings_cents": 0,
            "fee_cents": 0,
            "net_paid_cents": 0,
            "status": "DRAFT",
            "_default_payout_fee_bps_snapshot": None,
        }
    )
    db.payout_cycles.insert(row)
    return created(serialize(row))


@bp.get("/pod/payout-cycles/<pid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_cycle(pid):
    return ok(serialize(_get_cycle_or_404(pid)))


@bp.get("/pod/creators/<cid>/payout-cycles")
@require_auth(["Creator", "PlatformAdmin"])
def list_creator_cycles(cid):
    _get_creator_or_404(cid)
    rows = [c for c in db.payout_cycles.all() if c["creator_id"] == cid]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


def _compute_gross_earnings(creator_id, start_iso, end_iso):
    """Sum delivered order margins within [cycle_start, cycle_end) for this creator."""
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    total = 0
    for order in db.orders.all():
        if order["fulfillment_status"] != "DELIVERED":
            continue
        if order.get("is_sample"):
            continue
        delivered_at = order.get("_delivered_at")
        if not delivered_at:
            continue
        listing = db.listings.get(order["listing_id"])
        storefront = db.storefronts.get(listing["storefront_id"]) if listing else None
        if not storefront or storefront["creator_id"] != creator_id:
            continue
        dt = parse_iso(delivered_at)
        # Half-open [start, end).
        if dt < start or dt >= end:
            continue
        total += int(order.get("creator_net_cents", 0))
    return total


@bp.post("/pod/payout-cycles/<pid>/release")
@require_auth(["PlatformAdmin"])
def release_cycle(pid):
    cycle = _get_cycle_or_404(pid)
    if cycle["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "cycle must be DRAFT")

    creator = db.creators.get(cycle["creator_id"])
    if not creator:
        raise_error("ERR_NOT_FOUND", "creator not found")

    # Priority 7: creator must be VERIFIED.
    if creator["verification_status"] != "VERIFIED":
        raise_error("ERR_CREATOR_NOT_VERIFIED", "creator must be VERIFIED")

    # Step 1: gross earnings.
    gross = _compute_gross_earnings(creator["id"], cycle["cycle_start"], cycle["cycle_end"])
    if gross <= 0:
        raise_error("ERR_PAYOUT_ZERO_GROSS", "gross_earnings_cents must be > 0")
    # Step 2: fee (floor).
    fee_bps = int(creator["default_payout_fee_bps"])
    fee = floor_fee(gross, fee_bps)
    # Step 3: net.
    net = gross - fee

    cycle["gross_earnings_cents"] = gross
    cycle["fee_cents"] = fee
    cycle["net_paid_cents"] = net
    cycle["_default_payout_fee_bps_snapshot"] = fee_bps
    cycle["status"] = "RELEASED"
    db.bump(cycle)

    creator["payout_wallet_cents"] = int(creator["payout_wallet_cents"]) - net
    db.bump(creator)

    return ok(serialize(cycle))


@bp.post("/pod/payout-cycles/<pid>/return")
@require_auth(["PlatformAdmin"])
def return_cycle(pid):
    cycle = _get_cycle_or_404(pid)
    if cycle["status"] != "RELEASED":
        raise_error("ERR_INVALID_STATE", "cycle must be RELEASED")

    released_at = parse_iso(cycle["updated_at"])
    now = clock.now()
    if now >= released_at + timedelta(hours=72):
        raise_error("ERR_PAYOUT_RETURN_WINDOW_EXPIRED", "return window closed")

    creator = db.creators.get(cycle["creator_id"])
    if creator:
        credit = int(cycle["gross_earnings_cents"]) - int(cycle["fee_cents"])
        creator["payout_wallet_cents"] = int(creator["payout_wallet_cents"]) + credit
        db.bump(creator)

    cycle["status"] = "RETURNED"
    db.bump(cycle)
    return ok(serialize(cycle))
