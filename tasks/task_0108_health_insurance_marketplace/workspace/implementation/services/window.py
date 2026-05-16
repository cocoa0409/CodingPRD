"""Enrollment window resolver — OEP / SEP / CLOSED."""

from datetime import date

from db import db
from clock import clock
from .dates import parse_iso_date


# OEP window: For simplicity, treat OEP for coverage_year N as the period
# from Nov 1 of (N-1) through Jan 15 of N.
def is_in_oep_for_year(coverage_year: int) -> bool:
    now = clock.now().date()
    oep_start = date(coverage_year - 1, 11, 1)
    oep_end = date(coverage_year, 1, 15)
    return oep_start <= now <= oep_end


def resolve_enrollment_window(app: dict) -> str:
    """Compute the current enrollment_window: OEP / SEP / CLOSED."""
    # If any VERIFIED SEP is still open, window is SEP
    now_date = clock.now().date()
    for s in db.sep_events.values():
        if s["application_id"] != app["id"]:
            continue
        if s["status"] != "VERIFIED":
            continue
        if not s.get("window_opens_on") or not s.get("window_closes_on"):
            continue
        wc = parse_iso_date(s["window_closes_on"])
        if wc >= now_date:
            return "SEP"
    if is_in_oep_for_year(app["coverage_year"]):
        return "OEP"
    return "CLOSED"


def refresh_enrollment_window(app: dict) -> None:
    new_w = resolve_enrollment_window(app)
    if new_w != app.get("enrollment_window"):
        app["enrollment_window"] = new_w
