"""EventPackage routes: quote, negotiate/revise loop, confirm (deposit),
settle (final pricing + deposit waterfall), cancel (PRD §3.10; SCAFFOLD §1.5)."""

from flask import Blueprint, request

from db import db, stamp_common, stamp_immutable, touch
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INSUFFICIENT_FUNDS,
    ERR_FBTAB_NOT_CLOSED,
)
from services import validate as V
from services import calc
from services.lookup import get_or_404
from services.serialize import event_out

bp = Blueprint("event_packages", __name__)


@bp.post("/golf/event-packages")
def create_event_package():
    caller = get_caller()
    require_roles(caller, {"Guest", "RangeManager"})
    data = V.body()

    venue_id = V.as_str(V.require(data, "venue_id"), "venue_id")
    organizer_member_id = V.as_str(V.require(data, "organizer_member_id"), "organizer_member_id")
    headcount = V.int_min(V.require(data, "headcount_estimate"), "headcount_estimate", 1)
    per_head = V.as_int(V.require(data, "per_head_package_cents"), "per_head_package_cents")
    if per_head < 0:
        raise_err(ERR_INVALID_REQUEST, "per_head_package_cents must be >= 0")

    get_or_404(db.venues, venue_id, "venue")
    get_or_404(db.members, organizer_member_id, "member")

    bay_block = data.get("bay_block_cents", 15000)
    bay_block = V.as_int(bay_block, "bay_block_cents")
    if bay_block < 0:
        raise_err(ERR_INVALID_REQUEST, "bay_block_cents must be >= 0")
    deposit = data.get("deposit_cents", 0)
    deposit = V.as_int(deposit, "deposit_cents")
    if deposit < 0:
        raise_err(ERR_INVALID_REQUEST, "deposit_cents must be >= 0")

    estimated = calc.event_estimated_total(headcount, per_head, bay_block)

    ep = stamp_common({
        "venue_id": venue_id,
        "organizer_member_id": organizer_member_id,
        "headcount_estimate": headcount,
        "actual_attendee_count": None,
        "per_head_package_cents": per_head,
        "bay_block_cents": bay_block,
        "deposit_cents": deposit,
        "estimated_total_cents": estimated,
        "final_total_cents": None,
        "deposit_refund_cents": 0,
        "status": "QUOTED",
    })
    db.event_packages[ep["id"]] = ep
    return success(event_out(ep), status=201)


