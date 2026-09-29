"""Confidence-scored matching of reported plays to catalogued works (§3.3)
and the claim-mode variant used by the approval cascade (§3.5 link two)."""

from constants import (
    AUTO_MATCH_MIN_CONFIDENCE_BPS,
    CLAIM_MATCH_MIN_CONFIDENCE_BPS,
    ISRC_EXACT_CONFIDENCE_BPS,
    TITLE_ARTIST_CONFIDENCE_BPS,
    TITLE_ONLY_CONFIDENCE_BPS,
)
from db import by_created, db, now, parse_dt, touch
from services import derive
from validation import normalize_text


def score_candidate(work, norm_title, norm_artist, reported_isrc):
    """§3.3 step two: the branches are tried in this exact order."""
    if work["work_type"] != "RECORDING":
        return 0
    if reported_isrc and work["identifier"] == reported_isrc:
        return ISRC_EXACT_CONFIDENCE_BPS
    if (norm_artist
            and work["normalized_artist"] is not None
            and work["normalized_title"] == norm_title
            and work["normalized_artist"] == norm_artist):
        return TITLE_ARTIST_CONFIDENCE_BPS
    if work["normalized_title"] == norm_title:
        return TITLE_ONLY_CONFIDENCE_BPS
    return 0


def _is_candidate(work, norm_title, reported_isrc):
    if work["work_type"] != "RECORDING":
        return False
    if reported_isrc and work["identifier"] == reported_isrc:
        return True
    return work["normalized_title"] == norm_title


def candidates_for(line):
    norm_title = normalize_text(line["reported_title"])
    reported_isrc = line["reported_isrc"]
    return by_created([w for w in db.works.values()
                       if _is_candidate(w, norm_title, reported_isrc)])


def _winner(scored):
    """Highest score; ties by earlier created_at, then smaller identifier."""
    best = None
    for work, score in scored:
        key = (-score, work["created_at"], work["identifier"], work["_seq"])
        if best is None or key < best[0]:
            best = (key, work, score)
    if best is None:
        return None, 0
    return best[1], best[2]


def score_line(line, works):
    norm_title = normalize_text(line["reported_title"])
    norm_artist = normalize_text(line["reported_artist"]) if line["reported_artist"] else None
    reported_isrc = line["reported_isrc"]
    scored = []
    for work in works:
        scored.append((work, score_candidate(work, norm_title, norm_artist, reported_isrc)))
    return scored


# --------------------------------------------------------------------------
# batch-level run (§3.3)
# --------------------------------------------------------------------------

def run_batch_match(batch, actor_user_id):
    """Score every line of the batch, write the outcome, fork the batch."""
    touched_works = {}
    for line in derive.lines_of_batch(batch["id"]):
        cands = candidates_for(line)
        if not cands:
            new_work_id = None
            new_status = "UNMATCHED"
            new_conf = 0
        else:
            winner, score = _winner(score_line(line, cands))
            new_conf = score
            if score >= AUTO_MATCH_MIN_CONFIDENCE_BPS:
                new_work_id = winner["id"]
                new_status = "AUTO_MATCHED"
                if score < ISRC_EXACT_CONFIDENCE_BPS:
                    if winner["provisional_match_by_user_id"] != actor_user_id:
                        winner["provisional_match_by_user_id"] = actor_user_id
                        touched_works[winner["id"]] = winner
            else:
                new_work_id = None
                new_status = "UNMATCHED"

        if (line["work_id"] != new_work_id
                or line["match_status"] != new_status
                or line["match_confidence_bps"] != new_conf):
            line["work_id"] = new_work_id
            line["match_status"] = new_status
            line["match_confidence_bps"] = new_conf
            touch(line)

    for work in touched_works.values():
        touch(work)

    unmatched = derive.batch_unmatched_play_count(batch["id"])
    batch["status"] = "MATCHED" if unmatched == 0 else "PARTIALLY_MATCHED"
    touch(batch)
    return batch


# --------------------------------------------------------------------------
# claim-mode run (§3.5 link two)
# --------------------------------------------------------------------------

def run_claim_match(work):
    """Attach still-unattached usage to a single just-approved work.

    Returns the list of usage lines that were re-attached.
    """
    if work["work_type"] != "RECORDING":
        return []
    current = now()
    attached = []
    for line in by_created(list(db.usage_lines.values())):
        if line["work_id"] is not None:
            continue
        period = derive.period_of_line(line)
        if period is None:
            continue
        closes = parse_dt(period["claim_window_closes_at"])
        if closes is None or current > closes:
            continue
        score = score_line(line, [work])[0][1]
        if score < CLAIM_MATCH_MIN_CONFIDENCE_BPS:
            continue
        line["work_id"] = work["id"]
        line["match_confidence_bps"] = score
        line["match_status"] = "CLAIM_MATCHED"
        touch(line)
        attached.append(line)
    return attached
