"""Operational test-driving endpoints: clock, sweep, events."""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import require_auth
from services import validation as V
from services.common import get_ill_request, get_reader
from services.serialize import serialize_reader
from services.aggregates import recompute_title_aggregates
from services.reader_status import recompute_reader
from services import reservations as reservations_svc
from clock import parse_iso, parse_iso_duration, iso, now, set_now, advance


bp = Blueprint("system", __name__)


@bp.route("/library/_clock/advance", methods=["POST"])
@require_auth(roles={"Admin"})
def clock_advance():
    body = V.require_dict(request.get_json(silent=True) or {})
    iso_duration = V.require_str(body, "iso_duration")
    try:
        delta = parse_iso_duration(iso_duration)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))
    advance(delta)
    return success({"now": iso(now())})


@bp.route("/library/_sweep/run", methods=["POST"])
@require_auth(roles={"Admin"})
def sweep_run():
    expired_reservations = []
    expired_cards = []
    # 1) Expire READY_FOR_PICKUP reservations whose hold_expires_at <= now
    #    Process deterministically by (book_title_id, queue order)
    ready = [r for r in db.reservations.values()
             if r["status"] == "READY_FOR_PICKUP" and r.get("hold_expires_at")]
    ready.sort(key=lambda r: (r["created_at"], r["id"]))
    for r in ready:
        if parse_iso(r["hold_expires_at"]) <= now():
            held_copy_id = r.get("held_copy_id")
            r["status"] = "EXPIRED"
            db.stamp_update(r)
            expired_reservations.append(r["id"])
            if held_copy_id:
                copy = db.copies.get(held_copy_id)
                if copy is not None:
                    reservations_svc.release_copy_after_hold(copy)
                    recompute_title_aggregates(copy["book_title_id"])

    # 2) Expire ACTIVE cards whose valid_until <= now
    for c in list(db.cards.values()):
        if c["status"] == "ACTIVE":
            try:
                vu = parse_iso(c["valid_until"])
            except Exception:
                continue
            if vu <= now():
                c["status"] = "EXPIRED"
                db.stamp_update(c)
                expired_cards.append(c["id"])

    # 3) Recompute every reader's status
    for r in list(db.readers.values()):
        recompute_reader(r["id"])

    return success({
        "expired_reservations": expired_reservations,
        "expired_cards": expired_cards,
        "now": iso(now()),
    })


@bp.route("/library/_events/emit", methods=["POST"])
@require_auth(roles={"Admin"})
def event_emit():
    body = V.require_dict(request.get_json(silent=True) or {})
    event_type = V.require_str(body, "event_type")
    payload = body.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise err("ERR_INVALID_INPUT", "payload must be an object")
    payload = payload or {}

    if event_type == "PAYMENT_CONFIRMED":
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not key:
            raise err("ERR_INVALID_INPUT", "PAYMENT_CONFIRMED requires idempotency_key")
        if key not in db.payment_events:
            db.payment_events[key] = {"consumed": False, "fine_id": payload.get("fine_id")}
        return success({"event_type": event_type, "idempotency_key": key})

    if event_type == "IDENTITY_VERIFIED":
        reader_id = payload.get("reader_id")
        if not isinstance(reader_id, str):
            raise err("ERR_INVALID_INPUT", "IDENTITY_VERIFIED requires reader_id")
        reader = get_reader(reader_id)
        if not reader.get("identity_verified"):
            reader["identity_verified"] = True
            reader["identity_verified_at"] = iso(now())
            from db import stamp_update
            stamp_update(reader)
        return success({"event_type": event_type, "reader_id": reader_id})

    if event_type == "ILL_AVAILABILITY":
        ill_id = payload.get("ill_request_id")
        if not isinstance(ill_id, str):
            raise err("ERR_INVALID_INPUT", "ILL_AVAILABILITY requires ill_request_id")
        ill = get_ill_request(ill_id)
        available = bool(payload.get("available"))
        partner_max = payload.get("partner_max_days")
        if available and (not isinstance(partner_max, int) or partner_max <= 0):
            raise err("ERR_INVALID_INPUT",
                      "ILL_AVAILABILITY with available=true requires positive partner_max_days")
        db.ill_availability[ill_id] = {
            "available": available,
            "partner_max_days": partner_max if available else None,
        }
        return success({"event_type": event_type, "ill_request_id": ill_id, "available": available})

    if event_type == "ILL_DELIVERED":
        ill_id = payload.get("ill_request_id")
        if not isinstance(ill_id, str):
            raise err("ERR_INVALID_INPUT", "ILL_DELIVERED requires ill_request_id")
        ill = get_ill_request(ill_id)
        if ill["status"] != "IN_TRANSIT":
            raise err("ERR_INVALID_STATE",
                      f"ILLRequest is {ill['status']}, not IN_TRANSIT")
        ill["status"] = "AT_PARTNER"
        db.stamp_update(ill)
        return success({"event_type": event_type, "ill_request_id": ill_id})

    if event_type == "ILL_RETURN_INITIATED":
        ill_id = payload.get("ill_request_id")
        if not isinstance(ill_id, str):
            raise err("ERR_INVALID_INPUT", "ILL_RETURN_INITIATED requires ill_request_id")
        ill = get_ill_request(ill_id)
        if ill["status"] != "AT_PARTNER":
            raise err("ERR_INVALID_STATE",
                      f"ILLRequest is {ill['status']}, not AT_PARTNER")
        # Loan period gate
        from datetime import timedelta
        start = parse_iso(ill["in_transit_from"]) if ill.get("in_transit_from") else None
        if start is None or now() < start + timedelta(days=ill.get("agreed_loan_days", 0)):
            raise err("ERR_ILL_LOAN_PERIOD_NOT_MET",
                      "ILL_RETURN_INITIATED before loan period elapsed")
        ill["status"] = "RETURNED_TRANSIT"
        db.stamp_update(ill)
        return success({"event_type": event_type, "ill_request_id": ill_id})

    raise err("ERR_INVALID_INPUT", f"Unknown event_type: {event_type}")
