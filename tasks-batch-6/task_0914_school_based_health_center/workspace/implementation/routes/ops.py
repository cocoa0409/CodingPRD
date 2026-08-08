"""Logical clock and the daily epoch advance (PRD 2.5, 3.12)."""

from flask import Blueprint

import clock
import config
import envelope
import store
from fields import Field
from ladder import Op
from services import cascades

bp = Blueprint("ops", __name__)


@bp.post("/sbhc/_clock/set_current_utc")
def set_clock():
    op = Op("POST /sbhc/_clock/set_current_utc", ["SbhcAdmin"])
    op.schema([Field("to_iso8601", "datetime", required=True)])
    op.run()
    raw = op.body["to_iso8601"]
    clock.CLOCK.set(raw, clock.parse_datetime(raw))
    # The caller's own string is echoed back verbatim; it is never re-rendered.
    return envelope.ok({"current_utc": clock.current_utc_raw()})


@bp.post("/sbhc/operations/daily-sweep")
def daily_sweep():
    op = Op("POST /sbhc/operations/daily-sweep", ["SbhcAdmin"])
    op.run()

    consents_expired = 0
    for consent in store.all_rows("consents"):
        if consent["status"] != "ACTIVE":
            continue
        expires = clock.parse_datetime(consent["expires_at"])
        if clock.now_dt() > expires:
            consent["status"] = "EXPIRED"
            store.touch(consent)
            consents_expired += 1

    clearances_expired = 0
    today = clock.now_date()
    for clearance in store.all_rows("clearances"):
        if clearance["status"] == "ACTIVE":
            if clearance["valid_until"] is not None and today > clock.parse_date(
                clearance["valid_until"]
            ):
                clearance["status"] = "EXPIRED"
                store.touch(clearance)
                clearances_expired += 1
        elif clearance["status"] == "PENDING_REEVALUATION":
            deadline = clock.add_days(
                clock.parse_date(clearance["determination_date"]),
                config.DEFERRAL_REEVALUATION_WINDOW_DAYS,
            )
            if today > deadline:
                clearance["status"] = "EXPIRED"
                store.touch(clearance)
                clearances_expired += 1

    students = store.all_rows("students")
    for student in students:
        changed = cascades.recompute_compliance(student, raise_events=True)
        if changed:
            store.touch(student)

    return envelope.ok(
        {
            "consents_expired": consents_expired,
            "clearances_expired": clearances_expired,
            "students_recomputed": len(students),
            "current_utc": clock.current_utc_raw(),
        }
    )
