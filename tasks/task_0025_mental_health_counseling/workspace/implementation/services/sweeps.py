"""System-driven sweeps: holds, no-show, recert, retention, risk."""
from datetime import timedelta

import db
from clock import now, parse_iso, iso
from services import audit
from services.cascades import suspend_counselor_cascade
from services.risk import recompute_for_client


def hold_expiry():
    """HELD slots whose held_until <= now -> OPEN; their appts -> CANCELLED NO_SHOW_AUTO."""
    cur = now()
    for slot in list(db.availability_slots.values()):
        if slot["status"] != "HELD":
            continue
        held_until = slot.get("held_until")
        if not held_until:
            continue
        if parse_iso(held_until) > cur:
            continue
        appt_id = slot.get("held_appointment_id")
        slot["status"] = "OPEN"
        slot["held_until"] = None
        slot["held_appointment_id"] = None
        db.stamp_update(slot)
        appt = db.appointments.get(appt_id) if appt_id else None
        if appt is not None and appt["status"] == "HOLD":
            appt["status"] = "CANCELLED"
            appt["cancellation_reason"] = "NO_SHOW_AUTO"
            db.stamp_update(appt)


def no_show():
    """CONFIRMED appts past start_at + 30m -> NO_SHOW NON_REFUNDABLE."""
    cur = now()
    for appt in list(db.appointments.values()):
        if appt["status"] != "CONFIRMED":
            continue
        start = parse_iso(appt["start_at"])
        if cur < start + timedelta(minutes=30):
            continue
        appt["status"] = "NO_SHOW"
        appt["cancellation_reason"] = "NO_SHOW_AUTO"
        appt["refund_state"] = "NON_REFUNDABLE"
        db.stamp_update(appt)
        slot = db.availability_slots.get(appt.get("slot_id"))
        if slot is not None and slot["status"] in ("HELD", "BOOKED"):
            slot["status"] = "RELEASED"
            slot["held_until"] = None
            slot["held_appointment_id"] = None
            db.stamp_update(slot)


def recert(actor_user_id):
    """Cycles past deadline -> EXPIRED (with cascade to counselor)."""
    cur = now()
    for cyc in list(db.certification_cycles.values()):
        if cyc["status"] == "OPEN" and cur >= parse_iso(cyc["window_end_at"]):
            _expire_cycle(cyc, actor_user_id)
        elif cyc["status"] == "UNDER_REVIEW":
            deadline = parse_iso(cyc["window_end_at"]) + timedelta(days=14)
            if cur >= deadline:
                _expire_cycle(cyc, actor_user_id)


def _expire_cycle(cyc: dict, actor_user_id):
    cyc["status"] = "EXPIRED"
    cyc["decided_at"] = iso(now())
    cyc["decided_by_user_id"] = None
    db.stamp_update(cyc)
    counselor = db.counselors.get(cyc["counselor_id"])
    if counselor is not None and counselor["status"] == "ACTIVE":
        suspend_counselor_cascade(counselor)
    audit.append(
        actor_role="system", actor_user_id=actor_user_id,
        action="RECERT_DECISION",
        target_entity="CertificationCycle", target_id=cyc["id"],
        payload_summary={"decision": "EXPIRED"},
    )


def retention(actor_user_id):
    """ACTIVE counseling records past retention_expires_at -> PURGED."""
    cur = now()
    for rec in list(db.counseling_records.values()):
        if rec["redaction_status"] != "ACTIVE":
            continue
        ret = rec.get("retention_expires_at")
        if not ret:
            continue
        if cur < parse_iso(ret):
            continue
        rec["encrypted_note_blob"] = None
        rec["content_key_wrapped"] = None
        rec["redaction_status"] = "PURGED"
        # CounselingRecord has no version/updated_at
        audit.append(
            actor_role="system", actor_user_id=actor_user_id,
            action="RECORD_PURGE",
            target_entity="CounselingRecord", target_id=rec["id"],
            payload_summary={},
        )


def risk_recompute():
    """Recompute risk_flag for all clients."""
    for client in db.clients.values():
        recompute_for_client(client["id"])
