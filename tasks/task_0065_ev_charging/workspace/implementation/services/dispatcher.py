"""Synchronous external-event dispatcher."""

import db
from clock import parse_iso
from services import audit, queue_service, settlement


def _audit_billing(actor_id: str, entity_id: str, payload: dict) -> None:
    audit.write(
        actor_role="PlatformOperator",
        actor_id=actor_id or "EXTERNAL",
        entity_kind="ChargingSession",
        entity_id=entity_id,
        event_kind="BILLING_ADJUSTMENT",
        payload=payload,
    )


def dispatch(event: dict, actor_id: str = "EXTERNAL") -> None:
    """Apply side effects for an inbox event and flip `processed`."""
    source = event["source_system"]
    event_type = event["event_type"]
    payload = event.get("payload") or {}

    if source == "PAYMENT" and event_type == "payment.refunded":
        _handle_payment_refunded(payload, actor_id)
    elif source == "GRID" and event_type == "grid.pile_offline":
        _handle_grid_pile_offline(payload)
    elif source == "GRID" and event_type == "grid.pile_online":
        _handle_grid_pile_online(payload)
    elif source == "MAPPING" and event_type == "mapping.location.synced":
        _handle_mapping_location_synced(payload)
    # other event types are accepted but produce no side effect

    event["processed"] = True


def _handle_payment_refunded(payload: dict, actor_id: str) -> None:
    session_id = payload.get("session_id")
    if not session_id:
        return
    session = db.sessions.get(session_id)
    if session is None:
        return
    if session["status"] != "SETTLED":
        return

    # Determine whether the session is inside any payout window for its
    # station's operator before mutating anything.  This loop has to
    # account for both ISSUED and PENDING payouts.
    pile = db.piles[session["pile_id"]]
    station = db.stations[pile["station_id"]]
    station_owner_id = station["station_owner_id"]
    member = db.members[session["member_id"]]
    operator_ids = {
        station_owner_id,
        station["operator_id"],
        member["home_operator_id"],
    }

    settlement.reverse_session(session)
    _audit_billing(actor_id, session["id"], {"reason": "refund_reversal"})

    # Update affected payouts.
    if not session.get("ended_at"):
        return
    try:
        ended_dt = parse_iso(session["ended_at"])
    except Exception:
        return
    for payout in list(db.payouts.values()):
        if payout["operator_id"] not in operator_ids:
            continue
        try:
            ps = parse_iso(payout["period_start"])
            pe = parse_iso(payout["period_end"])
        except Exception:
            continue
        if not (ps <= ended_dt < pe):
            continue
        if payout["status"] == "ISSUED":
            payout["status"] = "REVERSED"
            db.bump(payout)
        elif payout["status"] == "PENDING":
            # PRD §3.7: when a refund arrives while the payout is still
            # PENDING, recompute net AND flag the payout so any subsequent
            # issue attempt is rejected with ERR_PAYOUT_PERIOD_DRIFT.
            _recompute_payout_totals(payout)
            payout["_drifted_by_refund"] = True


def _recompute_payout_totals(payout: dict) -> None:
    operator_id = payout["operator_id"]
    try:
        ps = parse_iso(payout["period_start"])
        pe = parse_iso(payout["period_end"])
    except Exception:
        return

    gross = 0
    reversal = 0
    for entry in db.ledger_entries.values():
        if entry["operator_id"] != operator_id:
            continue
        source_session = db.sessions.get(entry["session_id"])
        if source_session is None or not source_session.get("ended_at"):
            continue
        try:
            ended = parse_iso(source_session["ended_at"])
        except Exception:
            continue
        if not (ps <= ended < pe):
            continue
        amt = int(entry["amount_cents"])
        if amt > 0:
            gross += amt
        if entry["reason"] == "REFUND_REVERSAL" and amt < 0:
            reversal += -amt
    payout["gross_cents"] = gross
    payout["reversal_cents"] = reversal
    payout["net_cents"] = gross - reversal
    db.bump(payout)


def _handle_grid_pile_offline(payload: dict) -> None:
    pile_id = payload.get("pile_id")
    if not pile_id or pile_id not in db.piles:
        return
    pile = db.piles[pile_id]
    if pile["lifecycle_state"] != "ON_SHELF":
        return
    if pile["operational_state"] in {"IDLE", "IN_USE", "FAULT"}:
        pile["operational_state"] = "OFFLINE"
        db.bump(pile)


def _handle_grid_pile_online(payload: dict) -> None:
    pile_id = payload.get("pile_id")
    if not pile_id or pile_id not in db.piles:
        return
    pile = db.piles[pile_id]
    if pile["lifecycle_state"] != "ON_SHELF":
        return
    if pile["operational_state"] == "OFFLINE":
        pile["operational_state"] = "IDLE"
        db.bump(pile)
        queue_service.promote_if_possible(pile["station_id"])


def _handle_mapping_location_synced(payload: dict) -> None:
    station_id = payload.get("station_id")
    if not station_id or station_id not in db.stations:
        return
    station = db.stations[station_id]
    if "latitude" in payload:
        station["latitude"] = payload["latitude"]
    if "longitude" in payload:
        station["longitude"] = payload["longitude"]
    db.bump(station)
