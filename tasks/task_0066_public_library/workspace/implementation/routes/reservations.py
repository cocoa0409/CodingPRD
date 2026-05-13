"""Reservation routes."""
from datetime import timedelta
from flask import Blueprint, request, g

import db
from errors import err
from response import success
from middleware import require_auth
from services import validation as V
from services.common import (
    get_reservation, get_book_title, get_card, check_version, assert_reader_ownership,
)
from services.serialize import serialize_reservation
from services import audit
from services import reservations as reservations_svc
from services.money import HOLD_PERIOD_DAYS
from clock import iso, now


bp = Blueprint("reservations", __name__)


ACTIVE_LOAN_STATUSES = {"BORROWED", "RENEWED", "RECALL_PENDING"}


@bp.route("/library/reservations", methods=["POST"])
@require_auth(roles={"Reader", "Librarian"})
def create_reservation():
    body = V.require_dict(request.get_json(silent=True) or {})
    book_title_id = V.require_str(body, "book_title_id")
    card_id = V.require_str(body, "card_id")
    channel = V.require_enum(body, "channel", V.RESERVATION_CHANNELS)

    bt = get_book_title(book_title_id)
    card = get_card(card_id)
    if g.user_role == "Reader":
        if g.user_id != card["reader_id"]:
            raise err("ERR_FORBIDDEN", "Reader can reserve only with their own card")

    if card["status"] != "ACTIVE":
        raise err("ERR_CARD_NOT_ACTIVE", f"Card is {card['status']}, not ACTIVE")

    reader_id = card["reader_id"]

    # Duplicate reservation check
    # (a) Any open reservation on the title for this reader
    for r in db.reservations.values():
        if r["book_title_id"] == bt["id"] and r["reader_id"] == reader_id \
                and r["status"] in {"QUEUED", "READY_FOR_PICKUP"}:
            raise err("ERR_DUPLICATE_RESERVATION",
                      "Reader already has an active reservation on this title")
    # (b) Any open loan for this reader on a copy of this title
    for l in db.loans.values():
        if l["reader_id"] == reader_id and l["status"] in ACTIVE_LOAN_STATUSES:
            cp = db.copies.get(l["copy_id"])
            if cp and cp["book_title_id"] == bt["id"]:
                raise err("ERR_DUPLICATE_RESERVATION",
                          "Reader already has an active loan on this title")

    queue_pos = reservations_svc.next_queue_position(bt["id"])
    reservation = {
        "book_title_id": bt["id"],
        "card_id": card["id"],
        "reader_id": reader_id,
        "channel": channel,
        "queue_position": queue_pos,
        "held_copy_id": None,
        "hold_expires_at": None,
        "status": "QUEUED",
    }
    db.stamp_create(reservation)
    db.reservations[reservation["id"]] = reservation

    audit.append("RESERVATION_CREATED", "Reservation", reservation["id"],
                 {"after": {"book_title_id": bt["id"], "reader_id": reader_id,
                            "queue_position": queue_pos}})

    # If a Copy is currently AVAILABLE for this title and this reservation is the head,
    # cascade immediately to READY_FOR_PICKUP.
    if queue_pos == 1:
        avail = next(
            (c for c in sorted(db.copies.values(), key=lambda c: (c["created_at"], c["_seq"]))
             if c["book_title_id"] == bt["id"] and c["status"] == "AVAILABLE"),
            None,
        )
        if avail is not None:
            avail["status"] = "RESERVED"
            db.stamp_update(avail)
            reservation["status"] = "READY_FOR_PICKUP"
            reservation["held_copy_id"] = avail["id"]
            reservation["hold_expires_at"] = iso(now() + timedelta(days=HOLD_PERIOD_DAYS))
            db.stamp_update(reservation)
            # Recompute title aggregates since available_copies changed
            from services.aggregates import recompute_title_aggregates
            recompute_title_aggregates(bt["id"])

    return success(serialize_reservation(reservation), status=201)


@bp.route("/library/reservations/<rid>", methods=["GET"])
@require_auth(roles={"Reader", "Librarian", "Admin"})
def get_reservation_endpoint(rid):
    r = get_reservation(rid)
    assert_reader_ownership(r["reader_id"])
    return success(serialize_reservation(r))


@bp.route("/library/reservations/<rid>", methods=["DELETE"])
@require_auth(roles={"Reader", "Librarian"})
def cancel_reservation(rid):
    r = get_reservation(rid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(r, body)
    assert_reader_ownership(r["reader_id"])

    if r["status"] not in {"QUEUED", "READY_FOR_PICKUP"}:
        raise err("ERR_INVALID_STATE",
                  f"Reservation is {r['status']}; cannot cancel")

    was_ready = (r["status"] == "READY_FOR_PICKUP")
    held_copy_id = r.get("held_copy_id")

    r["status"] = "CANCELLED"
    db.stamp_update(r)

    if was_ready and held_copy_id:
        copy = db.copies.get(held_copy_id)
        if copy is not None:
            # release_copy_after_hold sets AVAILABLE then promotes next QUEUED if exists
            reservations_svc.release_copy_after_hold(copy)
            from services.aggregates import recompute_title_aggregates
            recompute_title_aggregates(copy["book_title_id"])
    else:
        # QUEUED cancellation: renumber trailing QUEUED reservations
        reservations_svc.renumber_queued_positions(r["book_title_id"])

    return success(serialize_reservation(r))
