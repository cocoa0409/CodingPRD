"""Device gateway ingress and the append-only access log (PRD §3.6)."""
from flask import Blueprint

import calc
import serialize
from core import (
    DEVICE, READ_ROLES, authenticate, body, db, fail, iso, lookup, new_common,
    now, ok, ordered, paginate, parse_dt, present, qfilter, touch,
)

bp = Blueprint("event", __name__)

ACTOR_TYPES = ("MEMBER", "CONTRACTOR", "UNKNOWN")


@bp.post("/_devices/access-attempts")
def access_attempt():
    authenticate([DEVICE])
    payload = body()

    # Rung 4 — body foreign keys, in declared input order.
    lockbox = None
    credential = None
    grant = None
    if present(payload, "lockbox_id"):
        lockbox = lookup("lockboxes", payload["lockbox_id"])
    if present(payload, "credential_id"):
        credential = lookup("credentials", payload["credential_id"])
    if present(payload, "grant_id"):
        grant = lookup("grants", payload["grant_id"])

    # Rung 5 — request shape.
    if lockbox is None:
        fail("ERR_INVALID_REQUEST", "lockbox_id is required.")
    if not present(payload, "actor_type") or payload["actor_type"] not in ACTOR_TYPES:
        fail("ERR_INVALID_REQUEST", "actor_type must be one of MEMBER, CONTRACTOR, UNKNOWN.")
    if present(payload, "occurred_at"):
        occurred_at = parse_dt(payload["occurred_at"])
        if occurred_at is None:
            fail("ERR_INVALID_REQUEST", "occurred_at must be an ISO 8601 instant.")
    else:
        occurred_at = now()

    # The pinned outcome ladder — the first matching rung wins.
    if lockbox["status"] == "MISSING":
        outcome = "DENIED_BOX_MISSING"
    elif credential is not None and credential["status"] != "ACTIVE":
        outcome = "DENIED_CREDENTIAL_INACTIVE"
    elif grant is not None and (
        grant["status"] != "APPROVED"
        or not (parse_dt(grant["window_start"]) <= occurred_at < parse_dt(grant["window_end"]))
    ):
        outcome = "DENIED_OUTSIDE_WINDOW"
    elif credential is None and grant is None:
        outcome = "DENIED_NO_CREDENTIAL"
    else:
        outcome = "GRANTED"

    listing_id = lockbox.get("current_listing_id")
    after_hours = calc.compute_after_hours(occurred_at)

    rec = new_common(extra_ts=False)
    rec.update({
        "lockbox_id": lockbox["id"],
        "credential_id": credential["id"] if credential else None,
        "grant_id": grant["id"] if grant else None,
        "listing_id": listing_id,
        "matched_appointment_id": None,
        "incident_review_id": None,
        "actor_type": payload["actor_type"],
        "occurred_at": iso(occurred_at),
        "outcome": outcome,
        "after_hours": after_hours,
    })
    rec["risk_weight"] = float(calc.event_risk_weight(rec))

    # Showing attribution — only for GRANTED events presenting a credential.
    if outcome == "GRANTED" and credential is not None and listing_id:
        candidates = []
        for appt in ordered(db.appointments):
            if appt["listing_id"] != listing_id or appt["status"] != "CONFIRMED":
                continue
            if appt["showing_member_id"] != credential["member_id"]:
                continue
            start = parse_dt(appt["window_start"])
            end = parse_dt(appt["window_end"])
            if start is None or end is None:
                continue
            if start <= occurred_at <= end:
                candidates.append(appt)
        if candidates:
            candidates.sort(key=lambda a: (a["window_start"], a.get("created_at") or "",
                                           a.get("_seq", 0)))
            rec["matched_appointment_id"] = candidates[0]["id"]

    db.events[rec["id"]] = rec

    # A granted event raises the grant's uses_count and may consume it.
    if outcome == "GRANTED" and grant is not None and grant["status"] == "APPROVED":
        if serialize.grant_uses_count(grant["id"]) >= grant["max_uses"]:
            grant["status"] = "CONSUMED"
            touch(grant)

    return ok(serialize.event(rec), 201)


@bp.get("/access-events/<event_id>")
def read_event(event_id):
    authenticate(READ_ROLES)
    return ok(serialize.event(lookup("events", event_id)))


@bp.get("/access-events")
def list_events():
    authenticate(READ_ROLES)
    rows = ordered(db.events)
    rows = qfilter(rows, "lockbox_id")
    rows = qfilter(rows, "credential_id")
    rows = qfilter(rows, "grant_id")
    rows = qfilter(rows, "listing_id")
    rows = qfilter(rows, "matched_appointment_id")
    rows = qfilter(rows, "incident_review_id")
    rows = qfilter(rows, "outcome")
    return paginate(rows, serialize.event)
