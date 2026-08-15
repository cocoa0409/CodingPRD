"""Epoch sweep (clock-set side effects) and shared cascade helpers."""
import uuid
from datetime import timedelta

import db
from response import now_iso
from services import calc


def new_id():
    return str(uuid.uuid4())


def bump(entity):
    """Version + updated_at on any modification (common-fields resources)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def write_system_tx(account, kind, amount_cents, posted_date):
    tx = {
        "id": new_id(),
        "share_account_id": account["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "posted_date": posted_date,
        "running_balance_cents": 0,
        "origin": "SYSTEM",
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.transactions[tx["id"]] = tx
    calc.replay_account(account)
    return tx


def close_account(account, closure_reason, current_date_str):
    """OPEN -> CLOSED: full-balance CLOSURE_DISBURSEMENT, enrollment cascade."""
    write_system_tx(account, "CLOSURE_DISBURSEMENT", account["balance_cents"], current_date_str)
    account["status"] = "CLOSED"
    account["closed_date"] = current_date_str
    account["closure_reason"] = closure_reason
    bump(account)
    for enr in db.enrollments.values():
        if enr["funding_share_account_id"] == account["id"] and enr["status"] == "ACTIVE":
            enr["status"] = "CLOSED"
            enr["closure_reason"] = "FORCED_ACCOUNT_CLOSURE"
            bump(enr)


def _apply_amendment(amendment, current_date_str):
    amendment["status"] = "EFFECTIVE"
    bump(amendment)
    charter = db.charters.get(amendment["charter_id"])
    if charter is not None:
        charter["version"] += 1
        charter["updated_at"] = now_iso()
    if amendment["amendment_type"] == "ADD_SEGMENT":
        seg = {
            "id": new_id(),
            "charter_id": amendment["charter_id"],
            "segment_type": amendment["proposed_segment_type"],
            "descriptor": amendment["proposed_segment_descriptor"],
            "required_documents": list(amendment["proposed_segment_required_documents"]),
            "status": "ACTIVE",
            "retired_at": None,
            "version": 1,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "_seq": db.next_seq(),
        }
        db.segments[seg["id"]] = seg
        amendment["applied_segment_id"] = seg["id"]
    else:  # RETIRE_SEGMENT
        for sid in amendment["retire_segment_ids"]:
            seg = db.segments.get(sid)
            if seg is None or seg["status"] != "ACTIVE":
                continue
            seg["status"] = "RETIRED"
            seg["retired_at"] = current_date_str
            bump(seg)
            for m in db.members.values():
                if (m["segment_id"] == sid
                        and m["eligibility_basis"] == "SEGMENT_MATCH"
                        and m["status"] == "ACTIVE"):
                    review = {
                        "id": new_id(),
                        "member_id": m["id"],
                        "reason": "SEGMENT_RETIRED",
                        "status": "OPEN",
                        "flagged_by_user_id": "system",
                        "decided_by_user_id": None,
                        "resolution_note": None,
                        "version": 1,
                        "created_at": now_iso(),
                        "updated_at": now_iso(),
                        "_seq": db.next_seq(),
                    }
                    db.reviews[review["id"]] = review
                    m["status"] = "INELIGIBLE_UNDER_REVIEW"
                    bump(m)


def epoch_sweep():
    """Runs on every clock set: amendment maturation, then grace expiry."""
    current = db.clock.current_date()
    current_s = current.isoformat()

    maturing = [a for a in db.amendments.values()
                if a["status"] == "APPROVED" and a["effective_date"] <= current_s]
    maturing.sort(key=lambda a: (a["effective_date"], a["created_at"], a["_seq"]))
    for a in maturing:
        _apply_amendment(a, current_s)

    expiring = [m for m in db.members.values()
                if m["status"] == "GRACE_PERIOD"
                and m["grace_end_date"] is not None
                and m["grace_end_date"] <= current_s]
    expiring.sort(key=lambda m: (m["created_at"], m["_seq"]))
    for m in expiring:
        m["status"] = "CLOSED_INELIGIBLE"
        bump(m)
        open_accounts = [a for a in db.accounts.values()
                         if a["member_id"] == m["id"] and a["status"] == "OPEN"]
        open_accounts.sort(key=lambda a: (a["opened_date"], a["created_at"], a["_seq"]))
        for acc in open_accounts:
            close_account(acc, "FORCED_INELIGIBILITY", current_s)


def grace_end_for(confirm_date):
    return (confirm_date + timedelta(days=90)).isoformat()
