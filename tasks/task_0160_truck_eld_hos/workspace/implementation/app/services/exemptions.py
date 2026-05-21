"""AdverseConditionsExemption helpers and the clock-advance sweep
(SCAFFOLD: state machine of AdverseConditionsExemption)."""

from __future__ import annotations

from datetime import datetime

from ..store import store
from ..timeutil import next_local_midnight_utc, parse_iso


def expire_crossed_exemptions(prev_clock: datetime, new_clock: datetime) -> int:
    """Transition ACTIVE exemptions to EXPIRED when their home-terminal midnight
    is crossed during a clock advance from prev_clock to new_clock.

    Returns the number of exemptions transitioned.
    """
    if new_clock <= prev_clock:
        return 0
    count = 0
    for exemption in list(store.adverse_exemptions.values()):
        if exemption.get("status") != "ACTIVE":
            continue
        driver = store.drivers.get(exemption["driver_id"])
        if driver is None:
            continue
        tz = driver.get("home_terminal_timezone") or "America/New_York"
        midnight = next_local_midnight_utc(exemption["applies_to_log_date"], tz)
        if prev_clock < midnight <= new_clock:
            exemption["status"] = "EXPIRED"
            store.bump(exemption)
            count += 1
    return count


def active_exemption_for_driver_on_date(driver_id: str, log_date: str):
    """Return the first ACTIVE exemption attached to (driver, log_date), or None."""
    for ex in store.adverse_exemptions.values():
        if (
            ex.get("driver_id") == driver_id
            and ex.get("status") == "ACTIVE"
            and ex.get("applies_to_log_date") == log_date
        ):
            return ex
    return None
