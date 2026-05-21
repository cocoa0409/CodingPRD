"""Precinct assignment (PRD §3.3): ranked by len(pattern) DESC then code ASC."""
from __future__ import annotations

import re
from typing import Optional

from ..store import store


def assign_precinct(voter: dict) -> Optional[str]:
    """Return the matched precinct_id or None when no match.

    Filter: precincts under the voter's election_id whose street_pattern
    matches the residency_address via re.match.
    Rank: longest street_pattern first, then smallest code.
    """
    s = store()
    election_id = voter.get("election_id")
    address = voter.get("residency_address", "")
    if not election_id:
        return None
    matches = []
    for p in s.precincts.values():
        if p.get("election_id") != election_id:
            continue
        pat = p.get("street_pattern", "")
        try:
            if re.match(pat, address):
                matches.append(p)
        except re.error:
            # Treat invalid regex as plain substring match.
            if pat and address.startswith(pat):
                matches.append(p)
    if not matches:
        return None
    matches.sort(key=lambda p: (-len(p.get("street_pattern", "")), p.get("code", "")))
    return matches[0]["id"]
