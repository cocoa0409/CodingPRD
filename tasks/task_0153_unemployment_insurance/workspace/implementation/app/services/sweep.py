"""Clock-driven state transitions run after every /_clock/advance.

Per PRD §2.9 and SCAFFOLD §1.2:
  - PandemicExtension: SCHEDULED -> ACTIVE on SystemClock.now >= effective_start
                       ACTIVE -> EXPIRED on SystemClock.now > effective_end
  - Claim: MONETARILY_ELIGIBLE/ACTIVE/EXHAUSTED -> CLOSED when now > benefit_year_end
  - Appeal: FILED -> DISMISSED_LATE when now > deadline_at
"""
from __future__ import annotations

from datetime import datetime

from ..clock import now_dt, now_iso
from ..store import get_store
from ..util import parse_iso8601, parse_iso_date


def _bump(entity: dict, now: str) -> None:
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 1) + 1


def sweep() -> None:
    """Run all clock-driven transitions atomically."""
    store = get_store()
    now_d: datetime = now_dt()
    now_date = now_d.date()
    now_str = now_iso()

    # PandemicExtension lifecycle.
    for ext in list(store.pandemic_extensions.values()):
        eff_start = parse_iso_date(ext["effective_start"])
        eff_end = parse_iso_date(ext["effective_end"])
        if eff_start is None or eff_end is None:
            continue
        old_status = ext["status"]
        if old_status == "SCHEDULED":
            if now_date > eff_end:
                ext["status"] = "EXPIRED"
                _bump(ext, now_str)
            elif now_date >= eff_start:
                ext["status"] = "ACTIVE"
                _bump(ext, now_str)
        elif old_status == "ACTIVE":
            if now_date > eff_end:
                ext["status"] = "EXPIRED"
                _bump(ext, now_str)

    # Claim benefit-year close.
    for cl in list(store.claims.values()):
        if cl["status"] in {"MONETARILY_ELIGIBLE", "ACTIVE", "EXHAUSTED", "EXTENDED"}:
            by_end = parse_iso_date(cl.get("benefit_year_end") or "")
            if by_end is not None and now_date > by_end:
                cl["status"] = "CLOSED"
                _bump(cl, now_str)

    # Appeal deadline.
    for a in list(store.appeals.values()):
        if a["status"] != "FILED":
            continue
        deadline = parse_iso8601(a.get("deadline_at") or "")
        if deadline is not None and now_d > deadline:
            a["status"] = "DISMISSED_LATE"
            _bump(a, now_str)
