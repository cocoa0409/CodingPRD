"""System hooks: /_clock/advance and external event ingest."""
from flask import Blueprint, request, g

import db
from clock import set_now, parse_iso, iso, now
from errors import err
from middleware import require_auth
from response import success
from services import audit, sweep


bp = Blueprint("system", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


@bp.post("/_clock/advance")
@require_auth(roles={"PlatformAdmin"})
def clock_advance():
    body = _get_body()
    target = body.get("target_time")
    if not target or not isinstance(target, str):
        raise err("ERR_BAD_REQUEST", "target_time is required")
    try:
        dt = parse_iso(target)
    except ValueError:
        raise err("ERR_BAD_REQUEST", "target_time is not a valid ISO 8601 timestamp")
    set_now(dt)
    sweep.run_due_transitions()
    return success({"current_time": iso(now())})


@bp.post("/_events/payment-confirmed")
@require_auth(roles={"PlatformAdmin"})
def event_payment_confirmed():
    body = _get_body()
    reservation_id = body.get("reservation_id")
    external_payment_id = body.get("external_payment_id")
    if not reservation_id or not external_payment_id:
        raise err("ERR_BAD_REQUEST", "reservation_id and external_payment_id are required")
    # PRD §3.8 / §2.11: idempotency on the COMBINATION (reservation_id,
    # external_payment_id). A repeated event with the same pair is a
    # no-op. A repeated event with the same reservation_id but a
    # contradictory external_payment_id — or vice versa — yields
    # ERR_IDEMPOTENCY_CONFLICT.
    existing_res_for_pay = db.payment_ingest_log.get(external_payment_id)
    if existing_res_for_pay is not None and existing_res_for_pay != reservation_id:
        raise err("ERR_IDEMPOTENCY_CONFLICT",
                  "external_payment_id already bound to another reservation")
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "reservation not found")
    # Inverse direction: same reservation_id with a different
    # external_payment_id is also a contradiction.
    existing_pay_for_res = r.get("_payment_external_id")
    if existing_pay_for_res is not None and existing_pay_for_res != external_payment_id:
        raise err("ERR_IDEMPOTENCY_CONFLICT",
                  "reservation already bound to a different external_payment_id")
    if existing_res_for_pay == reservation_id:
        # Idempotent replay: return the reservation
        return success(db.public(r))
    db.payment_ingest_log[external_payment_id] = reservation_id
    r["_payment_external_id"] = external_payment_id
    # Record audit event PAYMENT_CONFIRMED
    audit.record(
        subject_type="RESERVATION",
        subject_id=r["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="PAYMENT_CONFIRMED",
        from_state=r["status"],
        to_state=r["status"],
        payload_json={"external_payment_id": external_payment_id},
    )
    # Inter-department cost transfer ledger row
    eq = db.equipment.get(r["equipment_id"])
    lab = db.labs.get(eq["lab_id"]) if eq else None
    user = db.users.get(r["user_id"])
    if r["status"] == "COMPLETED":
        amount = int(r.get("final_owner_share_cents", 0) or 0)
    else:
        amount = int(r.get("estimated_owner_share_cents", 0) or 0)
    db.cost_transfer_ledger.append({
        "reservation_id": r["id"],
        "external_payment_id": external_payment_id,
        "debit_department": user["department"] if user else None,
        "credit_department": lab["department"] if lab else None,
        "amount_cents": amount,
        "created_at": iso(now()),
    })
    return success(db.public(r))


@bp.post("/_events/identity-verified")
@require_auth(roles={"PlatformAdmin"})
def event_identity_verified():
    body = _get_body()
    external_user_id = body.get("external_user_id")
    if not external_user_id:
        raise err("ERR_BAD_REQUEST", "external_user_id is required")
    user_id = db.user_external_index.get(external_user_id)
    if user_id is None:
        raise err("ERR_NOT_FOUND", "user with external_user_id not found")
    user = db.users[user_id]
    if user.get("identity_verified"):
        # Idempotent replay
        return success(db.public(user))
    user["identity_verified"] = True
    db.stamp_update(user)
    return success(db.public(user))


@bp.post("/_events/im-notified")
@require_auth(roles={"PlatformAdmin"})
def event_im_notified():
    body = _get_body()
    audit_event_id = body.get("audit_event_id")
    im_delivery_id = body.get("im_delivery_id")
    if not audit_event_id or not im_delivery_id:
        raise err("ERR_BAD_REQUEST", "audit_event_id and im_delivery_id are required")
    ev = db.audit_events.get(audit_event_id)
    if ev is None:
        raise err("ERR_NOT_FOUND", "audit_event not found")
    key = (audit_event_id, im_delivery_id)
    if key in db.im_ingest_log:
        # Idempotent replay
        return success({})
    # Check for conflicting prior im_delivery_id
    existing = ev["payload_json"].get("im_delivery_id")
    if existing is not None and existing != im_delivery_id:
        raise err("ERR_IDEMPOTENCY_CONFLICT",
                  "audit_event already has a different im_delivery_id")
    ev["payload_json"]["im_delivery_id"] = im_delivery_id
    db.im_ingest_log[key] = True
    return success({})
