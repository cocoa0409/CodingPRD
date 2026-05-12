"""Session endpoints: entry, read, exit, pay, waive."""
from datetime import timedelta

from flask import Blueprint, g

import db
from clock import now, parse_iso, iso
from errors import err
from middleware import require_auth
from response import success
from services.validation import (
    get_body, require_str, require_int, require_field, require_reason,
)
from services.projection import session_view
from services.billing import compute_session_fee, settlement_day_key
from services.payment import create_payment
from services.revenue import (
    create_revenue_entry, compute_card_balances, round_half_up_to_int,
)
from services.zones import recompute_zone_counts
from services.audit import write_audit
from services.cards import is_card_valid_now, expire_card_if_due
from services.reservations import reservation_match_credit
from routes.vehicles import normalize_plate, PLATE_REGEX


bp = Blueprint("sessions", __name__)


# ============================================================================
# Helpers
# ============================================================================

def _resolve_vehicle_for_entry(body):
    vid = body.get("vehicle_id")
    if vid:
        v = db.vehicles.get(vid)
        if v is None:
            raise err("ERR_NOT_FOUND", "Vehicle not found")
        return v
    plate_raw = body.get("plate")
    if plate_raw:
        plate = normalize_plate(plate_raw)
        if not plate or not PLATE_REGEX.match(plate):
            raise err("ERR_BAD_REQUEST", "plate must match the LPR regex after normalization")
        for v in db.vehicles.values():
            if v.get("plate") == plate:
                return v
        # Auto-register the vehicle on first sight per LPR semantics? PRD §3.5 says
        # "supply either a vehicle_id or a plate" but doesn't say to auto-register.
        # Safer: return ERR_NOT_FOUND to surface the missing-FK condition.
        raise err("ERR_NOT_FOUND", "Vehicle with this plate not found")
    raise err("ERR_BAD_REQUEST", "either vehicle_id or plate is required")


def _find_matching_held_reservation(vehicle_id, space, lot):
    """Return a HELD reservation that matches this gate-in, or None."""
    if space is None:
        return None
    n = now()
    # Window: [scheduled_start_at - 5m, scheduled_start_at + reservation_hold_minutes]
    hold = int(lot.get("reservation_hold_minutes", 15))
    for r in db.reservations.values():
        if r.get("status") != "HELD":
            continue
        if r.get("space_id") != space["id"]:
            continue
        if r.get("vehicle_id") != vehicle_id:
            continue
        try:
            sched = parse_iso(r["scheduled_start_at"])
        except Exception:
            continue
        if sched - timedelta(minutes=5) <= n <= sched + timedelta(minutes=hold):
            return r
    return None


def _select_entry_space(lot, body, matching_res=None):
    """Resolve which Space the session should enter."""
    space_id = body.get("space_id")
    if space_id:
        space = db.spaces.get(space_id)
        if space is None or space.get("lot_id") != lot["id"]:
            raise err("ERR_NOT_FOUND", "Space not found in lot")
        return space
    # Fall through: pick the lex-smallest-label FREE candidate respecting tow_grace
    candidates = []
    tow_grace = int(lot.get("tow_grace_minutes", 5))
    n = now()
    for s in db.spaces.values():
        if s.get("lot_id") != lot["id"]:
            continue
        if s.get("occupancy_status") != "FREE":
            continue
        if s.get("reservation_lock") == "RESERVED":
            continue  # held by someone else
        last_exit = s.get("last_exited_at")
        if last_exit is not None:
            try:
                le = parse_iso(last_exit)
                if n < le + timedelta(minutes=tow_grace):
                    continue
            except Exception:
                pass
        candidates.append(s)
    if not candidates:
        raise err("ERR_NO_SPACE_AVAILABLE", "No FREE space available for gate-in")
    candidates.sort(key=lambda s: (s.get("label") or "", s.get("id") or ""))
    return candidates[0]


# ============================================================================
# Endpoints
# ============================================================================

