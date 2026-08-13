"""Market posture derivation (PRD 2.6, pinned evaluation order).

posture is derived from flags + timestamps; it is never written directly.
The WEATHER_ALERT branch is driven by the market's alert flag, which is set
when a triggering WeatherEvent arrives while the market is OPEN and cleared
only by clear_weather_alert (PRD 3.7: the market stays in WEATHER_ALERT until
an operator clears it once no triggering event is within the past 6 hours).
"""
from datetime import timedelta

import clock
import db


def derive_posture(market):
    if market["_cancelled_flag"]:
        return "CANCELLED"
    if clock.now() >= market["closes_at"]:
        return "CLOSED_SEASON"
    if market["_weather_alert_flag"]:
        return "WEATHER_ALERT"
    if market["_opened_flag"]:
        return "OPEN"
    return "SETUP"


def has_recent_alert(market_id):
    """True iff any WeatherEvent for the market within the past 6 hours has
    triggers_alert true (measured on observed_at). The window is
    [now - 6h, now]: an event observed in the future is not "in the past"."""
    now = clock.now()
    cutoff = now - timedelta(hours=6)
    for ev in db.STORES["weather_events"].values():
        if (
            ev["market_id"] == market_id
            and ev["triggers_alert"]
            and cutoff <= ev["observed_at"] <= now
        ):
            return True
    return False
