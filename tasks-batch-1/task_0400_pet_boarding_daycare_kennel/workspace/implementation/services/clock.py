"""Clock-advance cascades (PRD §3.1, §3.3, §3.7).

Setting current_date := to_date, then:
  - recompute each affected pet's vaccination_status (VALID -> EXPIRED on lapse)
  - lapse ACTIVE packages whose 30-day cycle has run out into EXPIRED
"""
from db import db
from services.common import touch, parse_date
from services.pet import recompute_vaccination_status


def advance_clock(facility, to_date):
    facility["current_date"] = to_date
    touch(facility)

    # Pet vaccination expiry cascade (only pets in this facility).
    for pet in db.pets.values():
        if pet["facility_id"] != facility["id"]:
            continue
        recompute_vaccination_status(pet)

    # Package expiry cascade: ACTIVE package whose current_date is MORE than 30
    # days after cycle_start_date -> EXPIRED (PRD §3.7).
    cur = parse_date(to_date)
    for pkg in db.packages.values():
        if pkg["facility_id"] != facility["id"]:
            continue
        if pkg["status"] != "ACTIVE":
            continue
        lapsed_days = (cur - parse_date(pkg["cycle_start_date"])).days
        if lapsed_days > 30:
            pkg["status"] = "EXPIRED"
            touch(pkg)
