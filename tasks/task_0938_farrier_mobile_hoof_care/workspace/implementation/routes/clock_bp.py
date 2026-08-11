"""The logical clock, and the business events an advance sets off (PRD 2.4, 3.9)."""

from flask import Blueprint

from core.auth import authenticate
from core.envelope import ok
from core.store import db, order_key
from core.timeutil import clock, parse_iso_date, parse_iso_instant
from core.validate import bad, body
from domain.clients import refresh_client_standing
from domain.lameness import expire_prescription

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        bad("Field to_iso8601 is required.")
    parsed = parse_iso_instant(raw)
    if parsed is None:
        bad("Field to_iso8601 must be an ISO 8601 instant.")

    clock.set(raw, parsed)
    today = clock.today

    expired_ids = []
    due = []
    for prescription in db.all("vet_prescriptions"):
        if prescription["status"] != "ACTIVE":
            continue
        expires = parse_iso_date(prescription["expires_on"])
        if expires is not None and expires < today:
            due.append(prescription)
    for prescription in sorted(due, key=order_key):
        expire_prescription(prescription)
        expired_ids.append(prescription["id"])

    restanding_ids = []
    for client in db.all("clients"):
        row_changed, standing_changed = refresh_client_standing(client)
        if row_changed:
            db.touch(client)
        if standing_changed:
            restanding_ids.append(client["id"])

    # `current_utc` echoes the caller-supplied instant BYTE-VERBATIM: it is
    # never re-rendered into the server-minted `.mmmZ` form.
    return ok(
        {
            "current_utc": raw,
            "expired_prescription_ids": expired_ids,
            "restanding_client_ids": restanding_ids,
        }
    )
