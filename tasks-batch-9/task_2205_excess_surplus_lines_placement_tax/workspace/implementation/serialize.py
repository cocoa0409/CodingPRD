"""Record -> JSON body shaping. Private keys (leading underscore) never leak."""

import clock


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def license_status(rec):
    """BrokerLicense.status is never stored: ACTIVE while the logical clock is
    strictly before expires_on, LAPSED once the clock reaches or passes it."""
    expires = rec.get("_expires_at")
    if expires is None:
        return "ACTIVE"
    return "ACTIVE" if clock.now() < expires else "LAPSED"


def broker_license(rec):
    out = public(rec)
    out["status"] = license_status(rec)
    return out


def broker_licenses(rows):
    return [broker_license(r) for r in rows]


def many(rows):
    return [public(r) for r in rows]
