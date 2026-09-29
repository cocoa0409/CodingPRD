"""The logical clock and its three advancement sweeps (PRD 2.6)."""

from flask import Blueprint

from db import db, sort_records, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, json_body
from response import ok
from validation import req_ts

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(ALL_ROLES)
    body = json_body()
    current_utc = req_ts(body, "current_utc")

    if current_utc < db.current_utc:
        fail("ERR_CLOCK_NOT_MONOTONIC", "The logical clock may only move forward.")

    db.current_utc = current_utc

    # Sweep one: reusable domain control validations lapse (inclusive).
    for auth in sort_records(list(db.authorizations.values())):
        if (auth["state"] == "VALIDATED" and auth["expires_at"] is not None
                and auth["expires_at"] <= current_utc):
            auth["state"] = "EXPIRED"
            touch(auth)

    # Sweep two: certificates age out (inclusive, independent of revocation).
    for cert in sort_records(list(db.certificates.values())):
        if (cert["lifecycle_status"] in ("PREISSUANCE", "ISSUED")
                and cert["not_after"] is not None and cert["not_after"] <= current_utc):
            cert["lifecycle_status"] = "EXPIRED"
            touch(cert)

    # Sweep three: missed disclosure deadlines are flagged (strict).
    for incident in sort_records(list(db.incidents.values())):
        if (incident["state"] == "OPEN" and not incident["disclosure_breached"]
                and incident["disclosure_due_at"] is not None
                and incident["disclosure_due_at"] < current_utc):
            incident["disclosure_breached"] = True
            touch(incident)

    return ok({})
