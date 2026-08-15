"""The deterministic clock sweep (PRD §2.4): four effects, in order."""

import db
from services import risk


def _window_covers_today(w, today):
    return w["start_date"] <= today <= w["end_date"]


def _sync_vessel_availability(vessel_id, today):
    """Vessel returns to AVAILABLE when no active window covers today."""
    for w in db.all_of("maintenance_windows"):
        if w["vessel_id"] != vessel_id:
            continue
        if w["status"] in ("SCHEDULED", "IN_PROGRESS") and _window_covers_today(w, today):
            return
    vessel = db.get("vessels", vessel_id)
    if vessel is not None and vessel["status"] == "IN_MAINTENANCE":
        vessel["status"] = "AVAILABLE"
        db.touch(vessel)


def run_sweep():
    """Execute the sweep for the current logical clock; return the summary."""
    now = db.get_clock()
    today = now.date()
    summary = {
        "certificates_expired": 0,
        "renters_suspended": 0,
        "bookings_cancelled": 0,
        "maintenance_windows_started": 0,
        "maintenance_windows_completed": 0,
        "weather_advisories_expired": 0,
        "bookings_expired": 0,
    }

    # 1. VERIFIED certificates whose expires_on falls before the current date
    #    -> EXPIRED, with renter recompute and the suspension cascade.
    for cert in db.sorted_created(db.all_of("certificates")):
        if cert["status"] == "VERIFIED" and cert["expires_on"] < today:
            cert["status"] = "EXPIRED"
            db.touch(cert)
            summary["certificates_expired"] += 1
            renter = db.get("renters", cert["renter_id"])
            if renter is not None:
                newly_suspended, cancelled = risk.recompute_qualification(renter)
                if newly_suspended:
                    summary["renters_suspended"] += 1
                    summary["bookings_cancelled"] += cancelled

    # 2. Maintenance windows: SCHEDULED -> IN_PROGRESS when the current date
    #    enters the closed interval (vessel -> IN_MAINTENANCE); IN_PROGRESS ->
    #    COMPLETED once the current date passes end_date (vessel -> AVAILABLE
    #    when no other window covers the current date).
    for w in db.sorted_created(db.all_of("maintenance_windows")):
        if w["status"] == "SCHEDULED" and _window_covers_today(w, today):
            w["status"] = "IN_PROGRESS"
            db.touch(w)
            summary["maintenance_windows_started"] += 1
            vessel = db.get("vessels", w["vessel_id"])
            if vessel is not None and vessel["status"] == "AVAILABLE":
                vessel["status"] = "IN_MAINTENANCE"
                db.touch(vessel)
    for w in db.sorted_created(db.all_of("maintenance_windows")):
        if w["status"] == "IN_PROGRESS" and today > w["end_date"]:
            w["status"] = "COMPLETED"
            db.touch(w)
            summary["maintenance_windows_completed"] += 1
            _sync_vessel_availability(w["vessel_id"], today)

    # 3. ACTIVE advisories whose window_end lies before the current clock
    #    -> EXPIRED.
    for a in db.sorted_created(db.all_of("weather_advisories")):
        if a["status"] == "ACTIVE" and a["window_end"] < now:
            a["status"] = "EXPIRED"
            db.touch(a)
            summary["weather_advisories_expired"] += 1

    # 4. HELD bookings whose hold_expires_at lies before the current clock
    #    -> EXPIRED; the never-captured deposit goes PENDING -> RELEASED.
    for b in db.sorted_created(db.all_of("bookings")):
        if b["status"] == "HELD" and b["hold_expires_at"] < now:
            b["status"] = "EXPIRED"
            b["deposit_status"] = "RELEASED"
            b["deposit_applied_cents"] = 0
            b["deposit_released_cents"] = 0
            db.touch(b)
            summary["bookings_expired"] += 1

    return summary
