"""Sweep: auto-void expired contracts and fire due reminders."""

import math

from db import DB, new_id
from clock import now
from services.audit import append_audit
from services.contracts import _cascade_void
from services.reminders import VALID_CHANNELS  # reuse


def run_sweep(*, actor_user_id: str, actor_role: str) -> dict:
    n = now()
    auto_voided = 0
    reminders_fired = 0

    # 1) Auto-void expired contracts
    expired_contracts = []
    for c in DB.contracts.values():
        if c["status"] in ("PENDING_SIGN", "PARTIALLY_SIGNED"):
            if c["expires_at"] is not None and n >= c["expires_at"]:
                expired_contracts.append(c)
    for c in expired_contracts:
        _cascade_void(c, "EXPIRED_AUTO", n,
                      actor_user_id=actor_user_id,
                      actor_role=actor_role,
                      audit_action="CONTRACT_EXPIRED_AUTO")
        auto_voided += 1

    # 2) Fire due reminders
    for r in list(DB.reminder_rules.values()):
        if not r.get("enabled"):
            continue
        c = DB.contracts.get(r["contract_id"])
        if not c:
            continue
        if c["status"] not in ("PENDING_SIGN", "PARTIALLY_SIGNED"):
            continue
        last = r.get("last_fired_at") or c.get("activated_at")
        if last is None:
            continue
        threshold_seconds = r["interval_hours"] * 3600
        elapsed = (n - last).total_seconds()
        if elapsed < threshold_seconds:
            continue  # not due

        # idempotency_key = "{rule_id}:{floor(epoch_now / interval_seconds)}"
        slot = int(math.floor(n.timestamp() / threshold_seconds))
        idem = f"{r['id']}:{slot}"
        key = (r["id"], idem)
        if key in DB.reminder_idem:
            continue  # already fired this slot
        new_misses = r["misses_count"] + 1
        escalated = new_misses > r["escalation_after_misses"]
        channels_used = list(r["channels"])
        if escalated and "INITIATOR_IM" not in channels_used:
            channels_used = channels_used + ["INITIATOR_IM"]
        eid = new_id()
        e = {
            "id": eid,
            "reminder_rule_id": r["id"],
            "contract_id": r["contract_id"],
            "fired_at": n,
            "channels_used": channels_used,
            "escalated": escalated,
            "idempotency_key": idem,
            "created_at": n,
        }
        DB.reminder_events[eid] = e
        DB.reminder_idem[key] = eid
        r["misses_count"] = new_misses
        r["last_fired_at"] = n
        r["version"] += 1
        r["updated_at"] = n
        append_audit(
            contract_id=r["contract_id"],
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="REMINDER_FIRED",
            payload={
                "reminder_rule_id": r["id"],
                "idempotency_key": idem,
                "escalated": escalated,
            },
        )
        reminders_fired += 1

    return {"auto_voided": auto_voided, "reminders_fired": reminders_fired}
