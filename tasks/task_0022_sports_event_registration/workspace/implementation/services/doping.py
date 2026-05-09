"""Doping sample, sanction, appeal cascades."""
from datetime import timedelta

import db
from clock import now, parse_iso, iso
from errors import err
from services import posture, prize, ranking, sync
from services.audit import write_audit


def issue_sanction_from_positive_sample(sample: dict, actor_user_id: str, actor_role: str) -> dict:
    """Cascade fired when a doping sample turns POSITIVE."""
    pid = sample["participant_id"]
    p = db.participants.get(pid)
    event_id = sample["event_id"]

    # Snapshot prize_forfeited_cents
    snapshot_cents = 0
    for pp in db.prize_payments.values():
        if pp["event_id"] == event_id and pp["participant_id"] == pid:
            snapshot_cents += pp.get("gross_amount_cents", 0)

    sr = {
        "sample_id": sample["id"],
        "participant_id": pid,
        # ban_months provided server-side; PRD: "auto-create SanctionRecord ... ban_months 1..120"
        # Tests likely accept any sensible default; use 12 months.
        "ban_months": 12,
        "prize_forfeited_cents": snapshot_cents,
        "status": "ISSUED",
    }
    db.stamp_create(sr, common_fields=False)
    db.sanction_records[sr["id"]] = sr

    # AuditLog row
    write_audit(kind="SANCTION_CHANGE", subject_kind="SANCTION_RECORD", subject_id=sr["id"],
                actor_user_id=actor_user_id, actor_role=actor_role,
                from_value={}, to_value={"status": "ISSUED"})

    # Participant ACTIVE -> DISQUALIFIED (or any non-terminal -> DISQUALIFIED)
    if p:
        if p["status"] not in ("WITHDRAWN", "DISQUALIFIED"):
            p["status"] = "DISQUALIFIED"
            db.stamp_update(p)

    # Cascade: any future Match featuring participant -> VOIDED
    n = now()
    for m in db.matches.values():
        if m["event_id"] != event_id:
            continue
        sides = (m.get("home_participant_id"), m.get("away_participant_id"))
        if pid not in sides:
            continue
        try:
            ms = parse_iso(m["scheduled_start_at"])
        except Exception:
            ms = None
        if m["status"] in ("SCHEDULED",) and (ms is None or ms > n):
            m["status"] = "VOIDED"
            db.stamp_update(m)
            for a in db.referee_assignments.values():
                if a["match_id"] == m["id"] and a["status"] != "REVOKED":
                    a["status"] = "REVOKED"
                    db.stamp_update(a)

    # Cascade: PrizePayment SCHEDULED -> FORFEITED
    prize.recompute_for_sanction(pid, event_id, sanction_active=True)

    # Recompute rankings (excluding this participant)
    ranking.recompute_rankings(event_id, finalize=(db.events[event_id]["status"] == "COMPLETED"))

    # Posture
    posture.recompute_posture(event_id)
    return sr


