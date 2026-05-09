"""Idempotent system sweeps: registration auto-close, event auto-start,
prize-payment payout, sanction FINAL after 14d."""
from datetime import timedelta

import db
from clock import now, parse_iso
from services import posture, prize, ranking, sync
from services.audit import write_audit


def run_sweep(actor_user_id: str = "system", actor_role: str = "Organizer") -> None:
    n = now()
    # 1) Registration auto-close
    for ev in db.events.values():
        if ev["status"] == "OPEN":
            try:
                rc = parse_iso(ev["registration_closes_at"])
            except Exception:
                continue
            if n >= rc:
                ev["status"] = "REGISTRATION_CLOSED"
                db.stamp_update(ev)

    # 2) Event auto-start (only if every round-1 non-BYE match has ASSIGNED HEAD)
    for ev in db.events.values():
        if ev["status"] == "DRAWN":
            try:
                sa = parse_iso(ev["starts_at"])
            except Exception:
                continue
            if n >= sa:
                # Check round-1 referee assignments
                r1 = [m for m in db.matches.values()
                      if m["event_id"] == ev["id"] and m["round_index"] == 1 and m["status"] != "BYE"]
                ok = True
                for m in r1:
                    has_head = any(a for a in db.referee_assignments.values()
                                   if a["match_id"] == m["id"] and a["role"] == "HEAD"
                                   and a["status"] == "ASSIGNED")
                    if not has_head:
                        ok = False
                        break
                if ok:
                    ev["status"] = "IN_PROGRESS"
                    db.stamp_update(ev)
                    r1_ids = set()
                    for m in r1:
                        if m.get("home_participant_id"):
                            r1_ids.add(m["home_participant_id"])
                        if m.get("away_participant_id"):
                            r1_ids.add(m["away_participant_id"])
                    for pid in r1_ids:
                        p = db.participants.get(pid)
                        if p and p["status"] == "SEEDED":
                            p["status"] = "ACTIVE"
                            db.stamp_update(p)

    # 3) Sanctions ISSUED -> FINAL after 14 days with no Appeal
    for sr in list(db.sanction_records.values()):
        if sr["status"] != "ISSUED":
            continue
        try:
            created = parse_iso(sr["created_at"])
        except Exception:
            continue
        deadline = created + timedelta(days=14)
        # System runs only when now() is strictly later than deadline
        if n <= deadline:
            continue
        has_appeal = any(a for a in db.appeals.values() if a["sanction_id"] == sr["id"])
        if has_appeal:
            continue
        before = {"status": sr["status"]}
        sr["status"] = "FINAL"
        after = {"status": sr["status"]}
        write_audit(kind="SANCTION_CHANGE", subject_kind="SANCTION_RECORD", subject_id=sr["id"],
                    actor_user_id=actor_user_id, actor_role=actor_role,
                    from_value=before, to_value=after)
        sample = db.doping_samples.get(sr["sample_id"])
        if sample:
            posture.recompute_posture(sample["event_id"])
            sync.emit(target_system="GOVERNING_BODY", kind="SANCTION_ARCHIVED",
                      payload={"sanction_id": sr["id"]})

    # 4) PrizePayment SCHEDULED -> PAID (clock crosses scheduled_pay_at, posture CLEAN)
    for pp in list(db.prize_payments.values()):
        if pp["status"] != "SCHEDULED":
            continue
        try:
            sa = parse_iso(pp["scheduled_pay_at"])
        except Exception:
            continue
        if n < sa:
            continue
        ev = db.events.get(pp["event_id"])
        if not ev:
            continue
        if ev.get("posture") != "CLEAN":
            continue
        pp["status"] = "PAID"
        db.stamp_update(pp)
        sync.emit(target_system="PAYMENT", kind="PRIZE_PAID",
                  payload={"prize_payment_id": pp["id"], "net_amount_cents": pp["net_amount_cents"],
                           "participant_id": pp["participant_id"]})
        sync.emit(target_system="IM", kind="PRIZE_PAID",
                  payload={"prize_payment_id": pp["id"], "participant_id": pp["participant_id"]})
        prize.recompute_event_prize_total(ev["id"])
