"""Clock-driven and close-driven cascades.

Implements the automatic transitions specified in the PRD:
  - KDM ISSUED -> LIVE when clock >= valid_from_utc (and booking.print_status -> KEY_LIVE)
  - KDM LIVE -> EXPIRED when clock >= valid_until_utc (half-open: equality is expired)
  - ZoneClearance GRANTED/UPHELD -> EXPIRED when clock > effective_until_utc (closed)
  - BookingAgreement ACCEPTED -> IN_PLAY when clock >= opening_date AND print_status == KEY_LIVE
  - Film ANCILLARY_PENDING -> ANCILLARY_RELEASED when clock >= theatrical_window_end AND >=1 SCHEDULED window
  - AncillaryWindow SCHEDULED -> HANDED_OFF as part of the film handoff
  - IN_RELEASE -> HOLDOVER_PHASE when any booking becomes holdover-eligible (checked on settle/write-off)
"""
from datetime import timedelta

from db import db
from services.core import touch
from services.clock import get_logical_clock
from util import parse_dt, iso_from_dt


def _bump_kdm_states():
    now = get_logical_clock()
    for k in db.kdm_keys.values():
        vf = parse_dt(k["valid_from_utc"])
        vu = parse_dt(k["valid_until_utc"])
        if k["status"] == "ISSUED" and vf is not None and now >= vf:
            k["status"] = "LIVE"
            touch(k)
            b = db.booking_agreements.get(k["booking_agreement_id"])
            if b and b["print_status"] == "KDM_ISSUED":
                b["print_status"] = "KEY_LIVE"
                touch(b)
        if k["status"] == "LIVE" and vu is not None and now >= vu:
            k["status"] = "EXPIRED"
            touch(k)


def _bump_zone_clearance_expiry():
    now = get_logical_clock()
    for z in db.zone_clearances.values():
        if z["status"] in ("GRANTED", "UPHELD"):
            eu = parse_dt(z["effective_until_utc"])
            if eu is not None and now > eu:
                z["status"] = "EXPIRED"
                touch(z)


def _bump_accepted_to_in_play():
    now = get_logical_clock()
    for b in db.booking_agreements.values():
        if b["deal_status"] == "ACCEPTED" and b["print_status"] == "KEY_LIVE":
            od = parse_dt(b["opening_date"])
            if od is not None and now >= od:
                b["deal_status"] = "IN_PLAY"
                touch(b)


def _bump_ancillary_handoff():
    """Drive SCHEDULED ancillary windows to HANDED_OFF and ANCILLARY_PENDING films to ANCILLARY_RELEASED."""
    now = get_logical_clock()
    for f in db.films.values():
        if f["lifecycle_status"] != "ANCILLARY_PENDING":
            continue
        twe = parse_dt(f["theatrical_window_end"])
        if twe is None or now < twe:
            continue
        # Find all SCHEDULED windows for this film
        scheduled = [w for w in db.ancillary_windows.values()
                     if w["film_id"] == f["id"] and w["status"] == "SCHEDULED"]
        if not scheduled:
            continue
        # Hand off each SCHEDULED window whose scheduled_start_utc <= now AND >= theatrical_window_end
        for w in scheduled:
            ss = parse_dt(w["scheduled_start_utc"])
            if ss is None:
                continue
            if now >= ss and now >= twe:
                w["status"] = "HANDED_OFF"
                w["actual_start_utc"] = iso_from_dt(now)
                touch(w)
        # If no SCHEDULED windows remain for this film, mark film released
        remaining = [w for w in db.ancillary_windows.values()
                     if w["film_id"] == f["id"] and w["status"] == "SCHEDULED"]
        if not remaining:
            f["lifecycle_status"] = "ANCILLARY_RELEASED"
            touch(f)


def run_clock_cascades():
    """Run after set_current_utc. Order matters: KDM first (so IN_PLAY can fire), then zones, then IN_PLAY, then ancillary."""
    _bump_kdm_states()
    _bump_zone_clearance_expiry()
    _bump_accepted_to_in_play()
    _bump_ancillary_handoff()


def check_film_holdover_phase(film_id):
    """If film is IN_RELEASE and any of its bookings is IN_PLAY with holdover_eligible, transition to HOLDOVER_PHASE."""
    f = db.films.get(film_id)
    if not f or f["lifecycle_status"] != "IN_RELEASE":
        return
    for b in db.booking_agreements.values():
        if b["film_id"] == film_id and b["deal_status"] == "IN_PLAY" and b["weeks_played"] >= b["min_weeks_committed"]:
            f["lifecycle_status"] = "HOLDOVER_PHASE"
            touch(f)
            return
