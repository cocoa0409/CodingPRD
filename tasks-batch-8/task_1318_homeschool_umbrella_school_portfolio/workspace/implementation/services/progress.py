"""instructional_progress calculation (provisional and certified variants)."""
from collections import defaultdict

import db
from services import core

DAY_QUALIFYING_MINUTES = 240
DAILY_CREDIT_CAP_MINUTES = 600


def recompute_progress(enrollment):
    """Recompute both progress variants on the enrollment; touches it."""
    by_date_prov = defaultdict(int)
    by_date_cert = defaultdict(int)
    for entry in db.attendance_entries.values():
        if entry["enrollment_id"] != enrollment["id"]:
            continue
        if entry["status"] == "VOIDED":
            continue
        by_date_prov[entry["entry_date"]] += entry["minutes"]
        if entry["status"] == "VERIFIED":
            by_date_cert[entry["entry_date"]] += entry["minutes"]

    def tally(by_date):
        days = 0
        minutes = 0
        for total in by_date.values():
            if total >= DAY_QUALIFYING_MINUTES:
                days += 1
            minutes += min(total, DAILY_CREDIT_CAP_MINUTES)
        return days, minutes

    pd_, pm = tally(by_date_prov)
    cd, cm = tally(by_date_cert)
    enrollment["provisional_days_counted"] = pd_
    enrollment["provisional_minutes_credited"] = pm
    enrollment["certified_days_counted"] = cd
    enrollment["certified_minutes_credited"] = cm
    core.touch(enrollment)
