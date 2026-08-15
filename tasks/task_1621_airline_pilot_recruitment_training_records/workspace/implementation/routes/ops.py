"""Ops-run checkpoint (daily scan) and the controllable logical clock."""

from datetime import timedelta

from db import store
from errors import ApiError
from middleware import require_roles
from services import (
    LAPSED_TO_EXPIRED_DAYS, bump, evaluate_currency, grounding_cascade,
    medical_status_at, restoration_sweep, touch,
)
from util import get_body, render_ts, success_object
from flask import Blueprint

bp = Blueprint("ops", __name__)


@bp.post("/_ops/run-daily-scan")
def run_daily_scan():
    require_roles("SystemAdmin")
    now = store.now()
    counters = {
        "medical_updated": 0,
        "requests_expired": 0,
        "bid_periods_closed": 0,
        "qualifications_grounded": 0,
        "qualifications_currency_updated": 0,
        "events_cancelled": 0,
    }

    # Phase 1: medical validity re-evaluation; certificates leaving VALID fire
    # the grounding cascade; then grounded qualifications restore when a VALID
    # FIRST-class certificate exists again.
    cascade_applicants = []
    for cert in sorted(store.medical_certificates.values(), key=lambda m: m.get("_seq", 0)):
        if cert["status"] not in ("VALID", "DOWNGRADED"):
            continue  # SUSPENDED and EXPIRED are terminal for scan purposes
        evaluated = medical_status_at(cert, now)
        # The certificate machine is monotone: VALID -> DOWNGRADED/EXPIRED and
        # DOWNGRADED -> EXPIRED only. A DOWNGRADED certificate never returns to
        # VALID, even if the logical clock moves backwards.
        if cert["status"] == "DOWNGRADED" and evaluated != "EXPIRED":
            continue
        if evaluated != cert["status"]:
            left_valid = cert["status"] == "VALID"
            cert["status"] = evaluated
            touch(cert)  # scan-driven: updated_at refreshed, no version bump
            counters["medical_updated"] += 1
            if left_valid:
                cascade_applicants.append(cert["applicant_id"])
    for applicant_id in cascade_applicants:
        grounded, cancelled = grounding_cascade(applicant_id)
        counters["qualifications_grounded"] += grounded
        counters["events_cancelled"] += cancelled
    restoration_sweep()

    # Phase 2: records requests still SENT past due_at -> EXPIRED.
    for rec in store.records_requests.values():
        if rec["status"] == "SENT" and rec["due_at"] is not None and now > rec["due_at"]:
            rec["status"] = "EXPIRED"
            touch(rec)
            counters["requests_expired"] += 1

    # Phase 3: bid periods still OPEN past closes_at -> CLOSED.
    for period in store.bid_periods.values():
        if period["status"] == "OPEN" and now > period["closes_at"]:
            period["status"] = "CLOSED"
            bump(period)  # the close transition lists version += 1 for both triggers
            counters["bid_periods_closed"] += 1

    # Phase 4: currency re-evaluation for every qualification not yet EXPIRED,
    # then long-lapsed qualifications promote to EXPIRED.
    for qual in sorted(store.qualifications.values(), key=lambda q: q.get("_seq", 0)):
        if qual["currency_state"] == "EXPIRED":
            continue
        if evaluate_currency(qual):
            counters["qualifications_currency_updated"] += 1
        if (qual["currency_state"] == "LAPSED" and qual["lapsed_since"] is not None
                and qual["lapsed_since"] <= now - timedelta(days=LAPSED_TO_EXPIRED_DAYS)):
            qual["currency_state"] = "EXPIRED"
            touch(qual)
            counters["qualifications_currency_updated"] += 1

    return success_object(counters)


@bp.post("/_clock/set-current-utc")
def set_current_utc():
    require_roles("SystemAdmin")
    body = get_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is required and must be an ISO 8601 string")
    from util import parse_ts
    store.set_clock(parse_ts(to_iso8601, "to_iso8601"))
    return success_object({"current_utc": render_ts(store.now())})