@bp.route("/lots/<lot_id>/sessions", methods=["POST"])
@require_auth(roles={"GateSystem", "Operator"})
def create_session(lot_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    body = get_body()

    vehicle = _resolve_vehicle_for_entry(body)

    card_id = body.get("card_id")
    if card_id is not None:
        card = db.cards.get(card_id)
        if card is None:
            raise err("ERR_NOT_FOUND", "Card not found")

    # Determine target space — possibly via reservation match
    space_id = body.get("space_id")
    target_space = None
    matching_res = None

    if space_id:
        target_space = db.spaces.get(space_id)
        if target_space is None or target_space.get("lot_id") != lot_id:
            raise err("ERR_NOT_FOUND", "Space not found in lot")
        matching_res = _find_matching_held_reservation(vehicle["id"], target_space, lot)
    else:
        # Look for any HELD reservation matching this vehicle whose space is
        # bookable now; otherwise fall back to selector.
        n = now()
        hold = int(lot.get("reservation_hold_minutes", 15))
        candidate_match = None
        for r in db.reservations.values():
            if r.get("status") != "HELD":
                continue
            if r.get("vehicle_id") != vehicle["id"]:
                continue
            try:
                sched = parse_iso(r["scheduled_start_at"])
            except Exception:
                continue
            if not (sched - timedelta(minutes=5) <= n <= sched + timedelta(minutes=hold)):
                continue
            sp = db.spaces.get(r.get("space_id"))
            if sp is None or sp.get("occupancy_status") != "FREE":
                continue
            candidate_match = (r, sp)
            break
        if candidate_match is not None:
            matching_res, target_space = candidate_match
        else:
            target_space = _select_entry_space(lot, body)

    # Entry admission (priority 6 / 10)
    if target_space.get("occupancy_status") != "FREE":
        raise err("ERR_SPACE_OCCUPIED", "Space is currently occupied")

    if target_space.get("reservation_lock") == "RESERVED" and matching_res is None:
        raise err("ERR_SPACE_NOT_BOOKABLE",
                  "Space is reserved by another vehicle's HELD reservation")

    # tow_grace check when not held by a matching reservation
    if target_space.get("reservation_lock") == "UNRESERVED":
        last_exit = target_space.get("last_exited_at")
        if last_exit is not None:
            try:
                le = parse_iso(last_exit)
            except Exception:
                le = None
            if le is not None:
                tow_grace = int(lot.get("tow_grace_minutes", 5))
                if now() < le + timedelta(minutes=tow_grace):
                    raise err("ERR_SPACE_NOT_BOOKABLE",
                              "Space inside post-exit tow-grace buffer")

    # Build session row
    sess = {
        "lot_id": lot_id,
        "space_id": target_space["id"],
        "vehicle_id": vehicle["id"],
        "card_id": card_id,
        "reservation_id": matching_res["id"] if matching_res else None,
        "occupancy_status": "ACTIVE",
        "payment_status": "UNPAID",
        "entry_at": iso(now()),
        "exit_at": None,
        "estimated_fee_cents": 0,
        "final_fee_cents": None,
        "billing_kind": None,
    }
    db.stamp_create(sess)
    db.sessions_tbl[sess["id"]] = sess

    # Side effects: Space → OCCUPIED
    target_space["occupancy_status"] = "OCCUPIED"
    target_space["current_session_id"] = sess["id"]
    db.stamp_update(target_space)

    # Reservation match — if applicable
    if matching_res is not None:
        matching_res["status"] = "MATCHED"
        matching_res["matched_session_id"] = sess["id"]
        db.stamp_update(matching_res)
        target_space["reservation_lock"] = "UNRESERVED"
        db.stamp_update(target_space)
        # Revenue entry: negative discount
        lot_rec = db.parking_lots.get(lot_id)
        discount = reservation_match_credit(matching_res, lot_rec)
        create_revenue_entry(
            lot_id=lot_id,
            zone_id=target_space.get("zone_id"),
            billing_type="RESERVATION",
            source_kind="RESERVATION",
            source_id=matching_res["id"],
            gross_amount_cents=-discount,
        )

    # Recompute zone counts (occupancy went FREE→OCCUPIED)
    recompute_zone_counts(target_space["zone_id"])

    return success(session_view(sess), status=201)


@bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth(roles={"Driver", "Operator", "ParkingPartner", "GateSystem", "Auditor"})
def get_session(session_id):
    s = db.sessions_tbl.get(session_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Session not found")
    if g.user_role == "Driver" and s.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")
    return success(session_view(s))


@bp.route("/sessions/<session_id>/exit", methods=["POST"])
@require_auth(roles={"GateSystem", "Operator"})
def exit_session(session_id):
    s = db.sessions_tbl.get(session_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Session not found")
    if s.get("occupancy_status") != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Session is not ACTIVE")

    # Pin exit_at and run final billing
    s["exit_at"] = iso(now())
    fee, kind = compute_session_fee(s, variant="final")
    s["final_fee_cents"] = int(fee)
    s["billing_kind"] = kind
    s["occupancy_status"] = "EXITED"
    db.stamp_update(s)

    # Free the space
    space = db.spaces.get(s.get("space_id")) if s.get("space_id") else None
    if space is not None:
        space["occupancy_status"] = "FREE"
        space["last_exited_at"] = s["exit_at"]
        space["current_session_id"] = None
        db.stamp_update(space)
        recompute_zone_counts(space["zone_id"])

    # Auto-pay cascade if pinned card has auto_pay_enabled
    if s.get("card_id"):
        card = db.cards.get(s["card_id"])
        if card is not None and card.get("auto_pay_enabled") and card.get("status") == "ACTIVE":
            _auto_settle_session(s, card)

    return success(session_view(s))


def _auto_settle_session(s: dict, card: dict):
    """Auto-pay a session with a stored-value card (or a monthly-covered $0 fee)."""
    fee = int(s.get("final_fee_cents") or 0)
    if s.get("billing_kind") == "EXEMPT_VEHICLE":
        # Exempt → no fee, no payment, no revenue entry needed.
        return
    if fee == 0 and s.get("billing_kind") == "MONTHLY_COVERED":
        # Mark as PAID with a $0 SESSION_FEE? PRD says payment_status UNPAID→PAID
        # via cascade in this case. Create $0 revenue entry billing_type=MONTHLY.
        s["payment_status"] = "PAID"
        db.stamp_update(s)
        space = db.spaces.get(s.get("space_id")) if s.get("space_id") else None
        zone_id = space.get("zone_id") if space else None
        create_revenue_entry(
            lot_id=s["lot_id"],
            zone_id=zone_id,
            billing_type="MONTHLY",
            source_kind="SESSION",
            source_id=s["id"],
            gross_amount_cents=0,
        )
        return
    if fee == 0:
        return  # zero-fee non-monthly — leave UNPAID per conservative semantics
    # Stored-value path
    if card.get("card_type") == "STORED_VALUE":
        prov, _ = compute_card_balances(card["id"])
        if prov < fee:
            return  # not enough funds — leave UNPAID; no error in cascade
        create_payment(
            kind="SESSION_FEE",
            subject_id=s["id"],
            amount_cents=fee,
            card_id=card["id"],
        )
        s["payment_status"] = "PAID"
        db.stamp_update(s)
        space = db.spaces.get(s.get("space_id")) if s.get("space_id") else None
        zone_id = space.get("zone_id") if space else None
        create_revenue_entry(
            lot_id=s["lot_id"],
            zone_id=zone_id,
            billing_type="HOURLY",
            source_kind="SESSION",
            source_id=s["id"],
            gross_amount_cents=fee,
        )


@bp.route("/sessions/<session_id>/pay", methods=["POST"])
@require_auth(roles={"Driver", "Operator"})
def pay_session(session_id):
    s = db.sessions_tbl.get(session_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Session not found")
    if g.user_role == "Driver" and s.get("vehicle_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Driver scope mismatch")
    body = get_body() if True else {}
    if not isinstance(body, dict):
        body = {}
    card_id = body.get("card_id") if body else None
    external_ref = body.get("external_ref") if body else None
    if card_id is not None:
        card = db.cards.get(card_id)
        if card is None:
            raise err("ERR_NOT_FOUND", "Card not found")
    # Priority 6 state
    if s.get("occupancy_status") != "EXITED":
        raise err("ERR_INVALID_STATE", "Session is not EXITED")
    if s.get("payment_status") != "UNPAID":
        raise err("ERR_INVALID_STATE",
                  f"Session payment_status is {s.get('payment_status')}, not UNPAID")
    # Priority 7: exempt vehicle rejection
    veh = db.vehicles.get(s.get("vehicle_id"))
    if veh and veh.get("kind") in ("EMERGENCY", "DISABLED"):
        raise err("ERR_EXEMPT_VEHICLE",
                  "Cannot charge exempt vehicle's session")

    fee = int(s.get("final_fee_cents") or 0)
    used_card_id = card_id if card_id else s.get("card_id")
    used_card = db.cards.get(used_card_id) if used_card_id else None
    if used_card is not None:
        # priority 12: card validity
        if not is_card_valid_now(used_card):
            raise err("ERR_CARD_EXPIRED", "Card is expired or outside validity window")

    # Sufficient funds for STORED_VALUE
    if used_card is not None and used_card.get("card_type") == "STORED_VALUE":
        prov, _ = compute_card_balances(used_card["id"])
        if prov < fee:
            raise err("ERR_INSUFFICIENT_BALANCE", "Card balance below required amount")

    # Pin card_id on session if not yet
    if not s.get("card_id") and used_card_id:
        s["card_id"] = used_card_id

    create_payment(
        kind="SESSION_FEE",
        subject_id=s["id"],
        amount_cents=fee,
        card_id=used_card_id if used_card else None,
        external_ref=external_ref,
    )
    s["payment_status"] = "PAID"
    db.stamp_update(s)

    space = db.spaces.get(s.get("space_id")) if s.get("space_id") else None
    zone_id = space.get("zone_id") if space else None
    bk = s.get("billing_kind")
    billing_type = "MONTHLY" if bk == "MONTHLY_COVERED" else "HOURLY"
    create_revenue_entry(
        lot_id=s["lot_id"],
        zone_id=zone_id,
        billing_type=billing_type,
        source_kind="SESSION",
        source_id=s["id"],
        gross_amount_cents=fee,
    )
    return success(session_view(s))


@bp.route("/sessions/<session_id>/waive", methods=["POST"])
@require_auth(roles={"Operator"})
def waive_session(session_id):
    s = db.sessions_tbl.get(session_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Session not found")
    body = get_body()
    reason = require_reason(body)
    if s.get("occupancy_status") != "EXITED":
        raise err("ERR_INVALID_STATE", "Session is not EXITED")
    if s.get("payment_status") != "UNPAID":
        raise err("ERR_INVALID_STATE",
                  f"Session payment_status is {s.get('payment_status')}, not UNPAID")
    before = {"payment_status": s.get("payment_status")}
    s["payment_status"] = "WAIVED"
    db.stamp_update(s)
    after = {"payment_status": s.get("payment_status")}
    space = db.spaces.get(s.get("space_id")) if s.get("space_id") else None
    zone_id = space.get("zone_id") if space else None
    fee = int(s.get("final_fee_cents") or 0)
    create_revenue_entry(
        lot_id=s["lot_id"],
        zone_id=zone_id,
        billing_type="ADJUSTMENT",
        source_kind="SESSION",
        source_id=s["id"],
        gross_amount_cents=-fee,
        notes=reason,
    )
    write_audit(
        action="BILLING_ADJUSTMENT",
        subject_kind="Session",
        subject_id=s["id"],
        before=before,
        after=after,
        reason=reason,
    )
    return success(session_view(s))
