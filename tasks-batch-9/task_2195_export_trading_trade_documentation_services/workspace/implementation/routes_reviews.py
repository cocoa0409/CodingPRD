"""Terms reviews and discrepancy findings."""
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, pagination
from core import ApiError, ok, ok_list
from db import insert, ordered, require, serialize, serialize_all, store, touch
from routes_lc import guard_lc_live, lc_state_invalid, refresh_bounds
from routes_orders import guard_restricted

from flask import Blueprint, request

bp = Blueprint("reviews", __name__)

D = Decimal
REVIEW_READ = ("DocumentaryCreditReviewer", "ExportOpsCoordinator", "PlatformAdmin")
FINDING_READ = ("DocumentaryCreditReviewer", "ExportOpsCoordinator",
                "FinanceCollectionsOfficer", "ForeignBuyer", "PlatformAdmin")
FINDING_CODES = ("AMOUNT_MISMATCH", "EXPIRY_UNWORKABLE", "LATEST_SHIPMENT_UNWORKABLE",
                 "PARTIAL_SHIPMENT_BARRED", "DOC_TYPE_MISSING", "DESCRIPTION_MISMATCH",
                 "WEIGHT_MISMATCH", "ORIGIN_MISMATCH", "LATE_PRESENTATION",
                 "SHORT_DRAWING", "DOC_VOIDED")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
CLAUSES = ("AMOUNT", "EXPIRY", "LATEST_SHIPMENT", "DOCUMENTS", "GOODS", "OTHER")


def review_submitted():
    raise ApiError("ERR_REVIEW_ALREADY_SUBMITTED", 409,
                   "the review is no longer DRAFTING")


def new_finding(**fields):
    row = {
        "letter_of_credit_id": None,
        "lc_terms_review_id": None,
        "document_presentation_id": None,
        "waived_by_buyer_id": None,
        "source": "TERMS",
        "code": None,
        "severity": None,
        "clause_ref": None,
        "detail": None,
        "cure_status": "OPEN",
        "raised_in_round": 0,
        "buyer_reference": None,
    }
    row.update(fields)
    return insert(store.findings, row)


