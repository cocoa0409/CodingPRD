"""OfflineBatch endpoints (PRD §3.9) — idempotent batch upload and apply."""

import db
import domain
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from flask import Blueprint
from helpers import check_no_undeclared, get_body, ok_object, req_str, require
from routes.sessions import make_session

bp = Blueprint("offline_batches", __name__)

UPLOADERS = ("KioskDevice", "FarmManager")
RECORD_TYPES = ("VISIT_SESSION", "PAYMENT", "HARVEST_LINE")


def _find_session_by_ref(ref):
    for s in db.visit_sessions.values():
        if s["offline_ref"] == ref or s["id"] == ref:
            return s
    return None


def _payload_str(payload, key):
    v = payload.get(key)
    return v if isinstance(v, str) else None


def _payload_int(payload, key, min_value=None):
    v = payload.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    if min_value is not None and v < min_value:
        return None
    return v


def _apply_visit_session(rec, device_id):
    """Returns (outcome, entity_id). Four failure modes land the session
    directly in VOIDED with sync_outcome=SYNC_CONFLICT (PRD §3.9)."""
    payload = rec["payload"]
    window_id = _payload_str(payload, "window_id")
    waiver_id = _payload_str(payload, "waiver_id")
    policy_id = _payload_str(payload, "pricing_policy_id")
    party_size = _payload_int(payload, "party_size", min_value=1)
    container_count = _payload_int(payload, "container_count", min_value=0)
    parking_spaces = _payload_int(payload, "parking_spaces", min_value=0)
    if (
        window_id is None
        or waiver_id is None
        or party_size is None
        or container_count is None
        or parking_spaces is None
    ):
        return "SYNC_CONFLICT", None
    window = db.windows.get(window_id)
    if window is None:
        # Unknown window: conflict and NO session is created.
        return "SYNC_CONFLICT", None
    field = domain.field_of_window(window)
    season = domain.season_of_window(window)
    policy = db.pricing_policies.get(policy_id) if policy_id else None
    day = domain.sales_day_for(season["id"], window["date"]) if season else None
    admission = (
        domain.compute_admission_charge(policy, day, party_size, container_count)
        if policy is not None
        else 0
    )

    def _invalid():
        if window["status"] == "CANCELLED" and window["cancel_reason"] == "WEATHER":
            return True
        waiver = db.waivers.get(waiver_id)
        if waiver is None or season is None:
            return True
        try:
            domain.check_waiver_trio(waiver, season, party_size)
        except Exception:
            return True
        if (
            domain.window_booked_slots(window) + party_size
            > window["picking_capacity_slots"] + domain.OFFLINE_OVERBOOK_ALLOWANCE_SLOTS
        ):
            return True
        if any(s["offline_ref"] == rec["offline_ref"] for s in db.visit_sessions.values()):
            return True
        if policy is None:
            return True
        return False

    if _invalid():
        session = make_session(
            window=window,
            waiver_id=waiver_id,
            policy_id=policy_id,
            party_size=party_size,
            container_count=container_count,
            parking_spaces=parking_spaces,
            origin="OFFLINE",
            offline_ref=rec["offline_ref"],
            device_id=device_id,
            visit_status="VOIDED",
            sync_outcome="SYNC_CONFLICT",
            admission_charge_cents=admission,
        )
        return "SYNC_CONFLICT", session["id"]
    session = make_session(
        window=window,
        waiver_id=waiver_id,
        policy_id=policy_id,
        party_size=party_size,
        container_count=container_count,
        parking_spaces=parking_spaces,
        origin="OFFLINE",
        offline_ref=rec["offline_ref"],
        device_id=device_id,
        visit_status="CHECKED_IN",
        sync_outcome="APPLIED",
        admission_charge_cents=admission,
    )
    return "APPLIED", session["id"]


def _apply_payment(rec):
    payload = rec["payload"]
    session_ref = _payload_str(payload, "session_ref")
    method = _payload_str(payload, "method")
    amount = _payload_int(payload, "amount_cents", min_value=1)
    if session_ref is None or method != "OFFLINE_CARD" or amount is None:
        return "SYNC_CONFLICT", None
    session = _find_session_by_ref(session_ref)
    if session is None:
        return "SYNC_CONFLICT", None
    if session["visit_status"] == "VOIDED":
        payment = domain.new_entity()
        payment.update(
            {
                "session_id": session["id"],
                "kind": "CHARGE",
                "method": "OFFLINE_CARD",
                "amount_cents": amount,
                "idempotency_key": rec["offline_ref"],
                "refunded_amount_cents": 0,
                "status": "FAILED",
            }
        )
        db.payments[payment["id"]] = payment
        domain.touch(session)
        return "SYNC_CONFLICT", payment["id"]
    # Payment idempotency keys are unique per session.
    for p in domain.session_payments(session):
        if p["idempotency_key"] == rec["offline_ref"]:
            return "APPLIED", p["id"]
    payment = domain.new_entity()
    payment.update(
        {
            "session_id": session["id"],
            "kind": "CHARGE",
            "method": "OFFLINE_CARD",
            "amount_cents": amount,
            "idempotency_key": rec["offline_ref"],
            "refunded_amount_cents": 0,
            "status": "SETTLED",
        }
    )
    db.payments[payment["id"]] = payment
    domain.touch(session)
    return "APPLIED", payment["id"]