@bp.get("/golf/event-packages/<event_package_id>")
def get_event_package(event_package_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    ep = get_or_404(db.event_packages, event_package_id, "event package")
    return success(event_out(ep))


@bp.get("/golf/event-packages")
def list_event_packages():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(request.args)
    records = list(db.event_packages.values())
    for key in ("venue_id", "organizer_member_id"):
        val = request.args.get(key)
        if val is not None:
            records = [e for e in records if e.get(key) == val]
    window, total = paginate(records, limit, offset)
    return list_success([event_out(e) for e in window], limit, offset, total)


@bp.patch("/golf/event-packages/<event_package_id>")
def revise_event_package(event_package_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    ep = get_or_404(db.event_packages, event_package_id, "event package")
    data = V.body()

    if ep["status"] != "NEGOTIATING":
        raise_err(ERR_INVALID_STATE, "package is not NEGOTIATING")

    if "headcount_estimate" in data and data["headcount_estimate"] is not None:
        ep["headcount_estimate"] = V.int_min(data["headcount_estimate"], "headcount_estimate", 1)
    if "per_head_package_cents" in data and data["per_head_package_cents"] is not None:
        val = V.as_int(data["per_head_package_cents"], "per_head_package_cents")
        if val < 0:
            raise_err(ERR_INVALID_REQUEST, "per_head_package_cents must be >= 0")
        ep["per_head_package_cents"] = val
    if "bay_block_cents" in data and data["bay_block_cents"] is not None:
        val = V.as_int(data["bay_block_cents"], "bay_block_cents")
        if val < 0:
            raise_err(ERR_INVALID_REQUEST, "bay_block_cents must be >= 0")
        ep["bay_block_cents"] = val
    if "deposit_cents" in data and data["deposit_cents"] is not None:
        val = V.as_int(data["deposit_cents"], "deposit_cents")
        if val < 0:
            raise_err(ERR_INVALID_REQUEST, "deposit_cents must be >= 0")
        ep["deposit_cents"] = val

    ep["estimated_total_cents"] = calc.event_estimated_total(
        ep["headcount_estimate"], ep["per_head_package_cents"], ep["bay_block_cents"])
    ep["status"] = "QUOTED"
    touch(ep)
    return success(event_out(ep))


@bp.post("/golf/event-packages/<event_package_id>/negotiate")
def negotiate_event_package(event_package_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    ep = get_or_404(db.event_packages, event_package_id, "event package")
    V.body()
    if ep["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "package is not QUOTED")
    ep["status"] = "NEGOTIATING"
    touch(ep)
    return success(event_out(ep))


@bp.post("/golf/event-packages/<event_package_id>/confirm")
def confirm_event_package(event_package_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    ep = get_or_404(db.event_packages, event_package_id, "event package")
    V.body()
    if ep["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "package is not QUOTED")
    organizer = db.members.get(ep["organizer_member_id"])
    if organizer["wallet_balance_cents"] < ep["deposit_cents"]:
        raise_err(ERR_INSUFFICIENT_FUNDS, "organizer wallet below deposit")
    organizer["wallet_balance_cents"] -= ep["deposit_cents"]
    touch(organizer)
    ep["status"] = "CONFIRMED"
    touch(ep)
    return success(event_out(ep))


@bp.post("/golf/event-packages/<event_package_id>/settle")
def settle_event_package(event_package_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    ep = get_or_404(db.event_packages, event_package_id, "event package")
    data = V.body()
    actual = V.int_min(V.require(data, "actual_attendee_count"), "actual_attendee_count", 1)

    if ep["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "package is not CONFIRMED")

    # All event F&B tabs must be CLOSED.
    fb_total = 0
    for t in db.fb_tabs.values():
        if t["event_package_id"] == event_package_id:
            if t["status"] != "CLOSED":
                raise_err(ERR_FBTAB_NOT_CLOSED, "attached event F&B tab is still open")
            fb_total += t["total_cents"]

    ep["actual_attendee_count"] = actual
    per_head_total = actual * ep["per_head_package_cents"]
    final_total = calc.event_final_total(
        actual, ep["per_head_package_cents"], ep["bay_block_cents"], fb_total)
    ep["final_total_cents"] = final_total

    deposit_applied, deposit_refund = calc.deposit_waterfall(
        ep["deposit_cents"], ep["bay_block_cents"], per_head_total, fb_total)
    ep["deposit_refund_cents"] = deposit_refund

    organizer = db.members.get(ep["organizer_member_id"])
    charge = stamp_immutable({
        "member_id": ep["organizer_member_id"],
        "kind": "EVENT_SETTLEMENT",
        "amount_cents": final_total - deposit_applied,
        "pay_source": "CARD_ON_FILE",
        "status": "SETTLED",
    })
    db.charges[charge["id"]] = charge

    organizer["wallet_balance_cents"] += deposit_refund
    touch(organizer)

    ep["status"] = "SETTLED"
    touch(ep)
    return success(event_out(ep))


@bp.post("/golf/event-packages/<event_package_id>/cancel")
def cancel_event_package(event_package_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    ep = get_or_404(db.event_packages, event_package_id, "event package")
    V.body()
    if ep["status"] not in ("QUOTED", "NEGOTIATING", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE, "package cannot be cancelled from its current state")
    if ep["status"] == "CONFIRMED":
        organizer = db.members.get(ep["organizer_member_id"])
        organizer["wallet_balance_cents"] += ep["deposit_cents"]
        touch(organizer)
    ep["status"] = "CANCELLED"
    touch(ep)
    return success(event_out(ep))
