"""Screening match-scoring engine (calculation screening_match_score),
party posture aggregation (party_screening_posture), and the LIST_CHANGE
re-screen sweep."""

import re
from decimal import Decimal, ROUND_HALF_UP

import db

W_NAME = Decimal("0.60")
W_COUNTRY = Decimal("0.25")
W_CITY = Decimal("0.15")
THRESHOLD_RESTRICTED = Decimal("0.70")
THRESHOLD_PROHIBITED = Decimal("0.85")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CENT = Decimal("0.01")


def _tokens(s):
    return _TOKEN_RE.findall(s.lower())


def _normalized(s):
    return " ".join(_tokens(s))


def _name_signal(party_name, entry_name, variant):
    if _normalized(party_name) == _normalized(entry_name):
        return Decimal("1.00")
    if variant == "EXACT":
        return Decimal("0.00")
    # FUZZY: token-overlap ratio rounded to 2dp before weighting
    pt = set(_tokens(party_name))
    et = set(_tokens(entry_name))
    union = pt | et
    if not union:
        return Decimal("0.00")
    ratio = Decimal(len(pt & et)) / Decimal(len(union))
    return ratio.quantize(_CENT, rounding=ROUND_HALF_UP)


def pair_score(party, entry, variant):
    """Weighted match score for one (party, entry) pair, 2dp round-half-up."""
    s_name = _name_signal(party["legal_name"], entry["match_name"], variant)
    s_country = (
        Decimal("1.00") if party["country_code"] == entry["country_code"] else Decimal("0.00")
    )
    # Entries carry no city text: city signal mirrors the country signal.
    s_city = s_country
    # Hard gate: PROHIBITED entries score 0 without a country match.
    if entry["severity"] == "PROHIBITED" and s_country < Decimal("1.00"):
        return Decimal("0.00")
    score = W_NAME * s_name + W_COUNTRY * s_country + W_CITY * s_city
    return score.quantize(_CENT, rounding=ROUND_HALF_UP)


def threshold_of(entry):
    return THRESHOLD_PROHIBITED if entry["severity"] == "PROHIBITED" else THRESHOLD_RESTRICTED


def _tie_beats(new, current):
    """Tie-break: severity PROHIBITED first, then created_at ASC."""
    sev_rank = lambda e: 0 if e["severity"] == "PROHIBITED" else 1
    if sev_rank(new) != sev_rank(current):
        return sev_rank(new) < sev_rank(current)
    return db.sort_key(new) < db.sort_key(current)


def create_result(party, trigger_context, variant, matched_entry, score, threshold, status):
    result = {
        "party_id": party["id"],
        "trigger_context": trigger_context,
        "matched_entry_id": matched_entry["id"] if matched_entry else None,
        "algorithm_variant": variant,
        "score": float(score) if score is not None else 0.0,
        "threshold_used": float(threshold) if threshold is not None else None,
        "status": status,
        "resolved_by_user_id": None,
    }
    db.stamp_new(result)
    db.SCREENING_RESULTS[result["id"]] = result
    return result


def recompute_posture(party):
    """party_screening_posture: pure aggregation over the party's result set."""
    results = [r for r in db.SCREENING_RESULTS.values() if r["party_id"] == party["id"]]
    if any(r["status"] == "CONFIRMED_MATCH" for r in results):
        posture = "BLOCKED"
    elif any(r["status"] == "POTENTIAL_MATCH" for r in results):
        posture = "REVIEW_REQUIRED"
    elif results:
        posture = "CLEAR"
    else:
        posture = "UNSCREENED"
    last = None
    if results:
        newest = max(results, key=db.sort_key)
        last = newest["created_at"]
    changed = party["screening_posture"] != posture or party["last_screened_at"] != last
    party["screening_posture"] = posture
    party["last_screened_at"] = last
    if changed:
        db.touch(party)


def run_screening(party, trigger_context, variant):
    """Full screening run over all ACTIVE list entries. Always creates a result
    row (CLEAR or POTENTIAL_MATCH) and recomputes the party's posture."""
    candidates = [e for e in db.LIST_ENTRIES.values() if e["status"] == "ACTIVE"]
    best = None
    for entry in candidates:
        score = pair_score(party, entry, variant)
        if best is None or score > best[0] or (score == best[0] and _tie_beats(entry, best[1])):
            best = (score, entry)
    if best is not None:
        score, entry = best
        threshold = threshold_of(entry)
        if score >= threshold:
            result = create_result(
                party, trigger_context, variant, entry, score, threshold, "POTENTIAL_MATCH"
            )
            recompute_posture(party)
            return result
    result = create_result(party, trigger_context, variant, None, None, None, "CLEAR")
    recompute_posture(party)
    return result


def rescreen_sweep(entry):
    """LIST_CHANGE sweep for a newly ACTIVE entry: evaluate the FUZZY score of
    every party referenced by a CLEARED or LICENSED order against this entry
    only; create a POTENTIAL_MATCH row when the score reaches the threshold;
    cascade holds for parties whose posture deteriorated."""
    from services.cascade import cascade_party_hold

    # party_id -> (earliest qualifying order sort key, party)
    parties = {}
    for order in db.ORDERS.values():
        if order["status"] not in ("CLEARED", "LICENSED"):
            continue
        party = db.PARTIES.get(order["party_id"])
        if party is None:
            continue
        key = db.sort_key(order)
        current = parties.get(party["id"])
        if current is None or key < current[0]:
            parties[party["id"]] = (key, party)
    ordered = sorted(
        parties.values(), key=lambda item: (item[0], db.sort_key(item[1]))
    )
    for _, party in ordered:
        score = pair_score(party, entry, "FUZZY")
        threshold = threshold_of(entry)
        if score >= threshold:
            create_result(party, "LIST_CHANGE", "FUZZY", entry, score, threshold, "POTENTIAL_MATCH")
            recompute_posture(party)
        if party["screening_posture"] in ("REVIEW_REQUIRED", "BLOCKED"):
            cascade_party_hold(party)
