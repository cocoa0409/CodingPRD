from __future__ import annotations

"""BidMatch routes."""
from flask import Blueprint, request, g

import db
import errors as E
import response
import serializers as S
from middleware import require_auth
from services import chapter_service as cs
from services import pagination as P
from services import validation as V


bp = Blueprint("bid_matches", __name__)


def _bid_match_or_404(bid_id: str) -> dict:
    if bid_id not in db.bid_matches:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"BidMatch {bid_id} not found")
    return db.bid_matches[bid_id]


@bp.route("/rush/bid-matches", methods=["POST"])
@require_auth(["ChapterOfficer"])
def create_bid_match():
    body = request.get_json(silent=True) or {}
    round_id = V.require_string(body, "round_id")
    chapter_id = V.require_string(body, "chapter_id")
    pnm_id = V.require_string(body, "pnm_id")
    expected_version = V.require_int(body, "expected_chapter_version", min_val=1)

    # Priority 4: FK existence.
    if round_id not in db.rounds:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"round_id {round_id} not found")
    if chapter_id not in db.chapters:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"chapter_id {chapter_id} not found")
    if pnm_id not in db.pnms:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"pnm_id {pnm_id} not found")

    rnd = db.rounds[round_id]
    chapter = db.chapters[chapter_id]
    pnm = db.pnms[pnm_id]

    # Ownership: ChapterOfficer X-User-ID must equal chapter_id.
    if g.user_role == "ChapterOfficer" and g.user_id != chapter_id:
        raise E.APIError(
            E.ERR_UNAUTHORIZED,
            "ChapterOfficer may only bid for their own chapter",
        )

    # Priority 5: state - PNM must be ACTIVE to receive a manual bid.
    if pnm["status"] != "ACTIVE":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"PNM status is {pnm['status']}, cannot receive a bid",
        )

    # Priority 6: OCC.
    if expected_version != chapter["version"]:
        raise E.APIError(
            E.ERR_STALE_VERSION,
            f"Chapter version mismatch: expected {expected_version}, current {chapter['version']}",
        )

    # Priority 7: chapter suspension safety gate.
    if chapter["risk_status"] == "SUSPENDED":
        raise E.APIError(
            E.ERR_CHAPTER_SUSPENDED,
            "Chapter is suspended; cannot produce bids",
        )

    # Priority 12: round.phase IN {BID_DAY}.
    if rnd["phase"] != "BID_DAY":
        raise E.APIError(
            E.ERR_ROUND_PHASE_MISMATCH,
            f"Round phase is {rnd['phase']}, expected BID_DAY",
        )

    # Priority 13: chapter quota check.
    if chapter["pledged_count"] + 1 > chapter["quota_total"]:
        raise E.APIError(
            E.ERR_CHAPTER_QUOTA_FULL,
            "Chapter has reached its quota",
        )

    # Determine priority_kind.
    if (
        pnm["legacy_chapter_id"] == chapter_id
        and chapter["legacy_pledged_count"] < chapter["legacy_priority_slots"]
    ):
        priority_kind = "LEGACY"
    else:
        priority_kind = "STANDARD"

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
        "pnm_id": pnm_id,
        "status": "PROPOSED",
        "priority_kind": priority_kind,
        "dues_charged_cents": 0,
    }
    db.bid_matches[bid_id] = bm

    # Cascade: chapter.version++; PNM.status -> MATCHED; PNM.matched_chapter_id = chapter_id; PNM.version++.
    cs.bump_chapter_version(chapter_id)
    pnm["status"] = "MATCHED"
    pnm["matched_chapter_id"] = chapter_id
    cs.bump_pnm_version(pnm_id)

    return response.success_object(S.bid_match(bm), status=201)


@bp.route("/rush/bid-matches/<bid_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "PNM"])
def get_bid_match(bid_id):
    bm = _bid_match_or_404(bid_id)
    return response.success_object(S.bid_match(bm))


@bp.route("/rush/bid-matches", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "PNM"])
def list_bid_matches():
    limit, offset = P.parse_limit_offset()
    chapter_id = request.args.get("chapter_id")
    pnm_id = request.args.get("pnm_id")
    round_id = request.args.get("round_id")
    status = request.args.get("status")
    rows = list(db.bid_matches.values())
    if chapter_id is not None:
        rows = [b for b in rows if b["chapter_id"] == chapter_id]
    if pnm_id is not None:
        rows = [b for b in rows if b["pnm_id"] == pnm_id]
    if round_id is not None:
        rows = [b for b in rows if b["round_id"] == round_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.bid_match(b) for b in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/bid-matches/<bid_id>/dues-ledger-entries", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer"])
