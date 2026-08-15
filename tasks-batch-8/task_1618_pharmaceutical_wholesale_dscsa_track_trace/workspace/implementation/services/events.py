"""EPCIS event ledger: hash chaining, case state transitions, unit cascades.

PRD §3.3: events both record and drive the case state machine. Each event's
txn_history_hash chains the case's transaction history: the first event
recorded for a case carries an empty string; thereafter the digest chains the
previous event (greatest event_time, ties broken by greatest recorded_at).
"""
import hashlib

import db
from db import store


def previous_event(case_id):
    """The prior event for the case: greatest event_time, ties broken by
    greatest recorded_at; internal insertion order breaks further ties (the
    server rejects captured duplicates of event_time+recorded_at)."""
    events = [e for e in store.epcis_events.values()
              if e["subject_case_id"] == case_id]
    if not events:
        return None
    return max(events, key=lambda e: (e["event_time"], e["recorded_at"], e["_seq"]))


def compute_txn_hash(case_id, event_type, event_time):
    prev = previous_event(case_id)
    if prev is None:
        return ""
    material = prev["txn_history_hash"] + event_type + db.iso_logical(event_time)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append_event(event_type, case, event_time, order_id=None,
                 sender_partner_id=None, recipient_partner_id=None):
    """Append an immutable EpcisEvent ledger entry (captured or system-appended)."""
    now = db.logical_now()
    event = {
        "id": db.new_id(),
        "event_type": event_type,
        "subject_case_id": case["id"],
        "order_id": order_id,
        "event_time": db.iso_logical(event_time),
        "recorded_at": db.iso_logical(now),
        "sender_partner_id": sender_partner_id,
        "recipient_partner_id": recipient_partner_id,
        "txn_history_hash": compute_txn_hash(case["id"], event_type, event_time),
    }
    db.new_event_common(event)
    store.epcis_events[event["id"]] = event
    return event


def units_of(case_id):
    return [u for u in store.serialized_units.values() if u["case_id"] == case_id]


def transition_case(case, new_status, unit_from, unit_to=None):
    """Move the case and cascade its units; each mutation bumps version and
    refreshes updated_at (PRD §2.4, including cascaded mutations)."""
    case["case_status"] = new_status
    db.touch(case)
    for unit in units_of(case["id"]):
        if unit_from is None or unit["unit_status"] in unit_from:
            unit["unit_status"] = unit_to or new_status
            db.touch(unit)


def ship_case(case, order_id=None):
    """COMMISSIONED -> SHIPPED with units following; appends a SHIP event."""
    transition_case(case, "SHIPPED", unit_from={"COMMISSIONED"})
    append_event("SHIP", case, db.logical_now(), order_id=order_id)


def receive_case(case):
    """SHIPPED -> RECEIVED with units following."""
    transition_case(case, "RECEIVED", unit_from={"SHIPPED"})


def decommission_case(case, unit_from=("COMMISSIONED",)):
    """-> DECOMMISSIONED; only units in unit_from follow."""
    transition_case(case, "DECOMMISSIONED", unit_from=set(unit_from))


def quarantine_case(case, investigation_id):
    """-> QUARANTINED from COMMISSIONED/SHIPPED/RECEIVED; every unit that is
    not already DECOMMISSIONED follows; remembers the pre-quarantine status
    for the release rule (PRD §3.6)."""
    case["_pre_quarantine_status"] = case["case_status"]
    case["quarantine_link_id"] = investigation_id
    transition_case(case, "QUARANTINED", unit_from=None, unit_to="QUARANTINED")
    append_event("QUARANTINE", case, db.logical_now())


def release_case(case):
    """Release per PRD §3.6: restore RECEIVED when the case was quarantined
    from RECEIVED, else COMMISSIONED; QUARANTINED units follow."""
    restored = "RECEIVED" if case.get("_pre_quarantine_status") == "RECEIVED" else "COMMISSIONED"
    case["quarantine_link_id"] = None
    case["_pre_quarantine_status"] = None
    transition_case(case, restored, unit_from={"QUARANTINED"}, unit_to=restored)
    append_event("RELEASE", case, db.logical_now())


def decommission_quarantined_case(case):
    """QUARANTINED -> DECOMMISSIONED; QUARANTINED units follow (PRD §3.6)."""
    case["quarantine_link_id"] = None
    case["_pre_quarantine_status"] = None
    transition_case(case, "DECOMMISSIONED", unit_from={"QUARANTINED"})
    append_event("DECOMMISSION", case, db.logical_now())
