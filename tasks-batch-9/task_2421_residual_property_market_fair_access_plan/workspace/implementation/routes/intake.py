"""Application assembly, submission routing and eligibility review
(PRD 3.3 / 3.4) plus inspection ordering (PRD 3.5)."""

from flask import Blueprint

import lookup
from db import db, new_record, touch
from errors import fail
from middleware import own, require
from response import created, ok
from routes.common import matches, page, unique
from services import eligibility as eligibility_svc
from services import premium as premium_svc
from services import ratefiling as rate_svc
from services import zone as zone_svc
from services.constants import (
    APPLICATION_STATUSES,
    CONSTRUCTION_TYPES,
    DECLINATION_REASONS,
    ELIGIBILITY_DECISIONS,
    INSPECTION_RESULTS,
    MAX_DWELLING_LIMIT_CENTS,
    OCCUPANCIES,
    PERIL_PACKAGES,
)
from validate import (
    body,
    filter_enum,
    filter_string,
    opt_date,
    opt_string,
    pagination,
    req_date,
    req_enum,
    req_int,
    req_score,
    req_string,
    store_date,
    store_instant,
)

bp = Blueprint("intake", __name__)


# --- applicants -----------------------------------------------------------

@bp.post("/applicants")
def create_applicant():
    require("Producer")
    data = body()
    full_name = req_string(data, "full_name")
    email = req_string(data, "email")
    phone = opt_string(data, "phone")

    unique(db.applicants, "email", email, "email")

    applicant = new_record({
        "full_name": full_name,
        "email": email,
        "phone": phone,
    })
    db.applicants[applicant["id"]] = applicant
    return created(applicant)


# --- properties -----------------------------------------------------------

@bp.post("/properties")
def create_property():
    require("Producer")
    data = body()
    cat_zone_id = req_string(data, "cat_zone_id")
    address_line = req_string(data, "address_line")
    zip_code = req_string(data, "zip_code")
    construction_type = req_enum(data, "construction_type", CONSTRUCTION_TYPES)
    roof_age_years = req_int(data, "roof_age_years", minimum=0)
    replacement_cost_cents = req_int(data, "replacement_cost_cents", positive=True)
    condition_score = req_score(data, "condition_score")
    occupancy = req_enum(data, "occupancy", OCCUPANCIES)

    zone = lookup.cat_zone(cat_zone_id)

    prop = new_record({
        "cat_zone_id": zone["id"],
        "address_line": address_line,
        "zip_code": zip_code,
        "construction_type": construction_type,
        "roof_age_years": roof_age_years,
        "replacement_cost_cents": replacement_cost_cents,
        "condition_score": condition_score,
        "occupancy": occupancy,
    })
    db.properties[prop["id"]] = prop
    return created(prop)


@bp.get("/properties/<property_id>")
def read_property(property_id):
    require("Producer", "Underwriter", "Inspector", "PlanAdmin")
    return ok(lookup.prop(property_id))


# --- applications ---------------------------------------------------------

@bp.post("/applications")
def create_application():
    caller = require("Producer")
    data = body()
    property_id = req_string(data, "property_id")
    applicant_id = req_string(data, "applicant_id")
    requested_dwelling_limit_cents = req_int(
        data, "requested_dwelling_limit_cents", positive=True)
    requested_peril_package = req_enum(data, "requested_peril_package", PERIL_PACKAGES)

    # Rung 5 resolves body foreign keys in the ladder's own order.
    applicant = lookup.applicant(applicant_id)
    prop = lookup.prop(property_id)

    # producer_id is never accepted in the body; it is the caller's identity.
    producer = db.producers.get(caller.user_id)
    if producer is None or producer["agreement_status"] != "APPOINTED":
        fail("ERR_PRODUCER_NOT_APPOINTED",
             "Producer %s is not APPOINTED" % caller.user_id)

    zone = zone_svc.zone_of_property(prop)
    if requested_peril_package == "EXTENDED_WIND" and zone["peril"] != "HURRICANE":
        fail("ERR_PERIL_NOT_OFFERED",
             "EXTENDED_WIND is offered only in HURRICANE territories")

    if (requested_dwelling_limit_cents > MAX_DWELLING_LIMIT_CENTS
            or requested_dwelling_limit_cents > prop["replacement_cost_cents"]):
        fail("ERR_COVERAGE_LIMIT_EXCEEDED",
             "Requested dwelling limit exceeds the statutory ceiling or the "
             "property's replacement cost")

    application = new_record({
        "property_id": prop["id"],
        "applicant_id": applicant["id"],
        "producer_id": producer["id"],
        "requested_dwelling_limit_cents": requested_dwelling_limit_cents,
        "requested_peril_package": requested_peril_package,
        "status": "DRAFT",
        "declination_count": 0,
        "eligibility_hold_reason": None,
        "decline_reason": None,
        "quoted_annual_premium_cents": 0,
        "voluntary_equivalent_premium_cents": 0,
        "voluntary_market_comparison_pct": 0.0,
        "quote_rate_filing_id": None,
        "submitted_at": None,
        "eligibility_reviewer_user_id": None,
        "approved_to_bind_at": None,
        "bind_deadline_at": None,
    })
    db.applications[application["id"]] = application
    return created(application)


