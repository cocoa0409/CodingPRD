"""Conflict match scoring, hit materialization, and the lateral sweep
(PRD 2.6, 3.2, 3.4; scaffold calculations.conflict_match_score)."""

import db
from db import stamp_new, bump
from services import naming
from services.naming import (
    normalize, soundex, token_overlap,
    PHONETIC_SCORE, AFFILIATE_DEPTH_DISCOUNT, AFFILIATE_MAX_DEPTH,
    DEFAULT_MATCH_THRESHOLD,
)
from services.clearance import recompute_clearance, supersede_checks

LIVE_LIFECYCLES = ("INTAKE", "OPEN")

# Tiebreak preference when two derivations reach the same (party, matter)
# with equal scores: name channels beat affiliate expansion.
_VIA_RANK = {"DIRECT": 0, "ALIAS": 1, "LATERAL": 2, "AFFILIATE": 3}


def parties_on_matter(matter_id):
    """The matter's client party plus every roster party (deduped, in
    deterministic order: client first, then roster insertion order)."""
    result = []
    seen = set()
    matter = db.store.matters.get(matter_id)
    if matter is not None:
        client = db.store.parties.get(matter["client_party_id"])
        if client is not None:
            result.append(client)
            seen.add(client["id"])
    for mp in db.store.matter_parties.values():
        if mp["matter_id"] != matter_id:
            continue
        if mp["party_id"] in seen:
            continue
        party = db.store.parties.get(mp["party_id"])
        if party is not None:
            result.append(party)
            seen.add(party["id"])
    return result


def candidate_pool(exclude_matter_id):
    """(party, matter) pairs where the party is client or roster on a matter
    with lifecycle in {INTAKE, OPEN}; the check's own matter excluded."""
    pool = []
    seen = set()
    for matter in db.store.matters.values():
        if matter["id"] == exclude_matter_id:
            continue
        if matter["lifecycle_status"] not in LIVE_LIFECYCLES:
            continue
        for party in parties_on_matter(matter["id"]):
            key = (party["id"], matter["id"])
            if key in seen:
                continue
            seen.add(key)
            pool.append((party, matter))
    return pool


def descendants(party_id, max_depth=AFFILIATE_MAX_DEPTH):
    """Affiliate-tree walk DOWNWARD from party_id: parties whose
    affiliate_of chain leads up to it. Returns {descendant_id: min_depth}
    for depths 1..max_depth."""
    result = {}
    frontier = {party_id: 0}
    for depth in range(1, max_depth + 1):
        next_frontier = {}
        for p in db.store.parties.values():
            parent = p["affiliate_of_id"]
            if parent in frontier and p["id"] not in result and p["id"] != party_id:
                if p["id"] not in next_frontier:
                    next_frontier[p["id"]] = depth
                    result[p["id"]] = depth
        frontier = next_frontier
        if not frontier:
            break
    return result


def score_pair(q_norm, q_key, candidate, variant):
    """Base score + name channel for one (query, candidate) pair.
    STRICT: max(direct, alias); PHONETIC adds a 70-point soundex channel."""
    if q_norm == candidate["normalized_name"]:
        direct = 100
    else:
        direct = token_overlap(q_norm, candidate["normalized_name"])
    alias_best = 0
    for alias in candidate["aliases"]:
        if q_norm == alias["normalized_alias"]:
            value = 100
        else:
            value = token_overlap(q_norm, alias["normalized_alias"])
        if value > alias_best:
            alias_best = value
    phonetic = 0
    if variant == "PHONETIC" and q_key and q_key == candidate["phonetic_key"]:
        phonetic = PHONETIC_SCORE
    base = max(direct, alias_best, phonetic)
    if direct == base:
        via = "DIRECT"
    elif alias_best == base:
        via = "ALIAS"
    else:
        # Phonetic-only match: the soundex key derives from the normalized
        # name, so the name channel is recorded as DIRECT.
        via = "DIRECT"
    return base, via


def _record(best, party_id, matter_id, via, score):
    """Keep one candidate per (matched party, matched matter): max score;
    on ties prefer the more direct derivation channel."""
    key = (party_id, matter_id)
    current = best.get(key)
    if current is None:
        best[key] = [score, via]
        return
    if score > current[0]:
        current[0] = score
        current[1] = via
    elif score == current[0] and _VIA_RANK[via] < _VIA_RANK[current[1]]:
        current[1] = via


def compute_hits(subjects, pool, variant, threshold, lateral_via=None):
    """Score every (query subject, candidate) pair and expand each matched
    candidate through its affiliate tree (depth 1..3, -10 per level).
    A candidate becomes a hit iff score >= match_threshold (inclusive).
    Returns {(matched_party_id, matched_matter_id): [score, via]}."""
    best = {}
    for q_norm, q_key in subjects:
        for party, matter in pool:
            base, via = score_pair(q_norm, q_key, party, variant)
            name_via = lateral_via if lateral_via is not None else via
            if base >= threshold:
                _record(best, party["id"], matter["id"], name_via, base)
            for desc_id, depth in descendants(party["id"]).items():
                score = base - AFFILIATE_DEPTH_DISCOUNT * depth
                if score >= threshold:
                    _record(best, desc_id, matter["id"], "AFFILIATE", score)
    return best