@bp.post("/letters-of-credit/<lc_id>/reviews")
def open_review(lc_id):
    caller = authenticate(("DocumentaryCreditReviewer",))
    lc = require(store.lcs, lc_id, "ERR_LC_NOT_FOUND")
    body = valid.body()
    expected = valid.integer(body, "expected_letter_of_credit_version", minimum=0)

    if lc["status"] != "RECEIVED":
        lc_state_invalid("a review may only be opened on a RECEIVED credit")
    if expected != lc["version"]:
        raise ApiError("ERR_STALE_LC_VERSION", 412,
                       "expected_letter_of_credit_version is stale")
    order = store.orders[lc["export_order_id"]]
    guard_restricted(store.buyers[order["buyer_id"]])
    if caller.user_id == lc["captured_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "the user who captured the credit may not review it")
    guard_lc_live(lc)

    for other in ordered(store.reviews):
        if other["letter_of_credit_id"] == lc["id"] and other["status"] == "DRAFTING":
            other["status"] = "SUPERSEDED"
            touch(other)
    lc["status"] = "UNDER_REVIEW"
    touch(lc)
    row = insert(store.reviews, {
        "letter_of_credit_id": lc["id"],
        "reviewer_user_id": caller.user_id,
        "reviewed_lc_version": lc["version"],
        "recommendation": None,
        "terms_risk_score": D("0.00"),
        "finding_count": 0,
        "status": "DRAFTING",
    })
    return ok(serialize(row), 201)


@bp.get("/lc-terms-reviews")
def list_reviews():
    authenticate(REVIEW_READ)
    limit, offset = pagination()
    rows = ordered(store.reviews)
    lc_id = request.args.get("letter_of_credit_id")
    if lc_id:
        rows = [r for r in rows if r["letter_of_credit_id"] == lc_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/lc-terms-reviews/<review_id>")
def read_review(review_id):
    authenticate(REVIEW_READ)
    row = require(store.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/lc-terms-reviews/<review_id>/findings")
def record_finding(review_id):
    authenticate(("DocumentaryCreditReviewer",))
    review = require(store.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    body = valid.body()
    code = valid.enum(body, "code", FINDING_CODES)
    severity = valid.enum(body, "severity", SEVERITIES)
    clause_ref = valid.enum(body, "clause_ref", CLAUSES)
    detail = valid.string(body, "detail", max_len=2000)

    if review["status"] != "DRAFTING":
        review_submitted()

    row = new_finding(letter_of_credit_id=review["letter_of_credit_id"],
                      lc_terms_review_id=review["id"], source="TERMS", code=code,
                      severity=severity, clause_ref=clause_ref, detail=detail,
                      cure_status="OPEN", raised_in_round=0)
    review["finding_count"] = calc.finding_count(review["id"])
    touch(review)
    return ok(serialize(row), 201)


def _open_findings(review_id):
    return [f for f in store.findings.values()
            if f["lc_terms_review_id"] == review_id and f["cure_status"] == "OPEN"]


@bp.post("/lc-terms-reviews/<review_id>/submit")
def submit_review(review_id):
    authenticate(("DocumentaryCreditReviewer",))
    review = require(store.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    body = valid.body()
    recommendation = valid.enum(body, "recommendation", ("ACCEPT", "AMEND", "REJECT"))

    if review["status"] != "DRAFTING":
        review_submitted()
    lc = store.lcs[review["letter_of_credit_id"]]
    if lc["status"] != "UNDER_REVIEW":
        lc_state_invalid("the credit is not UNDER_REVIEW")
    if review["reviewed_lc_version"] != lc["version"]:
        lc_state_invalid("the credit has moved since the review was opened")

    score = calc.terms_risk_score(review)
    open_rows = _open_findings(review["id"])
    critical_open = any(f["severity"] == "CRITICAL" for f in open_rows)
    if recommendation == "ACCEPT":
        if critical_open or score >= calc.RISK_ACCEPT_CEILING:
            raise ApiError("ERR_RECOMMENDATION_NOT_PERMITTED", 409,
                           "ACCEPT is not permitted for this finding set")
    elif recommendation == "AMEND":
        if not open_rows or score >= calc.RISK_REJECT_FLOOR:
            raise ApiError("ERR_RECOMMENDATION_NOT_PERMITTED", 409,
                           "AMEND is not permitted for this finding set")
    else:
        if not critical_open and score < calc.RISK_REJECT_FLOOR:
            raise ApiError("ERR_RECOMMENDATION_NOT_PERMITTED", 409,
                           "REJECT is not permitted for this finding set")

    review["recommendation"] = recommendation
    review["terms_risk_score"] = score
    review["finding_count"] = calc.finding_count(review["id"])
    review["status"] = "SUBMITTED"
    touch(review)

    order = store.orders[lc["export_order_id"]]
    if recommendation == "ACCEPT":
        lc["status"] = "ACCEPTED"
        refresh_bounds(lc)
        touch(lc)
        if order["settlement_status"] == "UNSECURED":
            order["settlement_status"] = "LC_ACCEPTED"
            ledgers.charge_exposure(order)
            touch(order)
    elif recommendation == "AMEND":
        lc["status"] = "AMENDMENT_REQUESTED"
        touch(lc)
    else:
        lc["status"] = "REJECTED"
        touch(lc)
    return ok(serialize(review))


@bp.get("/discrepancy-findings")
def list_findings():
    authenticate(FINDING_READ)
    limit, offset = pagination()
    rows = ordered(store.findings)
    for field in ("letter_of_credit_id", "lc_terms_review_id",
                  "document_presentation_id", "waived_by_buyer_id", "source",
                  "severity", "cure_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/discrepancy-findings/<finding_id>")
def read_finding(finding_id):
    authenticate(FINDING_READ)
    row = require(store.findings, finding_id, "ERR_FINDING_NOT_FOUND")
    return ok(serialize(row))