@bp.get("/applications/<application_id>")
def read_application(application_id):
    require("Producer", "Underwriter", "Inspector", "PlanAdmin")
    return ok(lookup.application(application_id))


@bp.get("/applications")
def list_applications():
    require("Underwriter", "PlanAdmin")
    limit, offset = pagination()
    filters = {
        "applicant_id": filter_string("applicant_id"),
        "property_id": filter_string("property_id"),
        "producer_id": filter_string("producer_id"),
        "quote_rate_filing_id": filter_string("quote_rate_filing_id"),
        "status": filter_enum("status", APPLICATION_STATUSES),
    }
    rows = [a for a in db.applications.values() if matches(a, filters)]
    return page(rows, limit, offset)


# --- declinations ---------------------------------------------------------

@bp.post("/applications/<application_id>/declinations")
def record_declination(application_id):
    caller = require("Producer")
    data = body()
    member_insurer_id = req_string(data, "member_insurer_id")
    declined_on = req_date(data, "declined_on")
    reason_code = req_enum(data, "reason_code", DECLINATION_REASONS)
    evidence_reference = req_string(data, "evidence_reference")

    application = lookup.application(application_id)
    member = lookup.member(member_insurer_id)
    own(application["producer_id"] == caller.user_id,
        "Application belongs to another producer")

    for existing in db.declinations.values():
        if (existing["application_id"] == application["id"]
                and existing["member_insurer_id"] == member["id"]):
            fail("ERR_DUPLICATE_DECLINATION",
                 "This carrier has already declined this application")

    record = new_record({
        "application_id": application["id"],
        "member_insurer_id": member["id"],
        "declined_on": store_date(declined_on),
        "reason_code": reason_code,
        "evidence_reference": evidence_reference,
        "verified": member["status"] == "ACTIVE" and bool(evidence_reference.strip()),
    }, common=False)
    db.declinations[record["id"]] = record
    return created(record)


@bp.get("/applications/<application_id>/declinations")
def list_application_declinations(application_id):
    require("Producer", "Underwriter", "PlanAdmin")
    limit, offset = pagination()
    application = lookup.application(application_id)
    rows = eligibility_svc.declinations_for(application["id"])
    return page(rows, limit, offset)


# --- submission -----------------------------------------------------------

