from __future__ import annotations

"""Chapter-derived field reconciliation: risk_points, risk_status, dues_balance, pledged counts."""
import db


PROBATION_THRESHOLD = 6
SUSPEND_THRESHOLD = 15


def recompute_risk(chapter_id: str) -> None:
    """Recompute risk_points and risk_status from ACTIVE incidents.

    Caller is responsible for bumping Chapter.version + updated_at after.
    """
    chapter = db.chapters[chapter_id]
    points = sum(
        r["severity_points"]
        for r in db.risk_incidents.values()
        if r["chapter_id"] == chapter_id and r["status"] == "ACTIVE"
    )
    chapter["risk_points"] = points
    if points >= SUSPEND_THRESHOLD:
        chapter["risk_status"] = "SUSPENDED"
    elif points >= PROBATION_THRESHOLD:
        chapter["risk_status"] = "PROBATION"
    else:
        chapter["risk_status"] = "GOOD_STANDING"


def recompute_dues_balance(chapter_id: str) -> int:
    """Sum amount_cents over all ledger entries on this chapter and store on chapter."""
    balance = sum(
        e["amount_cents"]
        for e in db.dues_ledger_entries.values()
        if e["chapter_id"] == chapter_id
    )
    db.chapters[chapter_id]["dues_balance_cents"] = balance
    return balance


def recompute_running_balances(chapter_id: str) -> None:
    """Walk this chapter's ledger entries in chronological order and stamp running_balance_cents."""
    entries = [
        e for e in db.dues_ledger_entries.values() if e["chapter_id"] == chapter_id
    ]
    entries.sort(key=lambda e: (e["created_at"], e["_insertion_seq"]))
    running = 0
    for e in entries:
        running += e["amount_cents"]
        e["running_balance_cents"] = running


def bump_chapter_version(chapter_id: str) -> None:
    c = db.chapters[chapter_id]
    c["version"] += 1
    c["updated_at"] = db.now_utc()


def bump_pnm_version(pnm_id: str) -> None:
    p = db.pnms[pnm_id]
    p["version"] += 1
    p["updated_at"] = db.now_utc()


def bump_party_version(party_id: str) -> None:
    p = db.parties[party_id]
    p["version"] += 1
    p["updated_at"] = db.now_utc()


def bump_round_version(round_id: str) -> None:
    r = db.rounds[round_id]
    r["version"] += 1
    r["updated_at"] = db.now_utc()


def bump_invitation_version(invitation_id: str) -> None:
    i = db.invitations[invitation_id]
    i["version"] += 1
    i["updated_at"] = db.now_utc()


def bump_bid_match_version(bid_id: str) -> None:
    b = db.bid_matches[bid_id]
    b["version"] += 1
    b["updated_at"] = db.now_utc()


def bump_risk_incident_version(ri_id: str) -> None:
    r = db.risk_incidents[ri_id]
    r["version"] += 1
    r["updated_at"] = db.now_utc()


def recompute_party_confirmed_count(party_id: str) -> None:
    count = sum(
        1
        for i in db.invitations.values()
        if i["party_id"] == party_id and i["rsvp_status"] == "ACCEPTED"
    )
    db.parties[party_id]["confirmed_count"] = count


def recompute_chapter_pledged_counts(chapter_id: str, round_id: str | None = None) -> None:
    """Count ACCEPTED BidMatch rows for this chapter (optionally scoped to a round)."""
    rows = [
        b
        for b in db.bid_matches.values()
        if b["chapter_id"] == chapter_id
        and b["status"] == "ACCEPTED"
        and (round_id is None or b["round_id"] == round_id)
    ]
    db.chapters[chapter_id]["pledged_count"] = len(rows)
    db.chapters[chapter_id]["legacy_pledged_count"] = sum(
        1 for b in rows if b["priority_kind"] == "LEGACY"
    )