def _apply_harvest_line(rec):
    payload = rec["payload"]
    session_ref = _payload_str(payload, "session_ref")
    crop_id = _payload_str(payload, "crop_id")
    gross = _payload_int(payload, "gross_weight_oz", min_value=0)
    container_count = _payload_int(payload, "container_count", min_value=0)
    if session_ref is None or crop_id is None or gross is None or container_count is None:
        return "SYNC_CONFLICT", None
    if any(l["offline_ref"] == rec["offline_ref"] for l in db.harvest_lines.values()):
        return "SYNC_CONFLICT", None
    session = _find_session_by_ref(session_ref)
    if session is None:
        return "SYNC_CONFLICT", None
    if session["visit_status"] != "FIELD_ACTIVE":
        return "SYNC_CONFLICT", None
    crop = db.crops.get(crop_id)
    if crop is None:
        return "SYNC_CONFLICT", None
    tare_oz, net_oz, line_charge_cents = domain.compute_line_values(crop, gross, container_count)
    if net_oz < 0:
        return "SYNC_CONFLICT", None
    field = domain.field_of_session(session)
    line = domain.new_entity()
    line.update(
        {
            "session_id": session["id"],
            "field_id": field["id"],
            "crop_id": crop["id"],
            "gross_weight_oz": gross,
            "container_count": container_count,
            "tare_oz": tare_oz,
            "net_oz": net_oz,
            "line_charge_cents": line_charge_cents,
            "status": "PROVISIONAL",
            "offline_ref": rec["offline_ref"],
        }
    )
    db.harvest_lines[line["id"]] = line
    # Weigh-out creation advances the field's version (PRD §2.6).
    domain.touch(field)
    return "APPLIED", line["id"]


@bp.post("/farm/offline-batches")
def create_batch():
    require(UPLOADERS)
    body = get_body()
    check_no_undeclared(body, {"device_id", "batch_id", "records"})
    device_id = req_str(body, "device_id")
    batch_id = req_str(body, "batch_id")
    records = body.get("records")
    # Structural validity is all-or-nothing (ERR_INVALID_REQUEST, 400).
    if not isinstance(records, list) or len(records) == 0:
        raise_err(ERR_INVALID_REQUEST, "records must be a non-empty array")
    seen_seq = set()
    for rec in records:
        if not isinstance(rec, dict):
            raise_err(ERR_INVALID_REQUEST, "Each record must be an object")
        rtype = rec.get("record_type")
        seq = rec.get("sequence_index")
        ref = rec.get("offline_ref")
        payload = rec.get("payload")
        if rtype not in RECORD_TYPES:
            raise_err(ERR_INVALID_REQUEST, "Unknown record_type")
        if isinstance(seq, bool) or not isinstance(seq, int):
            raise_err(ERR_INVALID_REQUEST, "sequence_index must be an integer")
        if seq in seen_seq:
            raise_err(ERR_INVALID_REQUEST, "Duplicate sequence_index within the batch")
        seen_seq.add(seq)
        if not isinstance(ref, str) or ref == "":
            raise_err(ERR_INVALID_REQUEST, "offline_ref is required on every record")
        if not isinstance(payload, dict):
            raise_err(ERR_INVALID_REQUEST, "payload must be an object")
    # Idempotency: (device_id, batch_id) replay returns the stored batch.
    for b in db.offline_batches.values():
        if b["device_id"] == device_id and b["batch_id"] == batch_id:
            return ok_object(domain.serialize_batch(b), 201)
    results = []
    applied = 0
    for rec in sorted(records, key=lambda r: r["sequence_index"]):
        if rec["record_type"] == "VISIT_SESSION":
            outcome, entity_id = _apply_visit_session(rec, device_id)
        elif rec["record_type"] == "PAYMENT":
            outcome, entity_id = _apply_payment(rec)
        else:
            outcome, entity_id = _apply_harvest_line(rec)
        results.append(
            {"offline_ref": rec["offline_ref"], "outcome": outcome, "entity_id": entity_id}
        )
        if outcome == "APPLIED":
            applied += 1
    batch = domain.new_entity()
    batch.update(
        {
            "device_id": device_id,
            "batch_id": batch_id,
            "records": records,
            "status": "APPLIED" if applied == len(records) else "PARTIALLY_APPLIED",
            "results": results,
            "applied_count": applied,
            "conflict_count": len(records) - applied,
        }
    )
    db.offline_batches[batch["id"]] = batch
    return ok_object(domain.serialize_batch(batch), 201)


@bp.get("/farm/offline-batches/<bid>")
def get_batch(bid):
    require(UPLOADERS)
    batch = db.offline_batches.get(bid)
    if batch is None:
        raise_err(ERR_NOT_FOUND, "OfflineBatch not found")
    return ok_object(domain.serialize_batch(batch))