@bp.post("/applications/<application_id>/submission")
def submit_application(application_id):
    caller = require("Producer")
    body()

    application = lookup.application(application_id)
    own(application["producer_id"] == caller.user_id,
        "Application belongs to another producer")

    if application["status"] not in ("DRAFT", "ELIGIBILITY_HELD"):
        fail("ERR_APPLICATION_NOT_SUBMITTABLE",
             "Application status %s is not submittable" % application["status"])

    producer = db.producers.get(application["producer_id"])
    if producer is None or producer["agreement_status"] != "APPOINTED":
        fail("ERR_PRODUCER_NOT_APPOINTED", "Producer is not APPOINTED")

    prop = db.properties[application["property_id"]]
    zone = zone_svc.zone_of_property(prop)
    peril_package = application["requested_peril_package"]
    filing = rate_svc.select_rate_filing(zone["id"], peril_package, db.today())
    if filing is None:
        fail("ERR_NO_APPROVED_RATE",
             "No APPROVED rate filing covers this territory and package")

    now = db.now()
    application["submitted_at"] = store_instant(now)

    count = eligibility_svc.declination_count(application, now)
    application["declination_count"] = count

    limit_cents = application["requested_dwelling_limit_cents"]
    score = prop["condition_score"]

    _, _, quoted = premium_svc.compute(
        filing["filed_rate_per_1000_cents"], limit_cents,
        prop["construction_type"], prop["occupancy"], peril_package,
        zone["concentration_ratio"], score, 0)
    _, _, voluntary = premium_svc.compute(
        filing["voluntary_market_avg_rate_per_1000_cents"], limit_cents,
        prop["construction_type"], prop["occupancy"], peril_package,
        zone["concentration_ratio"], score, 0)

    application["quote_rate_filing_id"] = filing["id"]
    application["quoted_annual_premium_cents"] = quoted
    application["voluntary_equivalent_premium_cents"] = voluntary
    application["voluntary_market_comparison_pct"] = premium_svc.comparison_pct(
        quoted, voluntary)

    if eligibility_svc.sufficient(count):
        application["status"] = "SUBMITTED"
        application["eligibility_hold_reason"] = None
    else:
        application["status"] = "ELIGIBILITY_HELD"
        application["eligibility_hold_reason"] = "INSUFFICIENT_DECLINATIONS"

    touch(application)
    return ok(application)


# --- eligibility review ---------------------------------------------------

@bp.post("/applications/<application_id>/eligibility-review")
def review_eligibility(application_id):
    caller = require("Underwriter")
    data = body()
    decision = req_enum(data, "decision", ELIGIBILITY_DECISIONS)
    decline_reason = opt_string(data, "decline_reason")

    application = lookup.application(application_id)
    if application["status"] not in ("SUBMITTED", "ELIGIBILITY_HELD"):
        fail("ERR_APPLICATION_NOT_REVIEWABLE",
             "Application status %s is not reviewable" % application["status"])

    if decision == "ADVANCE":
        # The anchor is the UNCHANGED submitted_at, so rows may have aged out.
        count = eligibility_svc.declination_count(application)
        if not eligibility_svc.sufficient(count):
            fail("ERR_INSUFFICIENT_DECLINATIONS",
                 "Only %d qualifying declination(s) inside the lookback window"
                 % count)
        application["status"] = "INSPECTION_PENDING"
    else:
        application["status"] = "DECLINED"
        application["decline_reason"] = decline_reason

    application["eligibility_reviewer_user_id"] = caller.user_id
    touch(application)
    return ok(application)


# --- inspection ordering --------------------------------------------------

@bp.post("/applications/<application_id>/inspections")
def order_inspection(application_id):
    require("Underwriter")
    data = body()
    scheduled_for = opt_date(data, "scheduled_for")

    application = lookup.application(application_id)
    if application["status"] not in ("INSPECTION_PENDING", "IMPROVEMENTS_REQUIRED"):
        fail("ERR_INSPECTION_NOT_ORDERABLE",
             "Application status %s cannot be inspected" % application["status"])

    inspection = new_record({
        "application_id": application["id"],
        "inspector_user_id": None,
        "ordered_at": store_instant(db.now()),
        "scheduled_for": store_date(scheduled_for),
        "completed_at": None,
        "observed_condition_score": None,
        "result": "PENDING",
        "open_requirement_count": 0,
        "cleared_major_count": 0,
    })
    db.inspections[inspection["id"]] = inspection

    # A re-inspection additionally walks the application back.
    if application["status"] == "IMPROVEMENTS_REQUIRED":
        application["status"] = "INSPECTION_PENDING"
        touch(application)

    return created(inspection)


@bp.get("/applications/<application_id>/inspections")
def list_application_inspections(application_id):
    require("Underwriter", "Inspector", "Producer", "PlanAdmin")
    limit, offset = pagination()
    result = filter_enum("result", INSPECTION_RESULTS)
    application = lookup.application(application_id)
    rows = [i for i in db.inspections.values()
            if i["application_id"] == application["id"]
            and matches(i, {"result": result})]
    return page(rows, limit, offset)
