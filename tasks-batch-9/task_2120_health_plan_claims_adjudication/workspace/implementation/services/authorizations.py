"""Authorization unit consumption and derived status (PRD 3.3).

status is never set directly by an operator except by revocation: it is
re-derived from units_consumed every single time that number changes, in
either direction.
"""

from store import db


def derive_status(auth):
    if auth["status"] == "REVOKED":
        return "REVOKED"
    if auth["units_consumed"] <= 0:
        return "ACTIVE"
    if auth["units_consumed"] >= auth["authorized_units"]:
        return "EXHAUSTED"
    return "PARTIALLY_CONSUMED"


def consume(auth, units):
    auth["units_consumed"] = auth["units_consumed"] + units
    auth["status"] = derive_status(auth)
    db.touch(auth)
    return auth


def release(auth, units):
    auth["units_consumed"] = max(0, auth["units_consumed"] - units)
    auth["status"] = derive_status(auth)
    db.touch(auth)
    return auth
