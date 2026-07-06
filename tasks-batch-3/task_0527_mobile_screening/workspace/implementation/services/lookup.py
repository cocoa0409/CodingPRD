"""Resource lookup with resource-specific 404 error ids."""
from db import db
from errors import err

_NOT_FOUND = {
    "mobile_units": "ERR_UNIT_NOT_FOUND",
    "staff": "ERR_STAFF_NOT_FOUND",
    "sponsors": "ERR_SPONSOR_NOT_FOUND",
    "grants": "ERR_GRANT_NOT_FOUND",
    "events": "ERR_EVENT_NOT_FOUND",
    "participants": "ERR_PARTICIPANT_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "referrals": "ERR_REFERRAL_NOT_FOUND",
    "charges": "ERR_CHARGE_NOT_FOUND",
    "reminders": "ERR_REMINDER_NOT_FOUND",
}


def get_or_404(collection_name, rid):
    coll = getattr(db, collection_name)
    ent = coll.get(rid)
    if ent is None:
        raise err(_NOT_FOUND[collection_name], "%s not found" % rid)
    return ent
