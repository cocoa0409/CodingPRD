"""License lifecycle helpers shared by routes and the clock sweep (PRD 3.3, 3.9)."""
from db import store
from util import touch


def has_accepted_return(license_id):
    return any(
        r["license_id"] == license_id and r["status"] == "ACCEPTED"
        for r in store.returns.values()
    )


def expire_license(lic):
    """Move an ISSUED license -> EXPIRED and bubble owning application -> EXPIRED.

    Caller is responsible for the precondition checks; this performs the cascade.
    """
    lic["status"] = "EXPIRED"
    touch(lic)
    app = store.applications.get(lic["application_id"])
    if app is not None and app["status"] == "APPROVED":
        app["status"] = "EXPIRED"
        touch(app)


def sweep_expired(now):
    """Expire every ISSUED license past expires_at with no accepted return."""
    for lic in list(store.licenses.values()):
        if lic["status"] != "ISSUED":
            continue
        if now > lic["expires_at"] and not has_accepted_return(lic["id"]):
            expire_license(lic)
