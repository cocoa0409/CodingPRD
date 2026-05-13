"""Pile state transitions and fault cascade."""

from __future__ import annotations

import db
from clock import now_iso
from services import audit, queue_service


def set_operational(pile: dict, new_state: str | None) -> None:
    pile["operational_state"] = new_state
    db.bump(pile)


def cascade_fault(pile: dict, actor_role: str, actor_id: str) -> None:
    """Pile -> FAULT side effects:
       - cancel HELD reservations on this pile (no strike)
       - abort any in-flight CHARGING session on this pile
       - re-rank WAITING queue entries (no removal)
    """
    # Cancel HELD reservations on this pile.
    for res in list(db.reservations.values()):
        if res["pile_id"] == pile["id"] and res["status"] == "HELD":
            res["status"] = "CANCELLED"
            db.bump(res)

    # Abort in-flight CHARGING session on this pile.
    for sess in list(db.sessions.values()):
        if sess["pile_id"] == pile["id"] and sess["status"] == "CHARGING":
            sess["status"] = "ABORTED"
            sess["ended_at"] = now_iso()
            events = list(sess.get("abnormal_events") or [])
            events.append({"type": "COMMUNICATION_LOSS", "at": now_iso()})
            sess["abnormal_events"] = events
            sess["electricity_fee_cents"] = 0
            sess["service_fee_cents"] = 0
            sess["tax_cents"] = 0
            sess["total_cents"] = 0
            db.bump(sess)
            audit.write(
                actor_role=actor_role,
                actor_id=actor_id,
                entity_kind="ChargingSession",
                entity_id=sess["id"],
                event_kind="FAULT_EVENT",
                payload={"reason": "fault_cascade"},
            )

    # Set the pile to FAULT and bump.
    set_operational(pile, "FAULT")

    # Re-rank waiting entries — they remain but their positions are unchanged
    # because no entry was removed; nothing to do operationally beyond the
    # documented "re-ranked but not removed" no-op.


def station_for_pile(pile: dict) -> dict | None:
    return db.stations.get(pile["station_id"])


def resolve_fault_chain(pile: dict, actor_role: str, actor_id: str) -> None:
    """Set pile back to IDLE and fire queue-promotion at the parent station."""
    set_operational(pile, "IDLE")
    queue_service.promote_if_possible(pile["station_id"])
