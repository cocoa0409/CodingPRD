"""The compliance sweep: the platform's batch conscience."""

from flask import Blueprint

import calc
import store
import validation as v
from envelope import ok
from events import SYSTEM_ACTOR, append_event
from security import actor

bp = Blueprint("sweep", __name__)


@bp.post("/roi/compliance-sweeps")
def compliance_sweep():
    uid, role = actor(["PlatformAdmin", "PrivacyOfficer"])
    v.body()

    expired_authorization_ids = []
    for auth in store.ordered(list(store.authorizations.values())):
        if auth["status"] != "VALID":
            continue
        expires_at = store.parse_dt(auth["expires_at"])
        if expires_at is None or expires_at > store.now():
            continue
        auth["status"] = "EXPIRED"
        store.touch(auth)
        expired_authorization_ids.append(auth["id"])
        # the event is recorded against every live request the lapse touches
        for req in store.ordered(list(store.requests.values())):
            if req.get("authorization_id") != auth["id"]:
                continue
            if req["fulfillment_status"] in store.TERMINAL_FULFILLMENT:
                continue
            append_event(req["id"], "AUTHORIZATION_EXPIRED", SYSTEM_ACTOR,
                         days_late=calc.turnaround(req)["days_late_strict"],
                         detail="authorization_id=%s" % auth["id"])

    swept_request_count = 0
    breached_request_ids = []
    penalized_request_ids = []
    total_penalty_delta_cents = 0
    touched_facilities = []

    for req in store.ordered(list(store.requests.values())):
        if req["fulfillment_status"] in store.TERMINAL_FULFILLMENT:
            continue
        swept_request_count += 1
        calc.refresh_statutory_due_at(req)
        measured = calc.turnaround(req)
        delta = calc.refresh_penalties(req, SYSTEM_ACTOR)
        if measured["breached"]:
            breached_request_ids.append(req["id"])
        if delta > 0:
            penalized_request_ids.append(req["id"])
            total_penalty_delta_cents += delta
        if req["facility_id"] not in touched_facilities:
            touched_facilities.append(req["facility_id"])

    for facility_id in touched_facilities:
        calc.refresh_facility_penalty(facility_id)

    return ok({
        "swept_request_count": swept_request_count,
        "breached_request_ids": breached_request_ids,
        "penalized_request_ids": penalized_request_ids,
        "total_penalty_delta_cents": total_penalty_delta_cents,
        "expired_authorization_ids": expired_authorization_ids,
    })
