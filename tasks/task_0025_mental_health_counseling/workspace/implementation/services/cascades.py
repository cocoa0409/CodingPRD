"""Cross-entity cascades: counselor disqualification/suspension, refunds, etc."""
from clock import now, iso, parse_iso

import db
from services import audit
from services.calculations import appointment_refund


def _refresh(d: dict):
    db.stamp_update(d)


def _make_refund_ledger_row(appt: dict, components: dict):
    """Append a REFUND row with negative-signed amounts."""
    row = {
        "appointment_id": appt["id"],
        "direction": "REFUND",
        "gross_amount_cents": -components["gross_amount_cents"],
        "tax_cents": -components["tax_cents"],
        "counselor_share_cents": -components["counselor_share_cents"],
        "platform_share_cents": -components["platform_share_cents"],
        "payout_id": None,
    }
    db.stamp_create(row, common_fields=False)
    db.settlement_ledger[row["id"]] = row
    return row


def cancel_confirmed_appointment(*, appt: dict, reason: str,
                                  actor_role: str, actor_user_id):
    """CONFIRMED -> CANCELLED with refund, slot release, ledger row."""
    counselor = db.counselors[appt["counselor_id"]]
    client = db.clients[appt["client_id"]]
    start_at_dt = parse_iso(appt["start_at"]) if appt.get("start_at") else None

    # Compute hours_to_start using current clock
    hours = ((start_at_dt - now()).total_seconds() / 3600.0
             if start_at_dt else 0.0)

    components = appointment_refund(
        list_price_cents=appt["list_price_cents"],
        revenue_share_bps=counselor["revenue_share_bps"],
        cancellation_reason=reason,
        hours_to_start=hours,
    )

    appt["status"] = "CANCELLED"
    appt["cancellation_reason"] = reason
    appt["refund_state"] = components["refund_state"]
    _refresh(appt)

    # Release the linked slot
    slot = db.availability_slots.get(appt.get("slot_id"))
    if slot is not None and slot["status"] in ("HELD", "BOOKED"):
        slot["status"] = "RELEASED"
        slot["held_until"] = None
        slot["held_appointment_id"] = None
        _refresh(slot)

    if components["refund_state"] in ("FULL_REFUNDED", "PARTIAL_REFUNDED"):
        _make_refund_ledger_row(appt, components)
        if appt["payment_mode"] == "PACKAGE":
            client["package_balance_sessions"] = client.get("package_balance_sessions", 0) + 1
            _refresh(client)

    return appt


def disqualify_counselor(counselor: dict, actor_role: str, actor_user_id, reason=None):
    """Move counselor to DISQUALIFIED and execute the three-layer cascade."""
    counselor["status"] = "DISQUALIFIED"
    _refresh(counselor)

    # Layer 1: AvailabilitySlots in OPEN/HELD -> RELEASED
    for slot in list(db.availability_slots.values()):
        if slot["counselor_id"] != counselor["id"]:
            continue
        if slot["status"] in ("OPEN", "HELD"):
            slot["status"] = "RELEASED"
            slot["held_until"] = None
            slot["held_appointment_id"] = None
            _refresh(slot)

    # Layer 2: Appointments in HOLD -> CANCELLED (no refund)
    for appt in list(db.appointments.values()):
        if appt["counselor_id"] != counselor["id"]:
            continue
        if appt["status"] == "HOLD":
            appt["status"] = "CANCELLED"
            appt["cancellation_reason"] = "COUNSELOR_CANCEL"
            _refresh(appt)

    # Layer 3: Appointments in CONFIRMED future -> cancel + refund
    for appt in list(db.appointments.values()):
        if appt["counselor_id"] != counselor["id"]:
            continue
        if appt["status"] == "CONFIRMED":
            cancel_confirmed_appointment(
                appt=appt, reason="COUNSELOR_CANCEL",
                actor_role=actor_role, actor_user_id=actor_user_id,
            )

    audit.append(
        actor_role=actor_role, actor_user_id=actor_user_id,
        action="COUNSELOR_DISQUALIFIED",
        target_entity="Counselor", target_id=counselor["id"],
        payload_summary={"reason": reason} if reason else {},
    )
    return counselor


def suspend_counselor_cascade(counselor: dict):
    """When ACTIVE -> SUSPENDED: OPEN slots -> BLOCKED; HOLD appts cancelled."""
    counselor["status"] = "SUSPENDED"
    _refresh(counselor)

    for slot in list(db.availability_slots.values()):
        if slot["counselor_id"] != counselor["id"]:
            continue
        if slot["status"] == "OPEN":
            slot["status"] = "BLOCKED"
            _refresh(slot)
        elif slot["status"] == "HELD":
            # Per §3.2 "every appointment of that counselor still in HOLD auto-cancels"
            appt = db.appointments.get(slot.get("held_appointment_id"))
            if appt is not None and appt["status"] == "HOLD":
                appt["status"] = "CANCELLED"
                appt["cancellation_reason"] = "COUNSELOR_CANCEL"
                _refresh(appt)
            slot["status"] = "BLOCKED"
            slot["held_until"] = None
            slot["held_appointment_id"] = None
            _refresh(slot)
    return counselor


def crisis_handover_cascade(*, incident: dict, actor_role: str, actor_user_id):
    """When a CrisisIncident moves to HANDED_OVER and its appointment is IN_SESSION,
    cancel the appointment with reason CRISIS_HANDOVER, full refund, etc."""
    appt_id = incident.get("appointment_id")
    if not appt_id:
        return
    appt = db.appointments.get(appt_id)
    if appt is None:
        return
    if appt["status"] != "IN_SESSION":
        return
    counselor = db.counselors[appt["counselor_id"]]
    client = db.clients[appt["client_id"]]

    components = appointment_refund(
        list_price_cents=appt["list_price_cents"],
        revenue_share_bps=counselor["revenue_share_bps"],
        cancellation_reason="CRISIS_HANDOVER",
        hours_to_start=0.0,  # already started
    )
    appt["status"] = "CANCELLED"
    appt["cancellation_reason"] = "CRISIS_HANDOVER"
    appt["refund_state"] = components["refund_state"]
    _refresh(appt)

    slot = db.availability_slots.get(appt.get("slot_id"))
    if slot is not None and slot["status"] in ("HELD", "BOOKED"):
        slot["status"] = "RELEASED"
        slot["held_until"] = None
        slot["held_appointment_id"] = None
        _refresh(slot)

    if components["refund_state"] in ("FULL_REFUNDED", "PARTIAL_REFUNDED"):
        row = {
            "appointment_id": appt["id"],
            "direction": "REFUND",
            "gross_amount_cents": -components["gross_amount_cents"],
            "tax_cents": -components["tax_cents"],
            "counselor_share_cents": -components["counselor_share_cents"],
            "platform_share_cents": -components["platform_share_cents"],
            "payout_id": None,
        }
        db.stamp_create(row, common_fields=False)
        db.settlement_ledger[row["id"]] = row
        if appt["payment_mode"] == "PACKAGE":
            client["package_balance_sessions"] = client.get("package_balance_sessions", 0) + 1
            _refresh(client)
