"""Pickup schedule generation and holiday shift (SCAFFOLD §1.3 holiday_shift,
PRD §3.3, §3.6).
"""
from datetime import timedelta

import db
import clock
from util import parse_dt, to_midnight, iso_now
from services.common import new_record


def effective_pickup_date(account, service_date):
    """Map service_date -> effective_pickup_date via the zone's holiday calendar.

    Exact date match: if a Holiday on the account's zone has holiday_date ==
    service_date and shift_direction == DELAY_ONE_DAY, shift +1 day. Else
    unchanged. No ripple to later same-week pickups.
    """
    sd = to_midnight(parse_dt(service_date)) if isinstance(service_date, str) else to_midnight(service_date)
    zone_id = account["zone_id"]
    for hol in db.holidays.values():
        if hol["zone_id"] != zone_id:
            continue
        hd = to_midnight(parse_dt(hol["holiday_date"]))
        if hd == sd and hol["shift_direction"] == "DELAY_ONE_DAY":
            return sd + timedelta(days=1)
    return sd


def _iso_week(dt):
    return dt.isocalendar()[1]


def generate_schedule_rows(account, zone):
    """Generate PickupSchedule rows covering the next 28 days from the clock date.

    TRASH on every zone.base_pickup_weekday in the window. RECYCLING on the same
    weekday but only on weeks whose ISO week number parity matches
    zone.recycling_week_parity (EVEN/ODD). Each row begins PLANNED with
    effective_pickup_date derived from the holiday calendar.
    """
    start = clock.today_date()  # UTC midnight of the current clock date
    base_weekday = zone["base_pickup_weekday"]  # 0=Mon .. 6=Sun
    parity = zone["recycling_week_parity"]  # EVEN | ODD

    for offset in range(0, 28):
        day = start + timedelta(days=offset)
        # Python weekday(): Monday=0 .. Sunday=6, matches the zone convention.
        if day.weekday() != base_weekday:
            continue
        # TRASH every pickup weekday
        _create_row(account, day, "TRASH")
        # RECYCLING only on matching-parity ISO weeks
        wk = _iso_week(day)
        is_even = (wk % 2 == 0)
        if (parity == "EVEN" and is_even) or (parity == "ODD" and not is_even):
            _create_row(account, day, "RECYCLING")


def _create_row(account, service_date, stream, is_extra=False):
    eff = effective_pickup_date(account, service_date)
    rec = new_record({
        "account_id": account["id"],
        "service_date": _fmt_midnight(service_date),
        "stream": stream,
        "effective_pickup_date": _fmt_midnight(eff),
        "status": "PLANNED",
        "_is_extra": is_extra,
    })
    db.pickup_schedules[rec["id"]] = rec
    return rec


def _fmt_midnight(dt):
    """Format a UTC-midnight date (PRD §3.6 date field; no fractional seconds)."""
    from util import format_date
    return format_date(to_midnight(dt))


def cancel_future_planned(account):
    """Suspend cascade: cancel PLANNED rows whose effective_pickup_date >= clock date."""
    today = clock.today_date()
    for s in db.pickup_schedules.values():
        if s["account_id"] != account["id"]:
            continue
        if s["status"] != "PLANNED":
            continue
        eff = to_midnight(parse_dt(s["effective_pickup_date"]))
        if eff >= today:
            s["status"] = "CANCELLED"
            _touch(s)


def cancel_all_planned(account):
    """Stop / transfer cascade: cancel ALL PLANNED rows on the account."""
    for s in db.pickup_schedules.values():
        if s["account_id"] != account["id"]:
            continue
        if s["status"] == "PLANNED":
            s["status"] = "CANCELLED"
            _touch(s)


def _touch(rec):
    from services.common import touch
    touch(rec)
