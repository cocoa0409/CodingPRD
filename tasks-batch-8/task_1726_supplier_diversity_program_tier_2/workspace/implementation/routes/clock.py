"""Logical clock endpoint (PRD 2.6, 3.5): fires the expiration and
activation sweeps at the new date."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from services.core import (
    touch,
    refresh_diverse_eligible,
    refresh_risk_scores,
    recompute_events_for_supplier,
)
from util import CLOCK, clock_date, render_instant
from validate import get_body, req_clock_instant

bp = Blueprint("clock", __name__)


@bp.route("/api/v1/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorized(["DiversityAdmin"])
    body = get_body()
    to = req_clock_instant(body, "to_iso8601")
    CLOCK.set(to)
    new_date = clock_date()

    # Certification expiration sweep: VERIFIED with valid_to strictly before
    # the new clock date -> EXPIRED (valid_to == new date stays VERIFIED).
    affected_supplier_ids = []
    for cert in list(db["certifications"].values()):
        if cert["status"] == "VERIFIED" and cert["valid_to"] < new_date:
            cert["status"] = "EXPIRED"
            touch(cert)
            if cert["supplier_id"] not in affected_supplier_ids:
                affected_supplier_ids.append(cert["supplier_id"])
    for sid in affected_supplier_ids:
        supplier = db["suppliers"].get(sid)
        if supplier is None:
            continue
        changed = False
        if refresh_diverse_eligible(supplier):
            changed = True
            recompute_events_for_supplier(sid)
        if refresh_risk_scores(supplier):  # expired-unrenewed term
            changed = True
        if changed:
            touch(supplier)

    # Engagement activation sweep: ENROLLED with start_date <= new date.
    for eng in list(db["engagements"].values()):
        if eng["status"] == "ENROLLED" and eng["start_date"] <= new_date:
            eng["status"] = "ACTIVE"
            touch(eng)

    return success_object({"current_utc": render_instant(CLOCK.now())})
