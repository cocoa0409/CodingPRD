"""Admin / test-driving endpoints: clock advance, sweep, external sync listing, micro-balance read."""

from datetime import datetime, timezone

from db import store
from errors import raise_err
from clock import clock
from response import format_iso
from util import get_str, parse_iso8601


def advance_clock(body):
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "body required")
    target_str = get_str(body, "to")
    target = parse_iso8601(target_str)
    new_now = clock.set_to(target)
    return {"now": format_iso(new_now)}


def run_sweep(body):
    swept_payments = 0
    swept_works = 0
    with store.lock:
        from services.work import recompute_dispute_posture
        # 1. RETRYING payments → SENT.
        for pay in store.payments.values():
            if pay["status"] == "RETRYING":
                pay["status"] = "SENT"
                store.touch(pay)
                swept_payments += 1
                # Emit a fresh PAYMENT_INITIATED for retry attempt.
                ev = store.lean_fields()
                ev.update({
                    "target_system": "PAYMENT_PSP",
                    "event_kind": "PAYMENT_INITIATED",
                    "related_entity_kind": "Payment",
                    "related_entity_id": pay["id"],
                    "payload": {"payment_id": pay["id"], "retry_count": pay["retry_count"]},
                })
                store.external_sync_events[ev["id"]] = ev
        # 2. Recompute dispute_posture for all approved works.
        approved_work_ids = [w["id"] for w in store.works.values() if w["registration_status"] == "APPROVED"]
        for wid in approved_work_ids:
            recompute_dispute_posture(wid)
            swept_works += 1
    return {"swept_payments": swept_payments, "swept_works": swept_works}


def list_external_sync(args):
    from util import parse_pagination
    limit, offset = parse_pagination(args)
    target_system = args.get("target_system")
    event_kind = args.get("event_kind")
    related_entity_id = args.get("related_entity_id")
    with store.lock:
        rows = list(store.external_sync_events.values())
    if target_system:
        rows = [r for r in rows if r["target_system"] == target_system]
    if event_kind:
        rows = [r for r in rows if r["event_kind"] == event_kind]
    if related_entity_id:
        rows = [r for r in rows if r["related_entity_id"] == related_entity_id]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return [_serialize_ev(r) for r in page], total, limit, offset


def _serialize_ev(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "target_system": e["target_system"],
        "event_kind": e["event_kind"],
        "related_entity_kind": e["related_entity_kind"],
        "related_entity_id": e["related_entity_id"],
        "payload": e.get("payload", {}),
    }


def read_micro_balance(holder_id: str):
    with store.lock:
        if holder_id not in store.rights_holders:
            raise_err("ERR_NOT_FOUND", "RightsHolder not found")
        rows = [m for m in store.micro_balances.values() if m["rights_holder_id"] == holder_id]
        rows.sort(key=lambda r: r["created_at"])
        return [_serialize_mb(m) for m in rows]


def _serialize_mb(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "rights_holder_id": m["rights_holder_id"],
        "currency": m["currency"],
        "balance_cents": m["balance_cents"],
    }
