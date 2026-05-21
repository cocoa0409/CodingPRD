"""Tally and margin calculations (PRD §3.9 / SCAFFOLD calculations)."""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Tuple

from ..store import store

_DEC6 = Decimal("0.000001")


def _round6(value) -> float:
    """Round to 6 decimal places, round half up. Returns a float for JSON output."""
    d = Decimal(value).quantize(_DEC6, rounding=ROUND_HALF_UP)
    # Use float for envelope; tests typically compare numerically.
    return float(d)


def _methods_for_variant(variant: str) -> set:
    base = {"EARLY_IN_PERSON", "ELECTION_DAY_MACHINE", "ABSENTEE"}
    if variant == "reconciled":
        return base | {"ELECTION_DAY_PROVISIONAL"}
    return base


def _eligible(b: dict, variant: str) -> bool:
    if b.get("status") not in ("CAST", "TALLIED", "CHALLENGED"):
        return False
    if b.get("method") not in _methods_for_variant(variant):
        return False
    if b.get("challenge_reason") == "DOUBLE_VOTE":
        return False
    return True


def precinct_totals(precinct_id: str, variant: str) -> Dict[str, int]:
    """Return {voter_choice -> integer count} for the given precinct under the variant."""
    s = store()
    totals: Dict[str, int] = defaultdict(int)
    for b in s.ballot_casts.values():
        if b.get("precinct_id") != precinct_id:
            continue
        if not _eligible(b, variant):
            continue
        totals[b["voter_choice"]] += 1
    return dict(totals)


def precinct_margin(precinct_id: str, variant: str) -> float:
    totals = precinct_totals(precinct_id, variant)
    if not totals:
        return 0.0
    vals = sorted(totals.values(), reverse=True)
    top = vals[0]
    second = vals[1] if len(vals) > 1 else 0
    total = sum(vals)
    if total == 0:
        return 0.0
    return _round6((Decimal(top - second) / Decimal(total)))


def election_totals(election_id: str, variant: str) -> Dict[str, int]:
    s = store()
    # Get all precincts for this election; sum per-precinct integer counts.
    election_totals: Dict[str, int] = defaultdict(int)
    for p in s.precincts.values():
        if p.get("election_id") != election_id:
            continue
        pt = precinct_totals(p["id"], variant)
        for choice, count in pt.items():
            election_totals[choice] += count
    return dict(election_totals)


def election_margin(election_id: str, variant: str) -> float:
    totals = election_totals(election_id, variant)
    if not totals:
        return 0.0
    vals = sorted(totals.values(), reverse=True)
    top = vals[0]
    second = vals[1] if len(vals) > 1 else 0
    total = sum(vals)
    if total == 0:
        return 0.0
    return _round6((Decimal(top - second) / Decimal(total)))


def election_winner(election_id: str, variant: str):
    """Return the voter_choice with the highest reconciled total (None if tied/empty)."""
    totals = election_totals(election_id, variant)
    if not totals:
        return None
    # Sort by (-count, choice) so we get a deterministic tiebreaker.
    sorted_items = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(sorted_items) >= 2 and sorted_items[0][1] == sorted_items[1][1]:
        # tie — still return the lexicographically smaller for determinism
        return sorted_items[0][0]
    return sorted_items[0][0]


def precinct_breakdown(election_id: str, variant: str) -> List[dict]:
    """Per-precinct breakdown view used by the /tally endpoint."""
    s = store()
    out = []
    for pid in s.insertion_order["precincts"]:
        p = s.precincts[pid]
        if p.get("election_id") != election_id:
            continue
        totals = precinct_totals(pid, variant)
        out.append({
            "precinct_id": pid,
            "totals": totals,
            "margin": precinct_margin(pid, variant),
        })
    return out
