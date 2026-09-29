"""Tariff filing lifecycle (PRD 3.5)."""
from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, PLATFORM_ADMIN,
                  REGULATORY_AFFAIRS_SPECIALIST, REVENUE_ASSURANCE_CONTROLLER,
                  authenticate)
from constants import RATE_ELEMENTS
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_tariff_filing
from services.tariff import windows_intersect
from store import base_record, db, now, ordered, touch

bp = Blueprint("tariffs", __name__)


@bp.post("/tariff-filings")
def file_tariff():
    authenticate((REGULATORY_AFFAIRS_SPECIALIST,))
    payload = v.body()
    docket = v.string(payload, "filing_docket")
    rate_element = v.enum(payload, "rate_element", RATE_ELEMENTS)
    rate = v.number(payload, "rate_per_mou_usd", 6, gt=0)
    benchmark = v.number(payload, "benchmark_interstate_rate_per_mou_usd", 6, gt=0)
    effective_date = v.timestamp(payload, "effective_date")
    expiry_date = v.timestamp(payload, "expiry_date")

    if rate_element == "INTRASTATE_SWITCHED_ACCESS" and rate > benchmark:
        raise ApiError("ERR_ACCESS_REFORM_RATE_CAP_EXCEEDED",
                       "the intrastate rate exceeds the interstate benchmark")

    for existing in db.tariff_filings.values():
        if existing["filing_docket"] == docket:
            raise ApiError("ERR_DUPLICATE_FILING_DOCKET",
                           "filing_docket %s is already used" % docket)

    for existing in ordered(db.tariff_filings):
        if existing["rate_element"] != rate_element:
            continue
        if existing["status"] not in ("FILED", "EFFECTIVE"):
            continue
        if windows_intersect(effective_date, expiry_date,
                             existing["effective_date"], existing["expiry_date"]):
            raise ApiError("ERR_TARIFF_WINDOW_OVERLAP",
                           "the window overlaps an existing filing for this rate element")

    if expiry_date <= effective_date:
        raise ApiError("ERR_INVALID_TARIFF_WINDOW",
                       "expiry_date must be strictly after effective_date")

    filing = base_record()
    filing.update({
        "filing_docket": docket,
        "rate_element": rate_element,
        "rate_per_mou_usd": rate,
        "benchmark_interstate_rate_per_mou_usd": benchmark,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "status": "FILED",
        "superseded_by_filing_id": None,
        "superseded_at": None,
        "approved_at": None,
    })
    db.tariff_filings[filing["id"]] = filing
    return object_response(filing, 201)


@bp.get("/tariff-filings/<filing_id>")
def read_tariff(filing_id):
    authenticate((PLATFORM_ADMIN, REGULATORY_AFFAIRS_SPECIALIST,
                  ACCESS_BILLING_ANALYST, REVENUE_ASSURANCE_CONTROLLER))
    return object_response(get_tariff_filing(filing_id))


@bp.get("/tariff-filings")
def list_tariffs():
    authenticate((PLATFORM_ADMIN, REGULATORY_AFFAIRS_SPECIALIST,
                  ACCESS_BILLING_ANALYST, REVENUE_ASSURANCE_CONTROLLER))
    rows = ordered(db.tariff_filings)
    rate_element = request.args.get("rate_element")
    if rate_element:
        rows = [r for r in rows if r["rate_element"] == rate_element]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    superseded_by = request.args.get("superseded_by_filing_id")
    if superseded_by:
        rows = [r for r in rows if r["superseded_by_filing_id"] == superseded_by]
    return paginate(rows, request.args, lambda r: r)


@bp.post("/tariff-filings/<filing_id>/approve")
def approve_tariff(filing_id):
    authenticate((REGULATORY_AFFAIRS_SPECIALIST,))
    filing = get_tariff_filing(filing_id)
    payload = v.body()
    supersede_filing_id = v.string(payload, "supersede_filing_id", required=False)

    superseded = None
    if supersede_filing_id is not None:
        superseded = get_tariff_filing(supersede_filing_id)

    if filing["status"] != "FILED":
        raise ApiError("ERR_INVALID_TARIFF_FILING_STATE",
                       "only a FILED tariff filing may be approved")
    if now() < filing["effective_date"]:
        raise ApiError("ERR_EFFECTIVE_DATE_NOT_REACHED",
                       "the logical clock has not reached the filing's effective date")

    for existing in ordered(db.tariff_filings):
        if existing["id"] == filing["id"]:
            continue
        if existing["rate_element"] != filing["rate_element"]:
            continue
        if existing["status"] != "EFFECTIVE":
            continue
        if not windows_intersect(filing["effective_date"], filing["expiry_date"],
                                 existing["effective_date"], existing["expiry_date"]):
            continue
        if superseded is not None and existing["id"] == superseded["id"]:
            continue
        raise ApiError("ERR_TARIFF_WINDOW_OVERLAP",
                       "an effective filing already covers this window")

    if superseded is not None:
        if superseded["status"] != "EFFECTIVE":
            raise ApiError("ERR_INVALID_TARIFF_FILING_STATE",
                           "the superseded filing is not EFFECTIVE")
        if not (superseded["effective_date"] <= filing["effective_date"]
                < superseded["expiry_date"]):
            raise ApiError("ERR_INVALID_TARIFF_WINDOW",
                           "the approving filing does not start inside the superseded window")

    filing["status"] = "EFFECTIVE"
    filing["approved_at"] = now()
    touch(filing)

    if superseded is not None:
        superseded["expiry_date"] = filing["effective_date"]
        superseded["status"] = "SUPERSEDED"
        superseded["superseded_by_filing_id"] = filing["id"]
        superseded["superseded_at"] = now()
        touch(superseded)

    return object_response(filing)


@bp.post("/tariff-filings/<filing_id>/withdraw")
def withdraw_tariff(filing_id):
    authenticate((REGULATORY_AFFAIRS_SPECIALIST,))
    filing = get_tariff_filing(filing_id)
    payload = v.body()
    reason = v.string(payload, "withdrawal_reason")

    if filing["status"] != "FILED":
        raise ApiError("ERR_INVALID_TARIFF_FILING_STATE",
                       "only a FILED tariff filing may be withdrawn")

    filing["status"] = "WITHDRAWN"
    filing["_withdrawal_reason"] = reason
    touch(filing)
    return object_response(filing)
