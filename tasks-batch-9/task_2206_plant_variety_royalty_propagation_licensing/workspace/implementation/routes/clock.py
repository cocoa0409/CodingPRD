"""The logical clock and its deterministic three-class time sweep (PRD 2.5)."""

from flask import Blueprint

from derive import (apply, grace_deadline, lapse_filing,
                    recompute_active_sublicense_count, recompute_compliance)
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import ok
from store import parse_dt, store
from validation import DateTime

bp = Blueprint("clock", __name__)

CLOCK_SCHEMA = [("current_utc", DateTime(), True)]


def sweep_filings():
    """Class 1: created_at ascending, ties by jurisdiction_code ascending."""
    filings = store.ordered("filings", lambda f: f["jurisdiction_code"])
    count = 0
    for filing in filings:
        if filing["status"] != "MAINTENANCE_DUE":
            continue
        deadline = grace_deadline(filing)
        if deadline is None or store.now <= deadline:
            continue
        lapse_filing(filing, "GRACE_EXPIRED")
        count += 1
    return count


def sweep_brands():
    """Class 2: created_at ascending, ties by denomination ascending."""
    varieties = store.ordered("varieties", lambda v: v["denomination"])
    count = 0
    for variety in varieties:
        if variety["brand_status"] != "BRAND_REGISTERED":
            continue
        due = parse_dt(variety["brand_renewal_due_at"])
        if due is None or store.now < due:
            continue
        apply(variety, {"brand_status": "BRAND_RENEWAL_DUE"})
        count += 1
    return count


def sweep_grants():
    """Class 3: created_at, then territory_code, then sublicensee_name."""
    grants = store.ordered("grants",
                           lambda g: g["territory_code"],
                           lambda g: g["sublicensee_name"])
    count = 0
    for grant in grants:
        if grant["status"] != "ACTIVE":
            continue
        expiry = parse_dt(grant["expiry_date"])
        # Only grants strictly past their expiry expire (closed upper bound).
        if expiry is None or store.now <= expiry:
            continue
        apply(grant, {"status": "EXPIRED"})
        variety = store.varieties.get(grant["variety_id"])
        if variety is not None:
            recompute_active_sublicense_count(variety)
        count += 1
    return count


def sweep_compliance():
    """The rolling window slid, so every propagator is recomputed."""
    propagators = store.ordered("propagators", lambda p: p["legal_name"])
    for propagator in propagators:
        recompute_compliance(propagator)
    return len(propagators)


@endpoint(bp, "POST", "/_clock/set_current_utc", ALL_ROLES, CLOCK_SCHEMA)
def set_current_utc(actor, body):
    target = parse_dt(body["current_utc"])
    if target <= store.now:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    store.now = target
    lapsed = sweep_filings()
    brands = sweep_brands()
    expired = sweep_grants()
    recomputed = sweep_compliance()
    return ok({
        "current_utc": store.now_iso(),
        "lapsed_filing_count": lapsed,
        "brand_renewal_due_count": brands,
        "expired_grant_count": expired,
        "compliance_recompute_count": recomputed,
    })
