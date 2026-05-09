"""Bracket seeding per §3.2 / §1.3 bracket_seeding."""
import math
from typing import List, Tuple

import db
from errors import err


# Region inferred from the event host country_code. Per PRD: a participant whose
# region matches "the region implied by the event's host country_code" is band 1.
# We use a coarse mapping: for each region's representative country codes.
_COUNTRY_TO_REGION = {
    # AFC (Asian Football Confederation) - sample
    "JP": "AFC", "KR": "AFC", "CN": "AFC", "AU": "AFC", "IN": "AFC",
    "TH": "AFC", "VN": "AFC", "ID": "AFC", "MY": "AFC", "SG": "AFC",
    "PH": "AFC", "QA": "AFC", "AE": "AFC", "SA": "AFC", "IR": "AFC",
    "IQ": "AFC", "JO": "AFC", "LB": "AFC", "PK": "AFC", "UZ": "AFC",
    # CAF
    "EG": "CAF", "NG": "CAF", "ZA": "CAF", "GH": "CAF", "SN": "CAF",
    "MA": "CAF", "TN": "CAF", "DZ": "CAF", "CM": "CAF", "CI": "CAF",
    "KE": "CAF", "ET": "CAF", "UG": "CAF", "TZ": "CAF",
    # CONCACAF
    "US": "CONCACAF", "CA": "CONCACAF", "MX": "CONCACAF", "JM": "CONCACAF",
    "CR": "CONCACAF", "PA": "CONCACAF", "HT": "CONCACAF", "DO": "CONCACAF",
    "CU": "CONCACAF", "HN": "CONCACAF", "TT": "CONCACAF", "GT": "CONCACAF",
    # CONMEBOL
    "BR": "CONMEBOL", "AR": "CONMEBOL", "UY": "CONMEBOL", "CL": "CONMEBOL",
    "CO": "CONMEBOL", "PE": "CONMEBOL", "EC": "CONMEBOL", "PY": "CONMEBOL",
    "BO": "CONMEBOL", "VE": "CONMEBOL",
    # OFC
    "NZ": "OFC", "FJ": "OFC", "PG": "OFC", "SB": "OFC", "VU": "OFC",
    "TO": "OFC", "WS": "OFC",
    # UEFA
    "GB": "UEFA", "DE": "UEFA", "FR": "UEFA", "IT": "UEFA", "ES": "UEFA",
    "PT": "UEFA", "NL": "UEFA", "BE": "UEFA", "CH": "UEFA", "AT": "UEFA",
    "DK": "UEFA", "SE": "UEFA", "NO": "UEFA", "FI": "UEFA", "PL": "UEFA",
    "CZ": "UEFA", "RU": "UEFA", "TR": "UEFA", "GR": "UEFA", "IE": "UEFA",
    "HR": "UEFA", "RS": "UEFA", "RO": "UEFA", "HU": "UEFA", "BG": "UEFA",
    "UA": "UEFA", "IS": "UEFA", "LU": "UEFA",
}


def country_to_region(cc: str):
    return _COUNTRY_TO_REGION.get(cc)


def _seeding_priority(p, host_region):
    if p.get("world_ranking") is not None and p["world_ranking"] <= 16:
        return 0
    if host_region is not None and p.get("region") == host_region:
        return 1
    return 2


def _ranking_score(p):
    wr = p.get("world_ranking")
    if wr is None:
        return 0
    return 10000 - wr


def assign_seeds(event: dict, participants: List[dict]) -> List[dict]:
    """Sort participants by composite key and assign bracket_seed in place."""
    host_region = country_to_region(event["country_code"])

    def sort_key(p):
        return (
            _seeding_priority(p, host_region),
            -_ranking_score(p),
            p["id"],
        )

    ordered = sorted(participants, key=sort_key)
    for i, p in enumerate(ordered, start=1):
        p["bracket_seed"] = i
    return ordered


def bracket_size(n: int) -> int:
    if n <= 1:
        return max(2, n)
    return 2 ** math.ceil(math.log2(n))


def first_round_pairs(seeded: List[dict]) -> List[Tuple]:
    """Pair seed 1 vs seed N, seed 2 vs seed N-1, ... up to bracket size with byes."""
    n = len(seeded)
    cap = bracket_size(n)
    # Indexed by seed (1-based), or None for bye slot
    by_seed = {p["bracket_seed"]: p for p in seeded}
    pairs = []
    for i in range(1, cap // 2 + 1):
        high = by_seed.get(i)
        low = by_seed.get(cap - i + 1)  # may be None -> bye
        pairs.append([high, low])
    return pairs


def avoidance(pairs):
    """Single-sweep avoidance pass per PRD §3.2.

    Scans first-round pairs left-to-right; on a conflict (same team_code or
    same country_code), swap the lower-seed slot with the next non-conflicting
    lower-seed participant downstream.
    """
    def conflict(a, b):
        if a is None or b is None:
            return False
        if a.get("team_code") and a.get("team_code") == b.get("team_code"):
            return True
        if a.get("country_code") == b.get("country_code"):
            return True
        return False

    for i in range(len(pairs)):
        a, b = pairs[i]
        if not conflict(a, b):
            continue
        # Look downstream for a candidate to swap with b (the lower-seed slot)
        swapped = False
        for j in range(i + 1, len(pairs)):
            c, d = pairs[j]
            if d is None or c is None:
                continue
            # After swap b<->d, no conflicts in either pair
            if not conflict(a, d) and not conflict(c, b):
                pairs[i][1], pairs[j][1] = d, b
                swapped = True
                break
        if not swapped:
            raise err("ERR_AVOIDANCE_INFEASIBLE",
                      "Avoidance pass cannot resolve same-team/same-country conflict")
    return pairs
