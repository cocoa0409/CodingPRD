"""Plan-year resolution for claim submission (SCAFFOLD §1.3 plan_year_resolution)."""
from __future__ import annotations

import datetime as _dt

from ..clock import to_date
from ..store import store


def _service_date_in_window(service_date: _dt.date, calendar_year: int, end_date: _dt.date) -> bool:
    start = _dt.date(calendar_year, 1, 1)
    return start <= service_date <= end_date


def resolve_plan_year(account: dict, service_date_dt: _dt.datetime) -> dict | None:
    """Return the PlanYear row to which `service_date_dt` should be routed, or None.

    Coverage windows by account_type + year_end_policy:
      HSA: [Jan 1 of CY, Dec 31 of CY]
      HEALTH_FSA / DCFSA with GRACE_PERIOD: [Jan 1 of CY, Mar 15 of CY+1]
        tie-break: prior-year if status == GRACE_PERIOD AND service_date <= Mar 15 of Y+1
      HEALTH_FSA with CARRYOVER: [Jan 1 of CY, Dec 31 of CY]
      *_FSA with NONE: [Jan 1 of CY, Dec 31 of CY]
    """
    account_type = account["account_type"]
    policy = account["year_end_policy"]
    service_date = to_date(service_date_dt)

    # Collect candidate plan years for this account.
    candidates: list[dict] = [
        py for py in store.plan_years.values() if py["account_id"] == account["id"]
    ]
    if not candidates:
        return None

    def window_end(cy: int) -> _dt.date:
        if account_type in ("HEALTH_FSA", "DEPENDENT_CARE_FSA") and policy == "GRACE_PERIOD":
            return _dt.date(cy + 1, 3, 15)
        return _dt.date(cy, 12, 31)

    matches = [
        py for py in candidates
        if _service_date_in_window(service_date, py["calendar_year"], window_end(py["calendar_year"]))
    ]
    if not matches:
        return None

    if len(matches) == 1:
        return matches[0]

    # Tie-break for grace-period overlap: prefer prior-year if it's in GRACE_PERIOD
    # AND service_date <= Mar 15 of (prior_cy + 1).
    if account_type in ("HEALTH_FSA", "DEPENDENT_CARE_FSA") and policy == "GRACE_PERIOD":
        matches.sort(key=lambda py: py["calendar_year"])
        prior = matches[0]
        later_threshold = _dt.date(prior["calendar_year"] + 1, 3, 15)
        if prior["status"] == "GRACE_PERIOD" and service_date <= later_threshold:
            return prior
        # Else fall back to the later year
        return matches[-1]

    # Otherwise lower calendar_year wins.
    matches.sort(key=lambda py: py["calendar_year"])
    return matches[0]
