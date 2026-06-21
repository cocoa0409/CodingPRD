from __future__ import annotations

"""Mutual-selection allocator: two-pass waterfall producing BidMatch rows.

Triggered on Round.phase MUTUAL_SELECTION -> BID_DAY.
"""
import db
from services import chapter_service as cs


INF = float("inf")


def _eligible_chapters(round_id: str) -> list[dict]:
    """Chapters that may bid this cycle: not SUSPENDED. Ordered by created_at asc."""
    rows = [c for c in db.chapters.values() if c["risk_status"] != "SUSPENDED"]
    rows.sort(key=lambda c: (c["created_at"], c["_insertion_seq"]))
    return rows


def _build_preference_lookups(round_id: str) -> tuple[dict, dict]:
    """Return:

        chapter_rank: { (chapter_id, pnm_id): rank }
            ↑ chapter's CHAPTER_TO_PNM rank for that PNM
        pnm_rank:     { (pnm_id, chapter_id): rank }
            ↑ pnm's PNM_TO_CHAPTER rank for that chapter
    """
    chapter_rank: dict[tuple[str, str], int] = {}
    pnm_rank: dict[tuple[str, str], int] = {}
    for pref in db.preferences.values():
        if pref["round_id"] != round_id:
            continue
        if pref["side"] == "CHAPTER_TO_PNM":
            key = (pref["chapter_id"], pref["pnm_id"])
            chapter_rank[key] = pref["rank"]
        elif pref["side"] == "PNM_TO_CHAPTER":
            key = (pref["pnm_id"], pref["chapter_id"])
            pnm_rank[key] = pref["rank"]
    return chapter_rank, pnm_rank


def _mutual_eligible_pnms(chapter_id: str, chapter_rank: dict, pnm_rank: dict) -> list[dict]:
    """PNMs that share a mutual preference pair with this chapter AND have status==ACTIVE."""
    out = []
    for p in db.pnms.values():
        if p["status"] != "ACTIVE":
            continue
        if (chapter_id, p["id"]) in chapter_rank and (p["id"], chapter_id) in pnm_rank:
            out.append(p)
    return out


def _sort_candidates(chapter_id: str, candidates: list[dict], chapter_rank: dict, pnm_rank: dict) -> list[dict]:
    def keyfn(p):
        ck = chapter_rank.get((chapter_id, p["id"]), INF)
        pk = pnm_rank.get((p["id"], chapter_id), INF)
        return (ck, pk, p["created_at"], p["_insertion_seq"])

    return sorted(candidates, key=keyfn)


def _produce_bid_match(round_id: str, chapter_id: str, pnm: dict, priority_kind: str) -> str:
    """Create a PROPOSED BidMatch row, transition PNM to MATCHED, bump versions."""
    now = db.now_utc()
    bid_id = db.new_id()
    bm = {
        "id": bid_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "round_id": round_id,
        "chapter_id": chapter_id,
        "pnm_id": pnm["id"],
        "status": "PROPOSED",
        "priority_kind": priority_kind,
        "dues_charged_cents": 0,
    }
    db.bid_matches[bid_id] = bm

    # Transition PNM ACTIVE -> MATCHED.
    pnm["status"] = "MATCHED"
    pnm["matched_chapter_id"] = chapter_id
    cs.bump_pnm_version(pnm["id"])

    return bid_id


def run_mutual_selection(round_id: str) -> list[str]:
    """Execute the two-pass waterfall allocator. Return list of new bid_match ids.

    NOTE: matched-in-this-allocator-run is tracked locally; the PNM.status
    flips to MATCHED on each produced match, so candidate lookups that
    filter on status==ACTIVE also naturally exclude them. We still track a
    local set for clarity.
    """
    chapters = _eligible_chapters(round_id)
    chapter_rank, pnm_rank = _build_preference_lookups(round_id)
    matched_pnms: set[str] = set()
    new_bid_ids: list[str] = []

    # Per-chapter pending pledged counts. Start at 0 for the cycle - the round just opened.
    pending_pledged: dict[str, int] = {c["id"]: 0 for c in chapters}
    pending_legacy: dict[str, int] = {c["id"]: 0 for c in chapters}

    # ---- Step 1: LEGACY pass ----
    for chapter in chapters:
        cid = chapter["id"]
        if chapter["legacy_priority_slots"] <= 0:
            continue
        quota_room = chapter["quota_total"] - pending_pledged[cid]
        legacy_room = chapter["legacy_priority_slots"] - pending_legacy[cid]
        take_room = min(legacy_room, quota_room)
        if take_room <= 0:
            continue

        # Candidates: is_legacy=True, legacy_chapter_id == cid, mutual pair, ACTIVE, not yet matched.
        candidates = []
        for p in db.pnms.values():
            if p["id"] in matched_pnms:
                continue
            if p["status"] != "ACTIVE":
                continue
            if not p["is_legacy"]:
                continue
            if p["legacy_chapter_id"] != cid:
                continue
            if (cid, p["id"]) not in chapter_rank:
                continue
            if (p["id"], cid) not in pnm_rank:
                continue
            candidates.append(p)

        candidates = _sort_candidates(cid, candidates, chapter_rank, pnm_rank)
        for p in candidates[:take_room]:
            bid_id = _produce_bid_match(round_id, cid, p, "LEGACY")
            matched_pnms.add(p["id"])
            pending_pledged[cid] += 1
            pending_legacy[cid] += 1
            new_bid_ids.append(bid_id)

    # ---- Step 2: STANDARD pass ----
    for chapter in chapters:
        cid = chapter["id"]
        quota_room = chapter["quota_total"] - pending_pledged[cid]
        if quota_room <= 0:
            continue

        candidates = []
        for p in db.pnms.values():
            if p["id"] in matched_pnms:
                continue
            if p["status"] != "ACTIVE":
                continue
            if (cid, p["id"]) not in chapter_rank:
                continue
            if (p["id"], cid) not in pnm_rank:
                continue
            candidates.append(p)

        candidates = _sort_candidates(cid, candidates, chapter_rank, pnm_rank)
        for p in candidates[:quota_room]:
            bid_id = _produce_bid_match(round_id, cid, p, "STANDARD")
            matched_pnms.add(p["id"])
            pending_pledged[cid] += 1
            new_bid_ids.append(bid_id)

    return new_bid_ids
