"""License selection + compliance evaluation (SCAFFOLD §1.3 license_selection,
PRD §3.3).
"""
import db
from . import store


def select_license(physician_id, determined_state_code):
    """Return (selected_license_or_None, reason_when_blocked).

    reason_when_blocked is one of LICENSE_NOT_ACTIVE / NO_LICENSE_IN_STATE when
    no candidate qualifies, else None.

    Candidate filter:
      physician_id matches
      state_code == determined_state_code
      status == ACTIVE
      effective_date <= clock < expiration_date  (upper bound exclusive)

    Ranking: FULL before COMPACT_EXPEDITED, then latest effective_date, then
    earliest created_at.
    """
    now = db.clock_now()
    same_phys_state = [
        s for s in db.state_licenses.values()
        if s["physician_id"] == physician_id and s["state_code"] == determined_state_code
    ]

    candidates = []
    for s in same_phys_state:
        if s["status"] != "ACTIVE":
            continue
        eff = db.parse_iso(s["effective_date"])
        exp = db.parse_iso(s["expiration_date"])
        if eff is None or exp is None:
            continue
        if eff <= now < exp:
            candidates.append(s)

    if not candidates:
        # Distinguish reason: a physician+state license exists but not usable.
        if same_phys_state:
            return None, "LICENSE_NOT_ACTIVE"
        return None, "NO_LICENSE_IN_STATE"

    def rank_key(s):
        issuance_rank = 0 if s["issuance_type"] == "FULL" else 1
        eff = db.parse_iso(s["effective_date"])
        created = db.parse_iso(s["created_at"])
        # FULL before COMPACT (asc), latest effective_date (desc), earliest created (asc).
        return (issuance_rank, -eff.timestamp(), created.timestamp())

    candidates.sort(key=rank_key)
    return candidates[0], None
