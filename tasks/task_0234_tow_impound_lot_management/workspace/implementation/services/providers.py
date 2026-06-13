"""Provider standing recompute (scaffold provider_standing / PRD §3.7)."""
from decimal import Decimal

import db
from services import calc


def recompute_standing(provider):
    """Recompute raw_standing_pct (all-time) and effective_standing_pct (trailing
    window + suspension penalty) in place. Does NOT bump version."""
    # RAW: all-time counters.
    raw = calc.pct_round_half_up(provider["offers_accepted_count"], provider["offers_received_count"])
    provider["raw_standing_pct"] = float(raw)

    # EFFECTIVE: most-recent trailing_window_size assignments offered to this
    # provider, ordered by offered_at ASC then created_at ASC.
    assignments = [a for a in db.rotation_assignments.values()
                   if a["provider_id"] == provider["id"]]
    assignments.sort(key=lambda a: (a.get("_offered_dt") or _MIN, a["_seq"]))
    window = provider.get("trailing_window_size", 10)
    window_slice = assignments[-window:] if window > 0 else []
    offered_in_window = len(window_slice)
    accepted_in_window = sum(1 for a in window_slice if a["status"] == "ACCEPTED")
    if offered_in_window == 0:
        eff = Decimal("100.00")
    else:
        eff = calc.pct_round_half_up(accepted_in_window, offered_in_window)
    if provider["status"] == "SUSPENDED":
        eff = eff - calc.SUSPENSION_PENALTY_PCT
        if eff < Decimal("0.00"):
            eff = Decimal("0.00")
    if eff > Decimal("100.00"):
        eff = Decimal("100.00")
    provider["effective_standing_pct"] = float(eff)
    return provider


from datetime import datetime
_MIN = datetime.min
