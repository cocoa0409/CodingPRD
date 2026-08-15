"""Logical clock advancement and its time-based system transitions."""
import db
from services import coverage


def advance_clock(new_now):
    """Set the logical clock and fire all time-based transitions atomically."""
    db.CLOCK["now"] = new_now
    new_date = new_now.date()

    # 1. Credentials: ACTIVE -> EXPIRED when expires_on < new clock date,
    #    with driver suspension cascade for CDL_B / S_ENDORSEMENT.
    for cred in list(db.all_of("credentials")):
        if cred["status"] != "ACTIVE":
            continue
        expires = db.parse_date(cred["expires_on"])
        if expires is not None and expires < new_date:
            cred["status"] = "EXPIRED"
            db.touch(cred)
            coverage.expire_credential_cascade(cred)

    # 2. Inspections: SCHEDULED -> OVERDUE when scheduled_date < new date,
    #    with the grounding cascade.
    for insp in list(db.all_of("inspections")):
        if insp["status"] != "SCHEDULED":
            continue
        sched = db.parse_date(insp["scheduled_date"])
        if sched is not None and sched < new_date:
            insp["status"] = "OVERDUE"
            db.touch(insp)
            bus = db.find("buses", insp["bus_id"])
            if bus is not None:
                coverage.ground_bus(bus)

    # 3. CharterTrips: QUOTED -> EXPIRED once clock is strictly past
    #    quote_valid_until (exactly at the deadline stays QUOTED).
    for trip in list(db.all_of("charter_trips")):
        if trip["status"] != "QUOTED":
            continue
        valid_until = trip.get("_quote_valid_until_dt")
        if valid_until is not None and new_now > valid_until:
            trip["status"] = "EXPIRED"
            db.touch(trip)

    # 4. Contracts: ACTIVE -> EXPIRED once the clock date is past end_date.
    for contract in list(db.all_of("contracts")):
        if contract["status"] != "ACTIVE":
            continue
        end = db.parse_date(contract["end_date"])
        if end is not None and new_date > end:
            contract["status"] = "EXPIRED"
            db.touch(contract)
