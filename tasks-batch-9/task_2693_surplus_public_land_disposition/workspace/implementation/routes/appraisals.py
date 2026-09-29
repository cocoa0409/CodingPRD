"""Appraisal engagement, report, acceptance and the challenge track
(PRD 3.3, 3.4).
"""

from flask import Blueprint, g

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import (AGENCY_REP, APPRAISER, CLERK, FINANCE, MONITOR, RPO, SYSADMIN,
                        authorize)
from services import calc, derive, waterfall

bp = Blueprint("appraisals", __name__)

METHODS = ("SALES_COMPARISON", "INCOME", "COST")
APPRAISAL_STATUSES = ("ORDERED", "REPORTED", "ACCEPTED", "CHALLENGED", "SUPERSEDED",
                      "EXPIRED")
CHALLENGE_STATUSES = ("SUBMITTED", "SUSTAINED", "DENIED")
DETERMINATIONS = ("SUSTAINED", "DENIED")
READ_ROLES = (RPO, CLERK, MONITOR, AGENCY_REP, APPRAISER, SYSADMIN)
CHALLENGE_READ_ROLES = (RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, SYSADMIN)


@bp.post("/appraisals")
@authorize(RPO)
def create_appraisal():
    payload = shape.body()
    method = shape.req_enum(payload, "method", METHODS)
    start, start_raw = shape.req_instant(payload, "engagement_start_on")
    end, end_raw = shape.req_instant(payload, "engagement_end_on")
    expected_version = shape.req_int(payload, "expected_parcel_version")
    if end < start:
        fail("ERR_INVALID_REQUEST", "engagement_end_on may not precede engagement_start_on.")
    parcel_id = payload.get("parcel_id")
    if parcel_id is None:
        fail("ERR_INVALID_REQUEST", "parcel_id is required.")
    appraiser_id = payload.get("appraiser_id")
    if appraiser_id is None:
        fail("ERR_INVALID_REQUEST", "appraiser_id is required.")
    parcel = lookup.must_fk("parcels", parcel_id)
    appraiser = lookup.must_fk("appraisers", appraiser_id)

    if expected_version != parcel["version"]:
        fail("ERR_STALE_PARCEL_VERSION",
             "expected_parcel_version %s does not match the parcel's current version %s."
             % (expected_version, parcel["version"]))

    if (derive.license_status(appraiser) == "EXPIRED"
            or not appraiser["license_expires_on"] > end):
        fail("ERR_APPRAISER_LICENSE_EXPIRED",
             "The appraiser's licence does not cover the whole engagement.")

    if len(calc.intersecting_engagements(appraiser["id"], start, end)) >= \
            calc.APPRAISER_MAX_CONCURRENT_ENGAGEMENTS:
        fail("ERR_APPRAISER_CAPACITY_EXCEEDED",
             "The appraiser already holds two intersecting in-flight engagements.")

    row = db.insert("appraisals", {
        "parcel_id": parcel["id"],
        "appraiser_id": appraiser["id"],
        "method": method,
        "engagement_start_on": start,
        "engagement_end_on": end,
        "status": "ORDERED",
        "appraised_value_cents": None,
        "effective_date": None,
        "narrative": None,
        "reported_at": None,
        "expires_on": None,
        "challenge_count": 0,
        "revaluation_required": False,
        "accepted_at": None,
    })
    db.set_raw(row, "engagement_start_on", start_raw)
    db.set_raw(row, "engagement_end_on", end_raw)
    db.touch(parcel)
    return response.object_response(derive.appraisal_out(row), 201)


@bp.get("/appraisals/<row_id>")
@authorize(*READ_ROLES)
def get_appraisal(row_id):
    row = lookup.must("appraisals", row_id)
    return response.object_response(derive.appraisal_out(row))


