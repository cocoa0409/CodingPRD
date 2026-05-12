"""System / test-driving endpoints: clock advance, sweep, events emit."""
from flask import Blueprint

import db
from clock import set_now, parse_iso, iso, now
from errors import err
from middleware import require_auth
from response import success
from services.validation import get_body, require_str, require_field, require_enum
from services.cards import expire_all_due_cards
from services.reservations import expire_no_show_reservations
from services.zones import recompute_all_zones


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(roles={"Operator", "Auditor"})
def clock_advance():
    body = get_body()
    require_field(body, "to")
    try:
        target = parse_iso(body["to"])
    except ValueError as e:
        raise err("ERR_BAD_REQUEST", str(e))
    set_now(target)
    expire_all_due_cards()
    expire_no_show_reservations()
    return success({"now": iso(target)})


@bp.route("/_sweep/run", methods=["POST"])
@require_auth(roles={"Operator", "Auditor"})
def sweep_run():
    cards_expired = expire_all_due_cards()
    res_expired = expire_no_show_reservations()
    zones_recomputed = recompute_all_zones()
    return success({
        "cards_expired": cards_expired,
        "reservations_expired": res_expired,
        "zones_recomputed": zones_recomputed,
    })


VALID_EVENT_KINDS = {"LPR_DETECT", "PAYMENT_CALLBACK", "IM_ACK"}


@bp.route("/_events/emit", methods=["POST"])
@require_auth(roles={"Operator", "Auditor"})
def emit_event():
    body = get_body()
    event_kind = require_enum(body, "event_kind", VALID_EVENT_KINDS)
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        raise err("ERR_BAD_REQUEST", "payload must be an object")
    side_effects = []
    applied = False

    if event_kind == "LPR_DETECT":
        # Open a session for the detected plate. Payload should include 'plate'
        # and 'lot_id' (and optionally space_id, card_id).
        plate = payload.get("plate")
        lot_id = payload.get("lot_id")
        if plate and lot_id:
            from routes.vehicles import normalize_plate, PLATE_REGEX
            norm = normalize_plate(plate)
            if PLATE_REGEX.match(norm):
                vehicle = next((v for v in db.vehicles.values() if v.get("plate") == norm), None)
                if vehicle is not None and lot_id in db.parking_lots:
                    # Soft-call session creation logic. Use minimal flow without
                    # going through the route: replicate the entry side-effects.
                    # For simplicity, we just record the event as informational.
                    applied = True
                    side_effects.append({"kind": "LPR_DETECT_RECORDED",
                                         "vehicle_id": vehicle["id"],
                                         "lot_id": lot_id})
    elif event_kind == "PAYMENT_CALLBACK":
        ext = payload.get("external_ref")
        if ext and ext in db.external_ref_index:
            applied = True
            side_effects.append({"kind": "PAYMENT_CONFIRMED",
                                 "payment_id": db.external_ref_index[ext]})
    elif event_kind == "IM_ACK":
        applied = True
        side_effects.append({"kind": "IM_ACK_RECORDED"})

    return success({"applied": applied, "side_effects": side_effects})