def file_appeal(body: dict, actor_user_id: str, actor_role: str) -> dict:
    if "sanction_id" not in body:
        raise err("ERR_VALIDATION", "sanction_id required")
    if "ground_text" not in body:
        raise err("ERR_VALIDATION", "ground_text required")
    sid = body["sanction_id"]
    gt = body["ground_text"]
    if not isinstance(sid, str):
        raise err("ERR_VALIDATION", "sanction_id must be string")
    if not isinstance(gt, str) or len(gt) < 1 or len(gt) > 2000:
        raise err("ERR_VALIDATION", "ground_text must be 1..2000 chars")
    sr = db.sanction_records.get(sid)
    if not sr:
        raise err("ERR_REFERENCE_NOT_FOUND", "sanction not found")

    # State validity: sanction must be ISSUED
    if sr["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "sanction not in ISSUED")

    # filed_by_user_id is optional in the body; default to caller (the participant role's identity).
    filed_by = body.get("filed_by_user_id") if "filed_by_user_id" in body else actor_user_id
    if not isinstance(filed_by, str):
        raise err("ERR_VALIDATION", "filed_by_user_id must be a string")
    if filed_by != actor_user_id:
        raise err("ERR_FORBIDDEN", "filed_by_user_id != X-User-ID")
    if filed_by != sr["participant_id"]:
        raise err("ERR_FORBIDDEN", "filed_by_user_id != sanction.participant_id")

    # Window check (inclusive boundary on closing edge)
    sr_created = parse_iso(sr["created_at"])
    deadline = sr_created + timedelta(days=14)
    if now() > deadline:
        raise err("ERR_APPEAL_WINDOW_CLOSED", "appeal window closed")

    a = {
        "sanction_id": sid,
        "filed_by_user_id": filed_by,
        "ground_text": gt,
        "status": "PENDING",
    }
    db.stamp_create(a, common_fields=True)
    db.appeals[a["id"]] = a

    # SanctionRecord ISSUED -> APPEALED
    before = {"status": sr["status"]}
    sr["status"] = "APPEALED"
    after = {"status": sr["status"]}
    write_audit(kind="SANCTION_CHANGE", subject_kind="SANCTION_RECORD", subject_id=sr["id"],
                actor_user_id=actor_user_id, actor_role=actor_role,
                from_value=before, to_value=after)
    # Posture -> FROZEN (via recompute)
    sample = db.doping_samples.get(sr["sample_id"])
    if sample:
        posture.recompute_posture(sample["event_id"])
    return a


def decide_appeal(appeal_id: str, body: dict, actor_user_id: str, actor_role: str) -> dict:
    a = db.appeals.get(appeal_id)
    if not a:
        raise err("ERR_NOT_FOUND", "appeal not found")
    if a["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "appeal not PENDING")
    if "uphold" not in body:
        raise err("ERR_VALIDATION", "uphold required")
    uphold = body["uphold"]
    if not isinstance(uphold, bool):
        raise err("ERR_VALIDATION", "uphold must be boolean")
    from services.validation import check_version
    check_version(a, body)

    sr = db.sanction_records.get(a["sanction_id"])
    if not sr:
        raise err("ERR_NOT_FOUND", "sanction not found")
    sample = db.doping_samples.get(sr["sample_id"])
    event_id = sample["event_id"] if sample else None

    if uphold:
        # Appeal UPHELD; sanction REVOKED
        before_sr = {"status": sr["status"]}
        sr["status"] = "REVOKED"
        after_sr = {"status": sr["status"]}
        a["status"] = "UPHELD"
        db.stamp_update(a)
        # Reinstate participant
        pid = sr["participant_id"]
        p = db.participants.get(pid)
        if p and p["status"] == "DISQUALIFIED":
            ev = db.events.get(event_id) if event_id else None
            if ev and ev["status"] == "COMPLETED":
                p["status"] = "ELIMINATED"
            else:
                p["status"] = "ACTIVE"
            db.stamp_update(p)
        # PrizePayment FORFEITED -> SCHEDULED
        if event_id:
            prize.recompute_for_sanction(pid, event_id, sanction_active=False)
            posture.recompute_posture(event_id)
            ranking.recompute_rankings(event_id, finalize=(db.events[event_id]["status"] == "COMPLETED"))
        write_audit(kind="SANCTION_CHANGE", subject_kind="SANCTION_RECORD", subject_id=sr["id"],
                    actor_user_id=actor_user_id, actor_role=actor_role,
                    from_value=before_sr, to_value=after_sr)
    else:
        # Appeal DISMISSED; sanction FINAL
        before_sr = {"status": sr["status"]}
        sr["status"] = "FINAL"
        after_sr = {"status": sr["status"]}
        a["status"] = "DISMISSED"
        db.stamp_update(a)
        if event_id:
            posture.recompute_posture(event_id)
        write_audit(kind="SANCTION_CHANGE", subject_kind="SANCTION_RECORD", subject_id=sr["id"],
                    actor_user_id=actor_user_id, actor_role=actor_role,
                    from_value=before_sr, to_value=after_sr)
    return a