@bp.get("/appraisals")
@authorize(*READ_ROLES)
def list_appraisals():
    limit, offset = listing.bounds()
    parcel_id = shape.query_str("parcel_id")
    appraiser_id = shape.query_str("appraiser_id")
    status = shape.query_enum("status", APPRAISAL_STATUSES)
    method = shape.query_enum("method", METHODS)
    rows = db.all_rows("appraisals")
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if appraiser_id is not None:
        rows = [r for r in rows if r["appraiser_id"] == appraiser_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    return listing.respond(rows, derive.appraisal_out, limit, offset, listing.by_created_at)


@bp.post("/appraisals/<row_id>/report")
@authorize(APPRAISER)
def report_appraisal(row_id):
    row = lookup.must("appraisals", row_id)
    if row["appraiser_id"] != g.user_id:
        fail("ERR_NOT_ENGAGED_APPRAISER",
             "Only the engaged appraiser may deliver this report.")
    payload = shape.body()
    value = shape.req_cents(payload, "appraised_value_cents")
    effective_date, effective_raw = shape.req_instant(payload, "effective_date")
    narrative = shape.req_str(payload, "narrative", 1)
    if row["status"] != "ORDERED":
        fail("ERR_INVALID_APPRAISAL_STATE",
             "A report requires the appraisal to be ORDERED.")
    row["appraised_value_cents"] = value
    row["effective_date"] = effective_date
    row["narrative"] = narrative
    row["reported_at"] = clockmod.now()
    row["expires_on"] = clockmod.plus_days(effective_date, calc.APPRAISAL_VALIDITY_DAYS)
    row["status"] = "REPORTED"
    db.set_raw(row, "effective_date", effective_raw)
    db.touch(row)
    return response.object_response(derive.appraisal_out(row))


@bp.post("/appraisals/<row_id>/accept")
@authorize(RPO)
def accept_appraisal(row_id):
    row = lookup.must("appraisals", row_id)
    open_challenge = any(c["appraisal_id"] == row["id"] and c["status"] == "SUBMITTED"
                         for c in db.all_rows("appraisal_challenges"))
    if row["status"] != "REPORTED" or open_challenge:
        fail("ERR_INVALID_APPRAISAL_STATE",
             "Acceptance requires a REPORTED appraisal with no pending challenge.")
    if clockmod.now() >= row["expires_on"]:
        fail("ERR_APPRAISAL_EXPIRED", "The report has passed its validity window.")

    row["accepted_at"] = clockmod.now()
    row["status"] = "ACCEPTED"
    db.touch(row)
    for other in derive.parcel_appraisals(row["parcel_id"]):
        if other["id"] != row["id"] and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    parcel = db.get("parcels", row["parcel_id"])
    if parcel is not None:
        parcel["_valuation_forced_stale"] = False
        db.touch(parcel)
    return response.object_response(derive.appraisal_out(row))


# --------------------------------------------------------------------------
# Appraisal challenges (PRD 3.4)
# --------------------------------------------------------------------------

def _served_agency_ids(parcel_id):
    """Every agency served a statutory notice on a declaration for this parcel."""
    declaration_ids = [d["id"] for d in db.all_rows("declarations")
                       if d["parcel_id"] == parcel_id]
    return set(n["recipient_agency_id"] for n in db.all_rows("notices")
               if n["declaration_id"] in declaration_ids)


@bp.post("/appraisals/<row_id>/challenges")
@authorize(AGENCY_REP)
def file_challenge(row_id):
    payload = shape.body()
    asserted = shape.req_cents(payload, "asserted_value_cents")
    grounds = shape.req_str(payload, "grounds", 1)
    deposit_paid = shape.req_cents(payload, "deposit_paid_cents")
    appraisal = lookup.must("appraisals", row_id)

    if appraisal["status"] != "REPORTED":
        fail("ERR_INVALID_APPRAISAL_STATE",
             "A challenge may only be filed against a REPORTED appraisal.")
    deadline = clockmod.plus_days(appraisal["reported_at"], calc.CHALLENGE_WINDOW_DAYS)
    if clockmod.now() > deadline:
        fail("ERR_CHALLENGE_WINDOW_CLOSED",
             "The 30-day challenge window has closed.")
    if g.user_id not in _served_agency_ids(appraisal["parcel_id"]):
        fail("ERR_CHALLENGER_NOT_ELIGIBLE",
             "Only an agency served with the statutory notice may challenge the value.")

    appraised = appraisal["appraised_value_cents"]
    threshold = calc.challenge_delta_threshold(appraised)
    if abs(asserted - appraised) < threshold:
        fail("ERR_CHALLENGE_DELTA_TOO_SMALL",
             "The asserted value must differ from the appraised value by at least 5 percent.")
    required = calc.challenge_required_deposit(appraised)
    if deposit_paid < required:
        fail("ERR_CHALLENGE_DEPOSIT_INSUFFICIENT",
             "deposit_paid_cents must be at least %d." % required)

    row = db.insert("appraisal_challenges", {
        "appraisal_id": appraisal["id"],
        "challenger_agency_id": g.user_id,
        "asserted_value_cents": asserted,
        "grounds": grounds,
        "required_deposit_cents": required,
        "deposit_paid_cents": deposit_paid,
        "status": "SUBMITTED",
        "determined_by_user_id": None,
        "revised_value_cents": None,
        "deposit_refunded_cents": 0,
        "deposit_forfeited_cents": 0,
    })
    appraisal["status"] = "CHALLENGED"
    appraisal["challenge_count"] += 1
    db.touch(appraisal)
    return response.object_response(derive.challenge_out(row), 201)


@bp.get("/appraisal-challenges/<row_id>")
@authorize(*CHALLENGE_READ_ROLES)
def get_challenge(row_id):
    row = lookup.must("appraisal_challenges", row_id)
    return response.object_response(derive.challenge_out(row))


@bp.get("/appraisal-challenges")
@authorize(*CHALLENGE_READ_ROLES)
def list_challenges():
    limit, offset = listing.bounds()
    appraisal_id = shape.query_str("appraisal_id")
    challenger_agency_id = shape.query_str("challenger_agency_id")
    status = shape.query_enum("status", CHALLENGE_STATUSES)
    rows = db.all_rows("appraisal_challenges")
    if appraisal_id is not None:
        rows = [r for r in rows if r["appraisal_id"] == appraisal_id]
    if challenger_agency_id is not None:
        rows = [r for r in rows if r["challenger_agency_id"] == challenger_agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, derive.challenge_out, limit, offset, listing.by_created_at)


@bp.post("/appraisal-challenges/<row_id>/determine")
@authorize(CLERK)
def determine_challenge(row_id):
    row = lookup.must("appraisal_challenges", row_id)
    appraisal = db.get("appraisals", row["appraisal_id"])
    if appraisal is not None:
        for declaration in db.all_rows("declarations"):
            if (declaration["parcel_id"] == appraisal["parcel_id"]
                    and declaration.get("adopted_by_user_id") == g.user_id):
                fail("ERR_SEGREGATION_OF_DUTIES",
                     "The clerk who adopted the surplus resolution may not rule on the value.")

    payload = shape.body()
    determination = shape.req_enum(payload, "determination", DETERMINATIONS)
    revised = shape.opt_cents(payload, "revised_value_cents")
    if determination == "SUSTAINED" and revised is None:
        fail("ERR_INVALID_REQUEST", "revised_value_cents is required when sustaining.")

    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_CHALLENGE_STATE",
             "A challenge that is %s cannot be determined again." % row["status"])
    if determination == "DENIED" and not db.all_rows("funds"):
        fail("ERR_FUNDS_NOT_CONFIGURED",
             "A forfeited deposit needs at least one designated fund.")

    row["determined_by_user_id"] = g.user_id
    if determination == "SUSTAINED":
        row["revised_value_cents"] = revised
        row["deposit_refunded_cents"] = row["deposit_paid_cents"]
        row["status"] = "SUSTAINED"
        db.touch(row)
        if appraisal is not None:
            appraisal["appraised_value_cents"] = revised
            appraisal["revaluation_required"] = True
            appraisal["status"] = "REPORTED"
            db.touch(appraisal)
        return response.object_response(derive.challenge_out(row))

    row["deposit_forfeited_cents"] = row["deposit_paid_cents"]
    row["status"] = "DENIED"
    db.touch(row)
    waterfall.post_challenge_forfeiture(row, row["deposit_paid_cents"])
    if appraisal is not None:
        appraisal["status"] = "REPORTED"
        db.touch(appraisal)
    return response.object_response(derive.challenge_out(row))