def hit_sort_key(hit):
    """Deterministic hit order (PRD 3.4): match_score DESC, then matched
    party's created_at ASC, then matched matter's created_at ASC. Stable
    sort keeps emission order beyond those keys (never id)."""
    party = db.store.parties.get(hit["matched_party_id"])
    matter = db.store.matters.get(hit["matched_matter_id"])
    return (
        -hit["match_score"],
        party["created_at"] if party else "",
        matter["created_at"] if matter else "",
    )


def sort_hits(hits):
    return sorted(hits, key=hit_sort_key)


def _materialize_hits(check, best):
    rows = []
    for (party_id, matter_id), (score, via) in best.items():
        row = stamp_new({
            "check_id": check["id"],
            "matched_party_id": party_id,
            "matched_matter_id": matter_id,
            "matched_via": via,
            "match_score": int(score),
            "review_status": "PENDING",
            "reviewed_by_attorney_id": None,
            "review_note": "",
            "lateral_attorney_id": check["lateral_attorney_id"],
        })
        db.store.conflict_hits[row["id"]] = row
        rows.append(row)
    # Deterministic emission order for hit lists.
    ordered = sort_hits(rows)
    return ordered


def run_intake_check(matter, search_variant, match_threshold):
    """POST conflict-checks body of work: supersede the prior COMPLETED
    INTAKE check on this matter (staling its PENDING hits), compute hits,
    recompute clearance. Returns the new ConflictCheck row."""
    supersede_checks(matter, "INTAKE")
    check = stamp_new({
        "matter_id": matter["id"],
        "check_kind": "INTAKE",
        "search_variant": search_variant,
        "match_threshold": match_threshold,
        "status": "COMPLETED",
        "hit_count": 0,
        "lateral_attorney_id": None,
        "query_label": None,
    })
    db.store.conflict_checks[check["id"]] = check

    subjects = [
        (p["normalized_name"], p["phonetic_key"])
        for p in parties_on_matter(matter["id"])
    ]
    pool = candidate_pool(exclude_matter_id=matter["id"])
    best = compute_hits(subjects, pool, search_variant, match_threshold)
    hits = _materialize_hits(check, best)
    check["hit_count"] = len(hits)

    recompute_clearance(matter)
    db.bump(matter)  # endpoint side effect: matter.version += 1
    return check


def _day_of(ts_iso):
    return db.parse_ts(ts_iso).date()


def employment_overlaps(matter, employed_from, employed_to):
    """Day-granularity overlap; lateral_employed_to INCLUSIVE:
    activity_start_day <= employed_to AND (no closed_at OR
    closed_day >= employed_from). activity_start_day is the opened_at day
    for OPEN/CLOSED matters, else the created_at day (INTAKE = active
    prospect)."""
    from datetime import date as _date
    start = (_day_of(matter["opened_at"]) if matter["opened_at"]
             else _day_of(matter["created_at"]))
    if start > employed_to:
        return False
    if matter["closed_at"] is not None:
        if _day_of(matter["closed_at"]) < employed_from:
            return False
    return True


def run_lateral_sweep(attorney):
    """PRD 3.2: for each prior_client_name, PHONETIC match at threshold 60
    against parties on INTAKE/OPEN matters, then the employment-overlap
    day filter; per surviving (name, matter) pair create a LATERAL_SWEEP
    check (with hits) on that existing matter and recompute its clearance.
    Returns the number of PENDING sweep hits attributed to the attorney."""
    from datetime import datetime as _dt
    employed_from = _dt.strptime(attorney["lateral_employed_from"], "%Y-%m-%d").date()
    employed_to = _dt.strptime(attorney["lateral_employed_to"], "%Y-%m-%d").date()

    for name in attorney["prior_client_names"]:
        q_norm = normalize(name)
        q_key = soundex(q_norm)
        for matter in list(db.store.matters.values()):
            if matter["lifecycle_status"] not in LIVE_LIFECYCLES:
                continue
            pool = [(p, matter) for p in parties_on_matter(matter["id"])]
            best = compute_hits(
                [(q_norm, q_key)], pool, "PHONETIC",
                DEFAULT_MATCH_THRESHOLD, lateral_via="LATERAL",
            )
            if not best:
                continue
            if not employment_overlaps(matter, employed_from, employed_to):
                continue
            # Same-kind supersede scope: a new LATERAL_SWEEP check on this
            # matter supersedes the prior COMPLETED LATERAL_SWEEP check.
            supersede_checks(matter, "LATERAL_SWEEP")
            check = stamp_new({
                "matter_id": matter["id"],
                "check_kind": "LATERAL_SWEEP",
                "search_variant": "PHONETIC",
                "match_threshold": DEFAULT_MATCH_THRESHOLD,
                "status": "COMPLETED",
                "hit_count": 0,
                "lateral_attorney_id": attorney["id"],
                "query_label": name,
            })
            db.store.conflict_checks[check["id"]] = check
            hits = _materialize_hits(check, best)
            check["hit_count"] = len(hits)
            recompute_clearance(matter)

    return pending_sweep_hits(attorney["id"])


def pending_sweep_hits(attorney_id):
    return sum(
        1 for h in db.store.conflict_hits.values()
        if h["lateral_attorney_id"] == attorney_id
        and h["review_status"] == "PENDING"
    )