def list_bid_dues_ledger_entries(bid_id):
    bm = _bid_match_or_404(bid_id)
    limit, offset = P.parse_limit_offset()
    # Recompute running balances on the chapter so values are stable across reads.
    cs.recompute_running_balances(bm["chapter_id"])
    rows = [e for e in db.dues_ledger_entries.values() if e["bid_match_id"] == bid_id]
    rows.sort(key=lambda e: (e["created_at"], e["_insertion_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return response.success_array(
        [S.dues_ledger_entry(e) for e in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/bid-matches/<bid_id>/accept", methods=["POST"])
@require_auth(["PNM"])
def accept_bid_match(bid_id):
    bm = _bid_match_or_404(bid_id)
    pnm = db.pnms[bm["pnm_id"]]
    chapter = db.chapters[bm["chapter_id"]]
    rnd = db.rounds[bm["round_id"]]

    # Ownership: PNM may only act on their own bid.
    if g.user_id != bm["pnm_id"]:
        raise E.APIError(E.ERR_UNAUTHORIZED, "PNM may only act on their own bids")

    # Priority 5: state preconditions.
    if bm["status"] != "PROPOSED":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"BidMatch status is {bm['status']}, cannot accept",
        )
    if pnm["status"] != "MATCHED":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"PNM status is {pnm['status']}, cannot accept a bid",
        )

    # Priority 7: safety gate — chapter must not be SUSPENDED.
    if chapter["risk_status"] == "SUSPENDED":
        raise E.APIError(
            E.ERR_CHAPTER_SUSPENDED,
            "Chapter is suspended; cannot accept a bid",
        )

    # Priority 12: round phase must be BID_DAY.
    if rnd["phase"] != "BID_DAY":
        raise E.APIError(
            E.ERR_ROUND_PHASE_MISMATCH,
            f"Round phase is {rnd['phase']}, expected BID_DAY",
        )

    # Snapshot dues at acceptance instant.
    snapshot = chapter["dues_per_member_cents"]
    bm["status"] = "ACCEPTED"
    bm["dues_charged_cents"] = snapshot
    cs.bump_bid_match_version(bid_id)

    pnm["status"] = "BID_ACCEPTED"
    cs.bump_pnm_version(pnm["id"])

    # Append CHARGE DuesLedgerEntry.
    now = db.now_utc()
    eid = db.new_id()
    entry = {
        "id": eid,
        "created_at": now,
        "_insertion_seq": db.next_insertion_seq(),
        "chapter_id": chapter["id"],
        "bid_match_id": bid_id,
        "amount_cents": snapshot,
        "entry_kind": "CHARGE",
        "running_balance_cents": 0,
    }
    db.dues_ledger_entries[eid] = entry
    cs.recompute_running_balances(chapter["id"])
    cs.recompute_dues_balance(chapter["id"])

    # pledged_count++; if LEGACY, legacy_pledged_count++.
    chapter["pledged_count"] += 1
    if bm["priority_kind"] == "LEGACY":
        chapter["legacy_pledged_count"] += 1
    cs.bump_chapter_version(chapter["id"])

    return response.success_object(S.bid_match(bm))


@bp.route("/rush/bid-matches/<bid_id>/decline", methods=["POST"])
@require_auth(["PNM"])
def decline_bid_match(bid_id):
    bm = _bid_match_or_404(bid_id)
    pnm = db.pnms[bm["pnm_id"]]
    rnd = db.rounds[bm["round_id"]]

    if g.user_id != bm["pnm_id"]:
        raise E.APIError(E.ERR_UNAUTHORIZED, "PNM may only act on their own bids")

    if bm["status"] != "PROPOSED":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"BidMatch status is {bm['status']}, cannot decline",
        )
    if pnm["status"] != "MATCHED":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"PNM status is {pnm['status']}, cannot decline a bid",
        )

    if rnd["phase"] != "BID_DAY":
        raise E.APIError(
            E.ERR_ROUND_PHASE_MISMATCH,
            f"Round phase is {rnd['phase']}, expected BID_DAY",
        )

    bm["status"] = "DECLINED"
    cs.bump_bid_match_version(bid_id)

    pnm["status"] = "BID_DECLINED"
    pnm["matched_chapter_id"] = None
    cs.bump_pnm_version(pnm["id"])

    return response.success_object(S.bid_match(bm))


@bp.route("/rush/bid-matches/<bid_id>/rescind", methods=["POST"])
@require_auth(["ChapterOfficer"])
def rescind_bid_match(bid_id):
    bm = _bid_match_or_404(bid_id)
    body = request.get_json(silent=True) or {}
    expected_version = V.require_int(body, "expected_chapter_version", min_val=1)

    chapter = db.chapters[bm["chapter_id"]]
    pnm = db.pnms[bm["pnm_id"]]
    rnd = db.rounds[bm["round_id"]]

    # Ownership.
    if g.user_role == "ChapterOfficer" and g.user_id != chapter["id"]:
        raise E.APIError(
            E.ERR_UNAUTHORIZED,
            "ChapterOfficer may only rescind bids on their own chapter",
        )

    # Priority 5: state - bid must be ACCEPTED.
    if bm["status"] != "ACCEPTED":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"BidMatch status is {bm['status']}, cannot rescind",
        )

    # Priority 6: OCC.
    if expected_version != chapter["version"]:
        raise E.APIError(
            E.ERR_STALE_VERSION,
            f"Chapter version mismatch: expected {expected_version}, current {chapter['version']}",
        )

    # Priority 12: round phase must be BID_DAY.
    if rnd["phase"] != "BID_DAY":
        raise E.APIError(
            E.ERR_ROUND_PHASE_MISMATCH,
            f"Round phase is {rnd['phase']}, expected BID_DAY",
        )

    refund_amount = -bm["dues_charged_cents"]

    bm["status"] = "DECLINED"
    cs.bump_bid_match_version(bid_id)

    # Append REFUND entry.
    now = db.now_utc()
    eid = db.new_id()
    entry = {
        "id": eid,
        "created_at": now,
        "_insertion_seq": db.next_insertion_seq(),
        "chapter_id": chapter["id"],
        "bid_match_id": bid_id,
        "amount_cents": refund_amount,
        "entry_kind": "REFUND",
        "running_balance_cents": 0,
    }
    db.dues_ledger_entries[eid] = entry
    cs.recompute_running_balances(chapter["id"])
    cs.recompute_dues_balance(chapter["id"])

    # Decrement counters.
    chapter["pledged_count"] -= 1
    if bm["priority_kind"] == "LEGACY":
        chapter["legacy_pledged_count"] -= 1
    cs.bump_chapter_version(chapter["id"])

    # Push PNM back to ACTIVE.
    pnm["status"] = "ACTIVE"
    pnm["matched_chapter_id"] = None
    cs.bump_pnm_version(pnm["id"])

    return response.success_object(S.bid_match(bm))
