"""Ticket workflow (§3.7): issuance, scan in/out, void, refund."""

from decimal import Decimal

import db
import clock
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_INPUT,
    ERR_POSTURE_BLOCKED,
    ERR_CAPACITY_EXCEEDED,
    ERR_GROUP_INVALID,
)
from services.common import stamp_create, bump, check_occ, must_dict
from services import calculations


SATURATION_THRESHOLD = Decimal("0.95")
RECOVERY_THRESHOLD = Decimal("0.90")


def _get_ticket(tid):
    t = db.tickets.get(tid)
    if t is None:
        raise AppError(ERR_NOT_FOUND, "Ticket not found.", 404)
    return t


def _group_size(exhibition_id, group_id):
    """Count tickets sharing this group_id on this exhibition (in any state)."""
    return sum(
        1
        for t in db.tickets.values()
        if t["exhibition_id"] == exhibition_id and t.get("group_id") == group_id
    )


def issue_ticket(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    body = must_dict(body)
    kind = body.get("kind")
    channel = body.get("channel")
    group_id = body.get("group_id")
    if kind not in ("VISITOR", "PROFESSIONAL_BUYER", "STUDENT", "VIP"):
        raise AppError(ERR_INVALID_INPUT, "Invalid kind.", 422)
    if channel not in ("ONLINE_PRESALE", "ONSITE"):
        raise AppError(ERR_INVALID_INPUT, "Invalid channel.", 422)
    # PRD §3.7 does NOT enumerate a status precondition for issuance itself;
    # posture-driven gating in §2.9 is described against gate scanning and may
    # affect ONSITE sales but the spec doesn't formalize an ERR_POSTURE_BLOCKED
    # at issuance. We therefore allow issuance regardless of posture/status here.
    # If group_id is provided and the caller requests group discount semantics,
    # group_id must be a non-empty string. The discount itself is applied only
    # when current group size (after this issuance) is >= 10.
    if group_id is not None and not isinstance(group_id, str):
        raise AppError(ERR_INVALID_INPUT, "group_id must be a string or null.", 422)
    if group_id is not None and group_id == "":
        raise AppError(ERR_GROUP_INVALID, "group_id cannot be an empty string.", 422)
    with db.LOCK:
        # group size at issuance instant is current count + 1 (this one being issued).
        current_count = _group_size(exhibition_id, group_id) if group_id is not None else 0
        group_size = current_count + 1 if group_id is not None else 0
        price = calculations.ticket_price(kind, channel, group_size, group_id)
        row = {
            "exhibition_id": exhibition_id,
            "kind": kind,
            "channel": channel,
            "price_cents": price,
            "qr_code": db.new_qr(),
            "group_id": group_id,
            "status": "ISSUED",
            "scanned_in_at": None,
            "scanned_out_at": None,
        }
        stamp_create(row)
        db.tickets[row["id"]] = row
    return row


def scan_in(ticket_id, body):
    t = _get_ticket(ticket_id)
    ex = db.exhibitions.get(t["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    with db.LOCK:
        if t["status"] != "ISSUED":
            raise AppError(ERR_INVALID_STATE, "Ticket not in ISSUED.", 409)
        cap = int(ex["capacity_max"])
        occ = int(ex.get("live_occupancy", 0))
        # PRD §2.12 says that two scan-ins racing at the capacity
        # boundary serialize on the atomic occupancy increment and
        # the loser receives ERR_CAPACITY_EXCEEDED. That requires
        # the capacity check to surface CAPACITY_EXCEEDED on a
        # serialized loser whose predecessor pushed occupancy
        # to capacity_max even when the saturation-driven posture
        # flip would also apply. We therefore check capacity ahead
        # of posture so the boundary race reports the
        # PRD-mandated error.
        if occ >= cap:
            raise AppError(ERR_CAPACITY_EXCEEDED, "Capacity exceeded.", 409)
        if ex["posture"] != "OPEN":
            raise AppError(ERR_POSTURE_BLOCKED, "Posture is not OPEN.", 409)
        check_occ(t, body)
        t["status"] = "SCANNED_IN"
        t["scanned_in_at"] = clock.iso()
        bump(t)
        ex["live_occupancy"] = occ + 1
        # Saturation rule.
        if cap > 0:
            ratio = Decimal(ex["live_occupancy"]) / Decimal(cap)
            if ratio >= SATURATION_THRESHOLD and ex["posture"] == "OPEN":
                ex["posture"] = "RESTRICTED"
        bump(ex)
    return t


def scan_out(ticket_id, body):
    t = _get_ticket(ticket_id)
    ex = db.exhibitions.get(t["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    with db.LOCK:
        if t["status"] != "SCANNED_IN":
            raise AppError(ERR_INVALID_STATE, "Ticket not in SCANNED_IN.", 409)
        check_occ(t, body)
        t["status"] = "SCANNED_OUT"
        t["scanned_out_at"] = clock.iso()
        bump(t)
        new_occ = max(0, int(ex.get("live_occupancy", 0)) - 1)
        ex["live_occupancy"] = new_occ
        cap = int(ex["capacity_max"])
        if cap > 0 and ex["posture"] == "RESTRICTED":
            ratio = Decimal(new_occ) / Decimal(cap)
            if ratio < RECOVERY_THRESHOLD:
                ex["posture"] = "OPEN"
        bump(ex)
    return t


def refund_ticket(ticket_id, body):
    t = _get_ticket(ticket_id)
    ex = db.exhibitions.get(t["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if t["status"] != "ISSUED":
        raise AppError(ERR_INVALID_STATE, "Ticket not in ISSUED.", 409)
    if t["channel"] != "ONLINE_PRESALE":
        raise AppError(ERR_INVALID_STATE, "Refund only allowed for online presale tickets.", 409)
    if ex["status"] == "OPEN":
        raise AppError(ERR_INVALID_STATE, "Cannot refund while exhibition is OPEN.", 409)
    check_occ(t, body)
    t["status"] = "REFUNDED"
    bump(t)
    return t


def void_ticket(ticket_id, body):
    t = _get_ticket(ticket_id)
    if t["status"] != "ISSUED":
        raise AppError(ERR_INVALID_STATE, "Ticket not in ISSUED.", 409)
    check_occ(t, body)
    t["status"] = "VOID"
    bump(t)
    return t
