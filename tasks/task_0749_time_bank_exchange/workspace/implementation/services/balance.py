"""Ledger balance calculations — §1.3 chronological_balance and forward_looking_balance.

Also: trust_tier, no_show_strikes, and Member snapshot recomputation.
"""
import db
from db import parse_iso, format_iso


def _sort_ledger_key(entry):
    # Primary: posted_at ASC, secondary: created_at ASC. NO id fallback.
    # We rely on parse_iso for datetime ordering. Tie-breaks past that use
    # the monotonic _seq (which reflects insertion order and is proxy for
    # created_at within the same millisecond).
    return (parse_iso(entry["posted_at"]), parse_iso(entry["created_at"]), entry.get("_seq", 0))


def _member_ledger(member_id: str):
    return [e for e in db.ledger_entries.values() if e["member_id"] == member_id]


def chronological_balance(member_id: str) -> int:
    entries = sorted(_member_ledger(member_id), key=_sort_ledger_key)
    total = 0
    for e in entries:
        total += int(e["delta_minutes"])
    return total


def forward_looking_balance(member_id: str) -> int:
    chrono = chronological_balance(member_id)
    pending = 0
    for x in db.exchanges.values():
        if x["requester_member_id"] == member_id and x["status"] in ("SCHEDULED", "DELIVERED"):
            pending += int(x["committed_minutes"])
    return chrono - pending


def lifetime_earned(member_id: str) -> int:
    return sum(int(e["delta_minutes"]) for e in _member_ledger(member_id)
               if e["entry_kind"] == "EARNED" and int(e["delta_minutes"]) > 0)


def lifetime_redeemed(member_id: str) -> int:
    return sum(abs(int(e["delta_minutes"])) for e in _member_ledger(member_id)
               if e["entry_kind"] == "REDEMPTION")


def verified_credential_count(member_id: str) -> int:
    return sum(1 for c in db.verification_credentials.values()
               if c["subject_member_id"] == member_id and c["status"] == "VERIFIED")


def completed_exchange_count(member_id: str) -> int:
    return sum(1 for x in db.exchanges.values()
               if x["provider_member_id"] == member_id and x["status"] == "SETTLED")


def trust_tier(v: int, c: int) -> str:
    # §1.3 pinned evaluation order
    if v >= 3 and c >= 20:
        return "ANCHOR"
    if v >= 2 and c >= 5:
        return "TRUSTED"
    if v >= 1:
        return "BASIC"
    return "UNVERIFIED"


def no_show_strikes(member_id: str) -> int:
    """§1.3 no_show_strikes — rolling 90-day window on shift-end time,
    evaluated against the logical clock."""
    cutoff = db.clock_dt().timestamp() - 90 * 86400
    count = 0
    for a in db.shift_assignments.values():
        if a["member_id"] != member_id or a["status"] != "NO_SHOW":
            continue
        shift = db.project_shifts.get(a["shift_id"])
        if shift is None:
            continue
        shift_end = parse_iso(shift["shift_start_utc"]).timestamp() + shift["duration_minutes"] * 60
        if shift_end >= cutoff:
            count += 1
    return count


def recompute_member_snapshot(member_id: str, bump_version: bool = False):
    """Refresh all computed fields on the Member row and (optionally) bump version."""
    m = db.members.get(member_id)
    if m is None:
        return
    m["verified_credential_count"] = verified_credential_count(member_id)
    m["completed_exchange_count"] = completed_exchange_count(member_id)
    m["chronological_balance_minutes"] = chronological_balance(member_id)
    m["forward_looking_balance_minutes"] = forward_looking_balance(member_id)
    m["lifetime_earned_minutes"] = lifetime_earned(member_id)
    m["lifetime_redeemed_minutes"] = lifetime_redeemed(member_id)
    strikes = no_show_strikes(member_id)
    m["no_show_strikes"] = strikes
    if strikes >= 3:
        m["is_suspended"] = True
    m["trust_tier"] = trust_tier(m["verified_credential_count"], m["completed_exchange_count"])
    if bump_version:
        db.touch(m)
    else:
        m["updated_at"] = db._now_wall_iso()
