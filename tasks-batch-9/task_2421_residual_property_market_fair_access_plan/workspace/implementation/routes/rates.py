"""Rate filings and regulatory approval (PRD 3.2)."""

from flask import Blueprint

import lookup
from db import db, new_record, touch
from errors import fail
from middleware import require
from response import created, ok
from services import premium as premium_svc
from services import ratefiling as rate_svc
from services.constants import (
    FILING_QUIET_BUFFER_DAYS,
    MIN_VOLUNTARY_DIFFERENTIAL_PCT,
    PERIL_PACKAGES,
    REVIEW_DECISIONS,
)
from util import add_days, parse_date
from validate import (
    body,
    opt_string,
    req_date,
    req_enum,
    req_int,
    req_string,
    store_date,
)

bp = Blueprint("rates", __name__)


@bp.post("/rate-filings")
def create_filing():
    caller = require("RateAnalyst")
    data = body()
    cat_zone_id = req_string(data, "cat_zone_id")
    peril_package = req_enum(data, "peril_package", PERIL_PACKAGES)
    filed_rate = req_int(data, "filed_rate_per_1000_cents", positive=True)
    voluntary_rate = req_int(
        data, "voluntary_market_avg_rate_per_1000_cents", positive=True)
    effective_date = req_date(data, "effective_date")
    expected_zone_version = req_int(data, "expected_zone_version", minimum=0)

    zone = lookup.cat_zone(cat_zone_id)

    if expected_zone_version != zone["version"]:
        fail("ERR_STALE_VERSION",
             "Territory version is %s, not %s"
             % (zone["version"], expected_zone_version))

    differential_pct = premium_svc.differential_pct(filed_rate, voluntary_rate)
    if differential_pct < MIN_VOLUNTARY_DIFFERENTIAL_PCT:
        fail("ERR_RATE_BELOW_VOLUNTARY_FLOOR",
             "Differential %s is below the non-competition floor 0.1000"
             % differential_pct)

    filing = new_record({
        "cat_zone_id": zone["id"],
        "peril_package": peril_package,
        "filed_rate_per_1000_cents": filed_rate,
        "voluntary_market_avg_rate_per_1000_cents": voluntary_rate,
        "effective_date": store_date(effective_date),
        "differential_pct": differential_pct,
        "status": "FILED",
        "filed_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
        "review_note": None,
    })
    db.rate_filings[filing["id"]] = filing

    # A new filing changes the territory's rate posture.
    touch(zone)
    return created(filing)


@bp.post("/rate-filings/<filing_id>/review")
def review_filing(filing_id):
    caller = require("Regulator")
    data = body()
    decision = req_enum(data, "decision", REVIEW_DECISIONS)
    note = opt_string(data, "note")

    filing = lookup.rate_filing(filing_id)
    if filing["status"] != "FILED":
        fail("ERR_FILING_NOT_REVIEWABLE",
             "Filing status %s is not reviewable" % filing["status"])

    if filing["filed_by_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The analyst who filed the rate may not review it")

    incumbent = None
    if decision == "APPROVE":
        incumbent = rate_svc.latest_approved_filing(
            filing["cat_zone_id"], filing["peril_package"])
        if incumbent is not None:
            earliest = add_days(parse_date(incumbent["effective_date"]),
                                FILING_QUIET_BUFFER_DAYS)
            if parse_date(filing["effective_date"]) < earliest:
                fail("ERR_FILING_WINDOW_CONFLICT",
                     "Filings on this territory and package must be separated "
                     "by a thirty-day quiet buffer")

    filing["reviewed_by_user_id"] = caller.user_id
    filing["review_note"] = note
    filing["status"] = "APPROVED" if decision == "APPROVE" else "DISAPPROVED"
    touch(filing)

    if decision == "APPROVE":
        if incumbent is not None and (parse_date(filing["effective_date"])
                                      > parse_date(incumbent["effective_date"])):
            incumbent["status"] = "SUPERSEDED"
            touch(incumbent)
        # The territory's rate posture changed; a disapproval does not.
        touch(db.cat_zones[filing["cat_zone_id"]])

    return ok(filing)


@bp.get("/rate-filings/<filing_id>")
def read_filing(filing_id):
    require("RateAnalyst", "Regulator", "Underwriter", "PlanAdmin")
    return ok(lookup.rate_filing(filing_id))
